"""Adds or removes the clock hooks for Claude Code and GitHub Copilot CLI. Called by install.ps1 / uninstall.ps1.

    python setup_hooks.py install   --python <python.exe> [--claude] [--copilot]
    python setup_hooks.py uninstall

Claude Code: merges four hooks into ~/.claude/settings.json (a backup is written first; your other hooks stay).
Copilot CLI: writes its own file ~/.copilot/hooks/clock.json.
Running install twice is safe: old clock hooks are replaced, never doubled.
"""
import json
import os
import sys
from datetime import datetime

HOME = os.path.expanduser("~")
CLOCK = os.path.join(HOME, ".claude", "hooks", "clock.py")
CLAUDE_SETTINGS = os.path.join(HOME, ".claude", "settings.json")
COPILOT_FILE = os.path.join(HOME, ".copilot", "hooks", "clock.json")
CLAUDE_EVENTS = [("SessionStart", "start"), ("UserPromptSubmit", "prompt"), ("Stop", "stop"), ("SessionEnd", "end")]
COPILOT_EVENTS = [("sessionStart", "start"), ("userPromptSubmitted", "prompt"), ("postToolUse", "work"),
                  ("sessionEnd", "end")]


def is_clock(hook):
    """True for a hook that runs clock.py (ours, from any earlier install)."""
    text = " ".join([str(hook.get("command", ""))] + [str(a) for a in hook.get("args", [])])
    return "/hooks/clock.py" in text.replace("\\", "/").lower()


def read_settings():
    if not os.path.exists(CLAUDE_SETTINGS):
        return {}, "\n"
    raw = open(CLAUDE_SETTINGS, "rb").read()
    text = raw.decode("utf-8-sig")
    return (json.loads(text) if text.strip() else {}), ("\r\n" if b"\r\n" in raw else "\n")


def write_settings(settings, newline):
    os.makedirs(os.path.dirname(CLAUDE_SETTINGS), exist_ok=True)
    if os.path.exists(CLAUDE_SETTINGS):
        backup = f"{CLAUDE_SETTINGS}.bak-ai-day-tracker-{datetime.now():%Y%m%d-%H%M%S}"
        open(backup, "wb").write(open(CLAUDE_SETTINGS, "rb").read())
        print(f"  backup: {backup}")
    text = json.dumps(settings, indent=2, ensure_ascii=False) + "\n"
    with open(CLAUDE_SETTINGS, "w", encoding="utf-8", newline="") as f:
        f.write(text.replace("\n", newline))


def remove_clock_hooks(settings):
    """Drops every clock.py hook; groups and events left empty are dropped too. Returns how many were removed."""
    removed = 0
    hooks = settings.get("hooks") or {}
    for event in list(hooks):
        groups = []
        for group in hooks[event]:
            keep = [h for h in group.get("hooks", []) if not is_clock(h)]
            removed += len(group.get("hooks", [])) - len(keep)
            if keep:
                groups.append({**group, "hooks": keep})
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    if "hooks" in settings and not hooks:
        del settings["hooks"]
    return removed


def install_claude(python):
    settings, newline = read_settings()
    remove_clock_hooks(settings)
    hooks = settings.setdefault("hooks", {})
    for event, arg in CLAUDE_EVENTS:
        hooks.setdefault(event, []).append(
            {"hooks": [{"type": "command", "command": python, "args": [CLOCK, "claude", arg], "timeout": 10}]})
    write_settings(settings, newline)
    print(f"  Claude Code hooks added to {CLAUDE_SETTINGS}")


def install_copilot(python):
    def ps_quote(s):
        return "'" + s.replace("'", "''") + "'"

    def sh_path(p):
        p = p.replace("\\", "/")
        return "'" + (f"/{p[0].lower()}{p[2:]}" if len(p) > 1 and p[1] == ":" else p) + "'"

    hooks = {event: [{"type": "command",
                      "powershell": f"& {ps_quote(python)} {ps_quote(CLOCK)} copilot {arg}",
                      "bash": f"{sh_path(python)} {sh_path(CLOCK)} copilot {arg}",
                      "timeoutSec": 10}]
             for event, arg in COPILOT_EVENTS}
    os.makedirs(os.path.dirname(COPILOT_FILE), exist_ok=True)
    json.dump({"version": 1, "hooks": hooks}, open(COPILOT_FILE, "w", encoding="utf-8"), indent=2)
    print(f"  Copilot CLI hooks written to {COPILOT_FILE}")


def uninstall():
    settings, newline = read_settings()
    n = remove_clock_hooks(settings)
    if n:
        write_settings(settings, newline)
        print(f"  removed {n} Claude Code hooks from {CLAUDE_SETTINGS}")
    if os.path.exists(COPILOT_FILE):
        os.remove(COPILOT_FILE)
        print(f"  removed {COPILOT_FILE}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["install"] and "--python" in args:
        py = args[args.index("--python") + 1]
        if "--claude" in args:
            install_claude(py)
        if "--copilot" in args:
            install_copilot(py)
    elif args[:1] == ["uninstall"]:
        uninstall()
    else:
        sys.exit(__doc__)
