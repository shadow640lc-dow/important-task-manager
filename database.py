"""SQLite storage for Important Task Manager.

The database lives in the per-user application data directory so an
installed (possibly read-only) copy of the app can still save tasks.
Set ``ITM_DATA_DIR`` to relocate the directory, or ``ITM_DB_PATH`` to
point at a specific database file.
"""

import os
import shutil
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

APP_DIR_NAME = "ImportantTaskManager"

BASE_DIR = Path(__file__).resolve().parent

LEGACY_DB_PATH = BASE_DIR / "data" / "tasks.db"


def default_data_dir():
    """Return the per-user directory that should hold the database."""

    override = os.environ.get("ITM_DATA_DIR")
    if override:
        return Path(override).expanduser()

    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if root:
            return Path(root) / APP_DIR_NAME
        return Path.home() / "AppData" / "Local" / APP_DIR_NAME

    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / APP_DIR_NAME
        )

    root = os.environ.get("XDG_DATA_HOME")
    if root:
        return Path(root).expanduser() / APP_DIR_NAME

    return Path.home() / ".local" / "share" / APP_DIR_NAME


def default_db_path():
    """Return the database file path used unless one is overridden."""

    override = os.environ.get("ITM_DB_PATH")
    if override:
        return Path(override).expanduser()

    return default_data_dir() / "tasks.db"


DATA_DIR = default_data_dir()
DEFAULT_DB_PATH = default_db_path()
DB_PATH = DEFAULT_DB_PATH


def get_connection():
    # Create the directory DB_PATH points at, rather than the fixed
    # module-level DATA_DIR. Tests redirect DB_PATH to a temporary
    # file, and must not create or touch anything inside the
    # user's real data directory.
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row

    # WAL plus a busy timeout keeps a second copy of the app (or a
    # backup script) from failing with "database is locked".
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")

    return conn


@contextmanager
def connection():
    """Yield a connection, commit on success, and always close it.

    ``sqlite3.Connection`` used as a context manager commits or rolls
    back but never closes, so every ``with get_connection()`` call used
    to leak a file handle. On Windows those leaked handles keep the
    database file locked after the app exits.
    """

    conn = get_connection()

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def migrate_legacy_database():
    """Copy a database from an older source checkout into the data dir.

    Returns True when a copy was made. Only applies to the default
    location, so a redirected ``DB_PATH`` (tests, portable installs)
    never pulls in the checkout's own data.
    """

    if DB_PATH != DEFAULT_DB_PATH:
        return False

    if not LEGACY_DB_PATH.is_file() or DB_PATH.exists():
        return False

    if LEGACY_DB_PATH.resolve() == DB_PATH.resolve():
        return False

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(LEGACY_DB_PATH, DB_PATH)

    return True


def initialize_database():
    migrate_legacy_database()

    with connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                due_date TEXT,
                due_time TEXT,
                priority TEXT NOT NULL DEFAULT 'Normal',
                completed INTEGER NOT NULL DEFAULT 0,
                recurring INTEGER NOT NULL DEFAULT 0,
                recurrence TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                last_notified_at TEXT
            )
        """)

        # Upgrade databases created by the earlier schema.
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(tasks)")
        }

        if "last_notified_at" not in columns:
            conn.execute(
                "ALTER TABLE tasks ADD COLUMN last_notified_at TEXT"
            )


if __name__ == "__main__":
    initialize_database()
    print(f"Database initialized: {DB_PATH}")
