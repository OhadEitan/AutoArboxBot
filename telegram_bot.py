#!/usr/bin/env python3
"""
AutoArboxBot - Simple Telegram Bot

Run: python telegram_bot.py
"""

import os
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

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

# Import from src
import sys
sys.path.insert(0, str(Path(__file__).parent))
from src.arbox_client import ArboxClient

# ==================== Configuration ====================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")

# Data storage - use /data on Render (persistent disk) or local folder
DATA_DIR = Path(os.getenv("DATA_DIR", str(Path.home() / ".autoarboxbot")))
USERS_FILE = DATA_DIR / "users.json"
RULES_FILE = DATA_DIR / "rules.json"

# Bot token from environment variable
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

# ==================== Data Storage ====================

def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

def load_users() -> dict:
    """Load users. Format: {telegram_id: {name, email, password, membership_id, locations_box_id}}"""
    if not USERS_FILE.exists():
        return {}
    with open(USERS_FILE) as f:
        return json.load(f)

def save_users(users: dict):
    ensure_data_dir()
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)

def load_rules() -> dict:
    """Load rules. Format: {telegram_id: [list of rules]}"""
    if not RULES_FILE.exists():
        return {}
    with open(RULES_FILE) as f:
        return json.load(f)

def save_rules(rules: dict):
    ensure_data_dir()
    with open(RULES_FILE, "w") as f:
        json.dump(rules, f, indent=2)

def get_user(telegram_id: int):
    """Get user by telegram ID. Returns dict or None."""
    users = load_users()
    return users.get(str(telegram_id))

def add_user(telegram_id: int, name: str, email: str, password: str, membership_id: int, locations_box_id: int = 14):
    users = load_users()
    users[str(telegram_id)] = {
        "name": name,
        "email": email,
        "password": password,
        "membership_id": membership_id,
        "locations_box_id": locations_box_id,
    }
    save_users(users)

def get_user_rules(telegram_id: int) -> list:
    rules = load_rules()
    return rules.get(str(telegram_id), [])

def add_user_rule(telegram_id: int, rule: dict):
    rules = load_rules()
    if str(telegram_id) not in rules:
        rules[str(telegram_id)] = []
    rules[str(telegram_id)].append(rule)
    save_rules(rules)

def remove_user_rule(telegram_id: int, rule_id: str) -> bool:
    rules = load_rules()
    user_rules = rules.get(str(telegram_id), [])
    new_rules = [r for r in user_rules if r.get("id") != rule_id]
    if len(new_rules) < len(user_rules):
        rules[str(telegram_id)] = new_rules
        save_rules(rules)
        return True
    return False

def toggle_user_rule(telegram_id: int, rule_id: str):
    """Toggle rule. Returns new enabled status or None if not found."""
    rules = load_rules()
    user_rules = rules.get(str(telegram_id), [])
    for rule in user_rules:
        if rule.get("id") == rule_id:
            rule["enabled"] = not rule.get("enabled", True)
            save_rules(rules)
            return rule["enabled"]
    return None

# ==================== Conversation States ====================

SETUP_EMAIL, SETUP_PASSWORD, SETUP_MEMBERSHIP = range(3)
ADD_NAME, ADD_TRIGGER_DAY, ADD_TRIGGER_TIME, ADD_TARGET_CLASS, ADD_TARGET_DAY, ADD_TARGET_TIME, ADD_CONFIRM = range(10, 17)

temp_data: dict[int, dict] = {}

