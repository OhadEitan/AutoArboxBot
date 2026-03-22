#!/usr/bin/env python3
"""
Multi-user Telegram Bot for AutoArboxBot.

Allows multiple users to:
- Register their Arbox credentials
- Manage their own target sessions
- Receive personalized notifications
"""

from __future__ import annotations

import os
import json
import logging
import requests
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)

USERS_FILE = Path(__file__).parent.parent / "users.json"
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")


def load_users() -> dict:
    """Load users database."""
    if not USERS_FILE.exists():
        return {"users": {}}
    with open(USERS_FILE, "r") as f:
        return json.load(f)


def save_users(data: dict) -> None:
    """Save users database."""
    with open(USERS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_user(chat_id: str) -> Optional[dict]:
    """Get user by chat ID."""
    data = load_users()
    return data["users"].get(str(chat_id))


def save_user(chat_id: str, user_data: dict) -> None:
    """Save user data."""
    data = load_users()
    data["users"][str(chat_id)] = user_data
    save_users(data)


def delete_user(chat_id: str) -> bool:
    """Delete user."""
    data = load_users()
    if str(chat_id) in data["users"]:
        del data["users"][str(chat_id)]
        save_users(data)
        return True
    return False


def send_message(chat_id: str, text: str, parse_mode: str = "HTML") -> bool:
    """Send message to a specific chat."""
    if not BOT_TOKEN:
        logger.warning("No bot token configured")
        return False

    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        response = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }, timeout=10)
        return response.ok
    except Exception as e:
        logger.error(f"Failed to send message: {e}")
        return False


