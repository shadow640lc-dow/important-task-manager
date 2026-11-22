"""Tests for the pure (non-Qt) helpers that live in app.py."""

import csv
import json

from app import (
    EXPORT_FIELDS,
    FILTER_LABELS,
    TASK_LIST_HEADER,
    build_filters,
    export_csv,
    export_json,
    format_task_row,
    sort_tasks,
)


def make_task(**overrides):
    task = {
        "id": 1,
        "title": "Sample task",
        "description": "",
        "due_date": None,
        "due_time": None,
        "priority": "Normal",
        "completed": 0,
        "recurring": 0,
        "recurrence": None,
        "created_at": "2026-10-01 09:00:00",
        "completed_at": None,
    }

    task.update(overrides)

    return task


def test_filter_labels_match_filter_definitions():
    filters = build_filters(set(), "2026-10-05")

    assert [label for label, _ in filters] == FILTER_LABELS


def test_filter_predicates():
    today = "2026-10-05"

    overdue = make_task(id=7, due_date="2026-10-01", due_time="09:00")
    due_today = make_task(id=8, due_date=today, due_time="12:00")
    done = make_task(id=9, completed=1)
    high = make_task(id=10, priority="High")
    critical = make_task(id=11, priority="Critical")
    recurring = make_task(id=12, recurring=1, recurrence="daily")
    undated = make_task(id=13)

    tasks = [
        overdue,
        due_today,
        done,
        high,
        critical,
        recurring,
        undated,
    ]

    predicates = dict(build_filters({overdue["id"]}, today))

    def matching(label):
        return {task["id"] for task in tasks if predicates[label](task)}

    assert matching("ALL TASKS") == {task["id"] for task in tasks}
    assert matching("ACTIVE") == {
        task["id"] for task in tasks if not task["completed"]
    }
    assert matching("COMPLETED") == {done["id"]}
    assert matching("OVERDUE") == {overdue["id"]}
    assert matching("DUE TODAY") == {due_today["id"]}
    assert matching("HIGH PRIORITY") == {high["id"]}
    assert matching("CRITICAL") == {critical["id"]}
    assert matching("RECURRING") == {recurring["id"]}
    assert matching("NO DATE") == {
        task["id"]
        for task in tasks
        if not task["due_date"]
    }


def test_completed_tasks_excluded_from_priority_filters():
    today = "2026-10-05"

    completed_high = make_task(
        id=1,
        priority="High",
        completed=1,
        recurring=1,
        recurrence="daily",
    )

    predicates = dict(build_filters(set(), today))

    assert not predicates["HIGH PRIORITY"](completed_high)
    assert not predicates["CRITICAL"](
        make_task(id=2, priority="Critical", completed=1)
    )
    assert not predicates["RECURRING"](completed_high)


def test_format_task_row_columns_align_with_header():
    row = format_task_row(make_task(due_date="2026-10-10", due_time="09:30"))

    # The header and the data rows must start each column at the
    # same offset or the list looks scrambled.
    assert TASK_LIST_HEADER.index("TASK") == 4
    assert row[4:4 + len("Sample task")] == "Sample task"

    assert TASK_LIST_HEADER.index("PRIORITY") - 1 == row.index("[")
    assert TASK_LIST_HEADER.index("DUE") == row.index("2026-10-10")


def test_format_task_row_marks_overdue_and_recurring():
    task = make_task(
        id=5,
        due_date="2026-10-01",
        due_time="09:00",
        recurring=1,
        recurrence="daily",
    )

    row = format_task_row(task, {5})

    assert "OVERDUE" in row
    assert "\u21bb" in row

    # Completed tasks are never flagged as overdue.
    completed = make_task(id=5, completed=1, due_date="2026-10-01")
    assert "OVERDUE" not in format_task_row(completed, {5})


def test_format_task_row_truncates_long_titles():
    task = make_task(title="X" * 80)

    row = format_task_row(task)

    assert len(task["title"]) == 80
    assert "\u2026" in row
    assert "X" * 33 not in row


def test_format_task_row_without_due_date():
    row = format_task_row(make_task(due_date=None))

    assert " - " in row
    assert "None" not in row


def test_sort_by_due_date_puts_undated_last():
    tasks = [
        make_task(id=1, title="no date", due_date=None),
        make_task(id=2, title="later", due_date="2026-12-01"),
        make_task(id=3, title="sooner", due_date="2026-01-01"),
    ]

    ordered = sort_tasks(tasks, "DUE DATE")

    assert [task["title"] for task in ordered] == [
        "sooner",
        "later",
        "no date",
    ]


def test_sort_by_title_is_case_insensitive():
    tasks = [
        make_task(id=1, title="beta"),
        make_task(id=2, title="Alpha"),
    ]

    ordered = sort_tasks(tasks, "TITLE")

    assert [task["title"] for task in ordered] == ["Alpha", "beta"]


def test_sort_by_newest_first():
    tasks = [
        make_task(id=1, created_at="2026-01-01 00:00:00"),
        make_task(id=2, created_at="2026-09-09 00:00:00"),
    ]

    ordered = sort_tasks(tasks, "NEWEST")

    assert [task["id"] for task in ordered] == [2, 1]


def test_sort_by_priority_keeps_database_order():
    tasks = [make_task(id=1), make_task(id=2)]

    assert sort_tasks(tasks, "PRIORITY") == tasks
    # The input list must not be mutated.
    assert sort_tasks(tasks, "TITLE") is not tasks


def test_export_json_round_trip(tmp_path):
    tasks = [
        make_task(id=1, title="First", due_date="2026-10-10"),
        make_task(id=2, title="Second", priority="Critical"),
    ]

    path = tmp_path / "tasks.json"

    export_json(tasks, str(path))

    with open(path, encoding="utf-8") as handle:
        loaded = json.load(handle)

    assert len(loaded) == 2
    assert loaded[0]["title"] == "First"
    assert loaded[0]["due_date"] == "2026-10-10"
    assert loaded[1]["priority"] == "Critical"
    assert set(loaded[0]) == set(EXPORT_FIELDS)


def test_export_csv_round_trip(tmp_path):
    tasks = [
        make_task(id=1, title="First", due_date="2026-10-10"),
        make_task(id=2, title="Second"),
    ]

    path = tmp_path / "tasks.csv"

    export_csv(tasks, str(path))

    with open(path, encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 2
    assert list(rows[0]) == EXPORT_FIELDS
    assert rows[0]["title"] == "First"
    assert rows[1]["due_date"] == ""
