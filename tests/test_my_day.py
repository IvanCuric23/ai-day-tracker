import json

from conftest import DAY, PROMPTS


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