def process_command(chat_id: str, text: str, username: str = "") -> str:
    """Process a command from a user."""
    text = text.strip()
    user = get_user(chat_id)

    # /start - Welcome message
    if text == "/start":
        if user:
            return (
                f"<b>Welcome back!</b>\n\n"
                f"You're registered as: {user.get('name', 'Unknown')}\n"
                f"Arbox email: {user.get('email', 'Not set')}\n\n"
                f"Use /help to see available commands."
            )
        return (
            "<b>Welcome to AutoArboxBot!</b>\n\n"
            "This bot automatically registers you for CrossFit classes.\n\n"
            "<b>To get started:</b>\n"
            "/setup - Register your Arbox account\n\n"
            "Use /help for all commands."
        )

    # /help - Show all commands
    if text == "/help":
        return (
            "<b>AutoArboxBot Commands:</b>\n\n"
            "<b>Setup:</b>\n"
            "/setup - Start registration wizard\n"
            "/setcreds email password - Set Arbox credentials\n"
            "/setid membership_id - Set membership ID\n"
            "/status - Show your account status\n"
            "/delete - Delete your account\n\n"
            "<b>Rules:</b>\n"
            "/list - Show your rules\n"
            "/add name day time - Add rule\n"
            "  Example: /add CrossFit 0 18:00\n"
            "  Days: 0=Sun 1=Mon 2=Tue 3=Wed 4=Thu 5=Fri 6=Sat\n"
            "/remove number - Remove rule\n"
            "/toggle number - Enable/disable rule\n"
            "/clear - Remove all rules\n\n"
            "<b>Actions:</b>\n"
            "/workouts - Show upcoming classes\n"
            "/register id - Register for class by ID\n"
            "/myreg - Show my registrations"
        )

    # /setup - Registration wizard
    if text == "/setup":
        return (
            "<b>Setup Wizard</b>\n\n"
            "Step 1: Set your Arbox credentials:\n"
            "<code>/setcreds your@email.com yourpassword</code>\n\n"
            "Step 2: Set your membership ID:\n"
            "<code>/setid 7751132</code>\n\n"
            "(You can find your membership ID in the Arbox app or ask the admin)"
        )

    # /setcreds - Set Arbox credentials
    if text.startswith("/setcreds "):
        parts = text[10:].split(maxsplit=1)
        if len(parts) < 2:
            return "Usage: /setcreds email password"
        email, password = parts[0], parts[1]

        if not user:
            user = {"name": username, "targets": []}

        user["email"] = email
        user["password"] = password
        save_user(chat_id, user)

        return (
            f"<b>Credentials saved!</b>\n\n"
            f"Email: {email}\n"
            f"Password: {'*' * len(password)}\n\n"
            f"Now set your membership ID with:\n"
            f"<code>/setid YOUR_MEMBERSHIP_ID</code>"
        )

    # /setid - Set membership ID
    if text.startswith("/setid "):
        try:
            membership_id = int(text[7:].strip())
        except ValueError:
            return "Invalid membership ID. Must be a number."

        if not user:
            user = {"name": username, "targets": []}

        user["membership_user_id"] = membership_id
        save_user(chat_id, user)

        return (
            f"<b>Membership ID saved!</b>\n\n"
            f"ID: {membership_id}\n\n"
            f"You're all set! Use /list to see your rules or /add to create one."
        )

    # /status - Show account status
    if text == "/status":
        if not user:
            return "You're not registered. Use /setup to get started."

        targets = user.get("targets", [])
        enabled = sum(1 for t in targets if t.get("enabled", True))

        return (
            f"<b>Account Status</b>\n\n"
            f"<b>Name:</b> {user.get('name', 'Unknown')}\n"
            f"<b>Email:</b> {user.get('email', 'Not set')}\n"
            f"<b>Membership ID:</b> {user.get('membership_user_id', 'Not set')}\n"
            f"<b>Rules:</b> {enabled}/{len(targets)} enabled"
        )

    # /delete - Delete account
    if text == "/delete":
        if delete_user(chat_id):
            return "Your account has been deleted."
        return "No account found."

    # === Rule management ===

    # /list - List rules
    if text in ["/list", "/rules"]:
        if not user:
            return "You're not registered. Use /setup to get started."

        targets = user.get("targets", [])
        if not targets:
            return "No rules configured. Use /add to create one."

        days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        lines = ["<b>Your Rules:</b>\n"]
        for i, t in enumerate(targets, 1):
            status = "ON" if t.get("enabled", True) else "OFF"
            day = days[t["day_of_week"]]
            lines.append(f"{i}. [{status}] {t['name']} - {day} {t['time']}")

        return "\n".join(lines)

    # /add - Add rule
    if text.startswith("/add "):
        if not user:
            return "You're not registered. Use /setup to get started."

        parts = text[5:].split()
        if len(parts) < 3:
            return "Usage: /add name day time\nExample: /add CrossFit 0 18:00"

        name = parts[0]
        try:
            day = int(parts[1])
            if day < 0 or day > 6:
                return "Day must be 0-6 (0=Sunday, 6=Saturday)"
        except ValueError:
            return "Invalid day. Use 0-6."
        time = parts[2]

        if "targets" not in user:
            user["targets"] = []

        user["targets"].append({
            "name": name,
            "day_of_week": day,
            "time": time,
            "enabled": True,
        })
        save_user(chat_id, user)

        days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        return f"Added: {name} on {days[day]} at {time}"

    # /remove - Remove rule
    if text.startswith("/remove "):
        if not user:
            return "You're not registered. Use /setup to get started."

        try:
            idx = int(text[8:].strip()) - 1
        except ValueError:
            return "Usage: /remove number"

        targets = user.get("targets", [])
        if idx < 0 or idx >= len(targets):
            return f"Invalid rule number. You have {len(targets)} rules."

        removed = targets.pop(idx)
        user["targets"] = targets
        save_user(chat_id, user)

        return f"Removed: {removed['name']}"

    # /toggle - Toggle rule
    if text.startswith("/toggle "):
        if not user:
            return "You're not registered. Use /setup to get started."

        try:
            idx = int(text[8:].strip()) - 1
        except ValueError:
            return "Usage: /toggle number"

        targets = user.get("targets", [])
        if idx < 0 or idx >= len(targets):
            return f"Invalid rule number. You have {len(targets)} rules."

        targets[idx]["enabled"] = not targets[idx].get("enabled", True)
        user["targets"] = targets
        save_user(chat_id, user)

        status = "enabled" if targets[idx]["enabled"] else "disabled"
        return f"Rule {idx + 1} is now {status}"

    # /clear - Clear all rules
    if text == "/clear":
        if not user:
            return "You're not registered. Use /setup to get started."

        user["targets"] = []
        save_user(chat_id, user)
        return "All rules cleared."

    # /workouts - Show upcoming workouts (requires credentials)
    if text == "/workouts":
        if not user:
            return "You're not registered. Use /setup to get started."
        if not user.get("email") or not user.get("password"):
            return "Set your credentials first with /setcreds email password"

        # Import here to avoid circular imports
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from src.arbox_client import ArboxClient

        client = ArboxClient(user["email"], user["password"])
        if not client.login():
            return "Login failed. Check your credentials with /setcreds"

        workouts = client.get_upcoming_workouts(hours=96)
        if not workouts:
            return "No upcoming workouts found."

        lines = ["<b>Upcoming Workouts (96h):</b>\n"]
        for w in workouts[:15]:  # Limit to 15
            status = " [REG]" if w.get("is_registered") else ""
            spots = f"{w['max_participants'] - w['participants']}/{w['max_participants']}"
            lines.append(f"<code>{w['id']}</code> {w['date']} {w['time']} {w['name'][:15]} ({spots}){status}")

        return "\n".join(lines)

    # /myreg - Show my registrations
    if text == "/myreg":
        if not user:
            return "You're not registered. Use /setup to get started."
        if not user.get("email") or not user.get("password"):
            return "Set your credentials first with /setcreds email password"

        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from src.arbox_client import ArboxClient

        client = ArboxClient(user["email"], user["password"])
        if not client.login():
            return "Login failed. Check your credentials."

        regs = client.get_my_registrations()
        if not regs:
            return "No upcoming registrations."

        lines = ["<b>My Registrations:</b>\n"]
        for r in regs:
            lines.append(f"{r['date']} {r['time']} - {r['name']}")

        return "\n".join(lines)

    # /register ID - Register for a workout
    if text.startswith("/register "):
        if not user:
            return "You're not registered. Use /setup to get started."
        if not user.get("email") or not user.get("password") or not user.get("membership_user_id"):
            return "Complete your setup first. Use /status to check."

        try:
            workout_id = int(text[10:].strip())
        except ValueError:
            return "Usage: /register WORKOUT_ID"

        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from src.arbox_client import ArboxClient

        client = ArboxClient(user["email"], user["password"])
        if not client.login():
            return "Login failed. Check your credentials."

        result = client.register(
            schedule_id=workout_id,
            membership_user_id=user["membership_user_id"],
        )

        if result.success:
            return f"Registered successfully for workout {workout_id}!"
        return f"Registration failed: {result.message}"

    # Unknown command
    if text.startswith("/"):
        return "Unknown command. Use /help to see available commands."

    return None


