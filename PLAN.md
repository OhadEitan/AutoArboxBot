# AutoArboxBot - Coding Plan

## Overview
An automated registration system for Arbox fitness sessions (CrossFit). The app will automatically register you to training sessions exactly when they become available (72 hours before).

## Architecture Decision

### Challenge
Mobile apps have strict limitations on background execution. iOS/Android will kill background processes to save battery. For time-critical registration (where sessions fill in seconds), a pure mobile approach is risky.

### Recommended Architecture: Mobile App + Backend Service

```
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│   Mobile App    │ ──────► │  Backend Server │ ──────► │   Arbox API     │
│   (Kivy/Python) │         │    (Python)     │         │                 │
└─────────────────┘         └─────────────────┘         └─────────────────┘
        │                           │
        │                           ▼
        │                   ┌─────────────────┐
        └──────────────────►│  Push Notifs    │
                            │  (Firebase)     │
                            └─────────────────┘
```

**Why this approach?**
- Server runs 24/7, executes registration at exact millisecond
- Mobile app is just for configuration (no background limitations)
- Reliable push notifications

---

## Phase 1: Research & Reverse Engineering (CRITICAL)

### 1.1 Arbox API Discovery
**Goal:** Understand how Arbox mobile app communicates with servers

**Tasks:**
- [ ] Install Arbox app and use proxy (mitmproxy/Charles) to capture API calls
- [ ] Document authentication flow (login endpoint, token format)
- [ ] Document session listing endpoint
- [ ] Document registration endpoint
- [ ] Document waitlist endpoint
- [ ] Identify rate limits and security measures

**Expected Endpoints (to discover):**
```
POST /auth/login          - Login with email/password
GET  /schedule            - Get available sessions
POST /booking/register    - Register to a session
POST /booking/waitlist    - Join waitlist
GET  /user/bookings       - Get current bookings
```

### 1.2 Authentication Research
- [ ] Determine token type (JWT, session cookie, API key)
- [ ] Determine token expiration and refresh mechanism
- [ ] Test if tokens can be reused across devices

---

## Phase 2: Core Backend Service

### 2.1 Project Structure
```
AutoArboxBot/
├── backend/
│   ├── __init__.py
│   ├── config.py           # Configuration management
│   ├── arbox_client.py     # Arbox API wrapper
│   ├── scheduler.py        # Registration scheduler
│   ├── notifier.py         # Push notification sender
│   ├── database.py         # SQLite for storing sessions
│   └── main.py             # Entry point
├── mobile/
│   ├── main.py             # Kivy app entry
│   ├── screens/
│   │   ├── login.py        # Login screen
│   │   ├── sessions.py     # Session management screen
│   │   └── settings.py     # Settings screen
│   └── buildozer.spec      # Android build config
├── tests/
│   ├── test_arbox_client.py
│   ├── test_scheduler.py
│   └── test_integration.py
├── requirements.txt
├── README.md
└── PLAN.md
```

### 2.2 Arbox API Client (`arbox_client.py`)
```python
class ArboxClient:
    def __init__(self, email: str, password: str):
        """Initialize with user credentials"""

    async def login(self) -> bool:
        """Authenticate and store token"""

    async def get_schedule(self, date_from: date, date_to: date) -> List[Session]:
        """Fetch available sessions"""

    async def register(self, session_id: str) -> RegistrationResult:
        """Register to a session"""

    async def join_waitlist(self, session_id: str) -> bool:
        """Join waitlist for full session"""

    async def get_my_bookings(self) -> List[Booking]:
        """Get current bookings"""
```

### 2.3 Scheduler (`scheduler.py`)
```python
class RegistrationScheduler:
    def __init__(self, arbox_client: ArboxClient, notifier: Notifier):
        """Initialize scheduler"""

    def add_target_session(self, session: TargetSession):
        """Add a session to auto-register queue"""

    def remove_target_session(self, session_id: str):
        """Remove from queue"""

    def get_target_sessions(self) -> List[TargetSession]:
        """Get all queued sessions"""

    async def run(self):
        """Main loop - check and register at right time"""
```

### 2.4 Data Models
```python
@dataclass
class TargetSession:
    id: str
    name: str                    # e.g., "CrossFit"
    day_of_week: int             # 0=Monday, 6=Sunday
    time: time                   # e.g., 18:00
    instructor: Optional[str]    # Optional filter
    registration_opens: datetime # Calculated: session_time - 72h

@dataclass
class RegistrationResult:
    success: bool
    message: str
    joined_waitlist: bool
    position_in_waitlist: Optional[int]
```

