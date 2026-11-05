# Changelog

All notable changes to this project are listed here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [1.2.0] - 2026-11-05

### Changed
- The day page's **When** timeline follows the **Only 7:00–19:00** filter: ticked, it shows only the working hours; unticked, the whole day.

## [1.1.0] - 2026-11-05

### Added
- Check for update button in the dashboard.

## [1.0.0] - 2026-11-05

### Added
- Calendar dashboard at `http://localhost:8800`: hours per day, and per day when you worked, time per project and ticket, what you asked and what you committed.
- Hooks for Claude Code and GitHub Copilot CLI that record live session activity; VS Code Copilot Chat history is read as well.
- Scheduled task **My AI day** that calculates the day at 17:00 (Mon-Fri), and a **Refresh today** button for any time.
- Scheduled task **My AI dashboard server** that keeps the dashboard running on `localhost` only.
- Double-click `install.cmd` and `uninstall.cmd`; running the installer again updates the scripts and keeps your data and settings.
- Ticket detection from branch names, commit branches and `tickets.json`, with links for Jira and Azure DevOps.
- `docs/how-it-works.md` for maintainers, a beginner install guide and a dashboard screenshot in the README.

### Changed
- The Copilot hook is lighter: per-tool events skip the git branch lookup and leave project, branch and ticket out.
- The 17:00 run trims hook log lines older than 90 days; it never drops a new hook line or a line it cannot parse.
- Project folder names are shown as they are.

### Fixed
- `my_day.py` reads the hook log from the same `CLOCK_FILE` path as the hook and `daily.py`.
- Unreadable history sources and malformed VS Code entries are skipped instead of failing the day.
