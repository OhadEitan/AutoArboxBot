"""Configuration management for AutoArboxBot."""

import os
import json
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional

CONFIG_DIR = Path.home() / ".autoarboxbot"
CONFIG_FILE = CONFIG_DIR / "config.json"
TARGETS_FILE = CONFIG_DIR / "targets.json"


@dataclass
class UserConfig:
    """User configuration."""
    email: str
    password: str
    membership_user_id: int
    locations_box_id: int = 14
    boxes_id: int = 35


@dataclass
class TargetSession:
    """A target session to auto-register for."""
    name: str  # e.g., "CrossFit"
    day_of_week: int  # 0=Sunday, 1=Monday, ..., 6=Saturday (Israeli week)
    time: str  # e.g., "18:00"
    enabled: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TargetSession":
        return cls(**data)


def ensure_config_dir():
    """Create config directory if it doesn't exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def save_user_config(config: UserConfig):
    """Save user configuration."""
    ensure_config_dir()
    with open(CONFIG_FILE, "w") as f:
        json.dump(asdict(config), f, indent=2)
    # Set restrictive permissions (owner read/write only)
    os.chmod(CONFIG_FILE, 0o600)


def load_user_config() -> Optional[UserConfig]:
    """Load user configuration."""
    if not CONFIG_FILE.exists():
        return None
    with open(CONFIG_FILE, "r") as f:
        data = json.load(f)
    return UserConfig(**data)


def save_target_sessions(targets: list[TargetSession]):
    """Save target sessions."""
    ensure_config_dir()
    with open(TARGETS_FILE, "w") as f:
        json.dump([t.to_dict() for t in targets], f, indent=2)


def load_target_sessions() -> list[TargetSession]:
    """Load target sessions."""
    if not TARGETS_FILE.exists():
        return []
    with open(TARGETS_FILE, "r") as f:
        data = json.load(f)
    return [TargetSession.from_dict(d) for d in data]


# Day name mappings (Hebrew week starts on Sunday)
DAY_NAMES = {
    0: "Sunday (ראשון)",
    1: "Monday (שני)",
    2: "Tuesday (שלישי)",
    3: "Wednesday (רביעי)",
    4: "Thursday (חמישי)",
    5: "Friday (שישי)",
    6: "Saturday (שבת)",
}
