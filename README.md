# WA Scheduler — Backend

FastAPI backend for the Dietician WhatsApp Scheduler. Fully async, class-based architecture mirroring the Prompt Builder pattern — `*Access`, `*Validator`, `*Router` classes, `ResponseHelper` envelopes, and a singleton Selenium WhatsApp bot driven by an APScheduler background worker.

---

## Project Structure

```
backend/
├── main.py                          # App entry point, lifespan, middleware, router includes
├── requirements.txt
├── .env.dev                         # Local dev environment (not committed)
├── .env.example                     # Template — copy to .env.dev and fill in
├── .gitignore
└── app/
    ├── __init__.py
    ├── deps.py                      # DatabaseDependency — async session provider
    ├── config/
    │   ├── setting.py               # Settings(BaseSettings) — typed env config
    │   ├── postgres.py              # DatabaseManager singleton — async engine + init_db
    │   └── __init__.py
    ├── model/
    │   ├── base.py                  # DeclarativeBase
    │   ├── user.py                  # User ORM (UUID PK, Mapped[])
    │   ├── group.py                 # Group ORM
    │   ├── message_template.py      # MessageTemplate ORM
    │   ├── schedule.py              # Schedule ORM (JSONB days_of_week)
    │   └── __init__.py              # Imports all models — required for table creation
    ├── schemas/
    │   ├── response.py              # ApiResponse envelope
    │   ├── user.py                  # UserCreate, UserRead, UserLogin, UserToken
    │   ├── group.py                 # GroupCreate, GroupRead, GroupUpdate
    │   ├── template.py              # TemplateCreate, TemplateRead, TemplateUpdate
    │   ├── schedule.py              # ScheduleCreate, ScheduleRead, ScheduleUpdate
    │   └── __init__.py
    ├── services/
    │   ├── jwt/
    │   │   ├── passwords.py         # PasswordManager — bcrypt hash/verify
    │   │   ├── token_service.py     # TokenService — create_access_token
    │   │   ├── auth.py              # AuthService — get_current_user dependency
    │   │   └── __init__.py
    │   ├── whatsapp/
    │   │   ├── bot.py               # WhatsAppBot singleton — Selenium, QR, send_message
    │   │   └── __init__.py
    │   └── scheduler/
    │       ├── wa_scheduler.py      # WAScheduler singleton — APScheduler tick
    │       └── __init__.py
    ├── utils/
    │   ├── helper.py                # ResponseHelper — success/error envelope builder
    │   ├── validator.py             # ValueValidator — generic guards
    │   └── __init__.py
    ├── data/
    │   ├── success_detail.json      # Success message catalog keyed by response key
    │   └── error_detail.json        # Error message catalog keyed by error key
    └── router/
        └── user/
            ├── __init__.py
            ├── auth/
            │   ├── user.py              # UserAuthRouter class → /user/v1/auth/...
            │   ├── user_access.py       # UserAccess — all DB ops for User
            │   ├── user_validator.py    # UserValidator — unique checks, exists guard
            │   └── __init__.py
            ├── groups/
            │   ├── groups.py            # GroupRouter class → /user/v1/groups/...
            │   ├── group_access.py      # GroupAccess — all DB ops for Group
            │   ├── group_validator.py   # GroupValidator
            │   └── __init__.py
            ├── templates/
            │   ├── templates.py         # TemplateRouter class → /user/v1/templates/...
            │   ├── template_access.py   # TemplateAccess
            │   ├── template_validator.py
            │   └── __init__.py
            ├── schedules/
            │   ├── schedules.py         # ScheduleRouter class → /user/v1/schedules/...
            │   ├── schedule_access.py   # ScheduleAccess
            │   ├── schedule_validator.py
            │   └── __init__.py
            └── whatsapp/
                ├── whatsapp.py          # WhatsAppRouter class → /user/v1/whatsapp/...
                └── __init__.py
```

---

## Architecture Patterns

