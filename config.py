"""Shared configuration for Important Task Manager.

This module deliberately has no Qt imports so it can be used by the
database, scheduler, notification, and test code safely.
"""

APP_NAME = "Important Task Manager"

# Shown in the window title and used for packaged releases.
APP_VERSION = "1.1.0"

PROJECT_URL = "https://github.com/shadow640lc-dow/important-task-manager"

# How often the GUI checks the database for tasks that need a
# desktop reminder (seconds).
REMINDER_INTERVAL_SECONDS = 30

# Window size used the first time the app is opened.
DEFAULT_WINDOW_WIDTH = 1250
DEFAULT_WINDOW_HEIGHT = 800

# Earliest due date offered by the date pickers.
MIN_DUE_YEAR = 2000

# Identity used by QSettings to persist window/filter state.
SETTINGS_ORG = "ImportantTaskManager"
SETTINGS_APP = "ImportantTaskManager"

# Monospaced families tried in order. Fixed-pitch text is what keeps
# the task rows' columns aligned; DejaVu Sans Mono is Linux-only.
MONOSPACE_FONTS = [
    "DejaVu Sans Mono",
    "Menlo",
    "Consolas",
    "Liberation Mono",
    "Courier New",
]

# Terminal-green palette.
GREEN = "#00ff66"
GREEN_DIM = "#00aa44"
GREEN_DARK = "#003d1c"
CYAN = "#00ffd5"
RED = "#ff3030"
BLACK = "#020604"
AMBER = "#ffcc33"
MUTED = "#447755"
