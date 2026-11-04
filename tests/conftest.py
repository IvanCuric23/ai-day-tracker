"""Shared fixtures. Every test runs against invented data in tmp_path, never the real history."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DAY = "2026-03-10"
PROMPTS = ("refactor the invoice parser", "write unit tests for it")


def home_env(home: Path, **extra: str) -> dict[str, str]:
    """Environment whose user folder is `home`, so nothing reads the real ~/.claude, ~/.copilot or APPDATA."""
    env = {**os.environ, "USERPROFILE": str(home), "HOME": str(home), "APPDATA": str(home / "AppData"),
           "CLOCK_FILE": str(home / "clock.jsonl")}
    env.update(extra)
    return env


def run_my_day(clock: Path) -> subprocess.CompletedProcess:
    """Runs the my_day.py in `clock` for DAY; the user folder is the clock folder's parent."""
    return subprocess.run([sys.executable, "-X", "utf8", str(clock / "my_day.py"), DAY, "--no-open"],
                          capture_output=True, text=True, encoding="utf-8", env=home_env(clock.parent), timeout=60)


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Points USERPROFILE, HOME, APPDATA and CLOCK_FILE at tmp_path and returns it."""
    for key, value in home_env(tmp_path).items():
        monkeypatch.setenv(key, value)
    return tmp_path


@pytest.fixture
def load_module():
    """Loads a module by file path (src/hooks/clock.py and the src/clock/ folder share a name)."""
    def load(path: Path, name: str):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    return load


@pytest.fixture(scope="session")
def built_day(tmp_path_factory):
    """Runs my_day.py end to end on one invented Claude session; returns (clock folder, date)."""
    home = tmp_path_factory.mktemp("home")
    clock = home / "clock"
    clock.mkdir()
    for name in ("my_day.py", "my_day_template.html", "dashboard_template.html", "server.py"):
        shutil.copy(ROOT / "src" / "clock" / name, clock / name)
    (clock / "config.json").write_text(
        json.dumps({"authors": ["nobody"], "reports_dir": str(home / "reports")}), encoding="utf-8")

    session = home / ".claude" / "projects" / "p" / "s.jsonl"
    session.parent.mkdir(parents=True)
    rows = [{"type": "user", "timestamp": f"{DAY}T10:0{i * 5}:00", "cwd": "C:\\VS\\demo-proj", "gitBranch": "feature/ABC-123-x",
             "message": {"content": text}} for i, text in enumerate(PROMPTS)]
    lines = [json.dumps(rows[0]), "this line is not json {{{", json.dumps(rows[1])]        # a bad line is skipped
    session.write_text("\n".join(lines), encoding="utf-8")
    stamp = datetime.fromisoformat(f"{DAY}T12:00:00").timestamp()      # touched_today() filters by file mtime
    os.utime(session, (stamp, stamp))

    result = run_my_day(clock)
    assert result.returncode == 0, result.stderr
    return clock, DAY
