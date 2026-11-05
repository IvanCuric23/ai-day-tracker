import json
import subprocess
import sys
from datetime import datetime, timedelta

import pytest
from conftest import ROOT, home_env

DAILY = ROOT / "src" / "clock" / "daily.py"
NOW = datetime(2026, 6, 1, 17, 0).astimezone()


@pytest.fixture
def daily(load_module):
    return load_module(DAILY, "daily")


def row(days_ago: float) -> str:
    t = (NOW - timedelta(days=days_ago)).isoformat(timespec="seconds")
    return json.dumps({"time": t, "event": "work", "session": "s1"}) + "\n"


def test_trim_drops_only_lines_older_than_the_cutoff(daily, tmp_path):
    log = tmp_path / "clock.jsonl"
    old, edge, new = row(91), row(89), row(1)
    log.write_text(old + edge + new, encoding="utf-8", newline="")
    msg = daily.trim_clock_log(str(log), NOW)
    assert log.read_text(encoding="utf-8") == edge + new
    assert msg == "clock log: dropped 1 lines older than 90 days, kept 2"
    assert not (tmp_path / "clock.jsonl.tmp").exists()


def test_trim_keeps_lines_it_cannot_parse(daily, tmp_path):
    log = tmp_path / "clock.jsonl"
    odd = ["not json {{{\n", "[1, 2]\n", '{"event": "work"}\n', '{"time": "yesterday-ish"}\n', '{"time": 5}\n']
    log.write_text(row(200) + "".join(odd) + row(2), encoding="utf-8", newline="")
    daily.trim_clock_log(str(log), NOW)
    assert log.read_text(encoding="utf-8") == "".join(odd) + row(2)


def test_trim_leaves_the_file_alone_when_nothing_is_old(daily, tmp_path):
    log = tmp_path / "clock.jsonl"
    log.write_text(row(3), encoding="utf-8", newline="")
    before = log.stat().st_mtime_ns
    assert daily.trim_clock_log(str(log), NOW).startswith("clock log: dropped 0")
    assert log.stat().st_mtime_ns == before


def test_trim_reports_a_missing_log_instead_of_failing(daily, tmp_path):
    assert daily.trim_clock_log(str(tmp_path / "nope.jsonl"), NOW) == "clock log: none to trim"


def test_trim_reports_an_unwritable_log_instead_of_failing(daily, tmp_path):
    (tmp_path / "clock.jsonl.tmp").mkdir()                       # the temp file cannot be created
    log = tmp_path / "clock.jsonl"
    log.write_text(row(200), encoding="utf-8", newline="")
    assert daily.trim_clock_log(str(log), NOW).startswith("clock log: trim failed")
    assert log.read_text(encoding="utf-8") == row(200)


def test_daily_run_trims_the_log_and_notes_it_in_last_run_log(tmp_path):
    clock = tmp_path / "clock"
    clock.mkdir()
    (clock / "daily.py").write_text(DAILY.read_text(encoding="utf-8"), encoding="utf-8")
    now = datetime.now().astimezone()
    old = json.dumps({"time": (now - timedelta(days=120)).isoformat(timespec="seconds"), "event": "work"}) + "\n"
    new = json.dumps({"time": now.isoformat(timespec="seconds"), "event": "work"}) + "\n"
    (clock / "clock.jsonl").write_text(old + new, encoding="utf-8", newline="")
    subprocess.run([sys.executable, "-X", "utf8", str(clock / "daily.py")], capture_output=True, timeout=60,
                   env=home_env(tmp_path, CLOCK_FILE=str(clock / "clock.jsonl")))   # no my_day.py here: the builds fail, the trim still runs
    assert (clock / "clock.jsonl").read_text(encoding="utf-8") == new
    assert "clock log: dropped 1 lines older than 90 days, kept 1" in (clock / "days" / "last-run.log").read_text(encoding="utf-8")
