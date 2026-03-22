#!/usr/bin/env python3
"""
AutoArboxBot - Multi-User Telegram Bot

Run with: python telegram_bot_multi.py
"""

import os
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict, field
from typing import Optional
from zoneinfo import ZoneInfo
import uuid

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# ==================== CONFIGURATION ====================
# Add your bot token here
BOT_TOKEN = "8604292375:AAHtzV5-pC0w-sOPJl22AFI8MQ8GQh2SXtg"

# Add Telegram user IDs who can use this bot
# Your ID is 405606318, add others when you get them
ALLOWED_USERS = [
    405606318,  # Ohad (you)
    # Add more IDs here:
    # 123456789,  # Person 2
    # 234567890,  # Person 3
    # 345678901,  # Person 4
]

# Admin user IDs (can see all users)
ADMIN_IDS = [405606318]  # You are the admin

# ==================== END CONFIGURATION ====================

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Israel timezone
ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")

# Config directory
CONFIG_DIR = Path.home() / ".autoarboxbot"
USERS_FILE = CONFIG_DIR / "users.json"

# Day names
DAY_NAMES_SHORT = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
DAY_NAMES_FULL = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

# Conversation states
(
    SETUP_EMAIL, SETUP_PASSWORD, SETUP_MEMBERSHIP_ID, SETUP_CONFIRM,
    ADD_NAME, ADD_TRIGGER_DAY, ADD_TRIGGER_TIME,
    ADD_TARGET_CLASS, ADD_TARGET_DAY, ADD_TARGET_TIME, ADD_CONFIRM,
) = range(11)


# ==================== ARBOX CLIENT ====================
import requests

ARBOX_BASE_URL = "https://apiappv2.arboxapp.com/api/v2"
ARBOX_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "version": "13",
    "whitelabel": "Arbox",
    "referername": "app",
    "User-Agent": "Arbox/4000644 CFNetwork/3826.600.41 Darwin/24.6.0",
}


@dataclass
class Session:
    id: int
    name: str
    date: str
    time: str
    end_time: str
    max_users: int
    registered: int
    free: int
    booking_option: str
    coach_name: Optional[str]
    day_of_week: int
    enable_registration_time: int
    user_booked: Optional[int]

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


class ArboxClient:
    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.session = requests.Session()
        self.session.headers.update(ARBOX_HEADERS)

    def _get_auth_headers(self) -> dict:
        if not self.access_token:
            raise RuntimeError("Not logged in")
        return {
            "accesstoken": self.access_token,
            "refreshtoken": self.refresh_token or "",
        }

    def login(self) -> bool:
        url = f"{ARBOX_BASE_URL}/user/login"
        try:
            response = self.session.post(url, json={
                "email": self.email,
                "password": self.password,
            })
            response.raise_for_status()
            data = response.json()

            if "data" in data:
                self.access_token = data["data"].get("token") or data["data"].get("accessToken")
                self.refresh_token = data["data"].get("refreshToken")

            if not self.access_token:
                self.access_token = response.headers.get("accesstoken")
                self.refresh_token = response.headers.get("refreshtoken")

            return bool(self.access_token)
        except Exception as e:
            logger.error(f"Login failed: {e}")
            return False

    def get_schedule(self, from_date: datetime, to_date: datetime, locations_box_id: int = 14) -> list[Session]:
        url = f"{ARBOX_BASE_URL}/schedule/betweenDates"
        try:
            response = self.session.post(url, json={
                "from": from_date.strftime("%Y-%m-%dT00:00:00.000Z"),
                "to": to_date.strftime("%Y-%m-%dT00:00:00.000Z"),
                "locations_box_id": locations_box_id,
                "boxes_id": 35,
            }, headers=self._get_auth_headers())
            response.raise_for_status()
            data = response.json()

            items = data if isinstance(data, list) else data.get("data", [])
            sessions = []
            
            for item in items:
                box_cat = item.get("box_categories", {})
                if isinstance(box_cat, list) and len(box_cat) > 0:
                    cat_name = box_cat[0].get("name", "Unknown")
                elif isinstance(box_cat, dict):
                    cat_name = box_cat.get("name", "Unknown")
                else:
                    cat_name = "Unknown"

                coach = item.get("coach")
                coach_name = coach.get("full_name") if isinstance(coach, dict) else None

                sessions.append(Session(
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
                ))
            return sessions
        except Exception as e:
            logger.error(f"Schedule fetch failed: {e}")
            return []

    def register(self, schedule_id: int, membership_user_id: int) -> tuple[bool, str]:
        url = f"{ARBOX_BASE_URL}/scheduleUser/insert"
        try:
            response = self.session.post(url, json={
                "schedule_id": schedule_id,
                "membership_user_id": membership_user_id,
                "extras": {"spot": None},
            }, headers=self._get_auth_headers())
            response.raise_for_status()
            return True, "Registration successful!"
        except requests.exceptions.HTTPError as e:
            try:
                error_msg = e.response.json().get("message", str(e))
            except:
                error_msg = str(e)
            return False, error_msg
        except Exception as e:
            return False, str(e)

    def join_waitlist(self, schedule_id: int, membership_user_id: int) -> tuple[bool, str]:
        return self.register(schedule_id, membership_user_id)


