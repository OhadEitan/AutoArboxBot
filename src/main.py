#!/usr/bin/env python3
"""
AutoArboxBot - Automatic Arbox Class Registration

Usage:
    python -m src.main setup              # Initial setup (credentials + targets)
    python -m src.main run                # Run the bot
    python -m src.main status             # Check current status
    python -m src.main targets            # Manage target sessions
    python -m src.main test               # Test registration (dry run)
    python -m src.main workouts           # Show upcoming workouts (96 hours)
    python -m src.main my-registrations   # Show my registered sessions
    python -m src.main register <id>      # Register for a workout
    python -m src.main cancel <id>        # Cancel a registration
    python -m src.main waitlist           # Show my waitlist positions
"""

import sys
import logging
import argparse
from datetime import datetime, timedelta
from getpass import getpass

from .config import (
    UserConfig,
    TargetSession,
    load_user_config,
    save_user_config,
    load_target_sessions,
    save_target_sessions,
    DAY_NAMES,
)
from .arbox_client import ArboxClient
from .scheduler import RegistrationScheduler
from .notifier import notify_bot_started, notify_bot_stopped

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def setup_credentials():
    """Interactive setup for user credentials."""
    print("\n=== AutoArboxBot Setup ===\n")

    email = input("Arbox Email: ").strip()
    password = getpass("Arbox Password: ")

    # Test login
    print("\nTesting login...")
    client = ArboxClient(email, password)
    if not client.login():
        print("❌ Login failed. Please check your credentials.")
        return None

    print("✅ Login successful!")

    # Get membership_user_id by fetching schedule and looking at a booking
    print("\nFetching your membership info...")

    # Default values for CrossFit Haifa
    membership_user_id = input(
        "\nEnter your membership_user_id (from Proxyman capture, e.g., 7751132): "
    ).strip()

    try:
        membership_user_id = int(membership_user_id)
    except ValueError:
        print("❌ Invalid membership_user_id. Must be a number.")
        return None

    config = UserConfig(
        email=email,
        password=password,
        membership_user_id=membership_user_id,
        locations_box_id=14,  # CrossFit Haifa
        boxes_id=35,
    )

    save_user_config(config)
    print("\n✅ Configuration saved!")
    return config


def setup_targets():
    """Interactive setup for target sessions."""
    print("\n=== Setup Target Sessions ===")
    print("You can configure up to 3 sessions to auto-register.\n")

    targets = load_target_sessions()

    while True:
        print("\nCurrent targets:")
        if not targets:
            print("  (none)")
        else:
            for i, t in enumerate(targets, 1):
                status = "✅" if t.enabled else "❌"
                print(f"  {i}. {status} {t.name} on {DAY_NAMES[t.day_of_week]} at {t.time}")

        print("\nOptions:")
        print("  [a] Add new target")
        print("  [r] Remove target")
        print("  [t] Toggle enable/disable")
        print("  [d] Done")

        choice = input("\nChoice: ").strip().lower()

        if choice == "a":
            if len(targets) >= 3:
                print("❌ Maximum 3 targets allowed. Remove one first.")
                continue

            name = input("Class name (e.g., CrossFit): ").strip()

            print("\nDay of week:")
            for k, v in DAY_NAMES.items():
                print(f"  {k}: {v}")
            day = int(input("Day (0-6): ").strip())

            time_str = input("Time (HH:MM, e.g., 18:00): ").strip()

            targets.append(TargetSession(
                name=name,
                day_of_week=day,
                time=time_str,
                enabled=True,
            ))
            save_target_sessions(targets)
            print("✅ Target added!")

        elif choice == "r":
            if not targets:
                print("No targets to remove.")
                continue
            idx = int(input("Remove which number? ")) - 1
            if 0 <= idx < len(targets):
                removed = targets.pop(idx)
                save_target_sessions(targets)
                print(f"✅ Removed {removed.name}")
            else:
                print("Invalid number.")

        elif choice == "t":
            if not targets:
                print("No targets to toggle.")
                continue
            idx = int(input("Toggle which number? ")) - 1
            if 0 <= idx < len(targets):
                targets[idx].enabled = not targets[idx].enabled
                save_target_sessions(targets)
                status = "enabled" if targets[idx].enabled else "disabled"
                print(f"✅ {targets[idx].name} is now {status}")
            else:
                print("Invalid number.")

        elif choice == "d":
            break

    print(f"\n✅ {len(targets)} target(s) configured.")
    return targets


