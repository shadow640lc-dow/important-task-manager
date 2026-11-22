import csv
import json
import sys
from datetime import datetime

from PySide6.QtCore import QDate, QSettings, Qt, QTime, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from config import (
    AMBER,
    APP_NAME,
    APP_VERSION,
    BLACK,
    CYAN,
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    GREEN,
    GREEN_DARK,
    GREEN_DIM,
    MONOSPACE_FONTS,
    MUTED,
    RED,
    REMINDER_INTERVAL_SECONDS,
    SETTINGS_APP,
    SETTINGS_ORG,
)
from database import initialize_database
from dialogs import (
    AboutDialog,
    EditTaskDialog,
    setup_due_widgets,
    widget_due_values,
)
from scheduler import check_due_tasks
from tasks import (
    complete_recurring_task,
    create_task,
    delete_completed_tasks,
    delete_task,
    get_overdue_tasks,
    list_tasks,
    reopen_task,
    update_task,
)

# Sidebar filters. Labels and predicates are kept together so the
# sidebar and the filtering logic can never drift apart.
FILTER_LABELS = [
    "ALL TASKS",
    "ACTIVE",
    "COMPLETED",
    "OVERDUE",
    "DUE TODAY",
    "HIGH PRIORITY",
    "CRITICAL",
    "RECURRING",
    "NO DATE",
]

SORT_ORDERS = ["PRIORITY", "DUE DATE", "TITLE", "NEWEST"]

EXPORT_FIELDS = [
    "id",
    "title",
    "description",
    "due_date",
    "due_time",
    "priority",
    "completed",
    "recurring",
    "recurrence",
    "created_at",
    "completed_at",
]

TITLE_WIDTH = 32

TASK_LIST_HEADER = (
    f"{'ST':<2}  {'TASK':<{TITLE_WIDTH}}  "
    f"[{'PRIORITY':<8}]  {'DUE':<16} MARKS"
)


def build_filters(overdue_ids, today):
    """Return ``(label, predicate)`` pairs for the sidebar."""

    predicates = {
        "ALL TASKS": lambda task: True,
        "ACTIVE": lambda task: not task["completed"],
        "COMPLETED": lambda task: task["completed"],
        "OVERDUE": lambda task: task["id"] in overdue_ids,
        "DUE TODAY": lambda task: task["due_date"] == today,
        "HIGH PRIORITY": lambda task: (
            task["priority"] == "High" and not task["completed"]
        ),
        "CRITICAL": lambda task: (
            task["priority"] == "Critical" and not task["completed"]
        ),
        "RECURRING": lambda task: (
            task["recurring"] and not task["completed"]
        ),
        "NO DATE": lambda task: not task["due_date"],
    }

    return [(label, predicates[label]) for label in FILTER_LABELS]


def format_task_row(task, overdue_ids=frozenset()):
    """Render one task as a fixed-width row for the list widget."""

    status = "\u2713" if task["completed"] else "\u25a1"

    title = task["title"]
    if len(title) > TITLE_WIDTH:
        title = title[: TITLE_WIDTH - 1] + "\u2026"

    if task["due_date"]:
        due = task["due_date"]
        if task["due_time"]:
            due += f" {task['due_time']}"
    else:
        due = "-"

    marks = []
    if task["id"] in overdue_ids and not task["completed"]:
        marks.append("OVERDUE")
    if task["recurring"]:
        marks.append("\u21bb")

    suffix = f" {' '.join(marks)}" if marks else ""

    return (
        f"{status:<2}  {title:<{TITLE_WIDTH}}  "
        f"[{task['priority']:<8}]  {due:<16}{suffix}"
    )


def sort_tasks(tasks, order):
    """Sort a copy of ``tasks`` for display."""

    if order == "DUE DATE":
        return sorted(
            tasks,
            key=lambda task: (
                task["due_date"] is None,
                task["due_date"] or "",
                task["due_time"] or "",
            ),
        )

    if order == "TITLE":
        return sorted(tasks, key=lambda task: task["title"].lower())

    if order == "NEWEST":
        return sorted(
            tasks,
            key=lambda task: task["created_at"] or "",
            reverse=True,
        )

    # PRIORITY keeps the database order, which already sorts by
    # priority, then due date, then id.
    return list(tasks)


