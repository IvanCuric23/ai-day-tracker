"""My AI day: where did my time go?

Reads Claude Code, Copilot CLI/app and VS Code Copilot Chat history on this PC
and writes one HTML page per day: a timeline, hours per project and ticket,
what you asked and what you committed.

    python -X utf8 my_day.py              -> today
    python -X utf8 my_day.py 2026-11-02   -> that day
    python -X utf8 my_day.py yesterday
"""
import collections
import glob
import html
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import urllib.parse
import webbrowser
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta, timezone

HOME = os.path.expanduser("~")
HERE = os.path.dirname(os.path.abspath(__file__))
try:
    logging.basicConfig(filename=os.path.join(HERE, "clock.log"), level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", encoding="utf-8")
except OSError:                                        # log file locked or unwritable: build without it
    logging.getLogger().addHandler(logging.NullHandler())
logger = logging.getLogger(__name__)


def read_json(path: str, encoding: str = "utf-8") -> dict:
    """The JSON object in a file; {} when it is missing, or unreadable (that is logged)."""
    try:
        with open(path, encoding=encoding) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        logger.warning("cannot read %s", path, exc_info=True)
        return {}


def read_jsonl(path: str) -> Iterator[dict]:
    """The JSON objects of a .jsonl file; a line that is not valid JSON, or not an object, is skipped."""
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except ValueError:
                entry = None
            if isinstance(entry, dict):
                yield entry
            else:
                logger.debug("skipping a bad line in %s", path)


def load_config() -> dict:
    """config.json next to this script (written by install.ps1); every key is optional."""
    return read_json(os.path.join(HERE, "config.json"), "utf-8-sig")


def git_authors() -> list[str]:
    """No authors in config.json: use your git user.name and user.email."""
    out = []
    for key in ("user.name", "user.email"):
        try:
            v = subprocess.run(["git", "config", "--global", key], capture_output=True, text=True).stdout.strip()
        except OSError:                                # git is not installed
            v = ""
        if v:
            out.append(v)
    return out


CONFIG = load_config()
GAP = int(CONFIG.get("gap_minutes", 10)) * 60                                # steps further apart = you were away
DAY_FROM, DAY_TO = int(CONFIG.get("day_from", 7)), int(CONFIG.get("day_to", 19))   # working hours for the day view
AUTHORS = CONFIG.get("authors") or git_authors()                             # whose commits count as yours
REPORTS_DIR = os.path.expanduser(CONFIG.get("reports_dir") or os.path.join("~", "Documents", "DailyWorkReport", "reports"))
# branches whose name has no ticket number: one shared list with the clock hook, edit it once
TICKETS_FILE = os.path.join(HOME, ".claude", "hooks", "tickets.json")
TICKETS = read_json(TICKETS_FILE)
arg = next((a for a in sys.argv[1:] if not a.startswith("--")), "today")
DAY = date.today() - timedelta(days=1) if arg == "yesterday" else date.today() if arg == "today" else date.fromisoformat(arg)
T0 = datetime.combine(DAY, time()).astimezone()
T1 = T0 + timedelta(days=1)


def ts(s: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone()
    except (ValueError, OverflowError, OSError):       # not a timestamp, or out of the platform's range
        return None


def touched_today(path: str) -> bool:
    try:
        return os.path.getmtime(path) >= T0.timestamp()
    except OSError:
        return False


CANON = {"ai-agent-templates": "AI-Agent-Templates", "test-writer-plugin": "Test-Writer-Plugin",
         "powrshellagnet": "PowrshellAgnet", "hocuknjigu": "HocuKnjigu", "hk_consigrepo": "HocuKnjigu – Consignment",
         "zg bc impl orqa": "ZG BC IMPL ORQA", "zg-bc-impl-orqa.wiki": "ZG BC IMPL ORQA",
         "zg bc impl apis": "ZG BC IMPL APIS", "parcel-integration": "Parcel-Integration", "prima nav": "Prima NAV"}


OTHER = "Other (no project folder)"


def project(cwd: str | None) -> str:
    if not cwd:
        return OTHER
    p = cwd.replace("/", "\\")
    w = re.search(r"(?i)worktrees\\(?:[^\\_]+_)?([^\\]+)\\", p + "\\")
    if w:
        return CANON.get(w.group(1).lower(), w.group(1))
    m = re.match(r"(?i)c:\\VS\\([^\\]+)", p)
    if m:
        name = re.sub(r"(?i)(-wt.*|-ci|-notice|-verify|-v3|-stable|-al-cops)$", "", m.group(1))
        return CANON.get(name.lower(), name)
    return OTHER


def clean(text: str | None) -> str:
    text = re.sub(r"<[^>]+>.*?</[^>]+>", " ", text or "", flags=re.S)
    text = re.sub(r"\s+", " ", text).strip()
    if text.startswith(("Caveat:", "[Request interrupted", "<", "This session is being continued")):
        return ""
    return text[:300]


events = []                         # (time, project, branch)
prompts = collections.defaultdict(list)
cwds = collections.defaultdict(set)


def add(t: datetime | None, proj: str, branch: str | None, cwd: str | None = None) -> bool:
    if t and T0 <= t < T1:
        events.append((t, proj, branch or "?"))
        if cwd:
            cwds[proj].add(cwd)
        return True
    return False


def ask(t: datetime, proj: str, tool: str, text: str | None) -> None:
    text = clean(text)
    if text and T0 <= t < T1:
        prompts[proj].append((t, tool, text))


# Claude Code
for f in glob.glob(os.path.join(HOME, ".claude", "projects", "*", "*.jsonl")):
    if not touched_today(f):
        continue
    cwd = branch = None
    for e in read_jsonl(f):
        cwd, branch = e.get("cwd") or cwd, e.get("gitBranch") or branch
        t = ts(e.get("timestamp"))
        proj = project(cwd)
        if add(t, proj, branch, cwd) and e.get("type") == "user" and not e.get("isMeta") and not e.get("isSidechain"):
            c = (e.get("message") or {}).get("content")
            if isinstance(c, list):
                c = " ".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
            if isinstance(c, str):
                ask(t, proj, "Claude", c)

# Copilot CLI / app: live event files
for f in glob.glob(os.path.join(HOME, ".copilot", "session-state", "*", "events.jsonl")):
    if not touched_today(f):
        continue
    cwd = branch = None
    for e in read_jsonl(f):
        if e.get("type") == "session.start":
            ctx = (e.get("data") or {}).get("context") or {}
            cwd, branch = ctx.get("cwd"), ctx.get("branch")
        t = ts(e.get("timestamp"))
        if add(t, project(cwd), branch, cwd) and e.get("type") == "user.message":
            ask(t, project(cwd), "Copilot", (e.get("data") or {}).get("content"))

# Copilot session store (keeps sessions whose event files were already pruned)
dbf = os.path.join(HOME, ".copilot", "session-store.db")
if os.path.exists(dbf):
    try:
        db = sqlite3.connect(f"file:{dbf}?mode=ro", uri=True)
        sess = {i: (c, b) for i, c, b in db.execute("select id, cwd, branch from sessions")}
        for sid, created, dur in db.execute("select session_id, created_at, duration_ms from assistant_usage_events"):
            t, (cwd, branch) = ts(created), sess.get(sid, (None, None))
            if add(t, project(cwd), branch, cwd) and dur:
                add(t + timedelta(milliseconds=dur), project(cwd), branch)
        seen = {(p, x[2][:80]) for p, v in prompts.items() for x in v}
        for sid, msg, stamp in db.execute("select session_id, user_message, timestamp from turns"):
            t, (cwd, branch) = ts(stamp), sess.get(sid, (None, None))
            if t and (project(cwd), clean(msg)[:80]) not in seen:
                ask(t, project(cwd), "Copilot", msg)
    except (sqlite3.Error, TypeError, OverflowError):               # a corrupt store must not fail the day
        logger.warning("skipping the Copilot session store %s", dbf, exc_info=True)

# VS Code Copilot Chat
vsc = os.path.join(os.environ.get("APPDATA", ""), "Code", "User")
for f in glob.glob(os.path.join(vsc, "workspaceStorage", "*", "chatSessions", "*.jsonl")):
    if not touched_today(f):
        continue
    proj, cwd = OTHER, None
    wj = os.path.join(os.path.dirname(os.path.dirname(f)), "workspace.json")
    if os.path.exists(wj):
        uri = read_json(wj).get("folder") or ""
        cwd = urllib.parse.unquote(uri.replace("file:///", "")).replace("/", "\\")
        proj = project(cwd)
    reqs = {}
    for e in read_jsonl(f):
        k, v = e.get("k"), e.get("v")
        items = []
        if e.get("kind") == 0 and isinstance(v, dict):
            items = list(enumerate(v.get("requests") or []))
        elif k == ["requests"] and isinstance(v, list):
            items = [(len(reqs) + i, r) for i, r in enumerate(v)]
        elif isinstance(k, list) and len(k) == 3 and k[0] == "requests" and k[2] == "modelState" and isinstance(v, dict):
            if v.get("completedAt") and k[1] in reqs:
                reqs[k[1]][1] = v["completedAt"]
        for i, r in items:
            if isinstance(r, dict) and r.get("timestamp"):
                reqs[i] = [r["timestamp"], (r.get("modelState") or {}).get("completedAt"), (r.get("message") or {}).get("text")]
    for st, en, txt in reqs.values():
        try:
            a = datetime.fromtimestamp(st / 1000, timezone.utc).astimezone()
            b = datetime.fromtimestamp(en / 1000, timezone.utc).astimezone() if en else a
        except (TypeError, ValueError, OverflowError, OSError):
            logger.debug("skipping a request with a bad timestamp in %s", f)
            continue
        t = a
        while t <= b:
            add(t, proj, "?", cwd)
            t += timedelta(minutes=2)
        add(b, proj, "?")
        ask(a, proj, "VS Code", txt)


# ---- time maths ---------------------------------------------------------
def is_day(t: datetime) -> bool:
    return DAY_FROM <= t.hour < DAY_TO


def active(times: list[datetime]) -> float:
    times = sorted(times)
    return sum(g for g in ((b - a).total_seconds() for a, b in zip(times, times[1:], strict=False)) if g <= GAP)


def segments(times: list[datetime]) -> list[list[float]]:
    out, times = [], sorted(times)
    for t in times:
        m = (t - T0).total_seconds() / 60
        if out and m - out[-1][1] <= GAP / 60:
            out[-1][1] = m
        else:
            out.append([m, m])
    return [[round(a, 1), round(max(b, a + 2), 1)] for a, b in out]


def ticket(branch: str | None) -> str:
    if branch in TICKETS:
        return TICKETS[branch]
    m = re.search(r"([A-Z][A-Z0-9]+-\d+)", branch or "")
    if m:
        return m.group(1)
    m = re.search(r"(?:^|/)(\d{2,4})(?:-|$)", branch or "")
    return f"DevOps #{m.group(1)}" if m else ""


UNKNOWN = {"?", "HEAD", "", None}
by_row = collections.defaultdict(list)
by_proj = collections.defaultdict(list)
for t, p, b in events:
    by_row[(p, b)].append(t)
    by_proj[p].append(t)

rows = collections.defaultdict(lambda: {"all": 0.0, "day": 0.0, "branches": set()})
for p in by_proj:
    known = {b: ts_ for (pp, b), ts_ in by_row.items() if pp == p and b not in UNKNOWN and not b.startswith("detached")}
    unk = [t for (pp, b), ts_ in by_row.items() if pp == p and b not in known for t in ts_]
    for mode, keep in (("all", lambda t: True), ("day", is_day)):
        k = {b: active([t for t in v if keep(t)]) for b, v in known.items()}
        u = active([t for t in unk if keep(t)])
        tot = sum(k.values())
        if tot == 0:
            k = {"": u} if u else {}
        else:
            k = {b: s + u * s / tot for b, s in k.items()}
        for b, s in k.items():
            r = rows[(p, ticket(b))]
            r[mode] += s
            r["branches"].add(b or "no branch")

# commits per project from the repos those sessions ran in
commits = collections.defaultdict(list)
for p, dirs in cwds.items():
    roots = set()
    for d in dirs:
        if os.path.isdir(d):
            r = subprocess.run(["git", "-C", d, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
            if r.returncode == 0:
                roots.add(r.stdout.strip())
    seen = set()
    for root in roots:
        cmd = ["git", "-C", root, "log", "--all", "-i", f"--since={T0.isoformat()}", f"--until={T1.isoformat()}",
               "--date=format:%H:%M", "--format=%h%x09%ad%x09%s"] + [f"--author={a}" for a in AUTHORS]
        out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore").stdout
        found = [(line.split("\t", 2) + ["", ""])[:3] for line in out.splitlines()]
        names = subprocess.run(["git", "-C", root, "name-rev", "--name-only", "--refs=*/heads/*", "--refs=*/remotes/*"]
                               + [h for h, _, _ in found], capture_output=True, text=True).stdout.split() if found else []
        for (h, hm, s), ref in zip(found, names + [""] * len(found), strict=False):
            if s not in seen:
                seen.add(s)
                br = re.sub(r"^(remotes/)?(origin/)?|[~^].*$", "", ref)
                commits[p].append([hm, h, s, br])

# ticket links: Jira keys go to Jira, numbers to the Azure DevOps project of the repo's git remote
JIRA_URL = CONFIG.get("jira_url") or TICKETS.get("_jira", "")    # e.g. https://jira.example.com/browse/


def devops_items(remote: str) -> str:
    m = (re.search(r"dev\.azure\.com[:/](?:v3/)?([^/]+)/([^/]+)/(?:_git/)?[^/]+$", remote)
         or re.search(r"//(?:[^@/]+@)?([^./]+)\.visualstudio\.com/(?:DefaultCollection/)?([^/]+)/_git/", remote))
    return f"https://dev.azure.com/{m.group(1)}/{m.group(2)}/_workitems/edit/" if m else ""


links = {}
for p, dirs in cwds.items():
    for d in dirs:
        if os.path.isdir(d):
            remote = subprocess.run(["git", "-C", d, "remote", "get-url", "origin"], capture_output=True, text=True).stdout.strip()
            if devops_items(remote):
                links[p] = devops_items(remote)
                break

# a row without a ticket borrows the ticket of the branches its commits were made on
for p in by_proj:
    found = collections.Counter(ticket(c[3]) for c in commits.get(p, []) if ticket(c[3]))
    if (p, "") in rows and found:
        r = rows.pop((p, ""))
        tk = found.most_common(1)[0][0]
        rows[(p, tk)]["all"] += r["all"]
        rows[(p, tk)]["day"] += r["day"]
        rows[(p, tk)]["branches"] |= r["branches"] | {"ticket taken from commits"}

# still no ticket: a folder rule in tickets.json ("project:Parcel-Integration": "ZGPARCEL-12") decides
for p in by_proj:
    tk = TICKETS.get(f"project:{p}")
    if tk and (p, "") in rows:
        r = rows.pop((p, ""))
        rows[(p, tk)]["all"] += r["all"]
        rows[(p, tk)]["day"] += r["day"]
        rows[(p, tk)]["branches"] |= r["branches"] | {"ticket from folder rule"}

data = {
    "date": DAY.strftime("%A, %d.%m.%Y"), "dayFrom": DAY_FROM, "dayTo": DAY_TO,
    "union": {"all": active([t for t, _, _ in events]), "day": active([t for t, _, _ in events if is_day(t)])},
    "projects": [{
        "name": p,
        "segments": segments(by_proj[p]),
        "rows": [{"ticket": tk, "branches": sorted(r["branches"]), "all": r["all"], "day": r["day"]}
                 for (pp, tk), r in sorted(rows.items(), key=lambda kv: -kv[1]["all"]) if pp == p],
        "prompts": [[f"{t:%H:%M}", tool, x] for t, tool, x in sorted(prompts.get(p, []))],
        "commits": sorted(c[:3] for c in commits.get(p, [])),
    } for p in by_proj],
}

# clock: exact start/stop per session, written live by the clock.py hook
clock_file = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--clock=")),
                  os.path.join(HOME, ".claude", "clock", "clock.jsonl"))
by_session = collections.defaultdict(list)
if os.path.exists(clock_file):
    for raw in open(clock_file, encoding="utf-8", errors="ignore"):
        try:
            c = json.loads(raw)
            t = ts(c["time"])
        except (ValueError, KeyError, TypeError):
            logger.debug("skipping a bad line in %s", clock_file)
            continue
        if t and T0 <= t < T1:
            by_session[(c.get("tool"), c.get("session"))].append((t, c))
data["clock"] = []
for (tool, sid), lines in by_session.items():
    lines.sort(key=lambda x: x[0])
    times = [t for t, _ in lines]
    last = {}
    for _, c in lines:
        last.update({k: v for k, v in c.items() if v and k in ("project", "branch", "ticket", "system", "model")})
    data["clock"].append({
        "tool": tool, "session": sid, "start": f"{times[0]:%H:%M}", "end": f"{times[-1]:%H:%M}",
        "active": active(times) / 3600, "project": last.get("project", ""), "branch": last.get("branch", ""),
        "ticket": last.get("ticket", ""), "system": last.get("system", ""), "model": last.get("model", ""),
        "steps": [[f"{t:%H:%M}", c["event"], c.get("ask") or c.get("did") or ""]
                  for t, c in lines if c["event"] in ("start", "end") or c.get("ask") or c.get("did")],
    })
data["clock"].sort(key=lambda s: s["start"])

PALETTE = ["#4e79a7", "#f28e2b", "#59a14f", "#e15759", "#edc948", "#76b7b2", "#b07aa1", "#ff9da7",
           "#9c755f", "#17becf", "#bcbd22", "#8c6bd6", "#d4a373", "#2a9d8f", "#e76f51", "#bab0ac"]
COLORS_FILE = os.path.join(HERE, "days", "colors.json")


def update_colors(summary: dict | None = None) -> dict[str, str]:
    colors = read_json(COLORS_FILE)
    hours = collections.Counter()
    for s in (summary or {}).values():
        for p, _, h in s["projects"]:
            hours[p] += h
    for p in [p for p, _ in hours.most_common()] + [p["name"] for p in data["projects"]]:
        if p not in colors:
            free = [c for c in PALETTE if c not in colors.values()]
            colors[p] = free[0] if free else PALETTE[len(colors) % len(PALETTE)]
    os.makedirs(os.path.dirname(COLORS_FILE), exist_ok=True)
    json.dump(colors, open(COLORS_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return colors


_summary = read_json(os.path.join(HERE, "days", "summary.json"))
data["colors"] = update_colors(_summary)
data["iso"] = DAY.isoformat()
data["jira"], data["links"] = JIRA_URL, links
REPORT = os.path.join(REPORTS_DIR, f"work-log-{DAY.isoformat()}.md")
data["worklog"] = open(REPORT, encoding="utf-8-sig", errors="ignore").read() if os.path.exists(REPORT) else ""

page = open(os.path.join(HERE, "my_day_template.html"), encoding="utf-8").read()
page = page.replace("/*DATA*/null", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
page = page.replace("{{TITLE}}", html.escape(f"My AI day {DAY:%d.%m.%Y}"))
os.makedirs(os.path.join(HERE, "days"), exist_ok=True)
out = os.path.join(HERE, "days", f"my-day-{DAY.isoformat()}.html")
open(out, "w", encoding="utf-8").write(page)
json.dump(data, open(os.path.join(HERE, "days", f"{DAY.isoformat()}.json"), "w", encoding="utf-8"), ensure_ascii=False)
print(out)
print(f"{len(events)} steps, {len(by_proj)} projects, {data['union']['all'] / 3600:.2f} h AI-active "
      f"({data['union']['day'] / 3600:.2f} h between {DAY_FROM}:00 and {DAY_TO}:00)")


# ---- calendar dashboard: one summary line per day, rebuilt into index.html ----------
def project_hours(mode: str) -> dict[str, float]:
    total = sum(r[mode] for p in data["projects"] for r in p["rows"]) or 1
    k = data["union"][mode] / total / 3600
    return {p["name"]: sum(r[mode] for r in p["rows"]) * k for p in data["projects"]}


def ticket_rows() -> list[list]:
    """[project, ticket, hours 7-19, hours all day] per ticket row, for the week view."""
    out = []
    for mode in ("day", "all"):
        total = sum(r[mode] for p in data["projects"] for r in p["rows"]) or 1
        k = data["union"][mode] / total / 3600
        for p in data["projects"]:
            for r in p["rows"]:
                if mode == "day":
                    out.append([p["name"], r["ticket"], round(r["day"] * k, 2), 0])
                else:
                    next(o for o in out if o[0] == p["name"] and o[1] == r["ticket"])[3] = round(r["all"] * k, 2)
    return [o for o in out if o[3] >= 0.02]


summary_file = os.path.join(HERE, "days", "summary.json")
summary = read_json(summary_file)
hd, ha = project_hours("day"), project_hours("all")
summary[DAY.isoformat()] = {
    "day": data["union"]["day"] / 3600, "all": data["union"]["all"] / 3600,
    "projects": sorted(([p, round(hd[p], 2), round(ha[p], 2)] for p in ha if ha[p] >= 0.02), key=lambda x: -x[2]),
    "tickets": sorted({r["ticket"] for p in data["projects"] for r in p["rows"] if r["ticket"]}),
    "built": datetime.now().strftime("%d.%m. %H:%M"),
    "log": bool(data["worklog"]),
    "rows": ticket_rows(),
}
json.dump(summary, open(summary_file, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# one fixed colour per project, kept in colors.json so it never changes; biggest projects get the clearest colours
board = open(os.path.join(HERE, "dashboard_template.html"), encoding="utf-8").read()
board = board.replace("/*SUMMARY*/null", json.dumps(summary, ensure_ascii=False).replace("</", "<\\/"))
board = board.replace("/*COLORS*/null", json.dumps(update_colors(summary), ensure_ascii=False))
index = os.path.join(HERE, "index.html")
open(index, "w", encoding="utf-8").write(board)
print(index)
if "--no-open" not in sys.argv:
    webbrowser.open("file:///" + index.replace("\\", "/") + "#" + DAY.isoformat())
