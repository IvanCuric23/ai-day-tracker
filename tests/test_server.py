import pytest
from conftest import DAY, PROMPTS


@pytest.fixture
def server(built_day, load_module):
    clock, _ = built_day
    return load_module(clock / "server.py", "clock_server")           # the copy next to the built days/


def test_search_finds_prompt_and_ticket(server):
    found = server.search("invoice")
    assert [d["day"] for d in found] == [DAY]
    assert ("asked", f"10:00 {PROMPTS[0]}") in [(h["kind"], h["text"]) for h in found[0]["hits"]]
    assert any(h["kind"] == "ticket" for h in server.search("ABC-123")[0]["hits"])


def test_search_miss_and_short_query_return_nothing(server):
    assert server.search("no-such-thing-anywhere") == []
    assert server.search("a") == []