def cmd_setup(args):
    """Handle setup command."""
    config = setup_credentials()
    if config:
        setup_targets()


def cmd_run(args):
    """Handle run command."""
    config = load_user_config()
    if not config:
        print("❌ Not configured. Run 'setup' first.")
        sys.exit(1)

    targets = load_target_sessions()
    if not targets:
        print("❌ No target sessions configured. Run 'setup' first.")
        sys.exit(1)

    print("\n=== AutoArboxBot ===")
    print(f"Email: {config.email}")
    print(f"Targets: {len([t for t in targets if t.enabled])} enabled")

    # Login
    print("\nLogging in...")
    client = ArboxClient(config.email, config.password)
    if not client.login():
        print("❌ Login failed.")
        sys.exit(1)
    print("✅ Logged in")

    # Create scheduler
    scheduler = RegistrationScheduler(
        client=client,
        config=config,
        targets=targets,
    )

    # Send notification
    notify_bot_started()

    # Run
    print("\n🤖 Bot running. Press Ctrl+C to stop.\n")
    try:
        scheduler.run(check_interval=args.interval)
    except KeyboardInterrupt:
        print("\n\nStopping...")
        scheduler.stop()
        notify_bot_stopped()
        print("👋 Goodbye!")


def cmd_status(args):
    """Handle status command."""
    config = load_user_config()
    if not config:
        print("❌ Not configured. Run 'setup' first.")
        return

    targets = load_target_sessions()

    print("\n=== AutoArboxBot Status ===\n")
    print(f"Email: {config.email}")
    print(f"Membership ID: {config.membership_user_id}")
    print(f"Location ID: {config.locations_box_id}")

    print(f"\nTarget Sessions ({len(targets)}):")
    for t in targets:
        status = "✅ Enabled" if t.enabled else "❌ Disabled"
        print(f"  - {t.name} on {DAY_NAMES[t.day_of_week]} at {t.time} [{status}]")

    # Check upcoming schedule
    print("\nChecking upcoming sessions...")
    client = ArboxClient(config.email, config.password)
    if client.login():
        now = datetime.now()
        sessions = client.get_schedule(
            from_date=now,
            to_date=now + timedelta(days=7),
            locations_box_id=config.locations_box_id,
        )

        print(f"\nFound {len(sessions)} sessions in next 7 days")

        # Show matching sessions
        print("\nMatching target sessions:")
        for target in targets:
            if not target.enabled:
                continue
            for session in sessions:
                if (
                    session.name.lower() == target.name.lower()
                    and session.day_of_week == target.day_of_week
                    and session.time == target.time
                ):
                    reg_opens = session.registration_opens_at
                    status_icon = "✅" if session.is_registered else "⏳"
                    spots = f"{session.free}/{session.max_users} spots"
                    print(
                        f"  {status_icon} {session.name} {session.date} {session.time} "
                        f"({spots}) - Reg opens: {reg_opens}"
                    )
    else:
        print("❌ Could not login to check schedule.")


def cmd_targets(args):
    """Handle targets command."""
    setup_targets()


def cmd_test(args):
    """Handle test command - dry run without registering."""
    config = load_user_config()
    if not config:
        print("❌ Not configured. Run 'setup' first.")
        return

    print("\n=== Test Mode ===\n")
    print("Logging in...")
    client = ArboxClient(config.email, config.password)
    if not client.login():
        print("❌ Login failed.")
        return
    print("✅ Login successful")

    print("\nFetching schedule...")
    now = datetime.now()
    sessions = client.get_schedule(
        from_date=now,
        to_date=now + timedelta(days=7),
        locations_box_id=config.locations_box_id,
    )

    print(f"\n✅ Found {len(sessions)} sessions")

    # Filter to CrossFit only
    crossfit = [s for s in sessions if s.name.lower() == "crossfit"]
    print(f"\nCrossFit sessions ({len(crossfit)}):")
    for s in crossfit[:10]:  # Show first 10
        reg_status = "REGISTERED" if s.is_registered else f"{s.free} spots"
        print(f"  {s.date} {s.time}: {reg_status} (id={s.id})")

    print("\n✅ Test complete! Everything is working.")


