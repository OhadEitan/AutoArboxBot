#!/usr/bin/env python3
"""
Check rules and register for classes within 72 hours.
Runs via GitHub Actions hourly — tries to register for any class
whose next occurrence is within 72 hours.
"""

import json
import os
import smtplib
import sys
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.arbox_client import ArboxClient

ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")
DATA_DIR = Path(__file__).parent.parent / "data"

DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

WORKER_URL = os.environ.get("WORKER_URL", "")
WORKER_KEY = os.environ.get("WORKER_KEY", "")


# ── Data helpers ─────────────────────────────────────────────────────

def load_json(filename):
    filepath = DATA_DIR / filename
    if not filepath.exists():
        return {}
    with open(filepath) as f:
        return json.load(f)


def save_json(filename, data):
    filepath = DATA_DIR / filename
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)


# ── Credentials ──────────────────────────────────────────────────────

def get_user_creds(user_id):
    """
    Get credentials from Worker KV first, fall back to env vars.
    Returns dict with email, password, membership_id or None.
    """
    # Try Worker
    if WORKER_URL and WORKER_KEY:
        try:
            url = f"{WORKER_URL.rstrip('/')}/creds/{user_id}"
            resp = requests.get(url, headers={"X-Worker-Key": WORKER_KEY}, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                print(f"   Got creds for {user_id} from Worker KV")
                return data
        except Exception as e:
            print(f"   Worker KV fetch failed: {e}")

    # Fall back to env vars
    prefix = f"ARBOX_{user_id.upper()}"
    email = os.environ.get(f"{prefix}_EMAIL")
    password = os.environ.get(f"{prefix}_PASSWORD")
    membership = os.environ.get(f"{prefix}_MEMBERSHIP")
    if email and password and membership:
        print(f"   Got creds for {user_id} from env vars")
        return {"email": email, "password": password, "membership_id": int(membership)}

    return None


# ── Time helpers ─────────────────────────────────────────────────────

def get_current_time():
    return datetime.now(ISRAEL_TZ)


def next_occurrence(target_day, target_time, now):
    """Calculate the next occurrence of a class given day (0=Sun) and time (HH:MM)."""
    hh, mm = map(int, target_time.split(":"))
    today = (now.weekday() + 1) % 7  # 0=Sun
    days_ahead = (target_day - today + 7) % 7
    candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0) + timedelta(days=days_ahead)
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


def should_try_register(rule, now):
    """Try to register if the class is within 72 hours from now."""
    target = next_occurrence(rule["target_day"], rule["target_time"], now)
    hours_until = (target - now).total_seconds() / 3600
    return hours_until <= 72


# ── Email ────────────────────────────────────────────────────────────

def send_email(to_email, subject, body):
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")

    if not all([smtp_host, smtp_user, smtp_pass]):
        print(f"   (SMTP not configured, skipping email to {to_email})")
        print(f"   Subject: {subject}")
        return

    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = smtp_user
        msg["To"] = to_email

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, [to_email], msg.as_string())
        print(f"   Email sent to {to_email}")
    except Exception as e:
        print(f"   Email failed: {e}")


# ── Registration ─────────────────────────────────────────────────────

def register_for_class(creds, user_profile, rule):
    print(f"   Registering {user_profile['name']} for {rule['target_class']} "
          f"{DAY_NAMES[rule['target_day']]} {rule['target_time']}")

    client = ArboxClient(creds["email"], creds["password"])

    if not client.login():
        return {"success": False, "message": "Login failed"}

    now = get_current_time()
    sessions = client.get_schedule(
        from_date=now,
        to_date=now + timedelta(days=7),
        locations_box_id=user_profile.get("locations_box_id", 14),
    )

    target = None
    for s in sessions:
        if (
            s.name.lower() == rule["target_class"].lower()
            and s.day_of_week == rule["target_day"]
            and s.time == rule["target_time"]
            and not s.is_past
        ):
            target = s
            break

    if not target:
        return {"success": False, "message": "Session not found in schedule"}

    if target.is_registered:
        return {"success": True, "message": "Already registered", "already": True}

    membership_id = creds["membership_id"]

    if target.can_register:
        result = client.register(target.id, membership_id)
        if result.success:
            return {
                "success": True,
                "message": f"Registered! ({target.free} spots were free)",
                "date": target.date,
                "time": target.time,
            }
        return {"success": False, "message": result.message}

    if target.can_join_waitlist:
        result = client.join_waitlist(target.id, membership_id)
        if result.success:
            return {
                "success": True,
                "message": "Joined waitlist",
                "waitlist": True,
                "date": target.date,
                "time": target.time,
            }
        return {"success": False, "message": result.message}

    return {"success": False, "message": f"Cannot register: {target.booking_option}"}


