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
DATA_DIR = Path.home() / ".autoarboxbot"
USERS_FILE = DATA_DIR / "users.json"
RULES_FILE = DATA_DIR / "rules.json"

# Bot token - CHANGE THIS!
BOT_TOKEN = "8604292375:AAHtzV5-pC0w-sOPJl22AFI8MQ8GQh2SXtg"

# Admin user ID (your Telegram ID) - CHANGE THIS!
ADMIN_ID = None  # Set this to your Telegram user ID

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
        "/setup - Set your Arbox credentials\n\n"
        "*Rules:*\n"
        "/add - Add a registration rule\n"
        "/rules - List your rules\n"
        "/toggle <id> - Enable/disable rule\n"
        "/remove <id> - Delete rule\n\n"
        "*Other:*\n"
        "/test - Test Arbox connection\n"
        "/status - Your status\n\n"
        "*How rules work:*\n"
        "A rule = WHEN to register + WHAT to register for\n\n"
        "Example:\n"
        "Trigger: Sunday 18:00:00\n"
        "Target: CrossFit Wednesday 18:00\n\n"
        "→ At Sunday 18:00 the bot registers you for Wednesday's class.",
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

# ==================== Add Rule Conversation ====================

async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not get_user(user_id):
        await update.message.reply_text("❌ Use /setup first.")
        return ConversationHandler.END
    
    temp_data[user_id] = {}
    await update.message.reply_text(
        "➕ *Add New Rule*\n\nGive this rule a name (e.g., 'Wednesday Evening'):",
        parse_mode="Markdown",
    )
    return ADD_NAME

async def add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    temp_data[user_id]["name"] = update.message.text.strip()
    
    keyboard = [
        [InlineKeyboardButton(day, callback_data=f"tday_{i}") for i, day in enumerate(DAY_NAMES[:4])],
        [InlineKeyboardButton(day, callback_data=f"tday_{i}") for i, day in enumerate(DAY_NAMES[4:], 4)],
    ]
    
    await update.message.reply_text(
        "📅 *Trigger Day*\n\nWhen should the bot register you?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return ADD_TRIGGER_DAY

async def add_trigger_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    day = int(query.data.split("_")[1])
    temp_data[user_id]["trigger_day"] = day
    
    await query.edit_message_text(
        f"📅 Trigger: *{DAY_NAMES[day]}*\n\n"
        "⏰ Enter trigger time (HH:MM:SS):\n"
        "Example: `18:00:00`",
        parse_mode="Markdown",
    )
    return ADD_TRIGGER_TIME

async def add_trigger_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    time_str = update.message.text.strip()
    
    # Add seconds if missing
    if len(time_str.split(":")) == 2:
        time_str += ":00"
    
    try:
        datetime.strptime(time_str, "%H:%M:%S")
    except ValueError:
        await update.message.reply_text("❌ Invalid format. Use HH:MM:SS (e.g., 18:00:00)")
        return ADD_TRIGGER_TIME
    
    temp_data[user_id]["trigger_time"] = time_str
    
    await update.message.reply_text(
        "🏋️ *Target Class*\n\nWhat class to register for?\n"
        "Example: `CrossFit`",
        parse_mode="Markdown",
    )
    return ADD_TARGET_CLASS

async def add_target_class(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    temp_data[user_id]["target_class"] = update.message.text.strip()
    
    keyboard = [
        [InlineKeyboardButton(day, callback_data=f"xday_{i}") for i, day in enumerate(DAY_NAMES[:4])],
        [InlineKeyboardButton(day, callback_data=f"xday_{i}") for i, day in enumerate(DAY_NAMES[4:], 4)],
    ]
    
    await update.message.reply_text(
        "📅 *Target Day*\n\nWhat day is the class?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return ADD_TARGET_DAY

async def add_target_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    day = int(query.data.split("_")[1])
    temp_data[user_id]["target_day"] = day
    
    await query.edit_message_text(
        f"📅 Target: *{DAY_NAMES[day]}*\n\n"
        "⏰ Enter class time (HH:MM):\n"
        "Example: `18:00`",
        parse_mode="Markdown",
    )
    return ADD_TARGET_TIME

async def add_target_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    time_str = update.message.text.strip()
    
    try:
        datetime.strptime(time_str, "%H:%M")
    except ValueError:
        await update.message.reply_text("❌ Invalid format. Use HH:MM (e.g., 18:00)")
        return ADD_TARGET_TIME
    
    temp_data[user_id]["target_time"] = time_str
    
    data = temp_data[user_id]
    keyboard = [
        [
            InlineKeyboardButton("✅ Confirm", callback_data="confirm_yes"),
            InlineKeyboardButton("❌ Cancel", callback_data="confirm_no"),
        ]
    ]
    
    await update.message.reply_text(
        "📋 *Confirm Rule*\n\n"
        f"*Name:* {data['name']}\n"
        f"*Trigger:* {DAY_NAMES[data['trigger_day']]} {data['trigger_time']}\n"
        f"*Target:* {data['target_class']} {DAY_NAMES[data['target_day']]} {data['target_time']}\n\n"
        "Is this correct?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return ADD_CONFIRM

async def add_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if query.data == "confirm_no":
        del temp_data[user_id]
        await query.edit_message_text("❌ Cancelled.")
        return ConversationHandler.END
    
    data = temp_data[user_id]
    
    # Create rule
    import uuid
    rule = {
        "id": str(uuid.uuid4())[:8],
        "name": data["name"],
        "trigger_day": data["trigger_day"],
        "trigger_time": data["trigger_time"],
        "target_class": data["target_class"],
        "target_day": data["target_day"],
        "target_time": data["target_time"],
        "enabled": True,
    }
    
    add_user_rule(user_id, rule)
    del temp_data[user_id]
    
    await query.edit_message_text(
        f"✅ *Rule created!*\n\n"
        f"ID: `{rule['id']}`\n"
        f"{DAY_NAMES[rule['trigger_day']]} {rule['trigger_time']} → "
        f"{rule['target_class']} {DAY_NAMES[rule['target_day']]} {rule['target_time']}",
        parse_mode="Markdown",
    )
    
    await schedule_all_rules()
    return ConversationHandler.END

async def add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in temp_data:
        del temp_data[user_id]
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END

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

def main():
    global app
    
    print("🤖 AutoArboxBot starting...")
    print(f"📁 Data directory: {DATA_DIR}")
    
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
    
    # Add rule conversation
    add_handler = ConversationHandler(
        entry_points=[CommandHandler("add", add_start)],
        states={
            ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_name)],
            ADD_TRIGGER_DAY: [CallbackQueryHandler(add_trigger_day, pattern="^tday_")],
            ADD_TRIGGER_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_trigger_time)],
            ADD_TARGET_CLASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_target_class)],
            ADD_TARGET_DAY: [CallbackQueryHandler(add_target_day, pattern="^xday_")],
            ADD_TARGET_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_target_time)],
            ADD_CONFIRM: [CallbackQueryHandler(add_confirm, pattern="^confirm_")],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
    )
    app.add_handler(add_handler)
    
    # Run
    print("✅ Bot is running! Press Ctrl+C to stop.")
    app.run_polling()

if __name__ == "__main__":
    main()