# ==================== Bot Commands ====================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if user:
        rules = get_user_rules(user_id)
        enabled = len([r for r in rules if r.get("enabled", True)])
        await update.message.reply_text(
            f"👋 Welcome back, *{user['name']}*!\n\n"
            f"You have {enabled} active rules.\n\n"
            "/rules - Your rules\n"
            "/add - Add a rule\n"
            "/test - Test connection\n"
            "/help - Help",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            f"👋 Hello!\n\n"
            f"I'm the AutoArbox bot. I register you for gym classes automatically!\n\n"
            f"Use /setup to get started.\n\n"
            f"_Your Telegram ID: `{user_id}`_",
            parse_mode="Markdown",
        )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *AutoArboxBot Help*\n\n"
        "*Setup:*\n"
        "`/setup` - Set your Arbox credentials\n\n"
        "*Rules:*\n"
        "`/add Wed 18:00` - Add a workout\n"
        "`/rules` - List your rules\n"
        "`/toggle <id>` - Enable/disable rule\n"
        "`/remove <id>` - Delete rule\n\n"
        "*Other:*\n"
        "`/test` - Test Arbox connection\n"
        "`/status` - Your status\n\n"
        "*Example:*\n"
        "`/add Wednesday 18:00`\n"
        "→ Bot registers you 72h before (Sunday 18:00)",
        parse_mode="Markdown",
    )

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if not user:
        await update.message.reply_text("❌ Use /setup first.")
        return

    rules = get_user_rules(user_id)
    enabled = len([r for r in rules if r.get("enabled", True)])
    
    await update.message.reply_text(
        f"📊 *Your Status*\n\n"
        f"*Name:* {user['name']}\n"
        f"*Email:* {user['email']}\n"
        f"*Rules:* {enabled}/{len(rules)} enabled\n"
        f"*Time:* {datetime.now(ISRAEL_TZ).strftime('%H:%M:%S')}",
        parse_mode="Markdown",
    )

async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if not user:
        await update.message.reply_text("❌ Use /setup first.")
        return

    await update.message.reply_text("🔄 Testing connection...")

    client = ArboxClient(user["email"], user["password"])
    if not client.login():
        await update.message.reply_text("❌ Login failed! Check your credentials with /setup")
        return

    now = datetime.now(ISRAEL_TZ)
    sessions = client.get_schedule(
        from_date=now,
        to_date=now + timedelta(days=7),
        locations_box_id=user.get("locations_box_id", 14),
    )

    crossfit = [s for s in sessions if s.name.lower() == "crossfit"]

    msg = f"✅ *Connected!*\n\n{len(crossfit)} CrossFit sessions found:\n\n"
    for s in crossfit[:7]:
        day = DAY_NAMES[s.day_of_week]
        status = "✅" if s.is_registered else f"({s.free} spots)"
        msg += f"{day} {s.date} {s.time} {status}\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if not user:
        await update.message.reply_text("❌ Use /setup first.")
        return

    rules = get_user_rules(user_id)
    
    if not rules:
        await update.message.reply_text("📋 No rules yet.\n\nUse /add to create one!")
        return

    msg = "📋 *Your Rules*\n\n"
    for rule in rules:
        status = "✅" if rule.get("enabled", True) else "❌"
        trigger_day = DAY_NAMES[rule["trigger_day"]]
        target_day = DAY_NAMES[rule["target_day"]]
        
        msg += (
            f"{status} *{rule['name']}* (`{rule['id']}`)\n"
            f"   {trigger_day} {rule['trigger_time']} → "
            f"{rule['target_class']} {target_day} {rule['target_time']}\n"
        )
        if rule.get("last_result"):
            msg += f"   └ _{rule['last_result']}_\n"
        msg += "\n"

    msg += "/toggle <id> to enable/disable\n/remove <id> to delete"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text("Usage: /toggle <rule_id>")
        return

    rule_id = context.args[0]
    result = toggle_user_rule(user_id, rule_id)
    
    if result is None:
        await update.message.reply_text(f"❌ Rule `{rule_id}` not found", parse_mode="Markdown")
    else:
        status = "enabled ✅" if result else "disabled ❌"
        await update.message.reply_text(f"Rule `{rule_id}` is now {status}", parse_mode="Markdown")
        await schedule_all_rules()

async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text("Usage: /remove <rule_id>")
        return

    rule_id = context.args[0]
    
    if remove_user_rule(user_id, rule_id):
        await update.message.reply_text(f"🗑️ Rule `{rule_id}` removed", parse_mode="Markdown")
        await schedule_all_rules()
    else:
        await update.message.reply_text(f"❌ Rule `{rule_id}` not found", parse_mode="Markdown")

