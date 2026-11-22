"""Desktop notifications for Important Task Manager.

One backend per platform:

* Linux - ``notify-send`` from libnotify
* macOS - ``osascript`` ``display notification``
* Windows - a PowerShell toast

Every backend runs without a shell, and user text is passed as argv or
environment variables, so a task title can never be executed as code.
"""

import os
import subprocess
import sys

from config import APP_NAME

VALID_URGENCIES = {"low", "normal", "critical"}

NOTIFICATION_TIMEOUT_SECONDS = 10

MACOS_SCRIPT = """
on run argv
    display notification (item 1 of argv) with title (item 2 of argv) subtitle (item 3 of argv)
end run
"""

WINDOWS_SCRIPT = """
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$texts = $template.GetElementsByTagName('text')
$texts.Item(0).AppendChild($template.CreateTextNode($env:ITM_NOTIFICATION_TITLE)) > $null
$texts.Item(1).AppendChild($template.CreateTextNode($env:ITM_NOTIFICATION_MESSAGE)) > $null
$toast = [Windows.UI.Notifications.ToastNotification]::new($template)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:ITM_NOTIFICATION_APP).Show($toast)
"""


def _notify_linux(title, message, urgency):
    try:
        subprocess.run(
            [
                "notify-send",
                "--app-name",
                APP_NAME,
                "--urgency",
                urgency,
                title,
                message,
            ],
            check=True,
            timeout=NOTIFICATION_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "notify-send was not found. Install libnotify "
            "(for example: sudo apt install libnotify-bin) to "
            "receive task reminders."
        ) from exc


def _notify_macos(title, message, urgency):
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                MACOS_SCRIPT,
                message,
                APP_NAME,
                title,
            ],
            check=True,
            timeout=NOTIFICATION_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "osascript was not found. It ships with macOS, so this "
            "usually means the notification helper is unavailable."
        ) from exc


def _notify_windows(title, message, urgency):
    env = dict(os.environ)
    env["ITM_NOTIFICATION_APP"] = APP_NAME
    env["ITM_NOTIFICATION_TITLE"] = title
    env["ITM_NOTIFICATION_MESSAGE"] = message

    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                WINDOWS_SCRIPT,
            ],
            check=True,
            env=env,
            timeout=NOTIFICATION_TIMEOUT_SECONDS,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "PowerShell was not found, so Windows toast notifications "
            "cannot be shown."
        ) from exc


def send_notification(title, message, urgency="normal"):
    """Send a desktop notification through the platform's notifier."""

    if urgency not in VALID_URGENCIES:
        raise ValueError(
            f"Invalid urgency. Choose one of: "
            f"{', '.join(sorted(VALID_URGENCIES))}"
        )

    if sys.platform == "darwin":
        _notify_macos(title, message, urgency)
    elif sys.platform == "win32":
        _notify_windows(title, message, urgency)
    else:
        _notify_linux(title, message, urgency)


def send_task_reminder(task):
    """
    Send a notification for a task.
    """

    title = f"Task Due: {task['title']}"

    message_parts = []

    if task.get("due_date"):
        due = task["due_date"]

        if task.get("due_time"):
            due += f" at {task['due_time']}"

        message_parts.append(f"Due: {due}")

    if task.get("priority"):
        message_parts.append(f"Priority: {task['priority']}")

    message = "\n".join(message_parts)

    if not message:
        message = "This task is due."

    urgency = (
        "critical" if task.get("priority") == "Critical" else "normal"
    )

    send_notification(
        title,
        message,
        urgency,
    )
