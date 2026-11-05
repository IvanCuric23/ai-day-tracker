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


def add_vscode_chat(home, name, workspace, requests):
    """One VS Code chat session file (touched on DAY) under workspaceStorage/<name>, with its workspace.json."""
    folder = home / "AppData" / "Code" / "User" / "workspaceStorage" / name
    (folder / "chatSessions").mkdir(parents=True)
    (folder / "workspace.json").write_text(json.dumps(workspace), encoding="utf-8")
    chat = folder / "chatSessions" / "c.jsonl"
    chat.write_text(json.dumps({"kind": 0, "v": {"requests": requests}}), encoding="utf-8")
    stamp = datetime.fromisoformat(f"{DAY}T12:00:00").timestamp()
    os.utime(chat, (stamp, stamp))


def test_malformed_vscode_entries_are_skipped_and_valid_ones_kept(fresh_clock):
    def millis(hhmm):
        return int(datetime.fromisoformat(f"{DAY}T{hhmm}:00").timestamp() * 1000)

    home = fresh_clock.parent
    add_vscode_chat(home, "w1", {"folder": "file:///C:/VS/vs-proj"},
                    [{"timestamp": millis("11:00"), "message": {"text": "vs prompt"}},
                     {"timestamp": millis("11:05"), "message": ["not", "an", "object"]}])
    add_vscode_chat(home, "w2", {"folder": 5}, [{"timestamp": millis("12:00"), "message": {"text": "no folder"}}])
    result = run_my_day(fresh_clock)
    assert result.returncode == 0, result.stderr
    data = json.loads((fresh_clock / "days" / f"{DAY}.json").read_text(encoding="utf-8"))
    prompts = {p["name"]: [x[2] for x in p["prompts"]] for p in data["projects"]}
    assert prompts["vs-proj"] == ["vs prompt"]
    assert prompts["Other (no project folder)"] == ["no folder"]
    assert prompts["demo-proj"] == list(PROMPTS)


def test_clock_lines_are_read_from_the_clock_file_variable(fresh_clock):
    log = fresh_clock.parent / "clock.jsonl"                    # where conftest points CLOCK_FILE, not ~/.claude/clock
    log.write_text(json.dumps({"time": f"{DAY}T10:00:00", "event": "start", "tool": "Claude", "session": "s1234567",
                               "project": "demo-proj"}) + "\n", encoding="utf-8")
    result = run_my_day(fresh_clock)
    assert result.returncode == 0, result.stderr
    day = json.loads((fresh_clock / "days" / f"{DAY}.json").read_text(encoding="utf-8"))
    assert [(c["tool"], c["session"], c["start"]) for c in day["clock"]] == [("Claude", "s1234567", "10:00")]


def test_dashboard_shows_the_installed_version_when_version_file_exists(fresh_clock):
    (fresh_clock / "VERSION").write_text("1.2.3\n", encoding="utf-8")
    assert run_my_day(fresh_clock).returncode == 0
    assert '<div class="ver">v1.2.3</div>' in (fresh_clock / "index.html").read_text(encoding="utf-8")


def test_dashboard_builds_without_a_version_file_and_shows_no_version(fresh_clock):
    assert not (fresh_clock / "VERSION").exists()
    assert run_my_day(fresh_clock).returncode == 0
    page = (fresh_clock / "index.html").read_text(encoding="utf-8")
    assert 'class="ver"' not in page and "<!--VERSION-->" not in page


def test_dashboard_escapes_the_version_text(fresh_clock):
    (fresh_clock / "VERSION").write_text("<b>&", encoding="utf-8")
    assert run_my_day(fresh_clock).returncode == 0
    page = (fresh_clock / "index.html").read_text(encoding="utf-8")
    assert '<div class="ver">v&lt;b&gt;&amp;</div>' in page
    assert '<div class="ver">v<b>&' not in page
