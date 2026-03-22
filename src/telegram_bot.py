"""Telegram Bot for AutoArboxBot - Notifications and Rule Management."""

import os
import json
import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# Try to import telegram library
try:
    import requests
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    logger.warning("requests not available for Telegram notifications")


class TelegramBot:
    """Simple Telegram bot for notifications and commands."""

    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None):
        """
        Initialize Telegram bot.

        Args:
            token: Telegram bot token (from BotFather)
            chat_id: Your Telegram chat ID
        """
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
        self.base_url = f"https://api.telegram.org/bot{self.token}" if self.token else None

    @property
    def is_configured(self) -> bool:
        """Check if bot is properly configured."""
        return bool(self.token and self.chat_id and TELEGRAM_AVAILABLE)

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """
        Send a message to the configured chat.

        Args:
            text: Message text (supports HTML formatting)
            parse_mode: "HTML" or "Markdown"

        Returns:
            True if sent successfully
        """
        if not self.is_configured:
            logger.warning("Telegram not configured, skipping notification")
            return False

        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode,
            }
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            logger.info("Telegram message sent successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    def notify_registration_success(
        self,
        session_name: str,
        session_date: str,
        session_time: str,
        trainer: str = "TBD",
    ) -> bool:
        """Send notification for successful registration."""
        message = (
            f"<b>Registration Successful!</b>\n\n"
            f"<b>Class:</b> {session_name}\n"
            f"<b>Date:</b> {session_date}\n"
            f"<b>Time:</b> {session_time}\n"
            f"<b>Trainer:</b> {trainer}\n\n"
            f"<i>AutoArboxBot</i>"
        )
        return self.send_message(message)

    def notify_registration_failed(
        self,
        session_name: str,
        session_date: str,
        session_time: str,
        error: str,
    ) -> bool:
        """Send notification for failed registration."""
        message = (
            f"<b>Registration Failed</b>\n\n"
            f"<b>Class:</b> {session_name}\n"
            f"<b>Date:</b> {session_date}\n"
            f"<b>Time:</b> {session_time}\n"
            f"<b>Error:</b> {error}\n\n"
            f"<i>AutoArboxBot</i>"
        )
        return self.send_message(message)

    def notify_waitlist_joined(
        self,
        session_name: str,
        session_date: str,
        session_time: str,
        position: Optional[int] = None,
    ) -> bool:
        """Send notification for joining waitlist."""
        pos_text = f"Position: #{position}" if position else "Position: Unknown"
        message = (
            f"<b>Joined Waitlist</b>\n\n"
            f"<b>Class:</b> {session_name}\n"
            f"<b>Date:</b> {session_date}\n"
            f"<b>Time:</b> {session_time}\n"
            f"<b>{pos_text}</b>\n\n"
            f"<i>AutoArboxBot</i>"
        )
        return self.send_message(message)

    def notify_bot_status(self, status: str, details: str = "") -> bool:
        """Send bot status notification."""
        message = f"<b>AutoArboxBot Status</b>\n\n{status}"
        if details:
            message += f"\n\n{details}"
        return self.send_message(message)


