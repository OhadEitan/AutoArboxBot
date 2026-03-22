"""Arbox API Client for AutoArboxBot."""

import requests
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# API Configuration
BASE_URL = "https://apiappv2.arboxapp.com/api/v2"
DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "version": "13",
    "whitelabel": "Arbox",
    "referername": "app",
    "User-Agent": "Arbox/4000644 CFNetwork/3826.600.41 Darwin/24.6.0",
}


@dataclass
class Session:
    """Represents a class session from the schedule."""
    id: int
    name: str  # Category name (e.g., "CrossFit")
    date: str
    time: str
    end_time: str
    max_users: int
    registered: int
    free: int
    booking_option: str  # "insertScheduleUser", "insertStandby", "past", "cancelScheduleUser", "cancelWaitList"
    coach_name: Optional[str]
    day_of_week: int
    enable_registration_time: int  # Hours before when registration opens
    user_booked: Optional[int]  # schedule_user_id if user is booked
    user_in_standby: Optional[int]  # schedule_standby_id if user is on waitlist
    stand_by_position: Optional[int]  # Position in waitlist

    @property
    def can_register(self) -> bool:
        return self.booking_option == "insertScheduleUser"

    @property
    def can_join_waitlist(self) -> bool:
        return self.booking_option == "insertStandby"

    @property
    def is_registered(self) -> bool:
        return self.booking_option == "cancelScheduleUser"

    @property
    def is_on_waitlist(self) -> bool:
        return self.booking_option == "cancelWaitList"

    @property
    def is_past(self) -> bool:
        return self.booking_option == "past"

    @property
    def datetime(self) -> datetime:
        return datetime.strptime(f"{self.date} {self.time}", "%Y-%m-%d %H:%M")

    @property
    def registration_opens_at(self) -> datetime:
        return self.datetime - timedelta(hours=self.enable_registration_time)


@dataclass
class RegistrationResult:
    """Result of a registration attempt."""
    success: bool
    message: str
    joined_waitlist: bool = False
    waitlist_position: Optional[int] = None