# ==================== USER MANAGEMENT ====================

@dataclass
class RegistrationRule:
    id: str
    name: str
    trigger_day: int
    trigger_time: str
    target_class: str
    target_day: int
    target_time: str
    enabled: bool = True
    last_run: Optional[str] = None
    last_result: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "RegistrationRule":
        return cls(**data)


@dataclass
class UserConfig:
    telegram_id: int
    name: str
    email: str
    password: str
    membership_user_id: int
    locations_box_id: int = 14
    rules: list = field(default_factory=list)
    is_admin: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["rules"] = [r if isinstance(r, dict) else r.to_dict() for r in self.rules]
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "UserConfig":
        rules_data = data.pop("rules", [])
        rules = [RegistrationRule.from_dict(r) if isinstance(r, dict) else r for r in rules_data]
        return cls(rules=rules, **data)


class UserManager:
    def __init__(self):
        self.users: dict[int, UserConfig] = {}
        self._load()

    def _load(self):
        if not USERS_FILE.exists():
            return
        try:
            with open(USERS_FILE, "r") as f:
                data = json.load(f)
            for user_data in data:
                user = UserConfig.from_dict(user_data)
                self.users[user.telegram_id] = user
        except Exception as e:
            logger.error(f"Failed to load users: {e}")

    def _save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(USERS_FILE, "w") as f:
            json.dump([u.to_dict() for u in self.users.values()], f, indent=2)

    def get(self, telegram_id: int) -> Optional[UserConfig]:
        return self.users.get(telegram_id)

    def add(self, user: UserConfig):
        self.users[user.telegram_id] = user
        self._save()

    def update(self, user: UserConfig):
        self.users[user.telegram_id] = user
        self._save()

    def all_users(self) -> list[UserConfig]:
        return list(self.users.values())

    def add_rule(self, telegram_id: int, rule: RegistrationRule):
        user = self.get(telegram_id)
        if user:
            user.rules.append(rule)
            self._save()

    def toggle_rule(self, telegram_id: int, rule_id: str) -> Optional[bool]:
        user = self.get(telegram_id)
        if not user:
            return None
        for rule in user.rules:
            if rule.id == rule_id:
                rule.enabled = not rule.enabled
                self._save()
                return rule.enabled
        return None

    def remove_rule(self, telegram_id: int, rule_id: str) -> bool:
        user = self.get(telegram_id)
        if not user:
            return False
        original = len(user.rules)
        user.rules = [r for r in user.rules if r.id != rule_id]
        if len(user.rules) < original:
            self._save()
            return True
        return False

    def update_rule_status(self, telegram_id: int, rule_id: str, result: str):
        user = self.get(telegram_id)
        if not user:
            return
        for rule in user.rules:
            if rule.id == rule_id:
                rule.last_run = datetime.now().isoformat()
                rule.last_result = result
                self._save()
                return


# ==================== TELEGRAM BOT ====================