# ==================== Setup Conversation ====================

async def setup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    temp_data[user_id] = {"name": update.effective_user.first_name}
    
    await update.message.reply_text(
        "⚙️ *Setup Arbox Credentials*\n\n"
        "Enter your Arbox email:",
        parse_mode="Markdown",
    )
    return SETUP_EMAIL

async def setup_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    temp_data[user_id]["email"] = update.message.text.strip()
    
    await update.message.reply_text("Enter your Arbox password:")
    return SETUP_PASSWORD

async def setup_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    temp_data[user_id]["password"] = update.message.text.strip()
    
    # Delete the password message for security
    try:
        await update.message.delete()
    except:
        pass
    
    await update.message.reply_text(
        "Enter your membership_user_id:\n\n"
        "_This is from your Proxyman capture (e.g., 7751132)_",
        parse_mode="Markdown",
    )
    return SETUP_MEMBERSHIP

async def setup_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    try:
        membership_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Must be a number. Try again:")
        return SETUP_MEMBERSHIP
    
    data = temp_data[user_id]
    
    # Test login
    await update.message.reply_text("🔄 Testing login...")
    client = ArboxClient(data["email"], data["password"])
    
    if not client.login():
        await update.message.reply_text("❌ Login failed! Check your email/password and try /setup again.")
        del temp_data[user_id]
        return ConversationHandler.END
    
    # Save user
    add_user(
        telegram_id=user_id,
        name=data["name"],
        email=data["email"],
        password=data["password"],
        membership_id=membership_id,
    )
    
    del temp_data[user_id]
    
    await update.message.reply_text(
        f"✅ *Setup complete!*\n\n"
        f"Email: {data['email']}\n"
        f"Membership ID: {membership_id}\n\n"
        f"Now use /add to create your first rule!",
        parse_mode="Markdown",
    )
    return ConversationHandler.END

async def setup_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in temp_data:
        del temp_data[user_id]
    await update.message.reply_text("❌ Setup cancelled.")
    return ConversationHandler.END

# ==================== Add Rule (Simple) ====================

