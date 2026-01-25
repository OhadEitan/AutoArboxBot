# AutoArboxBot

Automatically register for Arbox (CrossFit Haifa) training sessions exactly when registration opens.

## Features

- Auto-register for up to 3 target sessions
- Registers exactly when 72-hour window opens (precision timing)
- Joins waitlist if class is full
- macOS notifications for success/failure
- Runs continuously in the background

## Installation

```bash
# Navigate to the project directory
cd AutoArboxBot

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Setup

### 1. Initial Setup

```bash
python run.py setup
```

This will:
- Ask for your Arbox email and password
- Test the login
- Ask for your `membership_user_id` (you captured this from Proxyman: **7751132**)
- Let you configure target sessions

### 2. Configure Target Sessions

During setup, you'll configure which classes to auto-register for:
- Class name (e.g., "CrossFit")
- Day of week (0=Sunday, 1=Monday, ..., 6=Saturday)
- Time (e.g., "18:00")

Example: To auto-register for CrossFit on Sunday at 18:00:
- Name: `CrossFit`
- Day: `0` (Sunday)
- Time: `18:00`

## Usage

### Run the Bot

```bash
python run.py run
```

The bot will:
1. Login to Arbox
2. Monitor your target sessions
3. Register automatically when the 72-hour window opens
4. Send macOS notifications on success/failure

### Check Status

```bash
python run.py status
```

### Manage Targets

```bash
python run.py targets
```

### Test Connection

```bash
python run.py test
```

## Running in Background (Recommended)

### Option 1: Keep Terminal Open

```bash
python run.py run
```

Keep the terminal window open. Press Ctrl+C to stop.

### Option 2: Run as Background Process

```bash
nohup python run.py run > ~/.autoarboxbot/bot.log 2>&1 &
```

To stop:
```bash
pkill -f "python run.py run"
```

### Option 3: Create a LaunchAgent (Auto-start on Mac)

Create `~/Library/LaunchAgents/com.autoarboxbot.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.autoarboxbot</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/path/to/AutoArboxBot/run.py</string>
        <string>run</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/autoarboxbot.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/autoarboxbot.err</string>
</dict>
</plist>
```

Then:
```bash
launchctl load ~/Library/LaunchAgents/com.autoarboxbot.plist
```

## Configuration Files

All configuration is stored in `~/.autoarboxbot/`:
- `config.json` - Your credentials (encrypted would be better - TODO)
- `targets.json` - Your target sessions

## Day of Week Reference

| Number | Day | Hebrew |
|--------|-----|--------|
| 0 | Sunday | ראשון |
| 1 | Monday | שני |
| 2 | Tuesday | שלישי |
| 3 | Wednesday | רביעי |
| 4 | Thursday | חמישי |
| 5 | Friday | שישי |
| 6 | Saturday | שבת |

## Security Note

Your password is stored in plain text in `~/.autoarboxbot/config.json`. The file has restricted permissions (only you can read it), but for better security, consider changing your password to something unique for this bot.

## Troubleshooting

### "Login failed"
- Check your email/password
- Make sure you can login to the Arbox app

### "Registration failed"
- Check if you have an active membership
- Check if the class requires a specific membership type

### Notifications not showing
- Make sure notifications are enabled for Terminal in System Preferences

## License

MIT