class AutoArboxBot:
    def __init__(self):
        self.user_manager = UserManager()
        self.scheduler = AsyncIOScheduler(timezone=ISRAEL_TZ)
        self.app: Optional[Application] = None
        self._temp: dict[int, dict] = {}

    def _is_allowed(self, user_id: int) -> bool:
        return user_id in ALLOWED_USERS

    def _is_admin(self, user_id: int) -> bool:
        return user_id in ADMIN_IDS

    async def _check_access(self, update: Update) -> bool:
        if not self._is_allowed(update.effective_user.id):
            await update.message.reply_text(
                f"⛔ You are not authorized.\n\nYour ID: `{update.effective_user.id}`\n\n"
                "Send this ID to the admin to get access.",
                parse_mode="Markdown",
            )
            return False
        return True

    # ==================== Commands ====================

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_access(update):
            return

        user_id = update.effective_user.id
        user = self.user_manager.get(user_id)

        if user:
            enabled = len([r for r in user.rules if r.enabled])
            await update.message.reply_text(
                f"👋 Welcome back, *{user.name}*!\n\n"
                f"📧 {user.email}\n"
                f"📋 {enabled} active rules\n\n"
                "Commands:\n"
                "/rules - Your rules\n"
                "/add - Add a rule\n"
                "/test - Test connection\n"
                "/help - Help",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                f"👋 Hello *{update.effective_user.first_name}*!\n\n"
                "I'm AutoArboxBot. I register you for gym classes automatically!\n\n"
                "Use /setup to configure your Arbox account.",
                parse_mode="Markdown",
            )

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_access(update):
            return

        await update.message.reply_text(
            "📖 *AutoArboxBot Help*\n\n"
            "*Setup:*\n/setup - Configure Arbox credentials\n\n"
            "*Rules:*\n"
            "/add - Add a rule\n"
            "/rules - List your rules\n"
            "/toggle <id> - Enable/disable\n"
            "/remove <id> - Delete rule\n\n"
            "*Status:*\n"
            "/test - Test Arbox connection\n"
            "/status - Your status\n\n"
            "*How it works:*\n"
            "A rule runs at a specific time and registers you.\n"
            "Example: Sunday 18:00 → register for Wednesday 18:00 CrossFit",
            parse_mode="Markdown",
        )

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_access(update):
            return

        user = self.user_manager.get(update.effective_user.id)
        if not user:
            await update.message.reply_text("❌ Use /setup first")
            return

        client = ArboxClient(user.email, user.password)
        status = "✅ Connected" if client.login() else "❌ Login failed"
        enabled = len([r for r in user.rules if r.enabled])

        await update.message.reply_text(
            f"📊 *{user.name}*\n\n"
            f"Arbox: {status}\n"
            f"Email: {user.email}\n"
            f"Rules: {enabled}/{len(user.rules)} enabled\n"
            f"Time: {datetime.now(ISRAEL_TZ).strftime('%H:%M:%S')}",
            parse_mode="Markdown",
        )

    async def cmd_test(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_access(update):
            return

        user = self.user_manager.get(update.effective_user.id)
        if not user:
            await update.message.reply_text("❌ Use /setup first")
            return

        await update.message.reply_text("🔄 Testing...")

        client = ArboxClient(user.email, user.password)
        if not client.login():
            await update.message.reply_text("❌ Login failed. Check /setup")
            return

        now = datetime.now(ISRAEL_TZ)
        sessions = client.get_schedule(now, now + timedelta(days=7), user.locations_box_id)
        crossfit = [s for s in sessions if "crossfit" in s.name.lower()]

        msg = f"✅ *Connected!*\n\nFound {len(crossfit)} CrossFit sessions:\n"
        for s in crossfit[:6]:
            icon = "✅" if s.is_registered else f"({s.free})"
            msg += f"\n{s.date} {s.time} {icon}"

        await update.message.reply_text(msg, parse_mode="Markdown")

    async def cmd_rules(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_access(update):
            return

        user = self.user_manager.get(update.effective_user.id)
        if not user:
            await update.message.reply_text("❌ Use /setup first")
            return

        if not user.rules:
            await update.message.reply_text("📋 No rules yet.\n\nUse /add to create one!")
            return

        msg = "📋 *Your Rules*\n\n"
        for r in user.rules:
            icon = "✅" if r.enabled else "❌"
            last = f"\n   └ {r.last_result}" if r.last_result else ""
            msg += (
                f"{icon} *{r.name}* (`{r.id}`)\n"
                f"   {DAY_NAMES_SHORT[r.trigger_day]} {r.trigger_time} → "
                f"{r.target_class} {DAY_NAMES_SHORT[r.target_day]} {r.target_time}{last}\n\n"
            )

        msg += "_/toggle <id> or /remove <id>_"
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def cmd_toggle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_access(update):
            return

        if not context.args:
            await update.message.reply_text("Usage: /toggle <rule_id>")
            return

        rule_id = context.args[0]
        result = self.user_manager.toggle_rule(update.effective_user.id, rule_id)

        if result is None:
            await update.message.reply_text(f"❌ Rule `{rule_id}` not found", parse_mode="Markdown")
        else:
            status = "enabled ✅" if result else "disabled ❌"
            await update.message.reply_text(f"Rule `{rule_id}` is now {status}", parse_mode="Markdown")
            await self._reschedule()

    async def cmd_remove(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_access(update):
            return

        if not context.args:
            await update.message.reply_text("Usage: /remove <rule_id>")
            return

        rule_id = context.args[0]
        if self.user_manager.remove_rule(update.effective_user.id, rule_id):
            await update.message.reply_text(f"🗑️ Rule `{rule_id}` removed", parse_mode="Markdown")
            await self._reschedule()
        else:
            await update.message.reply_text(f"❌ Rule `{rule_id}` not found", parse_mode="Markdown")

    async def cmd_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("⛔ Admin only")
            return

        users = self.user_manager.all_users()
        if not users:
            await update.message.reply_text("No users registered")
            return

        msg = "👥 *All Users*\n\n"
        for u in users:
            enabled = len([r for r in u.rules if r.enabled])
            msg += f"• *{u.name}* ({u.telegram_id})\n  {u.email} - {enabled} rules\n\n"

        await update.message.reply_text(msg, parse_mode="Markdown")

    # ==================== Setup Conversation ====================

    async def setup_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_access(update):
            return ConversationHandler.END

        self._temp[update.effective_user.id] = {
            "name": update.effective_user.first_name,
        }

        await update.message.reply_text(
            "⚙️ *Arbox Setup*\n\nEnter your Arbox *email*:",
            parse_mode="Markdown",
        )
        return SETUP_EMAIL

    async def setup_email(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self._temp[update.effective_user.id]["email"] = update.message.text.strip()
        await update.message.reply_text("🔑 Enter your Arbox *password*:", parse_mode="Markdown")
        return SETUP_PASSWORD

    async def setup_password(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self._temp[update.effective_user.id]["password"] = update.message.text.strip()

        # Delete the password message for security
        try:
            await update.message.delete()
        except:
            pass

        await update.message.reply_text(
            "🔢 Enter your *membership\\_user\\_id*:\n\n"
            "(This is the number you captured from Proxyman, e.g., 7751132)",
            parse_mode="Markdown",
        )
        return SETUP_MEMBERSHIP_ID

    async def setup_membership(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            mid = int(update.message.text.strip())
        except ValueError:
            await update.message.reply_text("❌ Must be a number. Try again:")
            return SETUP_MEMBERSHIP_ID

        self._temp[update.effective_user.id]["membership_user_id"] = mid

        # Test login
        data = self._temp[update.effective_user.id]
        await update.message.reply_text("🔄 Testing login...")

        client = ArboxClient(data["email"], data["password"])
        if not client.login():
            await update.message.reply_text(
                "❌ Login failed. Check your email/password.\n\nStart over with /setup"
            )
            return ConversationHandler.END

        keyboard = [[
            InlineKeyboardButton("✅ Save", callback_data="setup_save"),
            InlineKeyboardButton("❌ Cancel", callback_data="setup_cancel"),
        ]]

        await update.message.reply_text(
            f"✅ *Login successful!*\n\n"
            f"Email: {data['email']}\n"
            f"Membership ID: {mid}\n\n"
            f"Save this configuration?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return SETUP_CONFIRM

    async def setup_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        user_id = update.effective_user.id

        if query.data == "setup_cancel":
            del self._temp[user_id]
            await query.edit_message_text("❌ Setup cancelled")
            return ConversationHandler.END

        data = self._temp[user_id]
        user = UserConfig(
            telegram_id=user_id,
            name=data["name"],
            email=data["email"],
            password=data["password"],
            membership_user_id=data["membership_user_id"],
            is_admin=user_id in ADMIN_IDS,
        )
        self.user_manager.add(user)
        del self._temp[user_id]

        await query.edit_message_text(
            f"✅ *Setup complete!*\n\n"
            f"Welcome, {user.name}!\n\n"
            f"Now use /add to create your first rule.",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    async def setup_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id in self._temp:
            del self._temp[user_id]
        await update.message.reply_text("❌ Setup cancelled")
        return ConversationHandler.END

    # ==================== Add Rule Conversation ====================

    async def add_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_access(update):
            return ConversationHandler.END

        user = self.user_manager.get(update.effective_user.id)
        if not user:
            await update.message.reply_text("❌ Use /setup first")
            return ConversationHandler.END

        self._temp[update.effective_user.id] = {}
        await update.message.reply_text(
            "➕ *Add Rule*\n\nGive this rule a name (e.g., 'Wednesday Evening'):",
            parse_mode="Markdown",
        )
        return ADD_NAME

    async def add_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self._temp[update.effective_user.id]["name"] = update.message.text.strip()

        keyboard = [
            [InlineKeyboardButton(d, callback_data=f"tday_{i}") for i, d in enumerate(DAY_NAMES_SHORT[:4])],
            [InlineKeyboardButton(d, callback_data=f"tday_{i}") for i, d in enumerate(DAY_NAMES_SHORT[4:], 4)],
        ]

        await update.message.reply_text(
            "📅 *Trigger Day*\n\nWhen should the bot register you?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return ADD_TRIGGER_DAY

    async def add_trigger_day_cb(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        day = int(query.data.split("_")[1])
        self._temp[update.effective_user.id]["trigger_day"] = day

        await query.edit_message_text(
            f"📅 Trigger: *{DAY_NAMES_FULL[day]}*\n\n"
            "⏰ Enter trigger time (HH:MM:SS):\n"
            "Example: `18:00:00`",
            parse_mode="Markdown",
        )
        return ADD_TRIGGER_TIME

    async def add_trigger_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        time_str = update.message.text.strip()
        
        # Add seconds if not present
        if len(time_str.split(":")) == 2:
            time_str += ":00"

        try:
            datetime.strptime(time_str, "%H:%M:%S")
        except ValueError:
            await update.message.reply_text("❌ Invalid format. Use HH:MM:SS")
            return ADD_TRIGGER_TIME

        self._temp[update.effective_user.id]["trigger_time"] = time_str

        await update.message.reply_text(
            "🏋️ *Target Class*\n\nWhat class? (e.g., `CrossFit`):",
            parse_mode="Markdown",
        )
        return ADD_TARGET_CLASS

    async def add_target_class(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self._temp[update.effective_user.id]["target_class"] = update.message.text.strip()

        keyboard = [
            [InlineKeyboardButton(d, callback_data=f"xday_{i}") for i, d in enumerate(DAY_NAMES_SHORT[:4])],
            [InlineKeyboardButton(d, callback_data=f"xday_{i}") for i, d in enumerate(DAY_NAMES_SHORT[4:], 4)],
        ]

        await update.message.reply_text(
            "📅 *Target Day*\n\nWhat day is the class?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return ADD_TARGET_DAY

    async def add_target_day_cb(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        day = int(query.data.split("_")[1])
        self._temp[update.effective_user.id]["target_day"] = day

        await query.edit_message_text(
            f"📅 Class day: *{DAY_NAMES_FULL[day]}*\n\n"
            "⏰ Enter class time (HH:MM):\n"
            "Example: `18:00`",
            parse_mode="Markdown",
        )
        return ADD_TARGET_TIME

    async def add_target_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        time_str = update.message.text.strip()

        try:
            datetime.strptime(time_str, "%H:%M")
        except ValueError:
            await update.message.reply_text("❌ Invalid format. Use HH:MM")
            return ADD_TARGET_TIME

        self._temp[update.effective_user.id]["target_time"] = time_str

        data = self._temp[update.effective_user.id]
        keyboard = [[
            InlineKeyboardButton("✅ Confirm", callback_data="add_yes"),
            InlineKeyboardButton("❌ Cancel", callback_data="add_no"),
        ]]

        await update.message.reply_text(
            f"📋 *Confirm Rule*\n\n"
            f"*Name:* {data['name']}\n"
            f"*Trigger:* {DAY_NAMES_FULL[data['trigger_day']]} {data['trigger_time']}\n"
            f"*Target:* {data['target_class']} on {DAY_NAMES_FULL[data['target_day']]} {data['target_time']}\n\n"
            f"Save this rule?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return ADD_CONFIRM

    async def add_confirm_cb(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        user_id = update.effective_user.id

        if query.data == "add_no":
            del self._temp[user_id]
            await query.edit_message_text("❌ Cancelled")
            return ConversationHandler.END

        data = self._temp[user_id]
        rule = RegistrationRule(
            id=str(uuid.uuid4())[:8],
            name=data["name"],
            trigger_day=data["trigger_day"],
            trigger_time=data["trigger_time"],
            target_class=data["target_class"],
            target_day=data["target_day"],
            target_time=data["target_time"],
        )

        self.user_manager.add_rule(user_id, rule)
        del self._temp[user_id]

        await query.edit_message_text(
            f"✅ *Rule created!*\n\n"
            f"ID: `{rule.id}`\n"
            f"{DAY_NAMES_SHORT[rule.trigger_day]} {rule.trigger_time} → "
            f"{rule.target_class} {DAY_NAMES_SHORT[rule.target_day]} {rule.target_time}",
            parse_mode="Markdown",
        )

        await self._reschedule()
        return ConversationHandler.END

    async def add_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id in self._temp:
            del self._temp[user_id]
        await update.message.reply_text("❌ Cancelled")
        return ConversationHandler.END

    # ==================== Registration Execution ====================

    async def execute_rule(self, telegram_id: int, rule_id: str):
        """Execute a registration rule."""
        user = self.user_manager.get(telegram_id)
        if not user:
            return

        rule = None
        for r in user.rules:
            if r.id == rule_id:
                rule = r
                break

        if not rule or not rule.enabled:
            return

        logger.info(f"Executing rule {rule.name} for {user.name}")

        client = ArboxClient(user.email, user.password)
        if not client.login():
            result = "❌ Login failed"
            self.user_manager.update_rule_status(telegram_id, rule_id, result)
            await self._notify(telegram_id, f"⚠️ *{rule.name}*: {result}")
            return

        # Find target session
        now = datetime.now(ISRAEL_TZ)
        sessions = client.get_schedule(now, now + timedelta(days=7), user.locations_box_id)

        target = None
        for s in sessions:
            if (
                s.name.lower() == rule.target_class.lower()
                and s.day_of_week == rule.target_day
                and s.time == rule.target_time
                and not s.is_past
            ):
                target = s
                break

        if not target:
            result = f"❌ Session not found"
            self.user_manager.update_rule_status(telegram_id, rule_id, result)
            await self._notify(telegram_id, f"⚠️ *{rule.name}*: {result}")
            return

        if target.is_registered:
            result = "✅ Already registered"
            self.user_manager.update_rule_status(telegram_id, rule_id, result)
            await self._notify(telegram_id, f"ℹ️ *{rule.name}*: Already registered for {target.date} {target.time}")
            return

        if target.can_register:
            success, msg = client.register(target.id, user.membership_user_id)
            if success:
                result = f"✅ Registered ({target.free} spots)"
                self.user_manager.update_rule_status(telegram_id, rule_id, result)
                await self._notify(
                    telegram_id,
                    f"🎉 *{rule.name}*\n\n"
                    f"✅ Registered for {rule.target_class}\n"
                    f"📅 {target.date} {target.time}"
                )
            else:
                result = f"❌ {msg}"
                self.user_manager.update_rule_status(telegram_id, rule_id, result)
                await self._notify(telegram_id, f"⚠️ *{rule.name}*: {result}")

        elif target.can_join_waitlist:
            success, msg = client.join_waitlist(target.id, user.membership_user_id)
            if success:
                result = "🟡 Joined waitlist"
                self.user_manager.update_rule_status(telegram_id, rule_id, result)
                await self._notify(
                    telegram_id,
                    f"📋 *{rule.name}*\n\n"
                    f"🟡 Joined waitlist for {rule.target_class}\n"
                    f"📅 {target.date} {target.time}"
                )
            else:
                result = f"❌ {msg}"
                self.user_manager.update_rule_status(telegram_id, rule_id, result)
                await self._notify(telegram_id, f"⚠️ *{rule.name}*: {result}")
        else:
            result = f"⏳ Not open yet ({target.booking_option})"
            self.user_manager.update_rule_status(telegram_id, rule_id, result)

    async def _notify(self, telegram_id: int, message: str):
        """Send notification to user."""
        if self.app:
            try:
                await self.app.bot.send_message(telegram_id, message, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Notify failed: {e}")

    async def _reschedule(self):
        """Reschedule all rules."""
        self.scheduler.remove_all_jobs()

        day_map = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat']

        for user in self.user_manager.all_users():
            for rule in user.rules:
                if not rule.enabled:
                    continue

                parts = rule.trigger_time.split(":")
                hour, minute = int(parts[0]), int(parts[1])
                second = int(parts[2]) if len(parts) > 2 else 0

                trigger = CronTrigger(
                    day_of_week=day_map[rule.trigger_day],
                    hour=hour,
                    minute=minute,
                    second=second,
                    timezone=ISRAEL_TZ,
                )

                self.scheduler.add_job(
                    self.execute_rule,
                    trigger=trigger,
                    args=[user.telegram_id, rule.id],
                    id=f"{user.telegram_id}_{rule.id}",
                    replace_existing=True,
                )

                logger.info(f"Scheduled: {rule.name} ({user.name}) - {day_map[rule.trigger_day]} {rule.trigger_time}")

    async def post_init(self, app: Application):
        await self._reschedule()
        if not self.scheduler.running:
            self.scheduler.start()
        logger.info("Scheduler started")

    def run(self):
        """Run the bot."""
        self.app = Application.builder().token(BOT_TOKEN).post_init(self.post_init).build()

        # Commands
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("help", self.cmd_help))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("test", self.cmd_test))
        self.app.add_handler(CommandHandler("rules", self.cmd_rules))
        self.app.add_handler(CommandHandler("toggle", self.cmd_toggle))
        self.app.add_handler(CommandHandler("remove", self.cmd_remove))
        self.app.add_handler(CommandHandler("users", self.cmd_users))

        # Setup conversation
        self.app.add_handler(ConversationHandler(
            entry_points=[CommandHandler("setup", self.setup_start)],
            states={
                SETUP_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.setup_email)],
                SETUP_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.setup_password)],
                SETUP_MEMBERSHIP_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.setup_membership)],
                SETUP_CONFIRM: [CallbackQueryHandler(self.setup_confirm, pattern="^setup_")],
            },
            fallbacks=[CommandHandler("cancel", self.setup_cancel)],
        ))

        # Add rule conversation
        self.app.add_handler(ConversationHandler(
            entry_points=[CommandHandler("add", self.add_start)],
            states={
                ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_name)],
                ADD_TRIGGER_DAY: [CallbackQueryHandler(self.add_trigger_day_cb, pattern="^tday_")],
                ADD_TRIGGER_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_trigger_time)],
                ADD_TARGET_CLASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_target_class)],
                ADD_TARGET_DAY: [CallbackQueryHandler(self.add_target_day_cb, pattern="^xday_")],
                ADD_TARGET_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_target_time)],
                ADD_CONFIRM: [CallbackQueryHandler(self.add_confirm_cb, pattern="^add_")],
            },
            fallbacks=[CommandHandler("cancel", self.add_cancel)],
        ))

        logger.info("Starting bot...")
        logger.info(f"Allowed users: {ALLOWED_USERS}")
        self.app.run_polling()


if __name__ == "__main__":
    bot = AutoArboxBot()
    bot.run()
