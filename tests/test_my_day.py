import json
import shutil

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