def get_next_rule_number(telegram_id: int) -> int:
    """Get the next rule number for a user (1, 2, 3, etc.)"""
    rules = get_user_rules(telegram_id)
    if not rules:
        return 1
    # Find highest existing number
    max_num = 0
    for rule in rules:
        name = rule.get("name", "")
        if name.startswith("Rule "):
            try:
                num = int(name.split(" ")[1])
                max_num = max(max_num, num)
            except:
                pass
    return max_num + 1


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Simple add command: /add <day> <time>
    Example: /add Wednesday 18:00
    
    Bot automatically calculates trigger time (72 hours before).
    If class is within 72 hours, tries to register immediately.
    """
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if not user:
        await update.message.reply_text("❌ Use /setup first.")
        return
    
    # Parse arguments
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "📝 *Add a workout*\n\n"
            "Usage: `/add <day> <time>`\n\n"
            "Examples:\n"
            "`/add Wednesday 18:00`\n"
            "`/add Sun 09:00`\n"
            "`/add Thu 20:00`\n\n"
            "The bot will auto-register 72h before the class.\n"
            "If class is sooner, it registers immediately!",
            parse_mode="Markdown",
        )
        return
    
    day_input = context.args[0].lower()
    time_input = context.args[1]
    
    # Parse day
    day_map = {
        "sun": 0, "sunday": 0, "ראשון": 0,
        "mon": 1, "monday": 1, "שני": 1,
        "tue": 2, "tuesday": 2, "שלישי": 2,
        "wed": 3, "wednesday": 3, "רביעי": 3,
        "thu": 4, "thursday": 4, "חמישי": 4,
        "fri": 5, "friday": 5, "שישי": 5,
        "sat": 6, "saturday": 6, "שבת": 6,
    }
    
    target_day = day_map.get(day_input)
    if target_day is None:
        await update.message.reply_text(
            f"❌ Unknown day: `{day_input}`\n\n"
            "Use: Sun, Mon, Tue, Wed, Thu, Fri, Sat",
            parse_mode="Markdown",
        )
        return
    
    # Parse time
    try:
        datetime.strptime(time_input, "%H:%M")
    except ValueError:
        await update.message.reply_text(
            f"❌ Invalid time: `{time_input}`\n\n"
            "Use format: HH:MM (e.g., 18:00)",
            parse_mode="Markdown",
        )
        return
    
    # Calculate trigger day (72 hours = 3 days before)
    trigger_day = (target_day - 3) % 7
    trigger_time = f"{time_input}:00"
    
    # Get next rule number for this user
    rule_num = get_next_rule_number(user_id)
    
    # Create rule
    import uuid
    rule = {
        "id": str(uuid.uuid4())[:8],
        "name": f"Rule {rule_num}",
        "trigger_day": trigger_day,
        "trigger_time": trigger_time,
        "target_class": "CrossFit",
        "target_day": target_day,
        "target_time": time_input,
        "enabled": True,
    }
    
    add_user_rule(user_id, rule)
    
    # Calculate hours until class
    now = datetime.now(ISRAEL_TZ)
    
    # Our day format: 0=Sunday, 1=Monday, etc.
    # Python weekday(): 0=Monday, 1=Tuesday, etc.
    # Convert: Python Monday(0) = Our Monday(1), Python Sunday(6) = Our Sunday(0)
    python_weekday = now.weekday()  # 0=Mon, 6=Sun
    today_our_format = (python_weekday + 1) % 7  # Convert to 0=Sun, 1=Mon, etc.
    
    # Days until target
    days_until = (target_day - today_our_format) % 7
    
    # Build target datetime
    class_hour, class_min = map(int, time_input.split(":"))
    target_datetime = now.replace(hour=class_hour, minute=class_min, second=0, microsecond=0)
    target_datetime = target_datetime + timedelta(days=days_until)
    
    # If target is in the past (earlier today), add 7 days
    if target_datetime <= now:
        target_datetime = target_datetime + timedelta(days=7)
        days_until = 7
    
    hours_until = (target_datetime - now).total_seconds() / 3600
    
    logger.info(f"Add rule: target_day={target_day}, today={today_our_format}, days_until={days_until}, hours_until={hours_until:.1f}")
    
    # If class is within 72 hours, try to register now
    if hours_until <= 72:
        await update.message.reply_text(
            f"✅ *Rule {rule_num} created!*\n\n"
            f"📅 Class: CrossFit {DAY_NAMES[target_day]} {time_input}\n"
            f"⏰ Weekly: {DAY_NAMES[trigger_day]} {trigger_time}\n\n"
            f"🔄 Class is in {hours_until:.0f}h - registering now...",
            parse_mode="Markdown",
        )
        
        # Try to register immediately
        await try_register_now(user_id, user, rule)
    else:
        await update.message.reply_text(
            f"✅ *Rule {rule_num} created!*\n\n"
            f"📅 Class: CrossFit {DAY_NAMES[target_day]} {time_input}\n"
            f"⏰ Auto-register: {DAY_NAMES[trigger_day]} {trigger_time}\n\n"
            f"_Runs every week, 72h before class._",
            parse_mode="Markdown",
        )
    
    await schedule_all_rules()


async def try_register_now(telegram_id: int, user: dict, rule: dict):
    """Try to register for a class immediately."""
    
    client = ArboxClient(user["email"], user["password"])
    if not client.login():
        await notify_user(telegram_id, f"❌ Login failed. Check /setup")
        return
    
    # Find the target session
    now = datetime.now(ISRAEL_TZ)
    sessions = client.get_schedule(
        from_date=now,
        to_date=now + timedelta(days=7),
        locations_box_id=user.get("locations_box_id", 14),
    )
    
    target = None
    for s in sessions:
        if (
            s.name.lower() == rule["target_class"].lower()
            and s.day_of_week == rule["target_day"]
            and s.time == rule["target_time"]
            and not s.is_past
        ):
            target = s
            break
    
    if not target:
        await notify_user(telegram_id, f"⚠️ Session not found yet. Will try at scheduled time.")
        return
    
    # Already registered?
    if target.is_registered:
        await notify_user(telegram_id, f"✅ Already registered for {target.date} {target.time}!")
        return
    
    # Try to register
    if target.can_register:
        reg = client.register(target.id, user["membership_id"])
        if reg.success:
            await notify_user(
                telegram_id,
                f"🎉 *Registered!*\n\n"
                f"CrossFit {target.date} {target.time}\n"
                f"({target.free} spots were available)"
            )
        else:
            await notify_user(telegram_id, f"❌ Registration failed: {reg.message}")
    
    elif target.can_join_waitlist:
        reg = client.join_waitlist(target.id, user["membership_id"])
        if reg.success:
            await notify_user(
                telegram_id,
                f"📋 *Joined waitlist*\n\n"
                f"CrossFit {target.date} {target.time}"
            )
        else:
            await notify_user(telegram_id, f"❌ Waitlist failed: {reg.message}")
    
    else:
        await notify_user(
            telegram_id, 
            f"⏳ Registration not open yet.\n"
            f"Will auto-register at {DAY_NAMES[rule['trigger_day']]} {rule['trigger_time']}"
        )


# ==================== Scheduler ====================

scheduler = AsyncIOScheduler(timezone=ISRAEL_TZ)
app: Application = None

async def execute_rule(telegram_id: int, rule_id: str):
    """Execute a registration rule."""
    user = get_user(telegram_id)
    rules = get_user_rules(telegram_id)
    rule = next((r for r in rules if r["id"] == rule_id), None)
    
    if not user or not rule or not rule.get("enabled", True):
        return
    
    logger.info(f"Executing rule {rule['name']} for user {user['name']}")
    
    # Login to Arbox
    client = ArboxClient(user["email"], user["password"])
    if not client.login():
        result = "❌ Login failed"
        await notify_user(telegram_id, f"⚠️ *{rule['name']}*: {result}")
        update_rule_result(telegram_id, rule_id, result)
        return
    
    # Find the target session
    now = datetime.now(ISRAEL_TZ)
    sessions = client.get_schedule(
        from_date=now,
        to_date=now + timedelta(days=7),
        locations_box_id=user.get("locations_box_id", 14),
    )
    
    target = None
    for s in sessions:
        if (
            s.name.lower() == rule["target_class"].lower()
            and s.day_of_week == rule["target_day"]
            and s.time == rule["target_time"]
            and not s.is_past
        ):
            target = s
            break
    
    if not target:
        result = f"❌ Session not found"
        await notify_user(telegram_id, f"⚠️ *{rule['name']}*: {result}")
        update_rule_result(telegram_id, rule_id, result)
        return
    
    # Already registered?
    if target.is_registered:
        result = "✅ Already registered"
        await notify_user(telegram_id, f"ℹ️ *{rule['name']}*: {result} for {target.date}")
        update_rule_result(telegram_id, rule_id, result)
        return
    
    # Try to register
    if target.can_register:
        reg = client.register(target.id, user["membership_id"])
        if reg.success:
            result = f"✅ Registered! ({target.free} spots were free)"
            await notify_user(
                telegram_id,
                f"🎉 *{rule['name']}*\n\n"
                f"Registered for {rule['target_class']}\n"
                f"📅 {target.date} at {target.time}"
            )
        else:
            result = f"❌ {reg.message}"
            await notify_user(telegram_id, f"⚠️ *{rule['name']}*: {result}")
    
    elif target.can_join_waitlist:
        reg = client.join_waitlist(target.id, user["membership_id"])
        if reg.success:
            result = "🟡 Joined waitlist"
            await notify_user(
                telegram_id,
                f"📋 *{rule['name']}*\n\n"
                f"Joined waitlist for {rule['target_class']}\n"
                f"📅 {target.date} at {target.time}"
            )
        else:
            result = f"❌ {reg.message}"
            await notify_user(telegram_id, f"⚠️ *{rule['name']}*: {result}")
    
    else:
        result = f"⏳ Not open yet ({target.booking_option})"
        await notify_user(telegram_id, f"⏳ *{rule['name']}*: {result}")
    
    update_rule_result(telegram_id, rule_id, result)

def update_rule_result(telegram_id: int, rule_id: str, result: str):
    """Update the last result of a rule."""
    rules = load_rules()
    user_rules = rules.get(str(telegram_id), [])
    for rule in user_rules:
        if rule["id"] == rule_id:
            rule["last_result"] = result
            rule["last_run"] = datetime.now().isoformat()
            save_rules(rules)
            return

async def notify_user(telegram_id: int, message: str):
    """Send a notification to a user."""
    if app:
        try:
            await app.bot.send_message(chat_id=telegram_id, text=message, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to notify {telegram_id}: {e}")

async def schedule_all_rules():
    """Schedule all enabled rules."""
    scheduler.remove_all_jobs()
    
    rules = load_rules()
    day_map = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat']
    
    for telegram_id, user_rules in rules.items():
        for rule in user_rules:
            if not rule.get("enabled", True):
                continue
            
            parts = rule["trigger_time"].split(":")
            hour, minute = int(parts[0]), int(parts[1])
            second = int(parts[2]) if len(parts) > 2 else 0
            
            trigger = CronTrigger(
                day_of_week=day_map[rule["trigger_day"]],
                hour=hour,
                minute=minute,
                second=second,
                timezone=ISRAEL_TZ,
            )
            
            scheduler.add_job(
                execute_rule,
                trigger=trigger,
                args=[int(telegram_id), rule["id"]],
                id=f"rule_{telegram_id}_{rule['id']}",
                replace_existing=True,
            )
            
            logger.info(f"Scheduled: {rule['name']} ({rule['id']}) - {day_map[rule['trigger_day']]} {rule['trigger_time']}")

async def post_init(application: Application):
    """Called after app init."""
    global app
    app = application
    await schedule_all_rules()
    scheduler.start()
    logger.info("Scheduler started")

# ==================== Main ====================

# Simple web server to keep Render free tier happy
from threading import Thread
import http.server
import socketserver

def run_health_server():
    """Run a simple HTTP server for Render health checks."""
    port = int(os.getenv("PORT", 10000))
    
    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"AutoArboxBot is running!")
        
        def log_message(self, format, *args):
            pass  # Suppress logs
    
    with socketserver.TCPServer(("", port), Handler) as httpd:
        logger.info(f"Health server running on port {port}")
        httpd.serve_forever()

def main():
    global app
    
    # Check for bot token
    if not BOT_TOKEN:
        print("❌ Error: TELEGRAM_BOT_TOKEN environment variable not set!")
        print("Set it in Render dashboard or .env file")
        sys.exit(1)
    
    print("🤖 AutoArboxBot starting...")
    print(f"📁 Data directory: {DATA_DIR}")
    
    # Ensure data directory exists
    ensure_data_dir()
    
    # Start health check server in background (for Render free tier)
    health_thread = Thread(target=run_health_server, daemon=True)
    health_thread.start()
    
    # Build app
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    
    # Command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("test", cmd_test))
    app.add_handler(CommandHandler("rules", cmd_rules))
    app.add_handler(CommandHandler("toggle", cmd_toggle))
    app.add_handler(CommandHandler("remove", cmd_remove))
    
    # Setup conversation
    setup_handler = ConversationHandler(
        entry_points=[CommandHandler("setup", setup_start)],
        states={
            SETUP_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_email)],
            SETUP_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_password)],
            SETUP_MEMBERSHIP: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_membership)],
        },
        fallbacks=[CommandHandler("cancel", setup_cancel)],
    )
    app.add_handler(setup_handler)
    
    # Simple add command (no conversation needed)
    app.add_handler(CommandHandler("add", cmd_add))
    
    # Run
    print("✅ Bot is running!")
    app.run_polling()

if __name__ == "__main__":
    main()
