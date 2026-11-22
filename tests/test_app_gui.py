"""Offscreen smoke tests for the Qt GUI.

These exercise the window the same way a user would: set widget
values, call the slot a button is connected to, then assert against
the database and the widget state.

QT_QPA_PLATFORM is forced to "offscreen" so the suite runs on a
machine with no display server.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import csv
import json

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication, QMessageBox

import database
from app import FILTER_LABELS, TASK_LIST_HEADER, ImportantTaskManager
from database import initialize_database
from tasks import complete_task, create_task, get_task, list_tasks


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def settings_path(tmp_path):
    return tmp_path / "settings.ini"


@pytest.fixture
def make_settings(settings_path):
    def factory():
        return QSettings(
            str(settings_path),
            QSettings.Format.IniFormat,
        )

    return factory


@pytest.fixture
def window(qapp, tmp_path, monkeypatch, make_settings):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "gui.db")
    monkeypatch.setattr("app.create_settings", make_settings)

    win = ImportantTaskManager()
    # Reminders are exercised in their own test; keep the rest of the
    # suite free of timers and subprocesses.
    win.reminder_toggle.setChecked(False)

    yield win

    win.close()


def shown_titles(window):
    """Text of every real row, ignoring the empty-state placeholder."""

    return [
        window.task_list.item(row).text()
        for row in range(window.task_list.count())
        if window.task_list.item(row).flags()
        & Qt.ItemFlag.ItemIsSelectable
    ]


def shown_task_titles(window):
    """Just the title column of every real row."""

    from app import TITLE_WIDTH

    return [
        text[4 : 4 + TITLE_WIDTH].strip()
        for text in shown_titles(window)
    ]


# ----------------------------------------------------------------------
# Construction
# ----------------------------------------------------------------------
def test_window_builds_offscreen(window):
    assert window.filter_list.count() == len(FILTER_LABELS)
    assert window.filter_list.currentRow() == 0

    stats = window.stats.text()
    assert "TASKS:" in stats
    assert "OVERDUE:" in stats
    assert "DONE:" in stats

    assert window.task_list.count() == 1  # empty-state placeholder
    assert window.selected_task() is None

    # Nothing selected, so every selection button is inert.
    assert not window.edit_button.isEnabled()
    assert not window.complete_button.isEnabled()
    assert not window.reopen_button.isEnabled()
    assert not window.delete_button.isEnabled()


# ----------------------------------------------------------------------
# Adding tasks
# ----------------------------------------------------------------------
def test_add_task_without_due_date(window):
    window.due_check.setChecked(False)
    window.task_input.setText("Someday chore")
    window.add_task()

    tasks = list_tasks()

    assert len(tasks) == 1
    assert tasks[0]["due_date"] is None
    assert tasks[0]["due_time"] is None

    row = window.task_list.item(0).text()
    assert "Someday chore" in row
    assert "None" not in row
    assert "1752" not in row

    # The new task is selected and the input is cleared.
    assert window.task_input.text() == ""
    assert window.selected_task()["id"] == tasks[0]["id"]


def test_add_task_with_due_date_and_time(window):
    window.due_check.setChecked(True)
    window.task_input.setText("Dated chore")
    window.add_task()

    task = list_tasks()[0]

    assert task["due_date"] is not None
    assert task["due_time"] is not None
    assert len(task["due_date"]) == 10


def test_add_task_without_time(window):
    window.due_check.setChecked(True)
    window.time_edit.setTime(window.time_edit.minimumTime())
    window.task_input.setText("Date only")
    window.add_task()

    task = list_tasks()[0]

    assert task["due_date"] is not None
    assert task["due_time"] is None


def test_empty_title_is_rejected(window, monkeypatch):
    warnings = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args, **kwargs: warnings.append(args[2]),
    )

    window.task_input.setText("   ")
    window.add_task()

    assert list_tasks() == []
    assert warnings and "Enter a task first" in warnings[0]


# ----------------------------------------------------------------------
# Searching, sorting and filters
# ----------------------------------------------------------------------
def test_search_narrows_the_list(window):
    create_task("Water the plants")
    create_task("Pay the invoice")
    window.load_tasks()

    assert len(shown_titles(window)) == 2

    window.search_input.setText("water")

    rows = shown_titles(window)

    assert len(rows) == 1
    assert "Water the plants" in rows[0]

    window.search_input.setText("nothing matches")

    # Placeholder row only, and nothing selectable.
    assert shown_titles(window) == []
    assert window.task_list.count() == 1
    assert window.selected_task() is None
    assert not window.edit_button.isEnabled()

    window.search_input.clear()

    assert len(shown_titles(window)) == 2


def test_search_matches_description(window):
    create_task("Vague title", description="renew the passport")
    window.load_tasks()

    window.search_input.setText("passport")

    assert len(shown_titles(window)) == 1


def test_sort_by_due_date(window):
    create_task("No date here")
    create_task("Later", due_date="2099-01-01")
    create_task("Sooner", due_date="2026-01-01")
    window.load_tasks()

    window.sort_combo.setCurrentText("DUE DATE")

    assert shown_task_titles(window) == [
        "Sooner",
        "Later",
        "No date here",
    ]


def test_filter_switching(window):
    create_task("Still open", priority="Critical")
    done = create_task("Finished")
    complete_task(done)

    window.load_tasks()

    def switch(label):
        window.filter_list.setCurrentRow(FILTER_LABELS.index(label))
        return shown_titles(window)

    assert len(switch("ALL TASKS")) == 2

    completed = switch("COMPLETED")
    assert len(completed) == 1
    assert "Finished" in completed[0]

    critical = switch("CRITICAL")
    assert len(critical) == 1
    assert "Still open" in critical[0]

    assert len(switch("ACTIVE")) == 1
    assert len(switch("OVERDUE")) == 0
    assert len(switch("NO DATE")) == 2

    window.filter_list.setCurrentRow(0)
    assert window.selected_task() is None


def test_overdue_filter_selects_past_tasks(window):
    create_task("Old news", due_date="2020-01-01", due_time="09:00")
    create_task("Fresh", due_date="2099-01-01", due_time="09:00")
    window.load_tasks()

    window.filter_list.setCurrentRow(FILTER_LABELS.index("OVERDUE"))

    assert len(shown_titles(window)) == 1
    assert "Old news" in window.task_list.item(0).text()

    assert "OVERDUE" in window.task_list.item(0).text()


# ----------------------------------------------------------------------
# Completing / reopening
# ----------------------------------------------------------------------
def test_completing_recurring_task_rolls_forward(window):
    task_id = create_task(
        "Water the plants",
        due_date="2099-01-10",
        due_time="09:00",
        priority="High",
        recurring=True,
        recurrence="daily",
    )

    window.load_tasks()
    assert window.select_task(task_id)

    window.complete_selected_task()

    tasks = list_tasks()

    assert len(tasks) == 2
    assert get_task(task_id)["completed"] == 1

    created = next(task for task in tasks if task["id"] != task_id)
    assert created["due_date"] == "2099-01-11"
    assert created["due_time"] == "09:00"
    assert created["recurring"] == 1
    assert created["recurrence"] == "daily"
    assert created["priority"] == "High"

    assert "next occurrence" in window.statusBar().currentMessage()


def test_completing_plain_task_creates_no_duplicate(window):
    task_id = create_task("One off", due_date="2099-02-01")

    window.load_tasks()
    window.select_task(task_id)

    window.complete_selected_task()

    tasks = list_tasks()

    assert len(tasks) == 1
    assert tasks[0]["completed"] == 1
    assert window.statusBar().currentMessage() == "Task completed"


def test_buttons_track_completion_state(window):
    task_id = create_task("Toggle me")

    window.load_tasks()
    window.select_task(task_id)

    assert window.complete_button.isEnabled()
    assert not window.reopen_button.isEnabled()

    window.complete_selected_task()

    window.select_task(task_id)

    assert not window.complete_button.isEnabled()
    assert window.reopen_button.isEnabled()


def test_reopen_from_ui(window):
    task_id = create_task("Undo me")
    complete_task(task_id)

    window.load_tasks()
    window.select_task(task_id)

    window.reopen_selected_task()

    task = get_task(task_id)

    assert task["completed"] == 0
    assert task["completed_at"] is None


# ----------------------------------------------------------------------
# Editing
# ----------------------------------------------------------------------
def test_edit_dialog_reads_and_writes_every_field(window):
    from dialogs import EditTaskDialog

    task_id = create_task(
        "Original",
        description="original notes",
        due_date="2099-03-05",
        due_time="14:30",
        priority="Low",
    )
    window.load_tasks()
    task = get_task(task_id)

    dialog = EditTaskDialog(task, parent=window)
    assert dialog.title_input.text() == "Original"
    assert dialog.description_input.toPlainText() == "original notes"
    assert dialog.priority_combo.currentText() == "Low"
    assert dialog.due_check.isChecked()
    assert not dialog.recurrence_check.isChecked()

    dialog.title_input.setText("Renamed")
    dialog.description_input.setPlainText("new notes")
    dialog.priority_combo.setCurrentText("Critical")
    dialog.recurrence_check.setChecked(True)
    dialog.recurrence_combo.setCurrentIndex(
        dialog.recurrence_combo.findData("monthly")
    )

    values = dialog.values()

    assert values == {
        "title": "Renamed",
        "description": "new notes",
        "priority": "Critical",
        "due_date": "2099-03-05",
        "due_time": "14:30",
        "recurring": 1,
        "recurrence": "monthly",
    }

    dialog.accept()
    assert int(dialog.result()) == 1


def test_edit_dialog_clearing_due_date(window):
    from dialogs import EditTaskDialog

    task = {
        "title": "T",
        "description": "",
        "priority": "Normal",
        "due_date": "2099-03-05",
        "due_time": "14:30",
        "recurring": 0,
        "recurrence": None,
    }

    dialog = EditTaskDialog(task, parent=window)
    dialog.due_check.setChecked(False)

    values = dialog.values()

    assert values["due_date"] is None
    assert values["due_time"] is None


def test_edit_dialog_requires_title(window, monkeypatch):
    from dialogs import EditTaskDialog

    warnings = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args, **kwargs: warnings.append(args[2]),
    )

    dialog = EditTaskDialog(
        {"title": "x", "description": "", "priority": "Normal",
         "due_date": None, "due_time": None, "recurring": 0,
         "recurrence": None},
        parent=window,
    )
    dialog.title_input.setText("   ")
    dialog.accept()

    assert int(dialog.result()) == 0
    assert warnings and "title" in warnings[0].lower()


def test_edit_dialog_requires_date_for_recurring(window, monkeypatch):
    from dialogs import EditTaskDialog

    warnings = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args, **kwargs: warnings.append(args[2]),
    )

    dialog = EditTaskDialog(
        {"title": "x", "description": "", "priority": "Normal",
         "due_date": None, "due_time": None, "recurring": 0,
         "recurrence": None},
        parent=window,
    )
    dialog.recurrence_check.setChecked(True)
    dialog.due_check.setChecked(False)
    dialog.accept()

    assert int(dialog.result()) == 0
    assert warnings and "due date" in warnings[0].lower()


def test_edit_button_saves_changes(window, monkeypatch):
    task_id = create_task("Before", priority="Normal")
    window.load_tasks()
    window.select_task(task_id)

    class FakeDialog:
        def __init__(self, task, parent=None):
            self.task = task

        def setStyleSheet(self, style):
            pass

        def exec(self):
            return 1

        def values(self):
            return {
                "title": "After",
                "description": "noted",
                "priority": "High",
                "due_date": "2099-05-05",
                "due_time": "08:00",
                "recurring": 0,
                "recurrence": None,
            }

    monkeypatch.setattr("app.EditTaskDialog", FakeDialog)

    window.edit_selected_task()

    task = get_task(task_id)

    assert task["title"] == "After"
    assert task["priority"] == "High"
    assert task["description"] == "noted"
    assert task["due_date"] == "2099-05-05"
    assert window.selected_task()["id"] == task_id
    assert "After" in window.statusBar().currentMessage()


def test_edit_cancel_leaves_task_untouched(window, monkeypatch):
    task_id = create_task("Untouched")
    window.load_tasks()
    window.select_task(task_id)

    class CancelledDialog:
        def __init__(self, task, parent=None):
            pass

        def setStyleSheet(self, style):
            pass

        def exec(self):
            return 0

    monkeypatch.setattr("app.EditTaskDialog", CancelledDialog)

    window.edit_selected_task()

    assert get_task(task_id)["title"] == "Untouched"


# ----------------------------------------------------------------------
# Bulk actions
# ----------------------------------------------------------------------
def test_clear_completed_removes_only_done_tasks(
    window, monkeypatch
):
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    create_task("Keep me")
    done_a = create_task("Drop me A")
    done_b = create_task("Drop me B")
    complete_task(done_a)
    complete_task(done_b)

    window.load_tasks()
    window.clear_completed_tasks()

    remaining = list_tasks()

    assert len(remaining) == 1
    assert remaining[0]["title"] == "Keep me"
    assert "Cleared 2" in window.statusBar().currentMessage()


def test_clear_completed_with_nothing_done(
    window, monkeypatch
):
    # No confirmation dialog should appear at all.
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: pytest.fail(
            "should not ask for confirmation"
        ),
    )

    create_task("Only active")

    window.load_tasks()
    window.clear_completed_tasks()

    assert len(list_tasks()) == 1
    assert "No completed tasks" in window.statusBar().currentMessage()


def test_delete_selected_task(window, monkeypatch):
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    task_id = create_task("Bye")
    window.load_tasks()
    window.select_task(task_id)

    window.delete_selected_task()

    assert list_tasks() == []
    assert window.selected_task() is None


# ----------------------------------------------------------------------
# Reminders
# ----------------------------------------------------------------------
def test_reminder_toggle_wires_the_timer(
    qapp, tmp_path, monkeypatch, make_settings
):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "gui.db")
    monkeypatch.setattr("app.create_settings", make_settings)

    calls = []
    monkeypatch.setattr(
        "app.check_due_tasks",
        lambda: calls.append(1) or 0,
    )

    win = ImportantTaskManager()

    try:
        # One check runs as soon as the window opens.
        assert calls == [1]
        assert win.reminder_timer.isActive()

        win.reminder_toggle.setChecked(False)
        assert not win.reminder_timer.isActive()
        assert calls == [1]

        win.reminder_toggle.setChecked(True)
        assert win.reminder_timer.isActive()
        assert calls == [1, 1]
        assert "Reminders on" in win.statusBar().currentMessage()
    finally:
        win.close()


def test_reminder_check_survives_a_notification_failure(
    window, monkeypatch
):
    def boom():
        raise RuntimeError("notify-send exploded")

    monkeypatch.setattr("app.check_due_tasks", boom)

    window.run_reminder_check()  # must not raise

    assert "Reminder error" in window.statusBar().currentMessage()


# ----------------------------------------------------------------------
# Persistence
# ----------------------------------------------------------------------
def test_window_state_survives_a_restart(
    qapp, tmp_path, monkeypatch, make_settings
):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "gui.db")
    monkeypatch.setattr("app.create_settings", make_settings)
    initialize_database()

    create_task("Persists too")
    overdue_row = FILTER_LABELS.index("OVERDUE")

    first = ImportantTaskManager()
    # Keep the size inside the 800x800 offscreen virtual screen so
    # restoreGeometry does not clamp it.
    first.resize(700, 500)
    first.filter_list.setCurrentRow(overdue_row)
    first.reminder_toggle.setChecked(False)
    first.close()
    first.settings.sync()

    second = ImportantTaskManager()

    try:
        assert second.filter_list.currentRow() == overdue_row
        assert second.reminder_toggle.isChecked() is False
        assert not second.reminder_timer.isActive()
        assert second.width() == 700
        assert second.height() == 500

        # The restored view actually applies (nothing is overdue).
        assert len(list_tasks()) == 1
        assert shown_titles(second) == []
    finally:
        second.close()


# ----------------------------------------------------------------------
# Export
# ----------------------------------------------------------------------
def test_export_json_through_the_file_dialog(
    window, monkeypatch, tmp_path
):
    create_task("First", due_date="2099-01-01", due_time="09:00")
    create_task("Second", priority="Critical")
    window.load_tasks()

    target = tmp_path / "out.json"

    monkeypatch.setattr(
        "app.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(target), "JSON Files (*.json)"),
    )

    window.export_tasks()

    assert target.exists()

    data = json.loads(target.read_text(encoding="utf-8"))

    assert len(data) == 2
    assert {entry["title"] for entry in data} == {"First", "Second"}

    by_title = {entry["title"]: entry for entry in data}

    assert by_title["First"]["due_date"] == "2099-01-01"
    assert by_title["First"]["due_time"] == "09:00"
    assert by_title["Second"]["priority"] == "Critical"
    assert "Exported 2" in window.statusBar().currentMessage()


def test_export_csv_through_the_file_dialog(
    window, monkeypatch, tmp_path
):
    from app import EXPORT_FIELDS

    create_task("Alpha", due_date="2099-01-01")
    create_task("Beta", priority="High")
    window.load_tasks()

    target = tmp_path / "out.csv"

    monkeypatch.setattr(
        "app.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(target), "CSV Files (*.csv)"),
    )

    window.export_tasks()

    assert target.exists()

    with open(target, encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 2
    assert list(rows[0]) == EXPORT_FIELDS
    assert {row["title"] for row in rows} == {"Alpha", "Beta"}


def test_export_cancel_writes_nothing(window, monkeypatch, tmp_path):
    create_task("Never written")
    window.load_tasks()

    monkeypatch.setattr(
        "app.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: ("", ""),
    )

    before = window.statusBar().currentMessage()

    window.export_tasks()

    # The settings file legitimately lives here; no export file may.
    assert not [
        path for path in tmp_path.iterdir()
        if path.suffix in {".json", ".csv"}
    ]
    assert window.statusBar().currentMessage() == before


def test_export_with_nothing_to_export(window, monkeypatch):
    monkeypatch.setattr(
        "app.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: pytest.fail(
            "the file dialog must not open when there is nothing to export"
        ),
    )

    window.export_tasks()

    assert "Nothing to export" in window.statusBar().currentMessage()


# ----------------------------------------------------------------------
# Rendering fidelity
# ----------------------------------------------------------------------
def test_columns_align_in_real_pixels(qapp, window):
    """Header and rows must share column boundaries in device pixels.

    The stylesheet font is only applied once the widget is polished,
    so this measures the window after show() - measuring an unshown
    widget gives the unthemed default font and a false result.
    """

    create_task("Short")
    create_task(
        "X" * 60,
        due_date="2099-01-01",
        due_time="09:00",
        priority="Critical",
    )
    create_task(
        "Recurring one",
        due_date="2099-01-02",
        due_time="08:00",
        recurring=True,
        recurrence="daily",
    )
    create_task("No date at all")
    window.load_tasks()

    window.show()
    qapp.processEvents()

    metrics = QFontMetrics(window.task_list.font())

    # Character offsets where the PRIORITY and DUE columns begin.
    priority_col = TASK_LIST_HEADER.index("PRIORITY") - 1
    due_col = TASK_LIST_HEADER.index("DUE")

    rows = [TASK_LIST_HEADER] + shown_titles(window)

    # Header plus the four tasks, including a truncated title.
    assert len(rows) == 5
    assert any("\u2026" in text for text in rows)

    priority_starts = {
        metrics.horizontalAdvance(text[:priority_col]) for text in rows
    }
    due_starts = {
        metrics.horizontalAdvance(text[:due_col]) for text in rows
    }

    assert len(priority_starts) == 1, f"PRIORITY column misaligned: {priority_starts}"
    assert len(due_starts) == 1, f"DUE column misaligned: {due_starts}"