def export_json(tasks, path):
    """Write ``tasks`` to ``path`` as pretty-printed JSON."""

    with open(path, "w", encoding="utf-8") as handle:
        json.dump(
            [{field: task.get(field) for field in EXPORT_FIELDS} for task in tasks],
            handle,
            indent=2,
            ensure_ascii=False,
        )


def export_csv(tasks, path):
    """Write ``tasks`` to ``path`` as CSV."""

    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXPORT_FIELDS)
        writer.writeheader()

        for task in tasks:
            writer.writerow({field: task.get(field) for field in EXPORT_FIELDS})


def create_settings():
    """Build the QSettings object used to persist window state."""

    return QSettings(SETTINGS_ORG, SETTINGS_APP)


def resolve_monospace_font():
    """Return the first installed monospaced family from config.

    Fixed-pitch text is what keeps the task rows aligned, and DejaVu
    Sans Mono only ships on Linux. Fall back to the platform's fixed
    font when none of the preferred families are installed.
    """

    available = set(QFontDatabase.families())

    for family in MONOSPACE_FONTS:
        if family in available:
            return family

    return QFontDatabase.systemFont(
        QFontDatabase.SystemFont.FixedFont
    ).family()


class ImportantTaskManager(QMainWindow):
    def __init__(self):
        super().__init__()

        initialize_database()

        self.mono_family = resolve_monospace_font()
        self.settings = create_settings()
        self.all_tasks = []
        self.overdue_ids = set()

        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)

        self.setStyleSheet(f"""
            QMainWindow, QWidget {{
                background-color: {BLACK};
                color: {GREEN};
                font-family: "{self.mono_family}";
            }}

            QLabel {{
                color: {GREEN};
            }}

            QLineEdit, QComboBox, QDateEdit, QTimeEdit, QPlainTextEdit {{
                background-color: #00140a;
                border: 1px solid {GREEN_DIM};
                border-radius: 4px;
                padding: 10px;
                color: {GREEN};
                selection-background-color: {GREEN};
                selection-color: black;
            }}

            QLineEdit:disabled, QComboBox:disabled,
            QDateEdit:disabled, QTimeEdit:disabled {{
                color: {MUTED};
                border-color: #07351c;
            }}

            QComboBox QAbstractItemView {{
                background-color: #00140a;
                color: {GREEN};
                selection-background-color: {GREEN_DARK};
            }}

            QPushButton {{
                background-color: #00140a;
                border: 1px solid {GREEN};
                border-radius: 4px;
                padding: 10px 18px;
                color: {GREEN};
                font-weight: bold;
            }}

            QPushButton:hover {{
                background-color: {GREEN};
                color: black;
            }}

            QPushButton:disabled {{
                border-color: #07351c;
                color: #275c3d;
                background-color: {BLACK};
            }}

            QPushButton:disabled:hover {{
                background-color: {BLACK};
                color: #275c3d;
            }}

            QCheckBox {{
                color: {GREEN};
                spacing: 8px;
                padding: 6px;
            }}

            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border: 1px solid {GREEN_DIM};
                background-color: #00140a;
                border-radius: 3px;
            }}

            QCheckBox::indicator:checked {{
                background-color: {GREEN};
                border-color: {GREEN};
            }}

            QListWidget {{
                background-color: #010b05;
                border: 1px solid {GREEN_DIM};
                color: {GREEN};
                font-size: 14px;
                outline: none;
            }}

            QListWidget::item {{
                padding: 12px;
                border-bottom: 1px solid #07351c;
            }}

            QListWidget::item:selected {{
                background-color: #06351c;
                border: 1px solid {GREEN};
            }}

            QFrame#panel {{
                background-color: #010b05;
                border: 1px solid {GREEN_DIM};
                border-radius: 6px;
            }}

            QStatusBar {{
                background-color: #010b05;
                color: {CYAN};
                border-top: 1px solid #07351c;
            }}

            QToolTip {{
                background-color: #010b05;
                color: {GREEN};
                border: 1px solid {GREEN_DIM};
            }}
        """)

        self.build_ui()

        self.reminder_timer = QTimer(self)
        self.reminder_timer.setInterval(REMINDER_INTERVAL_SECONDS * 1000)
        self.reminder_timer.timeout.connect(self.run_reminder_check)

        self.reminder_toggle.toggled.connect(self.set_reminders_enabled)

        self.restore_settings()
        self.load_tasks()

        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.update_clock)
        self.clock_timer.start(1000)
        self.update_clock()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(12)

        # HEADER
        header = QHBoxLayout()

        title = QLabel("IMPORTANT TASK MANAGER")
        title.setFont(
            QFont(self.mono_family, 26, QFont.Weight.Bold)
        )
        title.setStyleSheet(f"color: {GREEN}; padding: 6px;")

        self.reminder_toggle = QCheckBox("REMINDERS")
        self.reminder_toggle.setToolTip(
            "Send a desktop notification when a task with a "
            f"time becomes due (checked every "
            f"{REMINDER_INTERVAL_SECONDS}s)."
        )
        self.reminder_toggle.setChecked(True)

        self.clock = QLabel()
        self.clock.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.clock.setStyleSheet(
            f"color: {CYAN}; font-size: 16px; padding: 8px;"
        )

        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.reminder_toggle)
        header.addWidget(self.clock)

        root.addLayout(header)

        subtitle = QLabel(
            "> SYSTEM READY  //  PLAN > EXECUTE > COMPLETE"
        )
        subtitle.setStyleSheet(
            f"color: {GREEN_DIM}; font-size: 13px;"
        )
        root.addWidget(subtitle)

        # ADD TASK PANEL
        add_panel = QFrame()
        add_panel.setObjectName("panel")
        add_layout = QHBoxLayout(add_panel)

        self.task_input = QLineEdit()
        self.task_input.setPlaceholderText(
            "Enter a new task, then press Enter..."
        )
        self.task_input.setToolTip("Press Enter to add the task")

        self.priority_combo = QComboBox()
        self.priority_combo.addItems(["Low", "Normal", "High", "Critical"])

        self.due_check = QCheckBox("DUE")
        self.due_check.setToolTip(
            "Uncheck for a task with no due date at all"
        )

        self.date_edit = QDateEdit()
        self.time_edit = QTimeEdit()

        now = datetime.now()
        setup_due_widgets(
            self.due_check,
            self.date_edit,
            self.time_edit,
            QDate(now.year, now.month, now.day),
            True,
        )
        # Default the picker to the current time rather than the
        # --:-- sentinel used for "no time".
        self.time_edit.setTime(QTime(now.hour, now.minute))

        add_button = QPushButton("+ ADD TASK")
        add_button.clicked.connect(self.add_task)

        add_layout.addWidget(self.task_input, 4)
        add_layout.addWidget(self.priority_combo, 1)
        add_layout.addWidget(self.due_check)
        add_layout.addWidget(self.date_edit, 1)
        add_layout.addWidget(self.time_edit, 1)
        add_layout.addWidget(add_button, 1)

        root.addWidget(add_panel)

        # MAIN AREA
        body = QHBoxLayout()

        # SIDEBAR
        sidebar = QFrame()
        sidebar.setObjectName("panel")
        sidebar.setFixedWidth(210)

        side = QVBoxLayout(sidebar)

        side_title = QLabel("TASK FILTERS")
        side_title.setStyleSheet(f"font-weight: bold; color: {CYAN};")
        side.addWidget(side_title)

        self.filter_list = QListWidget()
        self.filter_list.addItems(FILTER_LABELS)
        self.filter_list.setCurrentRow(0)
        side.addWidget(self.filter_list)

        self.stats = QLabel()
        self.stats.setStyleSheet(f"color: {GREEN_DIM}; padding: 8px;")
        side.addWidget(self.stats)

        body.addWidget(sidebar)

        # TASK LIST
        task_panel = QFrame()
        task_panel.setObjectName("panel")

        task_layout = QVBoxLayout(task_panel)

        # Search + sort row
        search_row = QHBoxLayout()

        search_label = QLabel("SEARCH:")
        search_label.setStyleSheet(f"color: {CYAN}; font-weight: bold;")

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            "Filter by title or notes..."
        )
        self.search_input.setClearButtonEnabled(True)

        self.sort_combo = QComboBox()
        self.sort_combo.addItems(SORT_ORDERS)
        self.sort_combo.setToolTip("Sort the current view")

        search_row.addWidget(search_label)
        search_row.addWidget(self.search_input, 1)
        search_row.addWidget(self.sort_combo)

        task_layout.addLayout(search_row)

        table_header = QLabel(TASK_LIST_HEADER)
        table_header.setStyleSheet(
            f"color: {CYAN}; font-weight: bold; padding: 8px;"
        )
        task_layout.addWidget(table_header)

        self.task_list = QListWidget()
        self.task_list.setUniformItemSizes(True)
        task_layout.addWidget(self.task_list, 1)

        self.detail_label = QLabel()
        self.detail_label.setWordWrap(True)
        self.detail_label.setMaximumHeight(46)
        self.detail_label.setStyleSheet(
            f"color: {GREEN_DIM}; font-size: 12px; padding: 6px;"
        )
        task_layout.addWidget(self.detail_label)

        body.addWidget(task_panel, 1)

        root.addLayout(body, 1)

        # BOTTOM BUTTONS
        buttons = QHBoxLayout()

        self.complete_button = QPushButton("✓ COMPLETE SELECTED")
        self.complete_button.clicked.connect(self.complete_selected_task)
        self.complete_button.setToolTip(
            "Recurring tasks automatically roll forward"
        )

        self.edit_button = QPushButton("EDIT SELECTED")
        self.edit_button.clicked.connect(self.edit_selected_task)
        self.edit_button.setToolTip("Double-click a task or press F2")

        self.reopen_button = QPushButton("REOPEN SELECTED")
        self.reopen_button.clicked.connect(self.reopen_selected_task)

        self.delete_button = QPushButton("✕ DELETE SELECTED")
        self.delete_button.setStyleSheet(f"""
            QPushButton {{
                background-color: #100303;
                border: 1px solid {RED};
                color: {RED};
                padding: 10px 18px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {RED};
                color: black;
            }}
            QPushButton:disabled {{
                background-color: {BLACK};
                border-color: #4a1010;
                color: #6b2020;
            }}
        """)
        self.delete_button.clicked.connect(self.delete_selected_task)

        self.clear_button = QPushButton("CLEAR COMPLETED")
        self.clear_button.clicked.connect(self.clear_completed_tasks)
        self.clear_button.setToolTip(
            "Delete every completed task at once"
        )

        self.export_button = QPushButton("EXPORT...")
        self.export_button.clicked.connect(self.export_tasks)
        self.export_button.setToolTip("Save a JSON or CSV backup")

        self.refresh_button = QPushButton("↻ REFRESH")
        self.refresh_button.clicked.connect(self.load_tasks)
        self.refresh_button.setToolTip("Reload from the database (F5)")

        self.about_button = QPushButton("ABOUT")
        self.about_button.clicked.connect(self.show_about)
        self.about_button.setToolTip("Version and project link")

        buttons.addWidget(self.complete_button)
        buttons.addWidget(self.edit_button)
        buttons.addWidget(self.reopen_button)
        buttons.addWidget(self.delete_button)
        buttons.addStretch()
        buttons.addWidget(self.clear_button)
        buttons.addWidget(self.export_button)
        buttons.addWidget(self.refresh_button)
        buttons.addWidget(self.about_button)

        root.addLayout(buttons)

        self.setCentralWidget(central)

        # Signals are wired after every widget exists so the
        # initial widget population above cannot trigger a filter
        # run against a half-built UI.
        self.task_input.returnPressed.connect(self.add_task)
        self.filter_list.currentRowChanged.connect(self.apply_filter)
        self.search_input.textChanged.connect(self.apply_filter)
        self.sort_combo.currentTextChanged.connect(self.apply_filter)
        self.task_list.currentRowChanged.connect(self.on_selection_changed)
        self.task_list.itemDoubleClicked.connect(self.edit_selected_task)

        shortcut_search = QShortcut(QKeySequence("Ctrl+F"), self)
        shortcut_search.activated.connect(self.focus_search)

        shortcut_new = QShortcut(QKeySequence("Ctrl+N"), self)
        shortcut_new.activated.connect(self.focus_new_task)

        shortcut_delete = QShortcut(
            QKeySequence("Delete"), self.task_list
        )
        shortcut_delete.activated.connect(self.delete_selected_task)

        shortcut_edit = QShortcut(QKeySequence("F2"), self.task_list)
        shortcut_edit.activated.connect(self.edit_selected_task)

        shortcut_refresh = QShortcut(QKeySequence("F5"), self)
        shortcut_refresh.activated.connect(self.load_tasks)

        self.statusBar().showMessage(
            "Ctrl+F search  ·  Ctrl+N new task  ·  F2 edit  ·  "
            "Del delete  ·  F5 refresh  ·  double-click to edit"
        )

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    def restore_settings(self):
        geometry = self.settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

        row = self.settings.value("filter_row", 0)
        try:
            row = int(row)
        except (TypeError, ValueError):
            row = 0

        if 0 <= row < self.filter_list.count():
            self.filter_list.setCurrentRow(row)

        reminders_on = self.settings.value("reminders", True, type=bool)

        self.reminder_toggle.blockSignals(True)
        self.reminder_toggle.setChecked(reminders_on)
        self.reminder_toggle.blockSignals(False)

        self.set_reminders_enabled(reminders_on)

    def closeEvent(self, event):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("filter_row", self.filter_list.currentRow())
        self.settings.setValue(
            "reminders",
            self.reminder_toggle.isChecked(),
        )

        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Reminders
    # ------------------------------------------------------------------
    def set_reminders_enabled(self, enabled):
        if enabled:
            self.reminder_timer.start()
            self.run_reminder_check()
            message = (
                f"Reminders on - checking every "
                f"{REMINDER_INTERVAL_SECONDS}s"
            )
        else:
            self.reminder_timer.stop()
            message = "Reminders off"

        self.settings.setValue("reminders", enabled)
        self.statusBar().showMessage(message, 4000)

    def run_reminder_check(self):
        try:
            sent = check_due_tasks()
        except Exception as exc:
            # A reminder failure must never take the window down.
            self.statusBar().showMessage(f"Reminder error: {exc}", 6000)
            return

        if sent:
            self.statusBar().showMessage(
                f"Sent {sent} task reminder(s)", 5000
            )

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------
    def update_clock(self):
        now = datetime.now()
        self.clock.setText(now.strftime("%a %b %d %Y   %I:%M:%S %p"))

    def load_tasks(self):
        self.all_tasks = list_tasks(include_completed=True)
        self.apply_filter()

    def apply_filter(self, *_):
        previous_id = self.selected_id()

        today = datetime.now().strftime("%Y-%m-%d")
        self.overdue_ids = {task["id"] for task in get_overdue_tasks()}

        row = self.filter_list.currentRow()
        row = max(row, 0)

        filters = build_filters(self.overdue_ids, today)
        row = min(row, len(filters) - 1)

        label, predicate = filters[row]

        tasks = [task for task in self.all_tasks if predicate(task)]

        query = self.search_input.text().strip().lower()
        if query:
            tasks = [
                task
                for task in tasks
                if query in task["title"].lower()
                or query in (task["description"] or "").lower()
            ]

        tasks = sort_tasks(tasks, self.sort_combo.currentText())

        self.task_list.clear()

        for task in tasks:
            item = QListWidgetItem(format_task_row(task, self.overdue_ids))
            item.setData(Qt.ItemDataRole.UserRole, task["id"])
            item.setToolTip(self.describe_task(task))

            if task["completed"]:
                item.setForeground(QColor(MUTED))
            elif task["priority"] == "Critical":
                item.setForeground(QColor(RED))
            elif task["priority"] == "High":
                item.setForeground(QColor(AMBER))

            self.task_list.addItem(item)

        if not tasks:
            empty = QListWidgetItem("   - no tasks in this view -")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.task_list.addItem(empty)

        if previous_id is not None:
            self.select_task(previous_id)

        self.stats.setText(self.build_stats(label))
        self.update_button_states()
        self.update_detail()

    def build_stats(self, filter_label):
        total = len(self.all_tasks)
        completed = sum(1 for task in self.all_tasks if task["completed"])
        active = total - completed
        percent = int(completed * 100 / total) if total else 0

        return (
            f"VIEW:\n{filter_label}\n\n"
            f"TASKS:      {total}\n"
            f"ACTIVE:     {active}\n"
            f"COMPLETED:  {completed}\n"
            f"OVERDUE:    {len(self.overdue_ids)}\n\n"
            f"DONE:       {percent}%"
        )

    @staticmethod
    def describe_task(task):
        parts = []

        if task["description"]:
            parts.append(task["description"])

        if task["recurring"] and task["recurrence"]:
            parts.append(f"Repeats {task['recurrence']}")
        else:
            parts.append("One-time task")

        if task["created_at"]:
            parts.append(f"Created {task['created_at']}")

        if task["completed"] and task["completed_at"]:
            parts.append(f"Completed {task['completed_at']}")

        return "  ·  ".join(parts)

    def update_detail(self):
        task = self.selected_task()

        if task is None:
            self.detail_label.setText(
                "Select a task to see its details."
            )
            return

        self.detail_label.setText(self.describe_task(task))

    def update_button_states(self):
        task = self.selected_task()
        selected = task is not None

        self.edit_button.setEnabled(selected)
        self.delete_button.setEnabled(selected)

        self.complete_button.setEnabled(
            selected and not task["completed"]
        )
        self.reopen_button.setEnabled(
            selected and task["completed"]
        )

    def on_selection_changed(self, *_):
        self.update_button_states()
        self.update_detail()

    # ------------------------------------------------------------------
    # Selection helpers
    # ------------------------------------------------------------------
    def selected_id(self):
        item = self.task_list.currentItem()

        if item is None:
            return None

        return item.data(Qt.ItemDataRole.UserRole)

    def selected_task(self):
        task_id = self.selected_id()

        if task_id is None:
            return None

        for task in self.all_tasks:
            if task["id"] == task_id:
                return task

        return None

    def select_task(self, task_id):
        for row in range(self.task_list.count()):
            item = self.task_list.item(row)

            if item.data(Qt.ItemDataRole.UserRole) == task_id:
                self.task_list.setCurrentRow(row)
                return True

        return False

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def add_task(self):
        title = self.task_input.text().strip()

        if not title:
            QMessageBox.warning(
                self,
                "Missing Task",
                "Enter a task first."
            )
            return

        try:
            due_date, due_time = widget_due_values(
                self.due_check,
                self.date_edit,
                self.time_edit,
            )

            task_id = create_task(
                title=title,
                priority=self.priority_combo.currentText(),
                due_date=due_date,
                due_time=due_time,
            )

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Task Error",
                str(exc)
            )
            return

        self.task_input.clear()
        self.load_tasks()
        self.select_task(task_id)

        due_note = " (no due date)" if due_date is None else ""
        self.statusBar().showMessage(
            f"Added: {title}{due_note}", 4000
        )

    def complete_selected_task(self):
        task = self.selected_task()

        if task is None:
            QMessageBox.information(
                self,
                "No Selection",
                "Select a task first."
            )
            return

        try:
            result = complete_recurring_task(task["id"])
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Task Error",
                str(exc)
            )
            return

        self.load_tasks()
        self.select_task(task["id"])

        if isinstance(result, dict) and "next_task" in result:
            next_task = result["next_task"]
            self.statusBar().showMessage(
                f"Completed - next occurrence: "
                f"{next_task['due_date']} {next_task['due_time'] or ''}",
                6000,
            )
        else:
            self.statusBar().showMessage("Task completed", 4000)

    def reopen_selected_task(self):
        task = self.selected_task()

        if task is None:
            QMessageBox.information(
                self,
                "No Selection",
                "Select a task first."
            )
            return

        reopen_task(task["id"])
        self.load_tasks()
        self.select_task(task["id"])

        self.statusBar().showMessage("Task reopened", 4000)

    def edit_selected_task(self, *_):
        task = self.selected_task()

        if task is None:
            QMessageBox.information(
                self,
                "No Selection",
                "Select a task first."
            )
            return

        dialog = EditTaskDialog(task, parent=self)
        dialog.setStyleSheet(self.styleSheet())

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            update_task(task["id"], **dialog.values())
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Task Error",
                str(exc)
            )
            return

        self.load_tasks()
        self.select_task(task["id"])

        updated = self.selected_task() or task

        self.statusBar().showMessage(
            f"Updated: {updated['title']}", 4000
        )

    def delete_selected_task(self):
        task = self.selected_task()

        if task is None:
            QMessageBox.information(
                self,
                "No Selection",
                "Select a task first."
            )
            return

        answer = QMessageBox.question(
            self,
            "Delete Task",
            f"Delete '{task['title']}'?"
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        delete_task(task["id"])
        self.load_tasks()

        self.statusBar().showMessage(
            f"Deleted: {task['title']}", 4000
        )

    def clear_completed_tasks(self):
        completed = [
            task for task in self.all_tasks if task["completed"]
        ]

        if not completed:
            self.statusBar().showMessage(
                "No completed tasks to clear", 4000
            )
            return

        answer = QMessageBox.question(
            self,
            "Clear Completed",
            f"Delete {len(completed)} completed task(s)?"
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        removed = delete_completed_tasks()
        self.load_tasks()

        self.statusBar().showMessage(
            f"Cleared {removed} completed task(s)", 4000
        )

    def export_tasks(self):
        if not self.all_tasks:
            self.statusBar().showMessage(
                "Nothing to export", 4000
            )
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Tasks",
            "tasks.json",
            "JSON Files (*.json);;CSV Files (*.csv)",
        )

        if not path:
            return

        try:
            if path.lower().endswith(".csv"):
                export_csv(self.all_tasks, path)
            else:
                export_json(self.all_tasks, path)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Export Failed",
                str(exc)
            )
            return

        self.statusBar().showMessage(
            f"Exported {len(self.all_tasks)} task(s) to {path}", 6000
        )

    def show_about(self):
        dialog = AboutDialog(parent=self)
        dialog.setStyleSheet(self.styleSheet())
        dialog.exec()

    # ------------------------------------------------------------------
    # Focus helpers for shortcuts
    # ------------------------------------------------------------------
    def focus_search(self):
        self.search_input.setFocus()
        self.search_input.selectAll()

    def focus_new_task(self):
        self.task_input.setFocus()


def main(argv=None):
    """Start the GUI. Also the ``important-task-manager`` entry point."""

    argv = list(sys.argv if argv is None else argv)

    if "--version" in argv[1:]:
        print(f"{APP_NAME} {APP_VERSION}")
        return 0

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    # Lets Wayland/GNOME match the window to its .desktop file and icon.
    app.setDesktopFileName("important-task-manager")

    window = ImportantTaskManager()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
