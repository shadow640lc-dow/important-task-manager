"""Tests for deployment behaviour: data location, connections, notifiers."""

import sqlite3

import pytest

import database
import notifications


# ----------------------------------------------------------------------
# Data location
# ----------------------------------------------------------------------
def test_data_dir_honours_environment_override(monkeypatch, tmp_path):
    monkeypatch.setenv("ITM_DATA_DIR", str(tmp_path / "custom"))

    assert database.default_data_dir() == tmp_path / "custom"


def test_data_dir_uses_xdg_on_linux(monkeypatch, tmp_path):
    monkeypatch.delenv("ITM_DATA_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(database.sys, "platform", "linux")

    assert (
        database.default_data_dir()
        == tmp_path / "ImportantTaskManager"
    )


def test_data_dir_uses_app_support_on_macos(monkeypatch):
    monkeypatch.delenv("ITM_DATA_DIR", raising=False)
    monkeypatch.setattr(database.sys, "platform", "darwin")

    assert database.default_data_dir() == (
        database.Path.home()
        / "Library"
        / "Application Support"
        / "ImportantTaskManager"
    )


def test_db_path_can_be_overridden(monkeypatch, tmp_path):
    target = tmp_path / "elsewhere.db"
    monkeypatch.setenv("ITM_DB_PATH", str(target))

    assert database.default_db_path() == target


# ----------------------------------------------------------------------
# Connections
# ----------------------------------------------------------------------
def test_connection_is_closed_after_use(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "closed.db")

    database.initialize_database()

    with database.connection() as conn:
        conn.execute("SELECT 1")

    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_connection_rolls_back_on_error(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "rollback.db")
    database.initialize_database()

    with pytest.raises(RuntimeError), database.connection() as conn:
        conn.execute(
            "INSERT INTO tasks (title) VALUES ('half written')"
        )
        raise RuntimeError("stop")

    with database.connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM tasks"
        ).fetchone()[0]

    assert count == 0


def test_initialize_database_can_run_twice(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "twice.db")

    database.initialize_database()
    database.initialize_database()

    with database.connection() as conn:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(tasks)")
        }

    assert "last_notified_at" in columns


# ----------------------------------------------------------------------
# Legacy migration
# ----------------------------------------------------------------------
def make_legacy_db(path):
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT)"
    )
    conn.execute("INSERT INTO tasks (title) VALUES ('old task')")
    conn.commit()
    conn.close()


def test_legacy_database_is_migrated(monkeypatch, tmp_path):
    legacy = tmp_path / "checkout" / "data" / "tasks.db"
    make_legacy_db(legacy)

    target = tmp_path / "user" / "tasks.db"

    monkeypatch.setattr(database, "LEGACY_DB_PATH", legacy)
    monkeypatch.setattr(database, "DB_PATH", target)
    monkeypatch.setattr(database, "DEFAULT_DB_PATH", target)

    assert database.migrate_legacy_database() is True
    assert target.is_file()

    conn = sqlite3.connect(target)
    title = conn.execute("SELECT title FROM tasks").fetchone()[0]
    conn.close()

    assert title == "old task"

    # A second launch must not overwrite the migrated copy.
    assert database.migrate_legacy_database() is False


def test_legacy_database_is_ignored_for_redirected_paths(
    monkeypatch, tmp_path
):
    legacy = tmp_path / "checkout" / "data" / "tasks.db"
    make_legacy_db(legacy)

    monkeypatch.setattr(database, "LEGACY_DB_PATH", legacy)
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "portable.db")
    monkeypatch.setattr(
        database, "DEFAULT_DB_PATH", tmp_path / "default.db"
    )

    assert database.migrate_legacy_database() is False
    assert not (tmp_path / "portable.db").exists()


# ----------------------------------------------------------------------
# Notification backends
# ----------------------------------------------------------------------
def test_linux_notification_uses_notify_send(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))

    monkeypatch.setattr(notifications.subprocess, "run", fake_run)
    monkeypatch.setattr(notifications.sys, "platform", "linux")

    notifications.send_notification("Title", "Body")

    command, kwargs = calls[0]

    assert command[0] == "notify-send"
    assert "Title" in command
    assert "Body" in command
    assert kwargs["check"] is True
    assert kwargs["timeout"] > 0


def test_macos_notification_uses_osascript(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)

    monkeypatch.setattr(notifications.subprocess, "run", fake_run)
    monkeypatch.setattr(notifications.sys, "platform", "darwin")

    notifications.send_notification("Title", "Body", urgency="critical")

    command = calls[0]

    assert command[0] == "osascript"
    # Message, app name and task title are passed as argv, never
    # interpolated into the AppleScript source.
    assert command[-3:] == ["Body", "Important Task Manager", "Title"]


def test_windows_notification_uses_powershell(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))

    monkeypatch.setattr(notifications.subprocess, "run", fake_run)
    monkeypatch.setattr(notifications.sys, "platform", "win32")

    notifications.send_notification("Title", "Body")

    command, kwargs = calls[0]

    assert command[0] == "powershell"
    assert "-NoProfile" in command
    assert kwargs["env"]["ITM_NOTIFICATION_TITLE"] == "Title"
    assert kwargs["env"]["ITM_NOTIFICATION_MESSAGE"] == "Body"
    assert "Title" not in " ".join(command)


def test_missing_notify_send_raises_actionable_error(monkeypatch):
    def boom(command, **kwargs):
        raise FileNotFoundError("notify-send")

    monkeypatch.setattr(notifications.subprocess, "run", boom)
    monkeypatch.setattr(notifications.sys, "platform", "linux")

    with pytest.raises(RuntimeError, match="notify-send"):
        notifications.send_notification("Title", "Body")


def test_invalid_urgency_is_rejected_before_dispatch(monkeypatch):
    def boom(command, **kwargs):
        pytest.fail("no backend should run")

    monkeypatch.setattr(notifications.subprocess, "run", boom)

    with pytest.raises(ValueError):
        notifications.send_notification("Title", "Body", urgency="loud")