def is_hebrew_char(char: str) -> bool:
    """Check if a character is Hebrew."""
    return '\u0590' <= char <= '\u05FF'


def fix_hebrew(text: str) -> str:
    """Fix Hebrew text for proper terminal display.

    Reverses Hebrew portions while keeping English portions intact.
    """
    if not any(is_hebrew_char(c) for c in text):
        return text

    # Split into segments of Hebrew and non-Hebrew
    segments = []
    current = []
    current_is_hebrew = None

    for char in text:
        char_is_hebrew = is_hebrew_char(char)
        if current_is_hebrew is None:
            current_is_hebrew = char_is_hebrew

        if char_is_hebrew == current_is_hebrew:
            current.append(char)
        else:
            segments.append((''.join(current), current_is_hebrew))
            current = [char]
            current_is_hebrew = char_is_hebrew

    if current:
        segments.append((''.join(current), current_is_hebrew))

    # Reverse Hebrew segments, keep others as-is, then reverse order of all segments
    result = []
    for seg, is_heb in reversed(segments):
        if is_heb:
            result.append(seg[::-1])
        else:
            result.append(seg)

    return ''.join(result)


def cmd_workouts(args):
    """Handle workouts command - show upcoming workouts within 96 hours."""
    config = load_user_config()
    if not config:
        print("❌ Not configured. Run 'setup' first.")
        return

    print("\n=== Upcoming Workouts (96 hours) ===\n")
    print("Logging in...")
    client = ArboxClient(config.email, config.password)
    if not client.login():
        print("❌ Login failed.")
        return

    workouts = client.get_upcoming_workouts(
        locations_box_id=config.locations_box_id,
        boxes_id=config.boxes_id,
        hours=args.hours,
    )

    if not workouts:
        print("No upcoming workouts found.")
        return

    print(f"Found {len(workouts)} workouts:\n")
    print(f"{'ID':<8} {'Date':<12} {'Time':<6} {'Name':<20} {'Trainer':<20} {'Spots':<10} {'Reg'}")
    print("-" * 85)

    for w in workouts:
        participants = f"{w['participants']}/{w['max_participants']}"
        name = fix_hebrew(w['name'])
        trainer = fix_hebrew(w['trainer'])
        status = "✓" if w['is_registered'] else ""
        print(f"{w['id']:<8} {w['date']:<12} {w['time']:<6} {name:<20} {trainer:<20} {participants:<10} {status}")


def cmd_my_registrations(args):
    """Handle my-registrations command - show sessions user is registered for."""
    config = load_user_config()
    if not config:
        print("❌ Not configured. Run 'setup' first.")
        return

    print("\n=== My Registrations ===\n")
    print("Logging in...")
    client = ArboxClient(config.email, config.password)
    if not client.login():
        print("❌ Login failed.")
        return

    registrations = client.get_my_registrations(
        locations_box_id=config.locations_box_id,
        boxes_id=config.boxes_id,
    )

    if not registrations:
        print("No upcoming registrations found.")
        return

    print(f"Found {len(registrations)} registrations:\n")
    print(f"{'ID':<8} {'Date':<12} {'Time':<6} {'Name':<20} {'Trainer':<20} {'Participants':<12}")
    print("-" * 85)

    for r in registrations:
        participants = f"{r['participants']}/{r['max_participants']}"
        name = fix_hebrew(r['name'])
        trainer = fix_hebrew(r['trainer'])
        print(f"{r['id']:<8} {r['date']:<12} {r['time']:<6} {name:<20} {trainer:<20} {participants:<12}")


