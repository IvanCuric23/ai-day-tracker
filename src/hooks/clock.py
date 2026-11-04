"""Clock hook: writes one line per AI session event to clock.jsonl.

Called by Claude Code and Copilot CLI hooks:
    python clock.py claude  start|prompt|stop|end      (JSON payload on stdin)
    python clock.py copilot start|prompt|work|end

Each line: time, event, tool, session, project, branch, ticket, and what you asked (prompt)
or what the AI answered + last commit (stop). Never prints, never fails: a hook must not
disturb the session.

    python clock.py backfill 2026-11-02   -> rebuild that day's lines from Claude history (demo / gaps)
"""
import functools
import glob
import json
import os
import re
import subprocess
import sys
import zlib
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.environ.get("CLOCK_FILE") or os.path.join(os.path.expanduser("~"), ".claude", "clock", "clock.jsonl")
TICKETS_FILE = os.path.join(HERE, "tickets.json")      # {"feature/my-branch": "ABC-123"}
TEXT = 200


@functools.lru_cache(None)
def tickets():
    try:
        return json.load(open(TICKETS_FILE, encoding="utf-8"))
    except Exception:
        return {}


def ticket(branch, proj=""):
    known = tickets()
    if branch in known:
        t = known[branch]
    else:
        m = re.search(r"([A-Z][A-Z0-9]+-\d+)", branch or "")
        n = re.search(r"(?:^|/)(\d{2,4})(?:-|$)", branch or "")
        t = m.group(1) if m else n.group(1) if n else known.get(f"project:{proj}", "")   # folder rule last
    t = re.sub(r"^DevOps #", "", t)
    return t, ("Jira" if "-" in t else "DevOps" if t else "")


def git(cwd, *args):
    try:
        r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, encoding="utf-8",
                           errors="ignore", timeout=3)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


@functools.lru_cache(None)
def project(cwd):
    root = git(cwd, "rev-parse", "--show-toplevel") or cwd
    name = os.path.basename(root.rstrip("\\/"))
    w = re.search(r"(?i)worktrees[\\/](?:[^\\/_]+_)?([^\\/]+)", cwd or "")
    return w.group(1) if w else name


def short(text):
    return re.sub(r"\s+", " ", text or "").strip()[:TEXT]


def last_answer(transcript):
    """First line of the AI's last text answer + model, read from the end of the transcript."""
    try:
        with open(transcript, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 400_000))
            lines = f.read().decode("utf-8", errors="ignore").splitlines()
    except Exception:
        return "", ""
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except Exception:
            continue
        msg = e.get("message") or {}
        if e.get("type") == "assistant" and isinstance(msg.get("content"), list):
            text = " ".join(c.get("text", "") for c in msg["content"] if c.get("type") == "text").strip()
            if text:
                return short(text.split("\n")[0]), msg.get("model", "")
    return "", ""


def line(t, event, tool, session, cwd, branch, **extra):
    proj = project(cwd) if cwd else ""
    tk, system = ticket(branch, proj)
    out = {"time": t.isoformat(timespec="seconds"), "event": event, "tool": tool, "session": session[:8],
           "project": proj, "cwd": cwd, "branch": branch, "ticket": tk, "system": system}
    out.update({k: v for k, v in extra.items() if v})
    return out


def write(rows):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def hook(tool, event):
    raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace") if not sys.stdin.isatty() else ""
    try:
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}
    cwd = data.get("cwd") or os.getcwd()
    # Copilot may send no session id: one id per tool + folder keeps its lines together
    session = str(data.get("session_id") or data.get("sessionId") or f"{tool[:2].lower()}{zlib.crc32(cwd.encode()):08x}"[:8])
    branch = git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    extra = {}
    if event == "prompt":
        extra["ask"] = short(data.get("prompt") or data.get("userPrompt"))
    if event == "stop":
        extra["did"], extra["model"] = last_answer(data.get("transcript_path", ""))
        extra["commit"] = git(cwd, "log", "-1", "--format=%h %s", "--since=12 hours ago")
        extra["changed"] = len(git(cwd, "status", "--porcelain").splitlines()) or ""
    if event == "start":
        extra["how"] = data.get("source", "")        # startup / resume / clear / compact
    if event == "end":
        extra["how"] = data.get("reason", "")
    write([line(datetime.now().astimezone(), event, tool, session, cwd, branch, **extra)])


def backfill(day):
    """Rebuild one day's clock lines from Claude Code history (branch as it was then)."""
    start = datetime.fromisoformat(day).astimezone()
    end = start + timedelta(days=1)
    rows = []
    for f in glob.glob(os.path.join(os.path.expanduser("~"), ".claude", "projects", "*", "*.jsonl")):
        if os.path.getmtime(f) < start.timestamp():
            continue
        session, seen = os.path.basename(f)[:8], False
        for raw in open(f, encoding="utf-8", errors="ignore"):
            try:
                e = json.loads(raw)
                t = datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00")).astimezone()
            except Exception:
                continue
            if not (start <= t < end) or e.get("isSidechain") or e.get("isMeta"):
                continue
            cwd, branch, msg = e.get("cwd", ""), e.get("gitBranch", ""), e.get("message") or {}
            c = msg.get("content")
            if not seen and cwd:
                rows.append(line(t, "start", "Claude", session, cwd, branch, how="backfill"))
                seen = True
            if e.get("type") == "user" and isinstance(c, str) and c.strip() and not c.lstrip().startswith("<"):
                rows.append(line(t, "prompt", "Claude", session, cwd, branch, ask=short(c)))
            elif e.get("type") == "assistant" and msg.get("stop_reason") == "end_turn" and isinstance(c, list):
                text = " ".join(x.get("text", "") for x in c if x.get("type") == "text").strip()
                if text:
                    rows.append(line(t, "stop", "Claude", session, cwd, branch, did=short(text.split("\n")[0]),
                                     model=msg.get("model", "")))
            elif e.get("type") == "assistant":
                rows.append(line(t, "work", "Claude", session, cwd, branch))
    rows.sort(key=lambda r: r["time"])
    # keep "work" lines sparse: one per session per 2 minutes is enough for the timeline
    last, slim = {}, []
    for r in rows:
        if r["event"] == "work":
            t = datetime.fromisoformat(r["time"])
            if r["session"] in last and t - last[r["session"]] < timedelta(minutes=2):
                continue
            last[r["session"]] = t
        slim.append(r)
    write(slim)
    print(f"{len(slim)} lines -> {LOG}")


if __name__ == "__main__":
    try:
        if len(sys.argv) > 2 and sys.argv[1] == "backfill":
            backfill(sys.argv[2])
        elif len(sys.argv) > 2:
            hook(sys.argv[1].capitalize() if sys.argv[1] != "copilot" else "Copilot", sys.argv[2])
    except Exception:
        pass                                           # a broken clock must never break the session
    sys.exit(0)
