import json
import os
import shutil
from datetime import datetime

from conftest import DAY, PROMPTS, run_my_day


def test_builds_day_page_and_data(built_day):
    clock, day = built_day
    assert (clock / "days" / f"my-day-{day}.html").is_file()
    assert (clock / "index.html").is_file()
    data = json.loads((clock / "days" / f"{day}.json").read_text(encoding="utf-8"))
    assert [p["name"] for p in data["projects"]] == ["demo-proj"]
    assert data["union"]["all"] == 300                                 # two prompts 5 minutes apart
    assert [x[2] for x in data["projects"][0]["prompts"]] == list(PROMPTS)
    assert data["projects"][0]["rows"][0]["ticket"] == "ABC-123"


def test_summary_lists_the_day(built_day):
    clock, day = built_day
    summary = json.loads((clock / "days" / "summary.json").read_text(encoding="utf-8"))
    assert list(summary) == [DAY]
    assert summary[day]["projects"][0][0] == "demo-proj"


def test_unreadable_summary_is_logged_and_rebuilt(built_day, tmp_path):
    clock = tmp_path / "clock"
    shutil.copytree(built_day[0], clock, ignore=shutil.ignore_patterns("days", "index.html", "clock.log"))
    (clock / "days").mkdir()
    (clock / "days" / "summary.json").write_text("{ not json", encoding="utf-8")
    result = run_my_day(clock)
    assert result.returncode == 0, result.stderr
    assert "cannot read" in (clock / "clock.log").read_text(encoding="utf-8")
    assert list(json.loads((clock / "days" / "summary.json").read_text(encoding="utf-8"))) == [DAY]


def test_build_survives_an_unopenable_log_file(built_day, tmp_path):
    clock = tmp_path / "clock"
    shutil.copytree(built_day[0], clock, ignore=shutil.ignore_patterns("days", "index.html", "clock.log"))
    (clock / "clock.log").mkdir()                                      # opening a folder as the log file raises OSError
    result = run_my_day(clock)
    assert result.returncode == 0, result.stderr
    assert (clock / "days" / f"{DAY}.json").is_file()


def projects_built(clock):
    return [p["name"] for p in json.loads((clock / "days" / f"{DAY}.json").read_text(encoding="utf-8"))["projects"]]


def test_unreadable_history_sources_are_skipped(fresh_clock):
    home = fresh_clock.parent
    (home / ".copilot").mkdir()
    (home / ".copilot" / "session-store.db").write_text("this is not a sqlite database", encoding="utf-8")
    workspace = home / "AppData" / "Code" / "User" / "workspaceStorage" / "w"
    (workspace / "chatSessions").mkdir(parents=True)
    (workspace / "workspace.json").write_text("{ not json", encoding="utf-8")
    chat = workspace / "chatSessions" / "c.jsonl"
    chat.write_text(json.dumps({"kind": 0, "v": {"requests": [{"timestamp": "abc", "message": {"text": "x"}}]}}), encoding="utf-8")
    stamp = datetime.fromisoformat(f"{DAY}T12:00:00").timestamp()
    os.utime(chat, (stamp, stamp))
    result = run_my_day(fresh_clock)
    assert result.returncode == 0, result.stderr
    assert projects_built(fresh_clock) == ["demo-proj"]
    assert "skipping the Copilot session store" in (fresh_clock / "clock.log").read_text(encoding="utf-8")


def test_json_lines_that_are_not_objects_are_skipped(fresh_clock):
    session = fresh_clock.parent / ".claude" / "projects" / "p" / "s.jsonl"
    first, _, last = session.read_text(encoding="utf-8").splitlines()
    session.write_text("\n".join([first, "[]", "123", '"x"', last]), encoding="utf-8")
    stamp = datetime.fromisoformat(f"{DAY}T12:00:00").timestamp()
    os.utime(session, (stamp, stamp))
    result = run_my_day(fresh_clock)
    assert result.returncode == 0, result.stderr
    data = json.loads((fresh_clock / "days" / f"{DAY}.json").read_text(encoding="utf-8"))
    assert [x[2] for x in data["projects"][0]["prompts"]] == list(PROMPTS)
