"""Scheduler for automatic class registration."""

import time
import logging
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from .arbox_client import ArboxClient, Session, RegistrationResult
from .config import TargetSession, UserConfig
from .notifier import (
    notify_registration_success,
    notify_registration_failed,
    notify_joined_waitlist,
)

logger = logging.getLogger(__name__)

# Israel timezone
ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")


class RegistrationScheduler:
    """
    Monitors the schedule and registers for classes at the right time.
    """

    def __init__(
        self,
        client: ArboxClient,
        config: UserConfig,
        targets: list[TargetSession],
    ):
        self.client = client
        self.config = config
        self.targets = targets
        self.pending_registrations: dict[int, Session] = {}  # schedule_id -> Session
        self.completed_registrations: set[int] = set()  # schedule_ids already processed
        self.running = False

    def _now(self) -> datetime:
        """Get current time in Israel timezone."""
        return datetime.now(ISRAEL_TZ)

    def _find_upcoming_sessions(self) -> list[tuple[TargetSession, Session]]:
        """
        Find upcoming sessions that match our targets.
        Returns list of (target, session) tuples.
        """
        # Fetch schedule for next 7 days
        now = self._now()
        from_date = now
        to_date = now + timedelta(days=7)

        sessions = self.client.get_schedule(
            from_date=from_date,
            to_date=to_date,
            locations_box_id=self.config.locations_box_id,
        )

        matches = []
        for target in self.targets:
            if not target.enabled:
                continue

            for session in sessions:
                # Match by name, day, and time
                if (
                    session.name.lower() == target.name.lower()
                    and session.day_of_week == target.day_of_week
                    and session.time == target.time
                    and not session.is_past
                    and session.id not in self.completed_registrations
                ):
                    matches.append((target, session))

        return matches

    def _should_register_now(self, session: Session) -> bool:
        """
        Check if we should try to register for this session now.
        Returns True if registration window is open or about to open.
        """
        now = self._now()
        registration_opens = session.registration_opens_at.replace(tzinfo=ISRAEL_TZ)

        # Register if:
        # 1. Registration is already open (registration_opens <= now)
        # 2. OR registration opens within the next 5 seconds (for precision timing)
        time_until_open = (registration_opens - now).total_seconds()

        if time_until_open <= 5:
            return True

        return False

    def _attempt_registration(self, session: Session) -> RegistrationResult:
        """
        Attempt to register for a session.
        If full, try to join waitlist.
        """
        if session.is_registered:
            logger.info(f"Already registered for {session.name} on {session.date} at {session.time}")
            return RegistrationResult(
                success=True,
                message="Already registered",
            )

        if session.can_register:
            logger.info(f"Attempting registration for {session.name} on {session.date} at {session.time}")
            result = self.client.register(
                schedule_id=session.id,
                membership_user_id=self.config.membership_user_id,
            )
            if result.success:
                notify_registration_success(session.name, session.date, session.time)
            else:
                notify_registration_failed(session.name, result.message)
            return result

        elif session.can_join_waitlist:
            logger.info(f"Session full, joining waitlist for {session.name} on {session.date} at {session.time}")
            result = self.client.join_waitlist(
                schedule_id=session.id,
                membership_user_id=self.config.membership_user_id,
            )
            if result.success:
                notify_joined_waitlist(session.name, session.date, session.time)
            else:
                notify_registration_failed(session.name, result.message)
            return result

        else:
            logger.warning(f"Cannot register for {session.name}: booking_option={session.booking_option}")
            return RegistrationResult(
                success=False,
                message=f"Cannot register: {session.booking_option}",
            )

    def check_and_register(self):
        """
        Main check loop - find sessions and register when appropriate.
        """
        logger.info("Checking for sessions to register...")

        matches = self._find_upcoming_sessions()
        logger.info(f"Found {len(matches)} matching upcoming sessions")

        for target, session in matches:
            now = self._now()
            registration_opens = session.registration_opens_at.replace(tzinfo=ISRAEL_TZ)
            time_until_open = (registration_opens - now).total_seconds()

            # Log status
            if time_until_open > 0:
                hours = int(time_until_open // 3600)
                minutes = int((time_until_open % 3600) // 60)
                logger.info(
                    f"  {session.name} {session.date} {session.time}: "
                    f"Registration opens in {hours}h {minutes}m"
                )
            else:
                logger.info(
                    f"  {session.name} {session.date} {session.time}: "
                    f"Registration OPEN (free={session.free})"
                )

            # Check if we should register now
            if self._should_register_now(session):
                # If registration opens very soon, wait for exact timing
                if 0 < time_until_open <= 5:
                    logger.info(f"  Waiting {time_until_open:.1f}s for registration to open...")
                    time.sleep(time_until_open + 0.1)  # Small buffer

                result = self._attempt_registration(session)
                if result.success:
                    self.completed_registrations.add(session.id)
                    logger.info(f"  ✅ {result.message}")
                else:
                    logger.error(f"  ❌ {result.message}")

    def run(self, check_interval: int = 60):
        """
        Run the scheduler continuously.

        Args:
            check_interval: Seconds between checks (default 60)
        """
        self.running = True
        logger.info(f"Scheduler started. Checking every {check_interval} seconds.")
        logger.info(f"Monitoring {len([t for t in self.targets if t.enabled])} target sessions")

        while self.running:
            try:
                self.check_and_register()
            except Exception as e:
                logger.error(f"Error in check loop: {e}")

            # Sleep until next check
            # Use shorter intervals when a registration is imminent
            time.sleep(check_interval)

    def stop(self):
        """Stop the scheduler."""
        self.running = False
        logger.info("Scheduler stopped")


def calculate_next_occurrence(day_of_week: int, time_str: str) -> datetime:
    """
    Calculate the next occurrence of a given day/time.

    Args:
        day_of_week: 0=Sunday, 6=Saturday
        time_str: Time in "HH:MM" format

    Returns:
        datetime of next occurrence
    """
    now = datetime.now(ISRAEL_TZ)
    hour, minute = map(int, time_str.split(":"))

    # Find next occurrence of this day
    days_ahead = day_of_week - now.weekday()
    if days_ahead < 0:  # Target day already happened this week
        days_ahead += 7

    next_date = now + timedelta(days=days_ahead)
    next_occurrence = next_date.replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )

    # If the time already passed today, move to next week
    if next_occurrence <= now:
        next_occurrence += timedelta(days=7)

    return next_occurrence