def update_user_classes(creds, user_profile):
    client = ArboxClient(creds["email"], creds["password"])
    if not client.login():
        return []

    now = get_current_time()
    sessions = client.get_schedule(
        from_date=now,
        to_date=now + timedelta(days=14),
        locations_box_id=user_profile.get("locations_box_id", 14),
    )

    return [
        {"name": s.name, "date": s.date, "time": s.time, "day": DAY_NAMES[s.day_of_week]}
        for s in sessions
        if s.is_registered
    ]


# ── Main ─────────────────────────────────────────────────────────────

def main():
    now = get_current_time()
    print(f"⏰ Running at {now.strftime('%Y-%m-%d %H:%M:%S')} (Israel time)")
    print(f"   Day: {DAY_NAMES[(now.weekday() + 1) % 7]} (index {(now.weekday() + 1) % 7})")

    users_data = load_json("users.json")
    rules_data = load_json("rules.json")
    classes_data = load_json("classes.json")

    users = users_data.get("users", {})
    rules = rules_data.get("rules", [])

    if not users:
        print("No users configured")
        return
    if not rules:
        print("No rules configured")
        return

    print(f"   {len(users)} users, {len(rules)} rules")

    triggered_count = 0
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        if not should_try_register(rule, now):
            continue

        triggered_count += 1
        user_id = rule["user_id"]
        user_profile = users.get(user_id)
        if not user_profile:
            print(f"   User {user_id} not found")
            continue

        creds = get_user_creds(user_id)
        if not creds:
            print(f"   No credentials for {user_id}")
            continue

        print(f"\n   Triggering: {rule['name']} for {user_profile['name']}")

        result = register_for_class(creds, user_profile, rule)
        print(f"   Result: {result['message']}")

        # Send notification
        notif_email = user_profile.get("notification_email")
        if notif_email:
            if result["success"]:
                if result.get("already"):
                    subj = f"Already registered: {rule['target_class']} {DAY_NAMES[rule['target_day']]} {rule['target_time']}"
                    body = "You were already registered for this class."
                elif result.get("waitlist"):
                    subj = f"Joined waitlist: {rule['target_class']} {result['date']} {result['time']}"
                    body = "Class was full. You're on the waitlist."
                else:
                    subj = f"Registered: {rule['target_class']} {result['date']} {result['time']}"
                    body = result["message"]
            else:
                subj = f"Registration failed: {rule['target_class']} {DAY_NAMES[rule['target_day']]} {rule['target_time']}"
                body = result["message"]
            send_email(notif_email, subj, body)

        rule["last_run"] = now.isoformat()
        rule["last_result"] = result["message"]

        # Disable once-only rules after trigger
        if rule.get("repeat") == "once":
            rule["enabled"] = False

    print(f"\n   Triggered {triggered_count} rules")

    # Update classes for all users
    print("\n   Updating class registrations...")
    classes_data["last_updated"] = now.isoformat()
    classes_data["classes"] = {}

    for user_id, user_profile in users.items():
        creds = get_user_creds(user_id)
        if not creds:
            continue
        registered = update_user_classes(creds, user_profile)
        classes_data["classes"][user_id] = registered
        print(f"   {user_profile['name']}: {len(registered)} classes")

    save_json("rules.json", rules_data)
    save_json("classes.json", classes_data)
    print("\nDone!")


if __name__ == "__main__":
    main()