| Pattern | Implementation |
|---------|----------------|
| **Router class** | `class XRouter` with `__init__` + `_register()` + async handler methods. Final line: `router = XRouter().router` |
| **Access class** | `class XAccess(db)` — all SQLAlchemy ops for one model. Raises `RuntimeError` on DB failure |
| **Validator class** | `class XValidator` — static methods, raises `HTTPException` on rule violations |
| **Response envelope** | `ResponseHelper.success(data, key=...)` / `ResponseHelper.error(key=..., reason=...)` |
| **Settings** | `Settings(BaseSettings)` singleton loaded from `.env.{APP_ENV}` |
| **DB manager** | `DatabaseManager.get_instance()` singleton — async SQLAlchemy engine |
| **Auth** | `AuthService.get_current_user` — `Depends()` callable, decodes JWT, returns `User` |

---

## API Endpoints

All endpoints return the standard envelope:
```json
{
  "detail": [{
    "detail_type": "Success",
    "traceback_id": "<uuid>",
    "msg": "Human readable message",
    "data": {},
    "ctx": { "reason": "..." }
  }]
}
```

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/user/v1/auth/register` | ❌ | Register new user |
| POST | `/user/v1/auth/login` | ❌ | Login, get JWT token |
| GET | `/user/v1/auth/me` | ✅ | Get current user profile |
| GET | `/user/v1/groups` | ✅ | List all active groups |
| POST | `/user/v1/groups` | ✅ | Create group |
| GET | `/user/v1/groups/{id}` | ✅ | Get group by ID |
| PUT | `/user/v1/groups/{id}` | ✅ | Update group |
| DELETE | `/user/v1/groups/{id}` | ✅ | Soft-delete group |
| GET | `/user/v1/templates` | ✅ | List all templates |
| POST | `/user/v1/templates` | ✅ | Create template |
| GET | `/user/v1/templates/{id}` | ✅ | Get template by ID |
| PUT | `/user/v1/templates/{id}` | ✅ | Update template |
| DELETE | `/user/v1/templates/{id}` | ✅ | Delete template |
| GET | `/user/v1/schedules` | ✅ | List all schedules |
| POST | `/user/v1/schedules` | ✅ | Create schedule |
| GET | `/user/v1/schedules/{id}` | ✅ | Get schedule by ID |
| PUT | `/user/v1/schedules/{id}` | ✅ | Update schedule |
| DELETE | `/user/v1/schedules/{id}` | ✅ | Delete schedule |
| GET | `/user/v1/whatsapp/status` | ✅ | WhatsApp session status |
| GET | `/user/v1/whatsapp/qr` | ✅ | Get QR code (base64 PNG) |
| POST | `/user/v1/whatsapp/wait-scan` | ✅ | Long-poll until QR scanned |
| GET | `/health` | ❌ | Health check |
| GET | `/keepalive` | ❌ | Uptime ping for cron-job.org |

Interactive docs: `http://localhost:8000/wa/v1/docs`

---

## Local Setup

### Prerequisites

Install all of these before starting:

1. **Python 3.11+** — https://www.python.org/downloads/
2. **PostgreSQL 15+** — https://www.postgresql.org/download/windows/
   - During install, set a password for the `postgres` user and remember it
3. **Google Chrome** — https://www.google.com/chrome/
   - Must be installed — Selenium uses it to automate WhatsApp Web

---

### Step 1 — Create the PostgreSQL database

Open **pgAdmin** or **psql** and run:

```sql
CREATE DATABASE wa_scheduler;
```

---

### Step 2 — Configure environment variables

```
cd "D:\Whatsapp Automation\backend"
copy .env.example .env.dev
```

Open `.env.dev` and fill in your values:

```env
APP_NAME=WA Scheduler Backend
APP_ENV=dev
DEBUG=True

DB_URL=postgresql+asyncpg://postgres:YOUR_PG_PASSWORD@localhost:5432/wa_scheduler

JWT_SECRET=generate-a-long-random-string-here
JWT_ALGORITHM=HS256
JWT_EXPIRES_MINUTES=10080

WA_PROFILE_DIR=C:/wa_chrome_profile

SCHEDULER_INTERVAL_SECONDS=60
SCHEDULER_TIMEZONE=Asia/Kolkata
```

**Generate a strong JWT_SECRET:**
```
python -c "import secrets; print(secrets.token_hex(32))"
```

**WA_PROFILE_DIR** — Chrome saves the WhatsApp session here. The folder is created automatically on first run.

---

### Step 3 — Create virtual environment and install dependencies

```
cd "D:\Whatsapp Automation\backend"
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

---

### Step 4 — Run the backend

```
cd "D:\Whatsapp Automation\backend"
venv\Scripts\activate
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

On first startup:
- Database tables are created automatically via `Base.metadata.create_all`
- Google Chrome opens and loads `https://web.whatsapp.com`
- The APScheduler background worker starts (checks every 60 seconds)

---

### Step 5 — Link WhatsApp

1. Open the frontend at `http://localhost:5173`
2. Register and log in
3. Navigate to **WhatsApp Link** in the navbar
4. A QR code appears (pulled from the Chrome browser via Selenium)
5. On your phone: **WhatsApp → Settings → Linked Devices → Link a Device → Scan QR**
6. Click **"I have scanned the QR"** — the system waits up to 2 minutes
7. On success the UI shows "WhatsApp linked!" — the session is persisted in `WA_PROFILE_DIR`

---

## Render Cloud Deployment

### Backend Web Service

1. Push code to GitHub
2. Create **Render → New Web Service**, connect repo
3. Set **Root directory** to `backend`
4. **Build command:**
```bash
apt-get update && apt-get install -y wget gnupg && \
wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add - && \
echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list && \
apt-get update && apt-get install -y google-chrome-stable && \
pip install -r requirements.txt
```
5. **Start command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
6. **Environment variables** (set in Render dashboard):

| Key | Value |
|-----|-------|
| `APP_NAME` | `WA Scheduler Backend` |
| `APP_ENV` | `production` |
| `DEBUG` | `False` |
| `DB_URL` | Render PostgreSQL external URL (use `postgresql+asyncpg://...`) |
| `JWT_SECRET` | Your generated secret |
| `JWT_ALGORITHM` | `HS256` |
| `JWT_EXPIRES_MINUTES` | `10080` |
| `WA_PROFILE_DIR` | `/tmp/wa_chrome_profile` |
| `SCHEDULER_INTERVAL_SECONDS` | `60` |
| `SCHEDULER_TIMEZONE` | `Asia/Kolkata` |

7. In `app/services/whatsapp/bot.py` — uncomment `--headless=new` option for server deployment

### PostgreSQL on Render

1. Render → **New → PostgreSQL** → Free plan
2. Copy the **External Database URL**
3. Replace `postgresql://` with `postgresql+asyncpg://` and set as `DB_URL`

### Keep Render Awake (Free Tier)

Render free services sleep after 15 minutes of inactivity.

1. Go to https://cron-job.org — create free account
2. New cron job:
   - **URL:** `https://your-backend.onrender.com/keepalive`
   - **Method:** GET
   - **Interval:** Every 10 minutes

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `ModuleNotFoundError` | Activate venv: `venv\Scripts\activate` |
| DB connection error | Check `DB_URL` in `.env.dev`, verify PostgreSQL is running |
| Chrome won't start | Ensure Google Chrome (not Chromium) is installed |
| QR not loading | Wait 15–20 s after backend starts for Chrome/WhatsApp Web to load |
| "Group not found" in scheduler | `whatsapp_group_name` must match the WhatsApp group name exactly (case-sensitive, spaces, emojis included) |
| `asyncpg` DSN error | URL must use `postgresql+asyncpg://` not `postgresql://` |
| Tables not created | Ensure `import app.model` is present in `main.py` (registers all ORM models) |
