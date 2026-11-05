import io
import json
import subprocess
import sys
from datetime import datetime

import pytest
from conftest import ROOT, home_env

HOOK = ROOT / "src" / "hooks" / "clock.py"


@pytest.fixture
def clock(isolated_home, load_module):
    module = load_module(HOOK, "hook_clock")
    (isolated_home / "tickets.json").write_text(
        json.dumps({"feature/my-branch": "ABC-123", "feature/devops": "DevOps #116", "project:demo": "ZZ-9"}),
        encoding="utf-8")
    module.TICKETS_FILE = str(isolated_home / "tickets.json")
    return module


def feed_stdin(monkeypatch, payload: bytes) -> None:
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(payload)))


def test_ticket_from_tickets_file(clock):
    assert clock.ticket("feature/my-branch") == ("ABC-123", "Jira")
    assert clock.ticket("feature/devops") == ("116", "DevOps")


def test_ticket_from_key_in_branch_name(clock):
    assert clock.ticket("feature/ORQA-42-login") == ("ORQA-42", "Jira")
    assert clock.ticket("feature/1234-login") == ("1234", "DevOps")


def test_ticket_folder_rule_and_none(clock):
    assert clock.ticket("main", "demo") == ("ZZ-9", "Jira")
    assert clock.ticket("main", "other") == ("", "")


def test_short_collapses_whitespace_and_truncates(clock):
    assert clock.short("a \n  b") == "a b"
    assert len(clock.short("x" * 500)) == clock.TEXT
    assert clock.short(None) == ""


def test_line_has_documented_fields(clock):
    row = clock.line(datetime(2026, 3, 10, 10, 0), "prompt", "Claude", "abcdef123456", "", "feature/ABC-1-x", ask="hi", did="")
    assert row["time"] == "2026-03-10T10:00:00"
    assert (row["event"], row["tool"], row["session"]) == ("prompt", "Claude", "abcdef12")
    assert (row["ticket"], row["system"], row["ask"]) == ("ABC-1", "Jira", "hi")
    assert "did" not in row                                            # empty extras are dropped


def test_unreadable_tickets_file_and_transcript_give_defaults(clock, isolated_home):
    (isolated_home / "tickets.json").write_text("{ not json", encoding="utf-8")
    assert clock.tickets() == {}
    assert clock.last_answer(str(isolated_home / "missing.jsonl")) == ("", "")


def test_hook_appends_one_row(clock, isolated_home, monkeypatch):
    feed_stdin(monkeypatch, json.dumps({"cwd": str(isolated_home), "session_id": "s1234567890", "prompt": "do it"}).encode())
    clock.hook("Claude", "prompt")
    rows = [json.loads(x) for x in (isolated_home / "clock.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert (rows[0]["event"], rows[0]["session"], rows[0]["ask"]) == ("prompt", "s1234567", "do it")


def test_hook_with_invalid_stdin_still_writes_a_row_and_prints_nothing(clock, isolated_home, monkeypatch, capsys):
    feed_stdin(monkeypatch, b"not json {{{")
    clock.hook("Claude", "prompt")
    out = capsys.readouterr()
    assert (out.out, out.err) == ("", "")
    assert len((isolated_home / "clock.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_work_event_writes_a_bare_row_without_running_git_or_project(clock, isolated_home, monkeypatch):
    def forbidden(*args):
        raise AssertionError("a work event must not run git or look up the project")
    monkeypatch.setattr(clock, "git", forbidden)
    monkeypatch.setattr(clock, "project", forbidden)
    feed_stdin(monkeypatch, json.dumps({"cwd": str(isolated_home), "session_id": "s1234567890"}).encode())
    clock.hook("Copilot", "work")
    rows = [json.loads(x) for x in (isolated_home / "clock.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(r["event"], r["tool"], r["session"], r["project"], r["branch"], r["ticket"], r["system"]) for r in rows] \
        == [("work", "Copilot", "s1234567", "", "", "", "")]
    assert rows[0]["cwd"] == str(isolated_home)


def test_git_with_nul_in_cwd_returns_empty(clock):
    assert clock.git("bad\0dir", "status") == ""


def test_script_never_fails_or_prints(tmp_path):
    result = subprocess.run([sys.executable, "-X", "utf8", str(HOOK), "claude", "prompt"], input=b"\xff\xfe garbage {{{",
                            capture_output=True, cwd=tmp_path, env=home_env(tmp_path), timeout=30)
    assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")


def test_script_error_is_logged_not_printed(tmp_path):
    result = subprocess.run([sys.executable, "-X", "utf8", str(HOOK), "backfill", "not-a-date"],
                            capture_output=True, cwd=tmp_path, env=home_env(tmp_path), timeout=30)
    assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")
    assert "ValueError" in (tmp_path / "clock.log").read_text(encoding="utf-8")


def test_script_stays_silent_when_log_folder_cannot_be_created(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, so its child folder cannot be made", encoding="utf-8")
    env = home_env(tmp_path, CLOCK_FILE=str(blocker / "clock.jsonl"))
    result = subprocess.run([sys.executable, "-X", "utf8", str(HOOK), "backfill", "not-a-date"], input=b"",
                            capture_output=True, cwd=tmp_path, env=env, timeout=30)
    assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")


def test_last_answer_skips_json_lines_that_are_not_objects(clock, isolated_home):
    answer = {"type": "assistant", "message": {"model": "m1", "content": [{"type": "text", "text": "hello there\nmore"}]}}
    transcript = isolated_home / "t.jsonl"
    transcript.write_text("\n".join([json.dumps(answer), "123", "[]", '"x"']), encoding="utf-8")
    assert clock.last_answer(str(transcript)) == ("hello there", "m1")
