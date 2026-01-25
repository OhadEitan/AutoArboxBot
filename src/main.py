#!/usr/bin/env python3
"""
AutoArboxBot - Automatic Arbox Class Registration

Usage:
    python -m src.main setup          # Initial setup (credentials + targets)
    python -m src.main run            # Run the bot
    python -m src.main status         # Check current status
    python -m src.main targets        # Manage target sessions
    python -m src.main test           # Test registration (dry run)
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
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
