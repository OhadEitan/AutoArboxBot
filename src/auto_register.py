#!/usr/bin/env python3
"""
Auto-registration script for GitHub Actions.

This script is designed to be run by GitHub Actions on a schedule.
It checks if any target sessions are ready for registration and registers them.
"""

from __future__ import annotations

import os
import sys
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

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
from src.telegram_bot import TelegramBot


def load_config_from_env() -> dict:
    """Load configuration from environment variables."""
    required_vars = ["ARBOX_EMAIL", "ARBOX_PASSWORD", "ARBOX_MEMBERSHIP_USER_ID"]

    for var in required_vars:
        if not os.environ.get(var):
            logger.error(f"Missing required environment variable: {var}")
            sys.exit(1)

    return {
        "email": os.environ["ARBOX_EMAIL"],
        "password": os.environ["ARBOX_PASSWORD"],
        "membership_user_id": int(os.environ["ARBOX_MEMBERSHIP_USER_ID"]),
        "locations_box_id": int(os.environ.get("ARBOX_LOCATIONS_BOX_ID", "14")),
        "boxes_id": int(os.environ.get("ARBOX_BOXES_ID", "35")),
    }


def load_targets_from_env() -> list[dict]:
    """Load targets from ARBOX_TARGETS environment variable (JSON string)."""
    targets_json = os.environ.get("ARBOX_TARGETS", "[]")
    try:
        targets = json.loads(targets_json)
        return [t for t in targets if t.get("enabled", True)]
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse ARBOX_TARGETS: {e}")
        return []


def load_targets_from_file(filepath: str = "targets.json") -> list[dict]:
    """Load targets from a JSON file."""
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r") as f:
        targets = json.load(f)
    return [t for t in targets if t.get("enabled", True)]


def find_matching_session(client: ArboxClient, target: dict, config: dict) -> Optional[dict]:
    """
    Find a session matching the target that is ready for registration.

    A session is ready if:
    1. It matches the target (name, day, time)
    2. Registration window is open (within the last few minutes or now open)
    3. User is not already registered
    """
    now = datetime.now()

    # Look ahead 7 days
    sessions = client.get_schedule(
        from_date=now,
        to_date=now + timedelta(days=7),
        locations_box_id=config["locations_box_id"],
        boxes_id=config["boxes_id"],
    )

    for session in sessions:
        # Check if session matches target
        if (
            target["name"].lower() in session.name.lower()
            and session.day_of_week == target["day_of_week"]
            and session.time == target["time"]
        ):
            # Skip if already registered
            if session.is_registered:
                logger.info(f"Already registered for {session.name} on {session.date} at {session.time}")
                return None

            # Skip if already on waitlist
            if session.is_on_waitlist:
                logger.info(f"Already on waitlist for {session.name} on {session.date} at {session.time}")
                return None

            # Check if registration is open
            if session.can_register or session.can_join_waitlist:
                logger.info(f"Found session ready for registration: {session.name} on {session.date} at {session.time}")
                return {
                    "id": session.id,
                    "name": session.name,
                    "date": session.date,
                    "time": session.time,
                    "trainer": session.coach_name or "TBD",
                    "can_register": session.can_register,
                    "can_join_waitlist": session.can_join_waitlist,
                    "free": session.free,
                    "max_users": session.max_users,
                }

            # Check if registration window opens soon (within 5 minutes)
            reg_opens = session.registration_opens_at
            time_until_open = (reg_opens - now).total_seconds()

            if 0 <= time_until_open <= 300:  # Within 5 minutes
                logger.info(f"Registration opens in {time_until_open:.0f} seconds for {session.name}")
                # Wait and retry (GitHub Actions will handle this via schedule)
                return None

            logger.info(f"Registration not yet open for {session.name} on {session.date} (opens {reg_opens})")
            return None

    return None


def register_for_session(
    client: ArboxClient,
    session: dict,
    config: dict,
    telegram: TelegramBot,
) -> bool:
    """Register for a session and send notification."""
    result = client.register(
        schedule_id=session["id"],
        membership_user_id=config["membership_user_id"],
    )

    if result.success:
        logger.info(f"Successfully registered for {session['name']} on {session['date']} at {session['time']}")
        telegram.notify_registration_success(
            session_name=session["name"],
            session_date=session["date"],
            session_time=session["time"],
            trainer=session["trainer"],
        )
        return True

    elif result.joined_waitlist:
        logger.info(f"Joined waitlist for {session['name']}")
        telegram.notify_waitlist_joined(
            session_name=session["name"],
            session_date=session["date"],
            session_time=session["time"],
            position=result.waitlist_position,
        )
        return True

    else:
        logger.error(f"Failed to register: {result.message}")
        telegram.notify_registration_failed(
            session_name=session["name"],
            session_date=session["date"],
            session_time=session["time"],
            error=result.message,
        )
        return False


def main():
    """Main entry point for auto-registration."""
    logger.info("=== AutoArboxBot Auto-Registration ===")
    logger.info(f"Current time: {datetime.now()}")

    # Load configuration
    config = load_config_from_env()
    logger.info(f"Loaded config for: {config['email']}")

    # Load targets (try env var first, then file)
    targets = load_targets_from_env()
    if not targets:
        targets = load_targets_from_file()

    if not targets:
        logger.warning("No targets configured. Nothing to do.")
        return

    logger.info(f"Loaded {len(targets)} target(s)")
    for t in targets:
        logger.info(f"  - {t['name']} on day {t['day_of_week']} at {t['time']}")

    # Initialize Telegram bot
    telegram = TelegramBot()
    if telegram.is_configured:
        logger.info("Telegram notifications enabled")
    else:
        logger.warning("Telegram not configured, notifications disabled")

    # Login to Arbox
    client = ArboxClient(config["email"], config["password"])
    if not client.login():
        logger.error("Failed to login to Arbox")
        telegram.notify_bot_status("Login failed", "Check credentials")
        sys.exit(1)

    logger.info("Logged in successfully")

    # Check each target
    registered_any = False
    for target in targets:
        logger.info(f"Checking target: {target['name']} on day {target['day_of_week']} at {target['time']}")

        session = find_matching_session(client, target, config)
        if session:
            success = register_for_session(client, session, config, telegram)
            if success:
                registered_any = True

    if not registered_any:
        logger.info("No sessions ready for registration at this time")

    logger.info("=== Auto-registration complete ===")


if __name__ == "__main__":
    main()
