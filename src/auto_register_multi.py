#!/usr/bin/env python3
"""
Multi-user auto-registration script for GitHub Actions.

Processes all registered users and registers them for their target sessions.
"""

from __future__ import annotations

import os
import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.arbox_client import ArboxClient
from src.multi_user_bot import (
    get_all_users_with_targets,
    notify_registration_success,
    notify_registration_failed,
    notify_waitlist_joined,
)


def find_matching_session(client: ArboxClient, target: dict, config: dict):
    """Find a session matching the target that is ready for registration."""
    now = datetime.now()

    sessions = client.get_schedule(
        from_date=now,
        to_date=now + timedelta(days=7),
        locations_box_id=config.get("locations_box_id", 14),
        boxes_id=config.get("boxes_id", 35),
    )

    for session in sessions:
        if (
            target["name"].lower() in session.name.lower()
            and session.day_of_week == target["day_of_week"]
            and session.time == target["time"]
        ):
            # Skip if already registered or on waitlist
            if session.is_registered:
                logger.info(f"Already registered for {session.name} on {session.date} at {session.time}")
                return None
            if session.is_on_waitlist:
                logger.info(f"Already on waitlist for {session.name} on {session.date} at {session.time}")
                return None

            # Check if can register
            if session.can_register or session.can_join_waitlist:
                return {
                    "id": session.id,
                    "name": session.name,
                    "date": session.date,
                    "time": session.time,
                    "trainer": session.coach_name or "TBD",
                    "can_register": session.can_register,
                    "can_join_waitlist": session.can_join_waitlist,
                }

            logger.info(f"Registration not open for {session.name} on {session.date}")
            return None

    return None


def process_user(chat_id: str, user: dict) -> int:
    """Process a single user's registrations. Returns number of successful registrations."""
    email = user.get("email")
    password = user.get("password")
    membership_user_id = user.get("membership_user_id")
    targets = [t for t in user.get("targets", []) if t.get("enabled", True)]

    logger.info(f"Processing user: {email} ({len(targets)} targets)")

    if not email or not password or not membership_user_id:
        logger.warning(f"User {chat_id} missing credentials, skipping")
        return 0

    # Login
    client = ArboxClient(email, password)
    if not client.login():
        logger.error(f"Login failed for {email}")
        return 0

    config = {
        "membership_user_id": membership_user_id,
        "locations_box_id": user.get("locations_box_id", 14),
        "boxes_id": user.get("boxes_id", 35),
    }

    registered = 0
    for target in targets:
        logger.info(f"  Checking: {target['name']} day {target['day_of_week']} at {target['time']}")

        session = find_matching_session(client, target, config)
        if not session:
            continue

        # Try to register
        result = client.register(
            schedule_id=session["id"],
            membership_user_id=membership_user_id,
        )

        if result.success:
            logger.info(f"  Registered for {session['name']} on {session['date']}")
            notify_registration_success(
                chat_id=chat_id,
                session_name=session["name"],
                date=session["date"],
                time=session["time"],
                trainer=session["trainer"],
            )
            registered += 1

        elif result.joined_waitlist:
            logger.info(f"  Joined waitlist for {session['name']}")
            notify_waitlist_joined(
                chat_id=chat_id,
                session_name=session["name"],
                date=session["date"],
                time=session["time"],
                position=result.waitlist_position,
            )
            registered += 1

        else:
            logger.error(f"  Registration failed: {result.message}")
            notify_registration_failed(
                chat_id=chat_id,
                session_name=session["name"],
                date=session["date"],
                time=session["time"],
                error=result.message,
            )

    return registered


def main():
    """Main entry point."""
    logger.info("=== AutoArboxBot Multi-User Auto-Registration ===")
    logger.info(f"Time: {datetime.now()}")

    # Set bot token from environment
    import src.multi_user_bot as bot_module
    bot_module.BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

    # Get all users with targets
    users = get_all_users_with_targets()
    logger.info(f"Found {len(users)} user(s) with active targets")

    if not users:
        logger.info("No users to process")
        return

    total_registered = 0
    for chat_id, user in users:
        try:
            registered = process_user(chat_id, user)
            total_registered += registered
        except Exception as e:
            logger.error(f"Error processing user {chat_id}: {e}")

    logger.info(f"=== Complete: {total_registered} registration(s) ===")


if __name__ == "__main__":
    main()
