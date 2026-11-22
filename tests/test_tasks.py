import pytest

import database
from database import initialize_database
from scheduler import check_due_tasks
from tasks import (
    complete_task,
    create_task,
    delete_completed_tasks,
    delete_task,
    get_overdue_tasks,
    get_task,
    list_tasks,
    reopen_task,
    update_task,
)


@pytest.fixture(autouse=True)
def test_database(tmp_path, monkeypatch):
    test_db = tmp_path / "test_tasks.db"

    monkeypatch.setattr(database, "DB_PATH", test_db)

    initialize_database()

    yield


def test_connection_follows_the_redirected_db_path(tmp_path, monkeypatch):
    """The directory created must follow DB_PATH, never the project.

    get_connection() used to mkdir the hard-coded module-level
    DATA_DIR, which meant every test run wrote into the real
    project directory even though the database itself was redirected.
    """

    redirected = tmp_path / "nested" / "elsewhere.db"
    monkeypatch.setattr(database, "DB_PATH", redirected)

    conn = database.get_connection()
    conn.close()

    # Before the fix nothing was created here, because the directory
    # came from the hard-coded project-level DATA_DIR instead.
    assert redirected.parent.is_dir()
    assert redirected.is_file()
    assert database.DATA_DIR != redirected.parent


def test_create_and_get_task():
    task_id = create_task(
        "Test Task",
        "Test description",
        priority="High",
    )

    task = get_task(task_id)

    assert task is not None
    assert task["title"] == "Test Task"
    assert task["description"] == "Test description"
    assert task["priority"] == "High"
    assert task["completed"] == 0


def test_complete_task():
    task_id = create_task("Complete Me")

    assert complete_task(task_id) is True

    task = get_task(task_id)

    assert task["completed"] == 1
    assert task["completed_at"] is not None


def test_reopen_task():
    task_id = create_task("Reopen Me")

    complete_task(task_id)
    assert reopen_task(task_id) is True

    task = get_task(task_id)

    assert task["completed"] == 0
    assert task["completed_at"] is None


def test_update_task():
    task_id = create_task("Old Title")

    updated = update_task(
        task_id,
        title="New Title",
        description="Updated description",
        priority="Critical",
    )

    assert updated is True

    task = get_task(task_id)

    assert task["title"] == "New Title"
    assert task["description"] == "Updated description"
    assert task["priority"] == "Critical"


def test_delete_task():
    task_id = create_task("Delete Me")

    assert delete_task(task_id) is True
    assert get_task(task_id) is None


def test_delete_completed_tasks_removes_only_finished():
    keep = create_task("Still Active")
    done_a = create_task("Done A")
    done_b = create_task("Done B")

    complete_task(done_a)
    complete_task(done_b)

    assert delete_completed_tasks() == 2

    remaining = list_tasks()

    assert [task["id"] for task in remaining] == [keep]


def test_delete_completed_tasks_with_none_done():
    create_task("Active Only")

    assert delete_completed_tasks() == 0
    assert len(list_tasks()) == 1


def test_list_tasks():
    create_task("Normal Task", priority="Normal")
    create_task("Critical Task", priority="Critical")
    create_task("High Task", priority="High")

    tasks = list_tasks(include_completed=False)

    assert len(tasks) == 3
    assert tasks[0]["priority"] == "Critical"
    assert tasks[1]["priority"] == "High"


def test_invalid_priority():
    with pytest.raises(ValueError):
        create_task("Bad Priority", priority="SUPER_IMPORTANT")


def test_empty_title():
    with pytest.raises(ValueError):
        create_task("")


def test_nonexistent_task():
    assert get_task(999999) is None
    assert complete_task(999999) is False
    assert reopen_task(999999) is False
    assert delete_task(999999) is False


def test_overdue_tasks():
    task_id = create_task(
        "Overdue Task",
        due_date="2020-01-01",
        due_time="10:00",
    )

    overdue = get_overdue_tasks()

    assert len(overdue) == 1
    assert overdue[0]["id"] == task_id


def test_daily_recurrence():
    from scheduler import calculate_next_occurrence

    next_date, next_time = calculate_next_occurrence(
        "2026-10-04",
        "daily",
        "09:00",
    )

    assert next_date == "2026-10-05"
    assert next_time == "09:00"


