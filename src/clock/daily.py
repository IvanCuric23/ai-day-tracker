"""The 17:00 run (task "My AI day"): rebuilds yesterday and today, with no window popping up.

Yesterday is rebuilt too, so work you did after 17:00 still lands on the right day.
Errors go to days/last-run.log.
"""
import os, subprocess, sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(os.path.dirname(sys.executable), "python.exe")     # started by pythonw: build with python.exe
os.makedirs(os.path.join(HERE, "days"), exist_ok=True)

failed = 0
with open(os.path.join(HERE, "days", "last-run.log"), "w", encoding="utf-8") as log:
    for day in ("yesterday", "today"):
        r = subprocess.run([PY, "-X", "utf8", os.path.join(HERE, "my_day.py"), day, "--no-open"],
                           capture_output=True, text=True, encoding="utf-8", errors="ignore",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        log.write(f"{datetime.now():%Y-%m-%d %H:%M} {day}: exit {r.returncode}\n{r.stdout}{r.stderr}\n")
        failed += r.returncode != 0
sys.exit(1 if failed else 0)
