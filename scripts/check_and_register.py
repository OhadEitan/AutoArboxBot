#!/usr/bin/env python3
"""
Check rules and register for classes when trigger time matches.
Runs via GitHub Actions.
"""

import json
import smtplib
import os
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

# Add parent directory to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.arbox_client import ArboxClient

ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")
DATA_DIR = Path(__file__).parent.parent / "data"

DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def load_json(filename):
    """Load a JSON file from data directory."""
    filepath = DATA_DIR / filename
    if not filepath.exists():
        return {}
    with open(filepath) as f:
        return json.load(f)


def save_json(filename, data):
    """Save data to a JSON file."""
    filepath = DATA_DIR / filename
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)


def send_email(to_email, subject, body):
    """Send email notification using GitHub Actions."""
    # For now, just print - we'll set up email later
    print(f"📧 EMAIL to {to_email}")
    print(f"   Subject: {subject}")
    print(f"   Body: {body}")
    # TODO: Implement actual email sending


def get_current_time():
    """Get current time in Israel timezone."""
    return datetime.now(ISRAEL_TZ)


def should_trigger_rule(rule, now):
    """Check if a rule should be triggered now."""
    # Rule format: trigger_day (0-6), trigger_time ("HH:MM:SS")
    
    # Convert Python weekday (0=Mon) to our format (0=Sun)
    python_weekday = now.weekday()
    today = (python_weekday + 1) % 7
    
    if rule["trigger_day"] != today:
        return False
    
    # Check hour (we run hourly, so just match the hour)
    trigger_parts = rule["trigger_time"].split(":")
    trigger_hour = int(trigger_parts[0])
    
    if now.hour != trigger_hour:
        return False
    
    return True


def register_for_class(user, rule):
    """Attempt to register user for their target class."""
    print(f"🔄 Registering {user['name']} for {rule['target_class']} {DAY_NAMES[rule['target_day']]} {rule['target_time']}")
    
    client = ArboxClient(user["email"], user["password"])
    
    if not client.login():
        return {"success": False, "message": "Login failed"}
    
    # Fetch schedule
    now = get_current_time()
    sessions = client.get_schedule(
        from_date=now,
        to_date=now + timedelta(days=7),
        locations_box_id=user.get("locations_box_id", 14),
    )
    
    # Find target session
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
        return {"success": False, "message": "Session not found"}
    
    if target.is_registered:
        return {"success": True, "message": "Already registered", "already": True}
    
    # Try to register
    if target.can_register:
        result = client.register(target.id, user["membership_id"])
        if result.success:
            return {
                "success": True,
                "message": f"Registered! ({target.free} spots were free)",
                "date": target.date,
                "time": target.time,
            }
        else:
            return {"success": False, "message": result.message}
    
    elif target.can_join_waitlist:
        result = client.join_waitlist(target.id, user["membership_id"])
        if result.success:
            return {
                "success": True,
                "message": "Joined waitlist",
                "waitlist": True,
                "date": target.date,
                "time": target.time,
            }
        else:
            return {"success": False, "message": result.message}
    
    else:
        return {"success": False, "message": f"Cannot register: {target.booking_option}"}


def update_user_classes(user_id, user):
    """Fetch and update user's current class registrations."""
    client = ArboxClient(user["email"], user["password"])
    
    if not client.login():
        return []
    
    now = get_current_time()
    sessions = client.get_schedule(
        from_date=now,
        to_date=now + timedelta(days=14),
        locations_box_id=user.get("locations_box_id", 14),
    )
    
    # Get registered classes
    registered = []
    for s in sessions:
        if s.is_registered:
            registered.append({
                "name": s.name,
                "date": s.date,
                "time": s.time,
                "day": DAY_NAMES[s.day_of_week],
            })
    
    return registered


def main():
    now = get_current_time()
    print(f"⏰ Running at {now.strftime('%Y-%m-%d %H:%M:%S')} (Israel time)")
    print(f"   Day: {DAY_NAMES[(now.weekday() + 1) % 7]} (index {(now.weekday() + 1) % 7})")
    
    # Load data
    users_data = load_json("users.json")
    rules_data = load_json("rules.json")
    classes_data = load_json("classes.json")
    
    users = users_data.get("users", {})
    rules = rules_data.get("rules", [])
    
    if not users:
        print("📭 No users configured")
        return
    
    if not rules:
        print("📭 No rules configured")
        return
    
    print(f"👥 {len(users)} users, 📋 {len(rules)} rules")
    
    # Check each rule
    triggered_count = 0
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        
        if not should_trigger_rule(rule, now):
            continue
        
        triggered_count += 1
        user_id = rule["user_id"]
        user = users.get(user_id)
        
        if not user:
            print(f"⚠️ User {user_id} not found for rule {rule['id']}")
            continue
        
        print(f"\n🎯 Triggering rule: {rule['name']} for {user['name']}")
        
        # Register
        result = register_for_class(user, rule)
        
        # Send notification email
        if user.get("notification_email"):
            if result["success"]:
                if result.get("already"):
                    subject = f"Already registered: {rule['target_class']} {DAY_NAMES[rule['target_day']]} {rule['target_time']}"
                    body = f"You were already registered for this class."
                elif result.get("waitlist"):
                    subject = f"Joined waitlist: {rule['target_class']} {result['date']} {result['time']}"
                    body = f"Class was full. You're on the waitlist."
                else:
                    subject = f"✅ Registered: {rule['target_class']} {result['date']} {result['time']}"
                    body = result["message"]
            else:
                subject = f"❌ Registration failed: {rule['target_class']} {DAY_NAMES[rule['target_day']]} {rule['target_time']}"
                body = result["message"]
            
            send_email(user["notification_email"], subject, body)
        
        # Update rule last run
        rule["last_run"] = now.isoformat()
        rule["last_result"] = result["message"]
    
    print(f"\n✅ Triggered {triggered_count} rules")
    
    # Update classes for all users
    print("\n📅 Updating class registrations...")
    classes_data["last_updated"] = now.isoformat()
    classes_data["classes"] = {}
    
    for user_id, user in users.items():
        registered = update_user_classes(user_id, user)
        classes_data["classes"][user_id] = registered
        print(f"   {user['name']}: {len(registered)} classes")
    
    # Save updated data
    save_json("rules.json", rules_data)
    save_json("classes.json", classes_data)
    
    print("\n✅ Done!")


if __name__ == "__main__":
    main()