class ArboxClient:
    """Client for interacting with the Arbox API."""

    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def _get_auth_headers(self) -> dict:
        """Get headers with authentication tokens."""
        if not self.access_token:
            raise RuntimeError("Not logged in. Call login() first.")
        return {
            "accesstoken": self.access_token,
            "refreshtoken": self.refresh_token or "",
        }

    def login(self) -> bool:
        """
        Login to Arbox and store authentication tokens.
        Returns True if successful.
        """
        url = f"{BASE_URL}/user/login"
        payload = {
            "email": self.email,
            "password": self.password,
        }

        try:
            response = self.session.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

            # Try to extract tokens from response body first
            if "data" in data:
                self.access_token = data["data"].get("token") or data["data"].get("accessToken") or data["data"].get("accesstoken")
                self.refresh_token = data["data"].get("refreshToken") or data["data"].get("refreshtoken")

            # Also check response headers (Arbox sends tokens there)
            if not self.access_token:
                self.access_token = response.headers.get("accesstoken")
                self.refresh_token = response.headers.get("refreshtoken")

            # Verify we actually got a token
            if self.access_token:
                logger.info("Login successful")
                return True

            logger.error(f"Login failed: No tokens in response. Keys: {data.keys() if isinstance(data, dict) else 'not dict'}")
            return False

        except requests.exceptions.HTTPError as e:
            logger.error(f"Login failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Login error: {e}")
            return False

    def get_schedule(
        self,
        from_date: datetime,
        to_date: datetime,
        locations_box_id: int = 14,
        boxes_id: int = 35,
    ) -> list[Session]:
        """
        Fetch schedule for a date range.
        Returns list of Session objects.
        """
        url = f"{BASE_URL}/schedule/betweenDates"
        payload = {
            "from": from_date.strftime("%Y-%m-%dT00:00:00.000Z"),
            "to": to_date.strftime("%Y-%m-%dT00:00:00.000Z"),
            "locations_box_id": locations_box_id,
            "boxes_id": boxes_id,
        }

        try:
            response = self.session.post(
                url,
                json=payload,
                headers=self._get_auth_headers(),
            )
            response.raise_for_status()
            data = response.json()

            # Handle both list response and {"data": [...]} response
            items = data if isinstance(data, list) else data.get("data", [])

            sessions = []
            for item in items:
                # Handle box_categories which can be dict or nested
                box_cat = item.get("box_categories", {})
                if isinstance(box_cat, list) and len(box_cat) > 0:
                    cat_name = box_cat[0].get("name", "Unknown")
                elif isinstance(box_cat, dict):
                    cat_name = box_cat.get("name", "Unknown")
                else:
                    cat_name = "Unknown"

                # Handle coach which can be dict or None
                coach = item.get("coach")
                coach_name = None
                if isinstance(coach, dict):
                    coach_name = coach.get("full_name")

                session = Session(
                    id=item["id"],
                    name=cat_name,
                    date=item["date"],
                    time=item["time"],
                    end_time=item["end_time"],
                    max_users=item["max_users"],
                    registered=item["registered"],
                    free=item["free"],
                    booking_option=item["booking_option"],
                    coach_name=coach_name,
                    day_of_week=item["day_of_week"],
                    enable_registration_time=item.get("enable_registration_time", 72),
                    user_booked=item.get("user_booked"),
                    user_in_standby=item.get("user_in_standby"),
                    stand_by_position=item.get("stand_by_position"),
                )
                sessions.append(session)

            logger.info(f"Fetched {len(sessions)} sessions")
            return sessions

        except requests.exceptions.HTTPError as e:
            logger.error(f"Failed to fetch schedule: {e}")
            return []
        except Exception as e:
            logger.error(f"Schedule fetch error: {e}")
            return []

    def register(
        self,
        schedule_id: int,
        membership_user_id: int,
    ) -> RegistrationResult:
        """
        Register for a class session.
        If class is full (516 error), automatically tries to join waitlist.
        """
        url = f"{BASE_URL}/scheduleUser/insert"
        payload = {
            "schedule_id": schedule_id,
            "membership_user_id": membership_user_id,
            "extras": {"spot": None},
        }

        try:
            response = self.session.post(
                url,
                json=payload,
                headers=self._get_auth_headers(),
            )
            response.raise_for_status()
            data = response.json()

            logger.info(f"Registration successful for schedule_id={schedule_id}")
            return RegistrationResult(
                success=True,
                message="Registration successful!",
            )

        except requests.exceptions.HTTPError as e:
            # Check if class is full (516 error) - automatically joins waitlist
            if e.response.status_code == 516:
                logger.info(f"Class full for schedule_id={schedule_id}")
                return RegistrationResult(
                    success=False,
                    message="Class is full. Check if you're already on the waitlist with 'my-registrations' or 'waitlist'.",
                )

            # Check if already registered (425 error)
            if e.response.status_code == 425:
                logger.info(f"Already registered for schedule_id={schedule_id}")
                return RegistrationResult(
                    success=True,  # Consider this success since user is registered
                    message="Already registered for this session.",
                )

            error_msg = str(e)
            try:
                error_data = e.response.json()
                error_msg = error_data.get("message", str(e))
            except:
                pass
            logger.error(f"Registration failed: {error_msg}")
            return RegistrationResult(
                success=False,
                message=f"Registration failed: {error_msg}",
            )
        except Exception as e:
            logger.error(f"Registration error: {e}")
            return RegistrationResult(
                success=False,
                message=f"Registration error: {e}",
            )

    def _try_join_waitlist(
        self,
        schedule_id: int,
        membership_user_id: int,
    ) -> RegistrationResult:
        """
        Try to join the waitlist for a full class.
        Uses the same scheduleUser/insert endpoint - Arbox handles waitlist automatically.
        """
        url = f"{BASE_URL}/scheduleUser/insert"
        payload = {
            "schedule_id": schedule_id,
            "membership_user_id": membership_user_id,
            "extras": {"spot": None},
        }

        try:
            # Use fresh session with exact app headers
            response = self.session.post(
                url,
                json=payload,
                headers=self._get_auth_headers(),
            )

            data = response.json()

            # Check if successfully added to waitlist
            if response.status_code == 200:
                waitlist_position = data.get("data", {}).get("stand_by_position")
                logger.info(f"Joined waitlist for schedule_id={schedule_id}, position={waitlist_position}")
                return RegistrationResult(
                    success=True,
                    message=f"Joined waitlist successfully! Position: {waitlist_position}",
                    joined_waitlist=True,
                    waitlist_position=waitlist_position,
                )

            # Check for specific error messages
            error_msg = data.get("error", {}).get("message", "Unknown error")
            if "already" in error_msg.lower() or response.status_code == 516:
                return RegistrationResult(
                    success=False,
                    message="Class is full. You may already be on the waitlist.",
                )

            logger.error(f"Waitlist join failed: {response.status_code} - {error_msg}")
            return RegistrationResult(
                success=False,
                message=f"Class is full. Waitlist join failed: {error_msg}",
            )

        except Exception as e:
            logger.error(f"Waitlist error: {e}")
            return RegistrationResult(
                success=False,
                message=f"Class is full. Waitlist join failed: {e}",
            )

    def join_waitlist(
        self,
        schedule_id: int,
        membership_user_id: int,
    ) -> RegistrationResult:
        """
        Join the waitlist for a full class.
        Uses the same endpoint as register - Arbox handles it automatically.
        """
        # Try registering - if class is full, Arbox should add to waitlist
        url = f"{BASE_URL}/scheduleUser/insert"
        payload = {
            "schedule_id": schedule_id,
            "membership_user_id": membership_user_id,
            "extras": {"spot": None},
        }

        try:
            response = self.session.post(
                url,
                json=payload,
                headers=self._get_auth_headers(),
            )
            data = response.json()

            # Check if added to waitlist
            if "standby" in str(data).lower() or "waitlist" in str(data).lower():
                logger.info(f"Joined waitlist for schedule_id={schedule_id}")
                return RegistrationResult(
                    success=True,
                    message="Joined waitlist",
                    joined_waitlist=True,
                )

            response.raise_for_status()
            logger.info(f"Registration successful (was expecting waitlist) for schedule_id={schedule_id}")
            return RegistrationResult(
                success=True,
                message="Registration successful (spot became available)!",
            )

        except requests.exceptions.HTTPError as e:
            error_msg = str(e)
            try:
                error_data = e.response.json()
                error_msg = error_data.get("message", str(e))
            except:
                pass
            logger.error(f"Waitlist join failed: {error_msg}")
            return RegistrationResult(
                success=False,
                message=f"Waitlist join failed: {error_msg}",
            )
        except Exception as e:
            logger.error(f"Waitlist error: {e}")
            return RegistrationResult(
                success=False,
                message=f"Waitlist error: {e}",
            )

    def cancel_registration(
        self,
        schedule_id: int,
        schedule_user_id: int,
        membership_user_id: int,
    ) -> bool:
        """
        Cancel a registration.
        Requires schedule_id, schedule_user_id, and membership_user_id.
        """
        url = f"{BASE_URL}/scheduleUser/delete"
        payload = {
            "schedule_id": schedule_id,
            "schedule_user_id": schedule_user_id,
            "membership_user_id": membership_user_id,
        }

        try:
            response = self.session.post(
                url,
                json=payload,
                headers=self._get_auth_headers(),
            )
            response.raise_for_status()
            logger.info(f"Cancelled registration schedule_id={schedule_id}")
            return True

        except Exception as e:
            logger.error(f"Cancel failed: {e}")
            return False

    def cancel_waitlist(
        self,
        schedule_id: int,
        schedule_standby_id: int,
        membership_user_id: int,
    ) -> bool:
        """
        Cancel a waitlist entry.
        Tries multiple approaches to cancel waitlist.
        """
        # Try the scheduleUser/delete endpoint with all three IDs
        url = f"{BASE_URL}/scheduleUser/delete"
        payload = {
            "schedule_id": schedule_id,
            "schedule_user_id": schedule_standby_id,
            "membership_user_id": membership_user_id,
        }

        try:
            response = self.session.post(
                url,
                json=payload,
                headers=self._get_auth_headers(),
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("data", {}).get("user_in_standby") is None:
                    logger.info(f"Cancelled waitlist for schedule_id={schedule_id}")
                    return True

            # If that didn't work, the API may not support waitlist cancellation properly
            logger.warning(f"Waitlist cancel API not working as expected")
            return False

        except Exception as e:
            logger.error(f"Waitlist cancel failed: {e}")
            return False

    def find_session(
        self,
        sessions: list[Session],
        name: str,
        day_of_week: int,
        time: str,
    ) -> Optional[Session]:
        """
        Find a specific session by name, day, and time.
        """
        for session in sessions:
            if (
                session.name.lower() == name.lower()
                and session.day_of_week == day_of_week
                and session.time == time
            ):
                return session
        return None

    def get_upcoming_workouts(
        self,
        locations_box_id: int = 14,
        boxes_id: int = 35,
        hours: int = 96,
    ) -> list[dict]:
        """
        Get all upcoming workouts within the specified hours (default 96).

        Returns a list of dicts with:
            - name: workout name
            - date: date string (YYYY-MM-DD)
            - time: time string (HH:MM)
            - trainer: coach name
            - participants: number of registered participants
            - max_participants: maximum capacity
            - free_spots: available spots
        """
        now = datetime.now()
        end_date = now + timedelta(hours=hours)

        sessions = self.get_schedule(
            from_date=now,
            to_date=end_date,
            locations_box_id=locations_box_id,
            boxes_id=boxes_id,
        )

        # Filter to only future sessions and sort by datetime
        workouts = []
        for session in sessions:
            # Skip past sessions
            if session.datetime < now:
                continue

            # Skip sessions beyond the hour limit
            if session.datetime > end_date:
                continue

            workouts.append({
                "id": session.id,
                "name": session.name,
                "date": session.date,
                "time": session.time,
                "trainer": session.coach_name or "TBD",
                "participants": session.registered,
                "max_participants": session.max_users,
                "free_spots": session.free,
                "is_registered": session.is_registered,
                "can_register": session.can_register,
                "can_join_waitlist": session.can_join_waitlist,
                "user_booked": session.user_booked,
            })

        # Sort by date and time
        workouts.sort(key=lambda w: (w["date"], w["time"]))

        return workouts

    def get_my_registrations(
        self,
        locations_box_id: int = 14,
        boxes_id: int = 35,
        days: int = 14,
    ) -> list[dict]:
        """
        Get all sessions the user is registered for.

        Returns a list of dicts with session info.
        """
        now = datetime.now()
        end_date = now + timedelta(days=days)

        sessions = self.get_schedule(
            from_date=now,
            to_date=end_date,
            locations_box_id=locations_box_id,
            boxes_id=boxes_id,
        )

        registrations = []
        for session in sessions:
            if session.is_registered:
                registrations.append({
                    "id": session.id,
                    "schedule_user_id": session.user_booked,
                    "name": session.name,
                    "date": session.date,
                    "time": session.time,
                    "trainer": session.coach_name or "TBD",
                    "participants": session.registered,
                    "max_participants": session.max_users,
                })

        registrations.sort(key=lambda w: (w["date"], w["time"]))
        return registrations

    def get_waitlist_positions(
        self,
        locations_box_id: int = 14,
        boxes_id: int = 35,
        days: int = 14,
    ) -> list[dict]:
        """
        Get all sessions where the user is on the waitlist.

        Returns a list of dicts with session info and waitlist position.
        """
        now = datetime.now()
        end_date = now + timedelta(days=days)

        sessions = self.get_schedule(
            from_date=now,
            to_date=end_date,
            locations_box_id=locations_box_id,
            boxes_id=boxes_id,
        )

        waitlist = []
        for session in sessions:
            # Check if user is on waitlist
            if session.is_on_waitlist:
                waitlist.append({
                    "id": session.id,
                    "schedule_standby_id": session.user_in_standby,
                    "name": session.name,
                    "date": session.date,
                    "time": session.time,
                    "trainer": session.coach_name or "TBD",
                    "participants": session.registered,
                    "max_participants": session.max_users,
                    "position": session.stand_by_position,
                })

        waitlist.sort(key=lambda w: (w["date"], w["time"]))
        return waitlist