def cmd_register(args):
    """Handle register command - register for a specific workout."""
    config = load_user_config()
    if not config:
        print("❌ Not configured. Run 'setup' first.")
        return

    print(f"\n=== Register for Workout {args.workout_id} ===\n")
    print("Logging in...")
    client = ArboxClient(config.email, config.password)
    if not client.login():
        print("❌ Login failed.")
        return

    result = client.register(
        schedule_id=args.workout_id,
        membership_user_id=config.membership_user_id,
    )

    if result.success:
        print(f"✅ {result.message}")
    else:
        print(f"❌ {result.message}")


def cmd_book(args):
    """Handle book command - register by day, time, and session name."""
    config = load_user_config()
    if not config:
        print("❌ Not configured. Run 'setup' first.")
        return

    print(f"\n=== Book Session ===\n")
    print(f"Looking for: {args.name} on {DAY_NAMES.get(args.day, args.day)} at {args.time}")
    print("Logging in...")

    client = ArboxClient(config.email, config.password)
    if not client.login():
        print("❌ Login failed.")
        return

    # Get upcoming workouts
    workouts = client.get_upcoming_workouts(
        locations_box_id=config.locations_box_id,
        boxes_id=config.boxes_id,
        hours=168,  # Look ahead 7 days
    )

    # Find matching workout
    matching = None
    for w in workouts:
        # Parse date to get day of week
        from datetime import datetime
        workout_date = datetime.strptime(w['date'], "%Y-%m-%d")
        workout_day = workout_date.weekday()
        # Convert to Sunday=0 format (Israeli week)
        workout_day = (workout_day + 1) % 7

        if (
            args.name.lower() in w['name'].lower()
            and workout_day == args.day
            and w['time'] == args.time
        ):
            matching = w
            break

    if not matching:
        print(f"\n❌ No matching session found.")
        print(f"   Make sure the session exists in the next 7 days.")
        return

    print(f"\nFound: {matching['name']} on {matching['date']} at {matching['time']}")
    available = matching['max_participants'] - matching['participants']
    print(f"       Trainer: {matching['trainer']}, Spots: {available}/{matching['max_participants']}")
    print(f"       ID: {matching['id']}")

    # Register
    print("\nRegistering...")
    result = client.register(
        schedule_id=matching['id'],
        membership_user_id=config.membership_user_id,
    )

    if result.success:
        print(f"✅ {result.message}")
    else:
        print(f"❌ {result.message}")


def cmd_cancel(args):
    """Handle cancel command - cancel a registration or waitlist entry."""
    config = load_user_config()
    if not config:
        print("❌ Not configured. Run 'setup' first.")
        return

    print(f"\n=== Cancel Registration ===\n")
    print("Logging in...")
    client = ArboxClient(config.email, config.password)
    if not client.login():
        print("❌ Login failed.")
        return

    # First check regular registrations
    registrations = client.get_my_registrations(
        locations_box_id=config.locations_box_id,
        boxes_id=config.boxes_id,
    )

    workout_info = None
    is_waitlist = False

    for r in registrations:
        if r['id'] == args.workout_id:
            workout_info = r
            break

    # If not found in registrations, check waitlist
    if not workout_info:
        waitlist = client.get_waitlist_positions(
            locations_box_id=config.locations_box_id,
            boxes_id=config.boxes_id,
        )
        for w in waitlist:
            if w['id'] == args.workout_id:
                workout_info = w
                is_waitlist = True
                break

    if not workout_info:
        print(f"❌ You are not registered or on waitlist for workout {args.workout_id}")
        return

    if is_waitlist:
        print(f"Cancelling waitlist (position #{workout_info.get('position', '?')}): {workout_info['name']} on {workout_info['date']} at {workout_info['time']}")
        success = client.cancel_waitlist(
            schedule_id=args.workout_id,
            schedule_standby_id=workout_info['schedule_standby_id'],
            membership_user_id=config.membership_user_id,
        )
    else:
        print(f"Cancelling: {workout_info['name']} on {workout_info['date']} at {workout_info['time']}")
        success = client.cancel_registration(
            schedule_id=args.workout_id,
            schedule_user_id=workout_info['schedule_user_id'],
            membership_user_id=config.membership_user_id,
        )

    if success:
        print("✅ Cancelled successfully")
    else:
        if is_waitlist:
            print("❌ Failed to cancel waitlist. Please use the Arbox app to cancel waitlist entries.")
        else:
            print("❌ Failed to cancel")