def test_weekly_recurrence():
    from scheduler import calculate_next_occurrence

    next_date, next_time = calculate_next_occurrence(
        "2026-10-04",
        "weekly",
        "14:30",
    )

    assert next_date == "2026-10-11"
    assert next_time == "14:30"


def test_monthly_recurrence():
    from scheduler import calculate_next_occurrence

    next_date, next_time = calculate_next_occurrence(
        "2026-10-04",
        "monthly",
        "18:00",
    )

    assert next_date == "2026-11-04"
    assert next_time == "18:00"


def test_monthly_end_of_month():
    from scheduler import calculate_next_occurrence

    next_date, next_time = calculate_next_occurrence(
        "2026-01-31",
        "monthly",
        "09:00",
    )

    assert next_date == "2026-02-28"
    assert next_time == "09:00"


def test_invalid_recurrence():
    from scheduler import calculate_next_occurrence

    with pytest.raises(ValueError):
        calculate_next_occurrence(
            "2026-10-04",
            "yearly",
            "09:00",
        )


def test_invalid_due_date():
    from scheduler import calculate_next_occurrence

    with pytest.raises(ValueError):
        calculate_next_occurrence(
            "October 4, 2026",
            "daily",
            "09:00",
        )


def test_invalid_due_time():
    from scheduler import calculate_next_occurrence

    with pytest.raises(ValueError):
        calculate_next_occurrence(
            "2026-10-04",
            "daily",
            "9 AM",
        )


def test_complete_recurring_task_creates_next_occurrence():
    from tasks import complete_recurring_task

    task_id = create_task(
        title="Pay electric bill",
        description="Monthly utility payment",
        due_date="2026-10-10",
        due_time="18:00",
        priority="High",
        recurring=True,
        recurrence="monthly",
    )

    result = complete_recurring_task(task_id)

    completed = result["completed_task"]
    next_task = result["next_task"]

    assert completed["completed"] == 1
    assert completed["due_date"] == "2026-10-10"
    assert completed["completed_at"] is not None

    assert next_task["completed"] == 0
    assert next_task["due_date"] == "2026-11-10"
    assert next_task["due_time"] == "18:00"
    assert next_task["priority"] == "High"
    assert next_task["recurring"] == 1
    assert next_task["recurrence"] == "monthly"


def test_complete_non_recurring_task_does_not_create_duplicate():
    from tasks import complete_recurring_task

    task_id = create_task(
        title="One-time task",
        due_date="2026-10-10",
    )

    result = complete_recurring_task(task_id)

    assert result["completed"] == 1

    tasks = list_tasks()

    assert len(tasks) == 1
    assert tasks[0]["id"] == task_id


def test_complete_recurring_task_missing_task():
    from tasks import complete_recurring_task

    result = complete_recurring_task(999999)

    assert result is None


def test_complete_already_completed_recurring_task():
    from tasks import complete_recurring_task

    task_id = create_task(
        title="Already Done",
        due_date="2026-10-10",
        recurring=True,
        recurrence="daily",
    )

    complete_recurring_task(task_id)

    second_result = complete_recurring_task(task_id)

    assert second_result is None

    tasks = list_tasks()

    assert len(tasks) == 2


def test_send_notification(monkeypatch):
    from notifications import send_notification

    calls = []

    def fake_run(command, check, **kwargs):
        calls.append((command, check))

    monkeypatch.setattr(
        "notifications.subprocess.run",
        fake_run,
    )

    send_notification(
        "Test Notification",
        "Testing notifications",
    )

    assert len(calls) == 1

    command, check = calls[0]

    assert check is True
    assert command[0] == "notify-send"
    assert "Test Notification" in command
    assert "Testing notifications" in command


def test_send_notification_critical(monkeypatch):
    from notifications import send_notification

    calls = []

    def fake_run(command, check, **kwargs):
        calls.append(command)

    monkeypatch.setattr(
        "notifications.subprocess.run",
        fake_run,
    )

    send_notification(
        "Critical Task",
        "Something important is due.",
        urgency="critical",
    )

    assert len(calls) == 1
    assert "--urgency" in calls[0]
    assert "critical" in calls[0]


