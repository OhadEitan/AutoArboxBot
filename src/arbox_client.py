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
    booking_option: str  # "insertScheduleUser", "insertStandby", "past", "cancelScheduleUser"
    coach_name: Optional[str]
    day_of_week: int
    enable_registration_time: int  # Hours before when registration opens
    user_booked: Optional[int]  # schedule_user_id if user is booked

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
                self.access_token = data["data"].get("accessToken") or data["data"].get("accesstoken")
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
    ) -> list[Session]:
        """
        Fetch schedule for a date range.
        Returns list of Session objects.
        """
        url = f"{BASE_URL}/schedule/weekly"
        payload = {
            "from": from_date.strftime("%Y-%m-%dT00:00:00.000Z"),
            "to": to_date.strftime("%Y-%m-%dT23:59:59.999Z"),
            "locations_box_id": locations_box_id,
        }

        try:
            response = self.session.post(
                url,
                json=payload,
                headers=self._get_auth_headers(),
            )
            response.raise_for_status()
            data = response.json()

            sessions = []
            for item in data.get("data", []):
                session = Session(
                    id=item["id"],
                    name=item.get("box_categories", {}).get("name", "Unknown"),
                    date=item["date"],
                    time=item["time"],
                    end_time=item["end_time"],
                    max_users=item["max_users"],
                    registered=item["registered"],
                    free=item["free"],
                    booking_option=item["booking_option"],
                    coach_name=item.get("coach", {}).get("full_name") if item.get("coach") else None,
                    day_of_week=item["day_of_week"],
                    enable_registration_time=item.get("enable_registration_time", 72),
                    user_booked=item.get("user_booked"),
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
        schedule_user_id: int,
    ) -> bool:
        """
        Cancel a registration.
        """
        url = f"{BASE_URL}/scheduleUser/{schedule_user_id}"

        try:
            response = self.session.delete(
                url,
                headers=self._get_auth_headers(),
            )
            response.raise_for_status()
            logger.info(f"Cancelled registration schedule_user_id={schedule_user_id}")
            return True

        except Exception as e:
            logger.error(f"Cancel failed: {e}")
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
