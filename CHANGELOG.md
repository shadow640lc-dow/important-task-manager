# Changelog

## [1.0.0] - 2026-11-21

First public release.

### Added

- Desktop task manager with priorities, due dates and optional due times.
- Nine filter views, full-text search, four sort orders.
- Recurring tasks (daily, weekly, monthly) with automatic roll-forward and
  month-end clamping.
- Desktop reminders with per-occurrence deduplication.
- Edit dialog, reopen, bulk clear completed, JSON and CSV export.
- Persisted window size, filter and reminder preferences.
- Keyboard shortcuts for new task, search, edit, delete and refresh.

### Changed

- Task data now lives in the per-user application data directory instead of
  next to the source code, so installed builds can save. A database from an
  older checkout is migrated automatically on first launch.
- Notifications now work on macOS (osascript) and Windows (PowerShell toast)
  as well as Linux (notify-send), and a missing notifier reports an
  actionable message instead of failing silently.
- SQLite connections are closed after every operation and use WAL mode with
  a busy timeout, so repeated use no longer leaks file handles.

### Packaging

- `pyproject.toml` with an `important-task-manager` entry point.
- PyInstaller spec, Linux desktop entry and icon.
- GitHub Actions CI (lint + tests on Linux, macOS and Windows) and a tagged
  release workflow that publishes standalone binaries.