def test_invalid_notification_urgency():
    from notifications import send_notification

    with pytest.raises(ValueError):
        send_notification(
            "Test",
            "Test",
            urgency="super-critical",
        )


def test_send_task_reminder(monkeypatch):
    from notifications import send_task_reminder

    calls = []

    def fake_send(title, message, urgency="normal"):
        calls.append((title, message, urgency))

    monkeypatch.setattr(
        "notifications.send_notification",
        fake_send,
    )

    task = {
        "title": "Pay electric bill",
        "due_date": "2026-10-10",
        "due_time": "18:00",
        "priority": "High",
    }

    send_task_reminder(task)

    assert len(calls) == 1

    title, message, urgency = calls[0]

    assert title == "Task Due: Pay electric bill"
    assert "2026-10-10" in message
    assert "18:00" in message
    assert "High" in message
    assert urgency == "normal"


def test_critical_task_uses_critical_notification(monkeypatch):
    from notifications import send_task_reminder

    calls = []

    def fake_send(title, message, urgency="normal"):
        calls.append((title, message, urgency))

    monkeypatch.setattr(
        "notifications.send_notification",
        fake_send,
    )

    task = {
        "title": "Critical Deadline",
        "due_date": "2026-10-04",
        "due_time": "17:00",
        "priority": "Critical",
    }

    send_task_reminder(task)

    assert calls[0][2] == "critical"


def test_task_notification_tracking():
    from tasks import mark_task_notified

    task_id = create_task(
        "Notification Test",
        due_date="2026-10-04",
        due_time="17:00",
    )

    task = get_task(task_id)
    assert task["last_notified_at"] is None

    assert mark_task_notified(
        task_id,
        "2026-10-04T17:00:00",
    ) is True

    task = get_task(task_id)

    assert task["last_notified_at"] == "2026-10-04T17:00:00"


def test_notification_tracking_nonexistent_task():
    from tasks import mark_task_notified

    assert mark_task_notified(
        999999,
        "2026-10-04T17:00:00",
    ) is False


def test_due_task_becomes_notified():
    from datetime import datetime

    from scheduler import is_task_due_for_notification
    from tasks import mark_task_notified

    task_id = create_task(
        "Reminder Test",
        due_date="2026-10-04",
        due_time="17:00",
    )

    task = get_task(task_id)

    now = datetime(2026, 10, 4, 18, 0)

    assert is_task_due_for_notification(task, now) is True

    mark_task_notified(
        task_id,
        "2026-10-04T18:00:00",
    )

    task = get_task(task_id)

    assert is_task_due_for_notification(task, now) is False


def test_check_due_tasks_notifies_once(monkeypatch):
    from scheduler import check_due_tasks

    notifications = []

    def fake_send(task):
        notifications.append(task["id"])

    monkeypatch.setattr(
        "notifications.send_task_reminder",
        fake_send,
    )

    task_id = create_task(
        "Anti-Spam Test",
        due_date="2020-01-01",
        due_time="09:00",
        priority="High",
    )

    assert check_due_tasks() == 1
    assert check_due_tasks() == 0
    assert check_due_tasks() == 0

    assert notifications == [task_id]

    task = get_task(task_id)

    assert task["last_notified_at"] is not None


def test_check_due_tasks_ignores_future_tasks(monkeypatch):
    notifications = []

    def fake_send(task):
        notifications.append(task["id"])

    monkeypatch.setattr(
        "notifications.send_task_reminder",
        fake_send,
    )

    create_task(
        "Future Task",
        due_date="2099-01-01",
        due_time="09:00",
    )

    assert check_due_tasks() == 0
    assert notifications == []


def test_check_due_tasks_ignores_completed_tasks(monkeypatch):
    notifications = []

    def fake_send(task):
        notifications.append(task["id"])

    monkeypatch.setattr(
        "notifications.send_task_reminder",
        fake_send,
    )

    task_id = create_task(
        "Completed Task",
        due_date="2020-01-01",
        due_time="09:00",
    )

    from tasks import complete_task

    complete_task(task_id)

    assert check_due_tasks() == 0
    assert notifications == []
