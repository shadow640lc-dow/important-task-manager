import calendar
from datetime import date, datetime, timedelta

VALID_RECURRENCES = {
    "daily",
    "weekly",
    "monthly",
}


def calculate_next_occurrence(
    due_date,
    recurrence,
    due_time=None,
):
    """
    Calculate the next occurrence of a recurring task.

    due_date:
        YYYY-MM-DD string

    recurrence:
        daily, weekly, or monthly

    due_time:
        Optional HH:MM string
    """

    if not due_date:
        raise ValueError("A due date is required for recurring tasks.")

    if recurrence not in VALID_RECURRENCES:
        raise ValueError(
            f"Invalid recurrence. Choose one of: "
            f"{', '.join(sorted(VALID_RECURRENCES))}"
        )

    try:
        current_date = datetime.strptime(
            due_date,
            "%Y-%m-%d",
        ).date()
    except ValueError as exc:
        raise ValueError(
            "due_date must use YYYY-MM-DD format."
        ) from exc

    if due_time:
        try:
            datetime.strptime(due_time, "%H:%M")
        except ValueError as exc:
            raise ValueError(
                "due_time must use HH:MM format."
            ) from exc

    if recurrence == "daily":
        next_date = current_date + timedelta(days=1)

    elif recurrence == "weekly":
        next_date = current_date + timedelta(days=7)

    else:  # monthly
        year = current_date.year
        month = current_date.month + 1

        if month > 12:
            month = 1
            year += 1

        # Preserve the day when possible.
        # Example:
        # January 31 → February 28/29
        last_day = calendar.monthrange(year, month)[1]

        next_date = date(
            year,
            month,
            min(current_date.day, last_day),
        )

    return (
        next_date.isoformat(),
        due_time,
    )


def is_recurring_task(task):
    """
    Determine whether a database task is configured
    as a recurring task.
    """

    return bool(
        task.get("recurring")
        and task.get("recurrence")
    )


def is_task_due_for_notification(task, now=None):
    """
    Return True when an incomplete task is due and has not
    already been notified for its current occurrence.
    """

    if task.get("completed"):
        return False

    if not task.get("due_date"):
        return False

    if not task.get("due_time"):
        return False

    if now is None:
        now = datetime.now()

    try:
        due = datetime.strptime(
            f"{task['due_date']} {task['due_time']}",
            "%Y-%m-%d %H:%M",
        )
    except ValueError:
        return False

    if now < due:
        return False

    last_notified = task.get("last_notified_at")

    if not last_notified:
        return True

    try:
        last_notification_time = datetime.fromisoformat(
            last_notified
        )
    except ValueError:
        return True

    # If the task was modified/recreated after the previous
    # notification, allow a new notification.
    return last_notification_time < due


def check_due_tasks():
    """
    Check the database for tasks that need a notification.

    Returns the number of notifications successfully sent.
    """

    from notifications import send_task_reminder
    from tasks import list_tasks, mark_task_notified

    notified_count = 0

    for task in list_tasks(include_completed=False):
        if not is_task_due_for_notification(task):
            continue

        try:
            send_task_reminder(task)

            mark_task_notified(task["id"])

            notified_count += 1

        except Exception as exc:
            # One failed notification must not stop the
            # reminder checker from processing other tasks.
            print(
                f"Reminder error for task "
                f"{task['id']}: {exc}"
            )

    return notified_count


def run_reminder_worker(interval_seconds=30, stop_event=None):
    """
    Run the reminder checker continuously.

    interval_seconds:
        How often the database is checked.

    stop_event:
        Optional threading.Event used for clean shutdown.
    """

    import time

    if interval_seconds <= 0:
        raise ValueError(
            "interval_seconds must be greater than zero."
        )

    while True:
        check_due_tasks()

        if stop_event is not None:
            if stop_event.wait(interval_seconds):
                break
        else:
            time.sleep(interval_seconds)