def notify_user(chat_id: str, message: str) -> bool:
    """Send notification to a specific user."""
    return send_message(chat_id, message)


def notify_registration_success(chat_id: str, session_name: str, date: str, time: str, trainer: str = "TBD") -> bool:
    """Notify user of successful registration."""
    message = (
        f"<b>Registration Successful!</b>\n\n"
        f"<b>Class:</b> {session_name}\n"
        f"<b>Date:</b> {date}\n"
        f"<b>Time:</b> {time}\n"
        f"<b>Trainer:</b> {trainer}"
    )
    return notify_user(chat_id, message)


def notify_registration_failed(chat_id: str, session_name: str, date: str, time: str, error: str) -> bool:
    """Notify user of failed registration."""
    message = (
        f"<b>Registration Failed</b>\n\n"
        f"<b>Class:</b> {session_name}\n"
        f"<b>Date:</b> {date}\n"
        f"<b>Time:</b> {time}\n"
        f"<b>Error:</b> {error}"
    )
    return notify_user(chat_id, message)


def notify_waitlist_joined(chat_id: str, session_name: str, date: str, time: str, position: Optional[int] = None) -> bool:
    """Notify user of joining waitlist."""
    pos_text = f"Position: #{position}" if position else ""
    message = (
        f"<b>Joined Waitlist</b>\n\n"
        f"<b>Class:</b> {session_name}\n"
        f"<b>Date:</b> {date}\n"
        f"<b>Time:</b> {time}\n"
        f"{pos_text}"
    )
    return notify_user(chat_id, message)


def get_all_users_with_targets() -> list[tuple[str, dict]]:
    """Get all users who have configured targets."""
    data = load_users()
    result = []

    for chat_id, user in data.get("users", {}).items():
        # Check if user has valid config
        if not user.get("email") or not user.get("password") or not user.get("membership_user_id"):
            continue

        targets = [t for t in user.get("targets", []) if t.get("enabled", True)]
        if targets:
            result.append((chat_id, user))

    return result