def cmd_waitlist(args):
    """Handle waitlist command - show sessions user is on waitlist for."""
    config = load_user_config()
    if not config:
        print("❌ Not configured. Run 'setup' first.")
        return

    print("\n=== My Waitlist ===\n")
    print("Logging in...")
    client = ArboxClient(config.email, config.password)
    if not client.login():
        print("❌ Login failed.")
        return

    waitlist = client.get_waitlist_positions(
        locations_box_id=config.locations_box_id,
        boxes_id=config.boxes_id,
    )

    if not waitlist:
        print("You are not on any waitlists.")
        return

    print(f"Found {len(waitlist)} waitlist entries:\n")
    print(f"{'ID':<10} {'Date':<12} {'Time':<6} {'Name':<20} {'Trainer':<20} {'Position':<8}")
    print("-" * 80)

    for w in waitlist:
        name = fix_hebrew(w['name'])
        trainer = fix_hebrew(w['trainer'])
        position = f"#{w['position']}" if w.get('position') else "?"
        print(f"{w['id']:<10} {w['date']:<12} {w['time']:<6} {name:<20} {trainer:<20} {position:<8}")


def main():
    parser = argparse.ArgumentParser(
        description="AutoArboxBot - Automatic Arbox Class Registration"
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Setup command
    subparsers.add_parser("setup", help="Initial setup")

    # Run command
    run_parser = subparsers.add_parser("run", help="Run the bot")
    run_parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Check interval in seconds (default: 60)",
    )

    # Status command
    subparsers.add_parser("status", help="Check current status")

    # Targets command
    subparsers.add_parser("targets", help="Manage target sessions")

    # Test command
    subparsers.add_parser("test", help="Test connection (dry run)")

    # Workouts command
    workouts_parser = subparsers.add_parser("workouts", help="Show upcoming workouts")
    workouts_parser.add_argument(
        "--hours",
        type=int,
        default=96,
        help="Hours to look ahead (default: 96)",
    )

    # My registrations command
    subparsers.add_parser("my-registrations", help="Show my registered sessions")

    # Register command
    register_parser = subparsers.add_parser("register", help="Register for a workout")
    register_parser.add_argument(
        "workout_id",
        type=int,
        help="Workout ID to register for",
    )

    # Cancel command
    cancel_parser = subparsers.add_parser("cancel", help="Cancel a registration")
    cancel_parser.add_argument(
        "workout_id",
        type=int,
        help="Workout ID to cancel",
    )

    # Waitlist command
    subparsers.add_parser("waitlist", help="Show my waitlist positions")

    # Book command (register by day/time/name)
    book_parser = subparsers.add_parser("book", help="Book by day, time, and name")
    book_parser.add_argument(
        "day",
        type=int,
        help="Day of week (0=Sunday, 1=Monday, ..., 6=Saturday)",
    )
    book_parser.add_argument(
        "time",
        type=str,
        help="Time (HH:MM format, e.g., 18:00)",
    )
    book_parser.add_argument(
        "name",
        type=str,
        help="Session name (e.g., CrossFit)",
    )

    args = parser.parse_args()

    if args.command == "setup":
        cmd_setup(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "targets":
        cmd_targets(args)
    elif args.command == "test":
        cmd_test(args)
    elif args.command == "workouts":
        cmd_workouts(args)
    elif args.command == "my-registrations":
        cmd_my_registrations(args)
    elif args.command == "register":
        cmd_register(args)
    elif args.command == "cancel":
        cmd_cancel(args)
    elif args.command == "waitlist":
        cmd_waitlist(args)
    elif args.command == "book":
        cmd_book(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
