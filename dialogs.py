"""Dialogs used by the Important Task Manager GUI."""

from PySide6.QtCore import QDate, QTime
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from config import MIN_DUE_YEAR
from tasks import VALID_PRIORITIES

RECURRENCE_CHOICES = [
    ("Daily", "daily"),
    ("Weekly", "weekly"),
    ("Monthly", "monthly"),
]


def widget_due_values(due_check, date_edit, time_edit):
    """Return ``(due_date, due_time)`` read from the editor widgets.

    Both values are ``None`` when the due-date checkbox is cleared.
    The time is ``None`` when the picker sits on its sentinel
    (``--:--``), meaning "date only, no specific time".
    """

    if not due_check.isChecked():
        return None, None

    due_date = date_edit.date().toString("yyyy-MM-dd")

    picked_time = time_edit.time()
    due_time = None if picked_time == time_edit.minimumTime() else picked_time.toString("HH:mm")

    return due_date, due_time


def setup_due_widgets(due_check, date_edit, time_edit, today, has_date):
    """Configure the shared due-date widget trio.

    Used by both the add panel and the edit dialog so the two stay
    consistent.
    """

    date_edit.setCalendarPopup(True)
    date_edit.setMinimumDate(QDate(MIN_DUE_YEAR, 1, 1))
    date_edit.setDate(today)

    time_edit.setDisplayFormat("HH:mm")
    time_edit.setSpecialValueText("--:--")
    time_edit.setTime(QTime(0, 0))

    due_check.setChecked(has_date)

    def sync(enabled):
        date_edit.setEnabled(enabled)
        time_edit.setEnabled(enabled)

    due_check.toggled.connect(sync)
    sync(has_date)


class EditTaskDialog(QDialog):
    """Edit every stored field of an existing task."""

    def __init__(self, task, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Edit Task")
        self.setModal(True)

        root = QVBoxLayout(self)

        form = QFormLayout()
        form.setSpacing(10)

        self.title_input = QLineEdit(task["title"])
        self.title_input.setPlaceholderText("Task title")
        form.addRow("TITLE", self.title_input)

        self.description_input = QPlainTextEdit(task.get("description") or "")
        self.description_input.setPlaceholderText("Optional notes...")
        self.description_input.setFixedHeight(90)
        form.addRow("NOTES", self.description_input)

        self.priority_combo = QComboBox()
        self.priority_combo.addItems(sorted(VALID_PRIORITIES, key=["Low", "Normal", "High", "Critical"].index))
        self.priority_combo.setCurrentText(task["priority"])
        form.addRow("PRIORITY", self.priority_combo)

        # Due widgets need a container so the checkbox sits beside them.
        due_row = QWidget()

        due_layout = QHBoxLayout(due_row)
        due_layout.setContentsMargins(0, 0, 0, 0)
        due_layout.setSpacing(6)

        self.due_check = QCheckBox("DUE")
        self.date_edit = QDateEdit()
        self.time_edit = QTimeEdit()

        due_layout.addWidget(self.due_check)
        due_layout.addWidget(self.date_edit)
        due_layout.addWidget(self.time_edit)
        due_layout.addStretch()

        today = QDate.fromString(task["due_date"], "yyyy-MM-dd") if task.get("due_date") else QDate.currentDate()
        setup_due_widgets(self.due_check, self.date_edit, self.time_edit, today, bool(task.get("due_date")))

        if task.get("due_time"):
            self.time_edit.setTime(QTime.fromString(task["due_time"], "H:mm"))
        else:
            self.time_edit.setTime(QTime(0, 0))

        form.addRow("DUE", due_row)

        self.recurrence_check = QCheckBox("Repeat this task")
        self.recurrence_check.setChecked(bool(task.get("recurring")))
        form.addRow("RECURRING", self.recurrence_check)

        self.recurrence_combo = QComboBox()
        for label, value in RECURRENCE_CHOICES:
            self.recurrence_combo.addItem(label, value)

        current = task.get("recurrence") or "daily"
        index = self.recurrence_combo.findData(current)
        self.recurrence_combo.setCurrentIndex(max(index, 0))

        self.recurrence_check.toggled.connect(self.recurrence_combo.setEnabled)
        self.recurrence_combo.setEnabled(bool(task.get("recurring")))

        form.addRow("EVERY", self.recurrence_combo)

        root.addLayout(form)

        hint = QLabel(
            "Tip: use --:-- for a due date with no specific time."
        )
        hint.setStyleSheet("color: #00aa44; font-size: 11px;")
        root.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def values(self):
        """Return the field mapping understood by ``tasks.update_task``."""

        due_date, due_time = widget_due_values(
            self.due_check,
            self.date_edit,
            self.time_edit,
        )

        recurring = self.recurrence_check.isChecked()

        return {
            "title": self.title_input.text().strip(),
            "description": self.description_input.toPlainText().strip(),
            "priority": self.priority_combo.currentText(),
            "due_date": due_date,
            "due_time": due_time,
            "recurring": int(recurring),
            "recurrence": self.recurrence_combo.currentData() if recurring else None,
        }

    def accept(self):
        from PySide6.QtWidgets import QMessageBox

        if not self.title_input.text().strip():
            QMessageBox.warning(self, "Missing Title", "Enter a task title first.")
            return

        if self.recurrence_check.isChecked() and not self.due_check.isChecked():
            QMessageBox.warning(
                self,
                "Due Date Required",
                "Recurring tasks need a due date so the next "
                "occurrence can be calculated.",
            )
            return

        super().accept()