class TelegramRuleManager:
    """Manage registration rules via Telegram commands."""

    RULES_FILE = "targets.json"

    def __init__(self, bot: TelegramBot, rules_file: Optional[str] = None):
        self.bot = bot
        self.rules_file = rules_file or self.RULES_FILE

    def load_rules(self) -> list[dict]:
        """Load rules from JSON file."""
        if not os.path.exists(self.rules_file):
            return []
        with open(self.rules_file, "r") as f:
            return json.load(f)

    def save_rules(self, rules: list[dict]) -> None:
        """Save rules to JSON file."""
        with open(self.rules_file, "w") as f:
            json.dump(rules, f, indent=2)

    def add_rule(self, name: str, day: int, time: str) -> str:
        """Add a new registration rule."""
        rules = self.load_rules()

        # Check if rule already exists
        for rule in rules:
            if rule["name"].lower() == name.lower() and rule["day_of_week"] == day and rule["time"] == time:
                return f"Rule already exists: {name} on day {day} at {time}"

        rules.append({
            "name": name,
            "day_of_week": day,
            "time": time,
            "enabled": True,
        })
        self.save_rules(rules)
        return f"Added rule: {name} on day {day} at {time}"

    def remove_rule(self, index: int) -> str:
        """Remove a rule by index (1-based)."""
        rules = self.load_rules()
        if index < 1 or index > len(rules):
            return f"Invalid rule number: {index}"

        removed = rules.pop(index - 1)
        self.save_rules(rules)
        return f"Removed rule: {removed['name']} on day {removed['day_of_week']} at {removed['time']}"

    def toggle_rule(self, index: int) -> str:
        """Toggle a rule enabled/disabled by index (1-based)."""
        rules = self.load_rules()
        if index < 1 or index > len(rules):
            return f"Invalid rule number: {index}"

        rules[index - 1]["enabled"] = not rules[index - 1]["enabled"]
        self.save_rules(rules)

        status = "enabled" if rules[index - 1]["enabled"] else "disabled"
        return f"Rule {index} is now {status}"

    def list_rules(self) -> str:
        """List all rules."""
        rules = self.load_rules()
        if not rules:
            return "No rules configured."

        day_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        lines = ["<b>Registration Rules:</b>\n"]

        for i, rule in enumerate(rules, 1):
            status = "ON" if rule.get("enabled", True) else "OFF"
            day = day_names[rule["day_of_week"]]
            lines.append(f"{i}. [{status}] {rule['name']} - {day} {rule['time']}")

        return "\n".join(lines)

    def process_command(self, text: str) -> Optional[str]:
        """
        Process a Telegram command.

        Commands:
            /list - List all rules
            /add <name> <day> <time> - Add a rule (day: 0-6, time: HH:MM)
            /remove <number> - Remove a rule
            /toggle <number> - Enable/disable a rule
            /help - Show help
        """
        text = text.strip()

        if text == "/list" or text == "/rules":
            return self.list_rules()

        elif text == "/help" or text == "/start":
            return (
                "<b>AutoArboxBot Commands:</b>\n\n"
                "/list - Show all rules\n"
                "/add &lt;name&gt; &lt;day&gt; &lt;time&gt; - Add rule\n"
                "  Example: /add CrossFit 0 18:00\n"
                "  Days: 0=Sun, 1=Mon, 2=Tue, 3=Wed, 4=Thu, 5=Fri, 6=Sat\n"
                "/remove &lt;number&gt; - Remove rule\n"
                "/toggle &lt;number&gt; - Enable/disable rule\n"
                "/status - Check bot status"
            )

        elif text.startswith("/add "):
            parts = text[5:].split()
            if len(parts) < 3:
                return "Usage: /add <name> <day> <time>\nExample: /add CrossFit 0 18:00"
            name = parts[0]
            try:
                day = int(parts[1])
                time = parts[2]
                if day < 0 or day > 6:
                    return "Day must be 0-6 (0=Sunday, 6=Saturday)"
                return self.add_rule(name, day, time)
            except ValueError:
                return "Invalid day number. Use 0-6."

        elif text.startswith("/remove "):
            try:
                index = int(text[8:].strip())
                return self.remove_rule(index)
            except ValueError:
                return "Usage: /remove <number>"

        elif text.startswith("/toggle "):
            try:
                index = int(text[8:].strip())
                return self.toggle_rule(index)
            except ValueError:
                return "Usage: /toggle <number>"

        elif text == "/status":
            rules = self.load_rules()
            enabled = sum(1 for r in rules if r.get("enabled", True))
            return f"Bot is running.\n{enabled}/{len(rules)} rules enabled."

        return None


def get_telegram_bot() -> TelegramBot:
    """Get a configured Telegram bot instance."""
    return TelegramBot()
