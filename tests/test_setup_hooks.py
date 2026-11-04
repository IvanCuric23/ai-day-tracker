import json

import pytest
from conftest import ROOT

FOREIGN = {"type": "command", "command": "other-tool"}


@pytest.fixture
def setup(isolated_home, load_module):
    module = load_module(ROOT / "src" / "setup_hooks.py", "setup_hooks")
    module.CLAUDE_SETTINGS = str(isolated_home / "settings.json")
    return module


def test_remove_clock_hooks_keeps_foreign_hook(setup):
    clock = {"type": "command", "command": "python", "args": ["C:\\Users\\x\\.claude\\hooks\\clock.py", "claude", "stop"]}
    settings = {"hooks": {"Stop": [{"hooks": [clock, FOREIGN]}], "SessionEnd": [{"hooks": [clock]}]}, "other": 1}
    assert setup.remove_clock_hooks(settings) == 2
    assert settings == {"hooks": {"Stop": [{"hooks": [FOREIGN]}]}, "other": 1}


def test_install_claude_twice_leaves_each_event_once(setup, isolated_home):
    (isolated_home / "settings.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [FOREIGN]}]}}), encoding="utf-8")
    setup.install_claude("python.exe")
    setup.install_claude("python.exe")
    hooks = json.loads((isolated_home / "settings.json").read_text(encoding="utf-8"))["hooks"]
    assert sorted(hooks) == ["SessionEnd", "SessionStart", "Stop", "UserPromptSubmit"]
    assert all(sum(setup.is_clock(h) for g in groups for h in g["hooks"]) == 1 for groups in hooks.values())
    assert FOREIGN in [h for g in hooks["Stop"] for h in g["hooks"]]
