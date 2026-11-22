from datetime import datetime

from database import connection

VALID_PRIORITIES = {"Low", "Normal", "High", "Critical"}


def create_task(
    title,
    description="",
    due_date=None,
    due_time=None,
    priority="Normal",
    recurring=False,
    recurrence=None,
):
    if not title or not title.strip():
        raise ValueError("Task title cannot be empty.")

    if priority not in VALID_PRIORITIES:
        raise ValueError(
            f"Invalid priority. Choose one of: {', '.join(sorted(VALID_PRIORITIES))}"
        )

    with connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tasks
            (title, description, due_date, due_time, priority, recurring, recurrence)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title.strip(),
                description.strip(),
                due_date,
                due_time,
                priority,
                int(recurring),
                recurrence,
            ),
        )

        conn.commit()
        return cursor.lastrowid


def get_task(task_id):
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()

        return dict(row) if row else None


def list_tasks(include_completed=True):
    with connection() as conn:
        if include_completed:
            rows = conn.execute(
                """
                SELECT *
                FROM tasks
                ORDER BY completed ASC,
                         CASE priority
                             WHEN 'Critical' THEN 1
                             WHEN 'High' THEN 2
                             WHEN 'Normal' THEN 3
                             WHEN 'Low' THEN 4
                         END,
                         due_date IS NULL,
                         due_date ASC,
                         due_time IS NULL,
                         due_time ASC,
                         id DESC
                """
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT *
                FROM tasks
                WHERE completed = 0
                ORDER BY
                    CASE priority
                        WHEN 'Critical' THEN 1
                        WHEN 'High' THEN 2
                        WHEN 'Normal' THEN 3
                        WHEN 'Low' THEN 4
                    END,
                    due_date IS NULL,
                    due_date ASC,
                    due_time IS NULL,
                    due_time ASC,
                    id DESC
                """
            ).fetchall()

        return [dict(row) for row in rows]


def update_task(task_id, **fields):
    allowed_fields = {
        "title",
        "description",
        "due_date",
        "due_time",
        "priority",
        "recurring",
        "recurrence",
    }

    unknown = set(fields) - allowed_fields

    if unknown:
        raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")

    if not fields:
        return False

    if "title" in fields:
        if not fields["title"] or not fields["title"].strip():
            raise ValueError("Task title cannot be empty.")
        fields["title"] = fields["title"].strip()

    if "priority" in fields and fields["priority"] not in VALID_PRIORITIES:
        raise ValueError(
            f"Invalid priority. Choose one of: {', '.join(sorted(VALID_PRIORITIES))}"
        )

    if "description" in fields and fields["description"] is not None:
        fields["description"] = fields["description"].strip()

    assignments = ", ".join(f"{field} = ?" for field in fields)
    values = list(fields.values())
    values.append(task_id)

    with connection() as conn:
        cursor = conn.execute(
            f"UPDATE tasks SET {assignments} WHERE id = ?",
            values,
        )
        conn.commit()

        return cursor.rowcount > 0


def complete_task(task_id):
    with connection() as conn:
        cursor = conn.execute(
            """
            UPDATE tasks
            SET completed = 1,
                completed_at = ?
            WHERE id = ?
            """,
            (datetime.now().isoformat(timespec="seconds"), task_id),
        )

        conn.commit()
        return cursor.rowcount > 0


def reopen_task(task_id):
    with connection() as conn:
        cursor = conn.execute(
            """
            UPDATE tasks
            SET completed = 0,
                completed_at = NULL
            WHERE id = ?
            """,
            (task_id,),
        )

        conn.commit()
        return cursor.rowcount > 0


def delete_task(task_id):
    with connection() as conn:
        cursor = conn.execute(
            "DELETE FROM tasks WHERE id = ?",
            (task_id,),
        )

        conn.commit()
        return cursor.rowcount > 0


def delete_completed_tasks():
    """
    Delete every completed task.

    Returns the number of rows removed.
    """

    with connection() as conn:
        cursor = conn.execute(
            "DELETE FROM tasks WHERE completed = 1"
        )

        conn.commit()

        return cursor.rowcount


def get_overdue_tasks():
    now = datetime.now()

    with connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM tasks
            WHERE completed = 0
              AND due_date IS NOT NULL
              AND (
                    due_date < ?
                    OR (
                        due_date = ?
                        AND due_time IS NOT NULL
                        AND due_time < ?
                    )
              )
            ORDER BY due_date ASC, due_time ASC
            """,
            (
                now.strftime("%Y-%m-%d"),
                now.strftime("%Y-%m-%d"),
                now.strftime("%H:%M"),
            ),
        ).fetchall()

        return [dict(row) for row in rows]


def complete_recurring_task(task_id):
    """
    Complete a recurring task and create its next occurrence.

    The completed task remains in the database as history.
    A new task is created for the next occurrence.
    """

    from scheduler import calculate_next_occurrence

    task = get_task(task_id)

    if task is None:
        return None

    if task["completed"]:
        return None

    if not task["recurring"] or not task["recurrence"]:
        complete_task(task_id)
        return get_task(task_id)

    if not task["due_date"]:
        raise ValueError(
            "Recurring tasks must have a due date."
        )

    # Mark the current occurrence complete.
    complete_task(task_id)

    # Calculate the next occurrence.
    next_date, next_time = calculate_next_occurrence(
        task["due_date"],
        task["recurrence"],
        task["due_time"],
    )

    # Create the next occurrence.
    next_task_id = create_task(
        title=task["title"],
        description=task["description"],
        due_date=next_date,
        due_time=next_time,
        priority=task["priority"],
        recurring=True,
        recurrence=task["recurrence"],
    )

    return {
        "completed_task": get_task(task_id),
        "next_task": get_task(next_task_id),
    }


def mark_task_notified(task_id, notified_at=None):
    """
    Record the time a task notification was sent.
    """

    if notified_at is None:
        notified_at = datetime.now().isoformat(timespec="seconds")

    with connection() as conn:
        cursor = conn.execute(
            """
            UPDATE tasks
            SET last_notified_at = ?
            WHERE id = ?
            """,
            (notified_at, task_id),
        )

        conn.commit()

        return cursor.rowcount > 0