### 2.5 Database Schema (SQLite)
```sql
-- User credentials (encrypted)
CREATE TABLE user (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL,
    encrypted_password TEXT NOT NULL,
    arbox_token TEXT,
    token_expires_at DATETIME
);

-- Target sessions to auto-register
CREATE TABLE target_sessions (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,           -- "CrossFit"
    day_of_week INTEGER NOT NULL, -- 0-6
    time TEXT NOT NULL,           -- "18:00"
    instructor TEXT,
    enabled BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Registration history
CREATE TABLE registration_log (
    id INTEGER PRIMARY KEY,
    target_session_id INTEGER,
    session_date DATE,
    status TEXT,                  -- 'success', 'waitlist', 'failed'
    message TEXT,
    registered_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## Phase 3: Mobile App (Kivy)

### 3.1 Screens

**Login Screen:**
- Email input
- Password input
- "Remember me" checkbox
- Login button
- Status indicator

**Sessions Screen (Main):**
- List of 3 target sessions (cards)
- Each card shows: Name, Day, Time, Status (enabled/disabled)
- "Edit" button on each card
- Add session button (if < 3)

**Edit Session Screen:**
- Session name dropdown (fetched from Arbox)
- Day of week picker
- Time picker
- Instructor filter (optional)
- Save/Delete buttons

**Settings Screen:**
- Push notification toggle
- Logout button
- Registration history view

### 3.2 Mobile-Backend Communication
- REST API between mobile app and backend
- Or: Direct SQLite sync if running locally

---

## Phase 4: Notifications

### 4.1 Push Notification Events
1. **Registration Success** - "You're registered for CrossFit on Monday 18:00!"
2. **Joined Waitlist** - "Session full. You're #3 on waitlist for CrossFit Monday 18:00"
3. **Waitlist Promoted** - "Good news! You've been moved from waitlist to registered!"
4. **Registration Failed** - "Failed to register for CrossFit Monday 18:00. Reason: ..."

### 4.2 Implementation Options
- **Firebase Cloud Messaging (FCM)** - Most reliable for mobile
- **Local notifications** - If app is running in foreground
- **Email fallback** - Optional backup

---

## Phase 5: Testing Strategy

### 5.1 Unit Tests
- [ ] ArboxClient authentication
- [ ] ArboxClient session fetching
- [ ] Scheduler timing logic
- [ ] Database operations

### 5.2 Integration Tests
- [ ] Full registration flow (with mock Arbox API)
- [ ] Waitlist flow
- [ ] Token refresh flow

### 5.3 Manual Testing
- [ ] Test with real Arbox account (your gym)
- [ ] Verify timing accuracy
- [ ] Test notification delivery

---

## Phase 6: Deployment Options

### Option A: Local Computer (Simplest)
- Run backend on your home computer
- Keep computer on 24/7
- Pros: Free, simple
- Cons: Unreliable if computer sleeps

### Option B: Raspberry Pi
- Dedicated small device
- Low power consumption
- Pros: Cheap, always on
- Cons: Need to set up

### Option C: Cloud Server (Most Reliable)
- AWS/Google Cloud/DigitalOcean
- Pros: 100% uptime, accessible anywhere
- Cons: ~$5-10/month cost

### Option D: Serverless (Cost Effective)
- AWS Lambda + CloudWatch Events
- Pros: Pay per execution, highly reliable
- Cons: More complex setup

---

## Implementation Order

### Sprint 1: Foundation
1. [ ] Set up project structure
2. [ ] Research Arbox API (capture traffic)
3. [ ] Implement basic ArboxClient (login, get schedule)
4. [ ] Write tests for ArboxClient

### Sprint 2: Core Functionality
5. [ ] Implement registration method
6. [ ] Implement waitlist method
7. [ ] Build scheduler logic
8. [ ] Set up database

### Sprint 3: Mobile App
9. [ ] Create Kivy app skeleton
10. [ ] Build login screen
11. [ ] Build session management screen
12. [ ] Connect to backend

### Sprint 4: Polish
13. [ ] Add push notifications
14. [ ] Add registration history
15. [ ] Error handling & retry logic
16. [ ] Final testing

---

## Risk Mitigation

### Risk 1: Arbox blocks automated access
**Mitigation:**
- Mimic real app behavior exactly
- Don't make excessive requests
- Use realistic delays between actions

### Risk 2: API changes break the bot
**Mitigation:**
- Implement robust error handling
- Set up alerts for failures
- Regularly test the flow

### Risk 3: Session fills before registration executes
**Mitigation:**
- Execute registration 1-2 seconds before opening
- Retry immediately if fails
- Join waitlist as backup

---

## Questions to Resolve

1. **What's your gym name on Arbox?** (Need this to test API)
2. **Do you have an Android or iOS device?** (For mobile app deployment)
3. **Where do you want to run the backend?** (Computer/Raspberry Pi/Cloud)
4. **Do you have a Firebase account for push notifications?**

---

## Next Steps

Once you answer the questions above, we'll start with:
1. Setting up the project structure
2. Researching the Arbox API together (I'll guide you through capturing traffic)
3. Building the ArboxClient

Ready to proceed?
