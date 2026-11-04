r"""My AI dashboard: serves the calendar at http://localhost:<port> (config.json, default 8800) (this PC only).

    GET  /                -> the calendar (index.html)
    GET  /days/<file>     -> a day page or its data
    GET  /worklog/<date>  -> that day's work-log report (reports_dir in config.json), read live
    GET  /worklogs        -> the dates that have one
    GET  /search?q=...    -> every day that mentions q (ticket, branch, prompt, commit, work log)
    POST /refresh         -> rebuild today now (or ?day=2026-11-03), then reload the page

Started hidden at logon (Startup folder) and every 5 min by the "My AI dashboard server" task; a copy that finds
the port taken quits at once, so exactly one server runs.
"""
import json, os, re, socket, subprocess, sys, threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
try:
    CONFIG = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8-sig"))
except Exception:
    CONFIG = {}
PORT = int(CONFIG.get("port", 8800))
PY = os.path.join(os.path.dirname(sys.executable), "python.exe")   # pythonw has no console for the build
BUILD = threading.Lock()
REPORTS = os.path.expanduser(CONFIG.get("reports_dir") or os.path.join("~", "Documents", "DailyWorkReport", "reports"))


def search(q):
    """Every day whose tickets, branches, prompts, commits or work log mention q, newest first.
    Hours = the day's hours (7-19) of the projects where q was found."""
    q = q.strip().lower()
    if len(q) < 2:
        return []
    days_dir = os.path.join(HERE, "days")
    try:
        summary = json.load(open(os.path.join(days_dir, "summary.json"), encoding="utf-8"))
    except Exception:
        summary = {}
    out = []
    for f in sorted(os.listdir(days_dir), reverse=True):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", f):
            continue
        day = f[:10]
        try:
            d = json.load(open(os.path.join(days_dir, f), encoding="utf-8"))
        except Exception:
            continue
        hits, projects = [], set()

        def hit(kind, proj, text):
            if q in str(text).lower():
                projects.add(proj)
                if len(hits) < 6:
                    hits.append({"kind": kind, "project": proj, "text": str(text)[:160]})

        for p in d.get("projects", []):
            hit("project", p["name"], p["name"])
            for r in p["rows"]:
                hit("ticket", p["name"], " ".join([r["ticket"]] + r["branches"]))
            for t, _, s in p.get("commits", []):
                hit("commit", p["name"], f"{t} {s}")
            for t, _, s in p.get("prompts", []):
                hit("asked", p["name"], f"{t} {s}")
        for line in (d.get("worklog") or "").splitlines():
            if q in line.lower() and line.startswith("|"):
                cells = [c.strip() for c in line.strip("|").split("|")]
                hit("work log", cells[3] if len(cells) > 5 else "", " · ".join(c for c in cells[1:] if c and c != "?"))
        if hits:
            ph = {p: h for p, h, _ in summary.get(day, {}).get("projects", [])}
            hours = sum(ph.get(p, 0) for p in projects) or summary.get(day, {}).get("day", 0)
            out.append({"day": day, "hours": round(hours, 2), "hits": hits})
    return out


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=HERE, **kw)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")                 # F5 always shows the newest data
        super().end_headers()

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html") or (path.startswith("/days/") and path.endswith((".html", ".json"))):
            return super().do_GET()
        if path == "/worklogs":                                       # dates that have a daily work-log report
            days = sorted(f[9:19] for f in os.listdir(REPORTS) if re.fullmatch(r"work-log-\d{4}-\d{2}-\d{2}\.md", f)) \
                if os.path.isdir(REPORTS) else []
            return self.send_json(days)
        if path == "/search":
            return self.send_json(search((parse_qs(urlparse(self.path).query).get("q") or [""])[0]))
        m = re.fullmatch(r"/worklog/(\d{4}-\d{2}-\d{2})", path)
        if m:                                                         # read live, so a report written after 17:00 shows on F5
            f = os.path.join(REPORTS, f"work-log-{m.group(1)}.md")
            if not os.path.exists(f):
                return self.send_json({"md": ""})                       # no report that day: empty, not an error
            return self.send_json({"md": open(f, encoding="utf-8-sig", errors="ignore").read()})
        self.send_error(404)                                          # nothing else in the folder is served

    def do_POST(self):
        url = urlparse(self.path)
        if url.path != "/refresh":
            return self.send_error(404)
        day = (parse_qs(url.query).get("day") or ["today"])[0]
        if day != "today" and not (len(day) == 10 and day[4] == day[7] == "-" and day.replace("-", "").isdigit()):
            return self.send_error(400)
        with BUILD:
            r = subprocess.run([PY, "-X", "utf8", os.path.join(HERE, "my_day.py"), day, "--no-open"],
                               capture_output=True, text=True, encoding="utf-8", errors="ignore",
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        body = json.dumps({"ok": r.returncode == 0, "out": (r.stdout or r.stderr)[-500:]}).encode()
        self.send_response(200 if r.returncode == 0 else 500)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class OneServer(ThreadingHTTPServer):
    """Only one copy may own the port: the 5-minute watchdog task starts this script again and again,
    and a second copy must fail to bind and quit (Windows would otherwise let it share the port)."""
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


if __name__ == "__main__":
    try:
        server = OneServer(("127.0.0.1", PORT), Handler)
    except OSError:
        sys.exit(0)                                                   # already running: nothing to do
    server.serve_forever()
