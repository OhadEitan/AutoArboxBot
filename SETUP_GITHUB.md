# AutoArboxBot - GitHub Actions Setup

This guide will help you set up automatic registration using GitHub Actions (free, fully automatic).

## Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     HOW IT WORKS                             │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│   GitHub Actions (runs every 30 min)                         │
│         │                                                    │
│         ▼                                                    │
│   Check if any target session registration is open           │
│         │                                                    │
│         ▼                                                    │
│   Register automatically                                     │
│         │                                                    │
│         ▼                                                    │
│   Send Telegram notification to your phone                   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Step 1: Create a Telegram Bot (for notifications)

1. Open Telegram and search for `@BotFather`
2. Send `/newbot`
3. Choose a name (e.g., "My Arbox Bot")
4. Choose a username (e.g., "myarbox_bot")
5. **Save the token** - looks like `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`

### Get your Chat ID

1. Search for `@userinfobot` on Telegram
2. Send `/start`
3. **Save your ID** - it's a number like `123456789`

## Step 2: Push Code to GitHub

1. Create a new repository on GitHub (can be private)
2. Push this code:

```bash
git remote add origin https://github.com/YOUR_USERNAME/AutoArboxBot.git
git branch -M main
git push -u origin main
```

## Step 3: Add GitHub Secrets

Go to your repository → Settings → Secrets and variables → Actions → New repository secret

Add these secrets:

| Secret Name | Value | Required |
|-------------|-------|----------|
| `ARBOX_EMAIL` | Your Arbox login email | Yes |
| `ARBOX_PASSWORD` | Your Arbox password | Yes |
| `ARBOX_MEMBERSHIP_USER_ID` | Your membership ID (e.g., `7751132`) | Yes |
| `ARBOX_LOCATIONS_BOX_ID` | Location ID (default: `14`) | No |
| `ARBOX_BOXES_ID` | Box ID (default: `35`) | No |
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather | Yes |
| `TELEGRAM_CHAT_ID` | Your chat ID | Yes |
| `ARBOX_TARGETS` | JSON string of targets (see below) | Optional |

### ARBOX_TARGETS Format

If you want to store targets in secrets instead of the file:

```json
[
  {"name": "CrossFit", "day_of_week": 0, "time": "18:00", "enabled": true},
  {"name": "CrossFit", "day_of_week": 2, "time": "19:00", "enabled": true},
  {"name": "CrossFit", "day_of_week": 4, "time": "21:00", "enabled": true}
]
```

Day of week: 0=Sunday, 1=Monday, 2=Tuesday, 3=Wednesday, 4=Thursday, 5=Friday, 6=Saturday

## Step 4: Enable GitHub Actions

1. Go to your repository → Actions
2. Click "I understand my workflows, go ahead and enable them"
3. The bot will now run every 30 minutes automatically!

## Managing Rules

### Option A: Edit targets.json file

Edit the `targets.json` file directly in GitHub:
1. Go to your repository
2. Click on `targets.json`
3. Click the pencil icon to edit
4. Make changes and commit

### Option B: Use GitHub Actions workflow (from phone)

1. Go to repository → Actions → "Manage Rules"
2. Click "Run workflow"
3. Select action (list/add/remove/toggle)
4. Fill in parameters
5. Click "Run workflow"

### Option C: Use GitHub Mobile App

1. Install GitHub app on your phone
2. Go to your repository → Actions → "Manage Rules"
3. Trigger the workflow with your desired action

## Testing

To test immediately:

1. Go to Actions → "Auto Register"
2. Click "Run workflow"
3. Check the logs

Or:

1. Go to Actions → "Manage Rules"
2. Select "register-now" action
3. Click "Run workflow"

## Notifications

When a registration happens, you'll receive a Telegram message like:

```
✅ Registration Successful!

Class: CrossFit
Date: 2024-01-15
Time: 18:00
Trainer: John Doe

- AutoArboxBot
```

## Troubleshooting

### "Login failed"
- Check ARBOX_EMAIL and ARBOX_PASSWORD secrets

### "No targets configured"
- Add targets to targets.json OR set ARBOX_TARGETS secret

### No Telegram notifications
- Verify TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
- Make sure you started a chat with your bot (send `/start`)

### Registration not happening
- Check if the registration window is actually open (72 hours before class)
- The bot runs every 30 minutes, so there may be a short delay

## How to Find Your Membership User ID

1. Run locally: `python run.py test`
2. Or use browser dev tools while using Arbox web app
3. Or use Proxyman/Charles to capture API requests from the app

## Cost

**Completely free!** GitHub Actions provides 2000 minutes/month for free.
Running every 30 minutes = ~1440 runs/month = ~720 minutes/month (well within free tier).
