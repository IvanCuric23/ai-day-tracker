"""The 17:00 run (task "My AI day"): rebuilds yesterday and today, with no window popping up.

Yesterday is rebuilt too, so work you did after 17:00 still lands on the right day.
Afterwards the hook log (clock.jsonl) is trimmed to the last CLOCK_KEEP_DAYS days.
Errors go to days/last-run.log.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(os.path.dirname(sys.executable), "python.exe")     # started by pythonw: build with python.exe
CLOCK_FILE = os.environ.get("CLOCK_FILE") or os.path.join(HERE, "clock.jsonl")   # same resolution as the clock.py hook
CLOCK_KEEP_DAYS = 90        # the hook log only grows and my_day.py reads it whole on every build: keep a quarter


def trim_clock_log(path: str, now: datetime, keep_days: int = CLOCK_KEEP_DAYS) -> str:
    """Drops lines whose `time` parses and is older than keep_days; everything else stays. Returns a log message."""
    cutoff = now.astimezone() - timedelta(days=keep_days)
    kept, dropped = [], 0
    tmp = path + ".tmp"
    try:
        with open(path, encoding="utf-8", errors="surrogateescape", newline="") as f:
            for raw in f:
                try:
                    old = datetime.fromisoformat(json.loads(raw)["time"]).astimezone() < cutoff
                except (ValueError, KeyError, TypeError, AttributeError, OverflowError, OSError):
                    old = False                  # unparseable or out of range (year 0001): keep it
                if old:
                    dropped += 1
                else:
                    kept.append(raw)
            seen = os.fstat(f.fileno())
        if dropped:
            with open(tmp, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
                f.writelines(kept)
            now_on_disk = os.stat(path)          # a hook appended meanwhile: replacing would lose that line
            if (now_on_disk.st_size, now_on_disk.st_mtime_ns) != (seen.st_size, seen.st_mtime_ns):
                return "clock log busy, trimmed next run"
            os.replace(tmp, path)
    except FileNotFoundError:
        return "clock log: none to trim"
    except OSError as e:
        return f"clock log: trim failed ({e})"
    finally:
        try:
            os.remove(tmp)                       # gone after a replace; left over after a failure or a busy log
        except OSError:
            pass
    return f"clock log: dropped {dropped} lines older than {keep_days} days, kept {len(kept)}"


if __name__ == "__main__":
    os.makedirs(os.path.join(HERE, "days"), exist_ok=True)
    failed = 0
    with open(os.path.join(HERE, "days", "last-run.log"), "w", encoding="utf-8") as log:
        for day in ("yesterday", "today"):
            r = subprocess.run([PY, "-X", "utf8", os.path.join(HERE, "my_day.py"), day, "--no-open"],
                               capture_output=True, text=True, encoding="utf-8", errors="ignore",
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            log.write(f"{datetime.now():%Y-%m-%d %H:%M} {day}: exit {r.returncode}\n{r.stdout}{r.stderr}\n")
            failed += r.returncode != 0
        try:
            outcome = trim_clock_log(CLOCK_FILE, datetime.now())
        except Exception as e:                   # the trim must never change the run's exit code
            outcome = f"clock log: trim crashed ({type(e).__name__}: {e})"
        log.write(f"{datetime.now():%Y-%m-%d %H:%M} {outcome}\n")
    sys.exit(1 if failed else 0)
