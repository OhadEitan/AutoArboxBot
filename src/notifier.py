"""macOS Notification system for AutoArboxBot."""

import subprocess
import logging

logger = logging.getLogger(__name__)


def send_notification(title: str, message: str, sound: bool = True):
    """
    Send a macOS notification.

    Args:
        title: Notification title
        message: Notification body
        sound: Whether to play a sound
    """
    try:
        sound_param = 'sound name "default"' if sound else ""
        script = f'''
        display notification "{message}" with title "{title}" {sound_param}
        '''
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
        )
        logger.info(f"Notification sent: {title} - {message}")
    except Exception as e:
        logger.error(f"Failed to send notification: {e}")


def notify_registration_success(session_name: str, date: str, time: str):
    """Notify successful registration."""
    send_notification(
        title="✅ Arbox Registration Success!",
        message=f"Registered for {session_name} on {date} at {time}",
    )


def notify_registration_failed(session_name: str, reason: str):
    """Notify failed registration."""
    send_notification(
        title="❌ Arbox Registration Failed",
        message=f"Could not register for {session_name}: {reason}",
    )


def notify_joined_waitlist(session_name: str, date: str, time: str):
    """Notify joined waitlist."""
    send_notification(
        title="⏳ Joined Waitlist",
        message=f"Added to waitlist for {session_name} on {date} at {time}",
    )


def notify_bot_started():
    """Notify that the bot has started."""
    send_notification(
        title="🤖 AutoArboxBot Started",
        message="Monitoring for class registrations...",
        sound=False,
    )


def notify_bot_stopped():
    """Notify that the bot has stopped."""
    send_notification(
        title="🛑 AutoArboxBot Stopped",
        message="No longer monitoring registrations",
        sound=False,
    )
