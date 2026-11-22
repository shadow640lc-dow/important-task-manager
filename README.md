# Important Task Manager

A local-first desktop task manager with a terminal-green interface, due
dates, priorities, recurring tasks, search, CSV/JSON export and desktop
reminders. Built with Python and PySide6, stores everything in SQLite on
your own machine. No account, no cloud, no network calls.

## Features

- Add tasks with priority, optional due date and optional due time
- Nine built-in views: all, active, completed, overdue, due today, high
  priority, critical, recurring and undated
- Search across titles and notes, sort by priority, due date, title or age
- Recurring tasks (daily, weekly, monthly) roll forward automatically when
  completed, including correct month-end handling (Jan 31 -> Feb 28)
- Desktop reminders for timed tasks, checked every 30 seconds, with a
  "notified once" marker so a reminder never spams you
- Edit every field of an existing task, reopen completed tasks, bulk-clear
  completed tasks
- Export your whole list to JSON or CSV
- About dialog with the app version and a link to the project page
- Window size, filter and reminder settings persist between launches
- Keyboard-driven: `Ctrl+N`, `Ctrl+F`, `F2`, `Delete`, `F5`

## Requirements

- Python 3.9 or newer
- A desktop session (X11, Wayland, macOS or Windows)
- Linux only: `libnotify` for reminders (`sudo apt install libnotify-bin`)
  plus the usual Qt runtime libraries (`libegl1`, `libxkbcommon0`), which a
  normal desktop install already has. The Linux binary is built against
  glibc, so it targets mainstream distributions rather than musl/Alpine.

## Install

```bash
git clone https://github.com/shadow640lc-dow/important-task-manager.git
cd important-task-manager
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
```

Run it:

```bash
important-task-manager
# or, without installing:
python app.py
```

Check the installed version with `important-task-manager --version`.

## Where your data lives

Tasks are stored in one SQLite file in your user data directory:

| Platform | Path |
|---|---|
| Linux | `~/.local/share/ImportantTaskManager/tasks.db` |
| macOS | `~/Library/Application Support/ImportantTaskManager/tasks.db` |
| Windows | `%LOCALAPPDATA%\ImportantTaskManager\tasks.db` |

On first launch, a `data/tasks.db` left over from an older source checkout
is copied there automatically, so existing tasks are not lost.

Overrides, useful for portable installs and backups:

```bash
ITM_DATA_DIR=/path/to/folder important-task-manager
ITM_DB_PATH=/path/to/tasks.db important-task-manager
```

Back up by copying that one file, or use **EXPORT...** in the app.

## Standalone builds

Prebuilt binaries for Linux, macOS and Windows are attached to each
[release](https://github.com/shadow640lc-dow/important-task-manager/releases).
Pushing a `v*` tag builds and publishes them through GitHub Actions.

Build one yourself:

```bash
pip install -e ".[build]"
pyinstaller packaging/important-task-manager.spec --noconfirm
```

The binary lands in `dist/`. On Linux, `packaging/important-task-manager.desktop`
and `packaging/important-task-manager.svg` can be installed to
`~/.local/share/applications/` and `~/.local/share/icons/hicolor/scalable/apps/`
to add a launcher entry.

## Development

```bash
pip install -e ".[dev]"
pytest            # 79+ tests, GUI tests run offscreen
ruff check .      # lint
```

Layout:

| File | Responsibility |
|---|---|
| `app.py` | Main window, filters, search, export, entry point |
| `tasks.py` | Task CRUD, recurring completion, notification markers |
| `database.py` | SQLite connection, schema, data directory, migration |
| `dialogs.py` | Edit-task dialog and shared due-date widgets |
| `scheduler.py` | Next-occurrence math and the reminder check |
| `notifications.py` | Linux/macOS/Windows notification backends |
| `config.py` | App name, version, palette, tunables |

## License

MIT. See [LICENSE](LICENSE).
