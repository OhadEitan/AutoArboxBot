#!/usr/bin/env python3
"""
Test script to verify Sunday 21:00 registration setup.
Run: python test_sunday.py
"""

import sys
sys.path.insert(0, '.')

from datetime import datetime, timedelta
from src.config import (
    UserConfig,
    TargetSession,
    save_user_config,
    save_target_sessions,
    load_user_config,
    load_target_sessions,
    DAY_NAMES,
)
from src.arbox_client import ArboxClient

def main():
    print("\n=== AutoArboxBot Sunday 21:00 Test ===\n")

    # Check if config exists
    config = load_user_config()
    if not config:
        print("No configuration found. Let's set it up.\n")

        email = input("Your Arbox email: ").strip()
        password = input("Your Arbox password: ")

        # Use known values from captured traffic
        config = UserConfig(
            email=email,
            password=password,
            membership_user_id=7751132,  # Your membership ID
            locations_box_id=14,  # CrossFit Haifa
            boxes_id=35,
        )
        save_user_config(config)
        print("\n✅ Config saved!")
    else:
        print(f"Using existing config for: {config.email}")

    # Set up target: Sunday 21:00 CrossFit
    target = TargetSession(
        name="CrossFit",
        day_of_week=0,  # Sunday
        time="21:00",
        enabled=True,
    )
    save_target_sessions([target])
    print(f"\n✅ Target set: {target.name} on {DAY_NAMES[target.day_of_week]} at {target.time}")

    # Test login
    print("\nTesting login...")
    client = ArboxClient(config.email, config.password)
    if not client.login():
        print("❌ Login failed! Check your credentials.")
        return
    print("✅ Login successful!")

    # Fetch schedule
    print("\nFetching schedule...")
    now = datetime.now()
    sessions = client.get_schedule(
        from_date=now,
        to_date=now + timedelta(days=10),  # Look ahead 10 days to find next Sunday
        locations_box_id=config.locations_box_id,
    )
    print(f"✅ Found {len(sessions)} total sessions")

    # Find Sunday 21:00 CrossFit sessions
    print("\n--- Sunday 21:00 CrossFit Sessions ---")
    sunday_21 = [
        s for s in sessions
        if s.name.lower() == "crossfit"
        and s.day_of_week == 0
        and s.time == "21:00"
    ]

    for s in sunday_21:
        reg_opens = s.registration_opens_at
        now_dt = datetime.now()
        time_until = (reg_opens - now_dt).total_seconds()

        if s.is_registered:
            status = "✅ ALREADY REGISTERED"
        elif s.can_register:
            status = f"🟢 CAN REGISTER NOW ({s.free} spots)"
        elif s.can_join_waitlist:
            status = "🟡 CLASS FULL (can join waitlist)"
        elif s.is_past:
            status = "⚫ PAST"
        else:
            status = f"⏳ REG NOT OPEN YET"

        hours_until = int(time_until // 3600) if time_until > 0 else 0
        mins_until = int((time_until % 3600) // 60) if time_until > 0 else 0

        print(f"\n  📅 {s.date} (Sunday)")
        print(f"  ⏰ {s.time} - {s.end_time}")
        print(f"  👤 Coach: {s.coach_name or 'Unknown'}")
        print(f"  📊 Spots: {s.free}/{s.max_users} available ({s.registered} registered)")
        print(f"  🎫 Status: {status}")
        print(f"  📬 Registration opens: {reg_opens}")
        if time_until > 0:
            print(f"  ⏱️  Opens in: {hours_until}h {mins_until}m")
        print(f"  🔑 Session ID: {s.id}")

    if not sunday_21:
        print("No Sunday 21:00 CrossFit sessions found in the next 10 days.")

    print("\n" + "="*50)
    print("TEST COMPLETE")
    print("="*50)
    print("\nTo run the bot continuously:")
    print("  python run.py run")
    print("\nThe bot will automatically register for Sunday 21:00 CrossFit")
    print("when the 72-hour registration window opens.")

if __name__ == "__main__":
    main()
