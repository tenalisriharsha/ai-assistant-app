# Scheduler AI — Complete Project Documentation

> For a dated, itemized history of what changed and why, see [CHANGELOG.md](CHANGELOG.md).
> This document describes the current state of the project; the changelog is the audit trail.

## 1. Project Overview

**Scheduler AI** is a local-first, natural-language calendar and reminder assistant. Users can type or speak everyday phrases like:

- *"Schedule standup every Monday at 10 AM for 3 weeks"*
- *"Free time tomorrow 1–5 PM for 60 minutes?"*
- *"Rename 'demo' to 'final review'"*
- *"Remind me 15 minutes before the review"*

The system parses these requests, manages a SQLite database of appointments and reminders, and exposes a chat-like React UI. It also ships as a packaged macOS Electron app with deep native integrations.

### Key Capabilities

| Capability | Description |
|------------|-------------|
| Natural-language control | Type or speak queries; no forms required |
| Appointments | One-off, recurring, all-day, timezone-aware |
| Reminders | In-app toasts + optional native macOS notifications |
| Conflict detection | Detects overlaps and proposes alternatives |
| Bulk operations | Move whole days, convert to recurring, create many at once |
| Search | Fuzzy title search across date ranges |
| Free-time queries | Finds available slots matching constraints |
| Voice input | Browser-based speech-to-text via Picovoice/Web Speech |
| macOS integrations | Calendar.app sync, Spotlight indexing, Siri Shortcuts, Today Widget, menubar tray |
| Import/Export | JSON backup/restore and `.ics` drag-and-drop import |
| Print/PDF | Export the current view to PDF |

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           User Interfaces                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐ │
│  │ Browser (dev)│  │ Electron app │  │ Siri/Widget  │  │ Menubar tray│ │
│  │ localhost:3000│  │ .app bundle  │  │ Extensions   │  │             │ │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬──────┘ │
└─────────┼────────────────┼────────────────┼────────────────┼──────────┘
          │                │                │                │
          └────────────────┴────────────────┘                │
                           │                                  │
                  ┌────────▼────────┐              ┌──────────▼─────────┐
                  │  React Frontend │              │  Native Swift      │
                  │  (src/App.js)   │              │  Helpers           │
                  └────────┬────────┘              │  calendar-sync     │
                           │                        │  spotlight-index   │
                  ┌────────▼────────┐              └────────────────────┘
                  │  Flask Backend  │
                  │  (app.py:5001)  │
                  └────────┬────────┘
                           │
                  ┌────────▼────────┐
                  │  SQLite DB      │
                  │  appointments.db│
                  └─────────────────┘
```

### Communication Flow

1. **Frontend** sends `POST /query` (JSON) to the backend.
2. **Backend** routes the request through:
   - Structured action handlers (`action: today`, `action: create`, etc.)
   - Natural-language fast-path handlers (`intents/nl/`)
   - LLM-based intent parser (`openai_handler.py`) as fallback
3. **Backend** reads/writes SQLite via `crud.py` and `models.py`.
4. **Backend** returns UI-optimized JSON (appointments, free slots, proposals, etc.).
5. **Frontend** renders the response in chat/results panels.

---

## 3. Directory Structure

```
/Users/tenalisriharsha/PycharmProjects/ai-assistant-app/
├── app.py                          # Main Flask API
├── crud.py                         # Database CRUD + conflict/search helpers
├── database.py                     # SQLAlchemy session utilities
├── models.py                       # SQLAlchemy models (Appointment, Reminder)
├── openai_handler.py               # Groq/LLM intent parser
├── schemas.py                      # Pydantic schemas (validation)
├── requirements.txt                # Python dependencies
├── requirements-dev.txt            # + pytest, for running tests/
├── start-dev.sh                    # One-command dev start
├── start_macos.sh                  # macOS launcher script
├── install_macos.sh                # Installs packaged .app
├── appointments.db                 # Local SQLite database
├── CHANGELOG.md                    # Dated log of what changed and why
│
├── tests/                          # pytest suite (isolated via SCHEDULER_DB_URL)
│   ├── conftest.py                 # Points the app at a throwaway SQLite DB
│   ├── test_reminders_due.py
│   ├── test_bulk_create_conflicts.py
│   └── test_create_flow_sessions.py
│
├── intents/                        # Intent dispatch packages
│   ├── __init__.py                 # Empty package marker
│   ├── nl/                         # NL fast-path handlers
│   │   ├── __init__.py             # dispatch_nl dispatcher
│   │   └── handlers.py             # 19 pure handler functions
│   ├── llm/                        # LLM intent dispatch
│   │   └── __init__.py             # handle_llm_intent dispatcher
│   ├── reminders.py                # Reminder-specific handlers
│   └── retrieve.py                 # Retrieval-specific handlers
│
├── utils/                          # Shared helper library
│   ├── __init__.py                 # Exports all helpers
│   ├── parsing.py                  # Date/time/text parsing
│   ├── dates.py                    # Date arithmetic
│   ├── slots.py                    # Free-slot algorithms
│   ├── serializers.py              # Model → dict serialization
│   ├── matching.py                 # Fuzzy matching
│   └── db.py                       # DB context utilities
│
├── scheduler/                      # Recurrence utilities
│   ├── __init__.py
│   ├── recurrence.py               # RRULE expansion
│   ├── plan_utils.py               # Planning helpers
│   └── templates.py                # Schedule templates
│
├── flows/                          # Conversational flows
│   └── create_appointment_flow.py  # Multi-turn create flow
│
├── scripts/                        # Utility scripts
│   ├── migrate_sqlite.py
│   ├── seed_aug16_31.py
│   └── setup-macos-signing.sh
│
├── native/                         # Native macOS integrations
│   ├── macOS-helpers/              # Swift Package Manager project
│   │   ├── Package.swift
│   │   └── Sources/
│   │       ├── Shared/             # Appointment model + backend client
│   │       ├── CalendarSync/       # EventKit → Calendar.app
│   │       └── SpotlightIndex/     # CoreSpotlight indexer
│   ├── SiriIntents/                # Siri Shortcuts stub
│   ├── TodayWidget/                # Today Widget stub
│   └── XCODE_SETUP.md              # Manual Xcode steps
│
├── frontend/                       # React + Electron app
│   ├── package.json                # NPM scripts & electron-builder config
│   ├── public/                     # Static assets
│   ├── src/                        # React source
│   │   ├── App.js                  # Main application (also defines the
│   │   │                           #   shared AppointmentListPanel component)
│   │   ├── api.js                  # Axios client (adds a per-tab X-Session-Id)
│   │   ├── App.test.js             # Jest/RTL tests
│   │   ├── components/             # UI components (MicButton, etc.)
│   │   └── hooks/                  # Custom React hooks
│   ├── electron/                   # Electron main process
│   │   ├── main.js                 # Main process, tray, IPC
│   │   ├── preload.js              # Renderer API bridge
│   │   ├── secrets.js              # Groq API key (gitignored)
│   │   └── assets/                 # Icons + native binaries
│   └── scripts/                    # Build scripts
│       ├── prebuild-backend.js
│       ├── build-native.js
│       └── sign-macos.js
│
└── frontend/backend/               # Copied backend for packaging
    # Mirror of root-level backend files
```

---

## 4. Technology Stack

### Backend

| Layer | Technology | Version |
|-------|-----------|---------|
| Runtime | Python | 3.13 |
| Web framework | Flask | ≥3.0.0 |
| CORS | flask-cors | ≥4.0.0 (restricted to known frontend origins, not wildcard) |
| Testing | pytest | see `requirements-dev.txt` |
| ORM | SQLAlchemy | ≥2.0.0 |
| Validation | Pydantic | ≥2.0.0 |
| HTTP client | requests | ≥2.31.0 |
| Data | pandas | ≥2.0.0 |
| Calendar parsing | icalendar | ≥5.0.0 |
| LLM API | Groq (OpenAI-compatible) | via raw HTTP |

### Frontend

| Layer | Technology | Version |
|-------|-----------|---------|
| Framework | React | 18.2.0 |
| Build tool | Create React App / react-scripts | 5.0.1 |
| Routing | react-router-dom | 7.7.1 |
| HTTP | axios | 1.11.0 |
| Icons | @heroicons/react | 2.2.0 |
| Voice | @picovoice/porcupine-web | 3.0.3 |
| Desktop shell | Electron | 31.7.7 |
| Packager | electron-builder | 24.13.3 |

### Native macOS Helpers

| Helper | Framework | Purpose |
|--------|-----------|---------|
| calendar-sync | EventKit | Push appointments to Calendar.app |
| spotlight-index | CoreSpotlight | Index appointments in Spotlight |
| SiriIntents.appex | AppIntents | Siri Shortcuts actions |
| SchedulerWidget.appex | WidgetKit | Today/Notification Center widget |

---

## 5. Backend Documentation

### 5.1 Entry Point (`app.py`)

`app.py` is the Flask application. It exposes:

- `GET /health` — health check
- `GET /` — root ping
- `POST /query` — main query/intent endpoint
- `GET /export` — export all appointments as JSON
- `POST /import` — bulk import appointments from JSON
- `POST /import_ics` — import `.ics` file

The `/query` endpoint accepts either:
- `{ "action": "today" }` — structured action
- `{ "query": "free time tomorrow" }` — natural language

CORS is restricted to known frontend origins (the CRA dev server, Electron
dev, and `null` for the packaged app's `file://` origin) rather than a
wildcard — see `ALLOWED_ORIGINS` in `app.py`.

The multi-turn create-appointment flow tracks state per client, not per IP,
using an `X-Session-Id` header the frontend generates once per browser tab
(`sessionStorage`, see `frontend/src/api.js`). This stops two tabs/users
behind the same IP from clobbering each other's in-progress flow. Abandoned
flows are pruned after 15 minutes idle (`_prune_stale_create_sessions` in
`app.py`).

### 5.2 Request Routing Pipeline

```
POST /query
    │
    ├──> Conversational create flow? → handle_create_appointment_flow()
    │      (keyed by X-Session-Id header, falls back to IP)
    │
    ├──> Structured action? → action handler (today, create, update, etc.)
    │
    ├──> NL fast-path? → dispatch_nl()  (intents/nl/handlers.py)
    │
    └──> LLM fallback? → parse_query() + handle_llm_intent()
```

### 5.3 Database Layer

#### `models.py`

**Appointment** table (`appointments`):

| Column | Type | Notes |
|--------|------|-------|
| id | Integer | Primary key |
| date | Date | Required, indexed |
| start_time | Time | Required, indexed |
| end_time | Time | Required, indexed |
| description | Text | Legacy/main text |
| title | String(200) | Display title |
| label | String(50) | Category label |
| color | String(20) | UI color |
| location | String(200) | Event location |
| modality | String(50) | e.g. zoom, in-person |
| timezone | String(50) | IANA timezone |
| attendees | Text | Comma/JSON list |
| recurrence_rule | String(255) | iCal RRULE |
| reminder_offset_min | Integer | Minutes before start |
| tentative | Boolean | Tentative flag |
| is_all_day | Boolean | All-day flag |
| notes | Text | Extra notes |
| external_id | String(255) | Calendar.app sync ID |
| created_at | DateTime | Auto |
| updated_at | DateTime | Auto |

**Reminder** table (`reminders`):

| Column | Type | Notes |
|--------|------|-------|
| id | Integer | Primary key |
| date | Date | Required |
| time | Time | Required |
| title | String(200) | Required |
| description | Text | Optional |
| lead_minutes | Integer | Minutes before target |
| channel | String(50) | inapp / email / sms / webhook |
| active | Boolean | Default true |
| delivered | Boolean | Default false |
| appointment_id | Integer | FK to appointments.id |
| created_at | DateTime | Auto |
| updated_at | DateTime | Auto |

#### `crud.py`

Core CRUD functions:

- `create_appointment(...)` / `create_appointment_if_free(...)`
- `create_appointment_lenient(...)` / `bulk_create_appointments(...)`
- `update_appointment(...)` / `update_appointment_time(...)` / `update_appointment_title(...)`
- `reschedule_appointment(...)`
- `delete_appointment_by_id(...)` / `delete_appointments_by_selector(...)`
- `get_appointment_by_id(...)` / `get_next_appointment(...)`
- `get_appointments_by_date(...)` / `get_appointments_for_week(...)`
- `get_appointments_between(...)` / `get_appointments_after_time(...)`
- `search_appointments_by_description(...)` — fuzzy search
- `get_conflicting_appointments(...)` — overlap detection
- `count_appointments_in_range(...)`
- Reminder CRUD: `create_reminder`, `get_due_reminders`, `snooze_reminder`, etc.

### 5.4 Natural Language Processing

#### Fast Path Handlers (`intents/nl/handlers.py`)

19 pure functions matching common patterns without calling the LLM:

| Handler | Example Trigger |
|---------|-----------------|
| `handle_nl_delete` | *"cancel gym tomorrow"* |
| `handle_nl_reminder` | *"remind me at 3pm"* |
| `handle_nl_free_time` | *"free time friday 1-3pm"* |
| `handle_nl_count` | *"how many meetings this month"* |
| `handle_nl_title_search` | *"find demo"* |
| `handle_nl_rename` | *"rename demo to review"* |
| `handle_nl_create` | *"schedule lunch today at 12"* |
| `handle_nl_recurring` | *"every monday 10am for 3 weeks"* |
| `handle_nl_human_date` | *"oct 11"*, *"11th october"* |
| `handle_nl_show_on_date` | *"what do i have on friday"* |
| `handle_nl_recurring_weekly` | *"weekly standup"* |

#### LLM Fallback (`openai_handler.py`)

When fast paths miss, the backend calls the Groq API (`https://api.groq.com/openai/v1/chat/completions`) with a system prompt that coerces the response into a canonical intent shape:

```json
{
  "intent": "CREATE_SINGLE | UPDATE_RESCHEDULE | UPDATE_TITLE | ...",
  "params": { ... }
}
```

If the API key is missing, a naive regex fallback handles basic queries.

#### LLM Dispatch (`intents/llm/__init__.py`)

Maps parsed LLM intents to backend actions:

- `CREATE_SINGLE`
- `CREATE_RECURRING`
- `UPDATE_RESCHEDULE`
- `UPDATE_TITLE`
- `MOVE_DAY_ALL`
- `CONVERT_TO_RECURRING`
- `CANCEL_DELETE`
- `RETRIEVE_*`
- `FREE_TIME`
- `CONFLICT`
- `REMINDER_*`

### 5.5 Recurrence Engine (`scheduler/recurrence.py`)

Expands recurrence rules into concrete dates. Supports:

- Weekly by weekday(s)
- Range-bounded (`between Oct 1 and Oct 31`)
- Count-bounded (`for 4 occurrences`)
- Interval (`every 2 weeks`)
- Preview mode (no DB write)

### 5.6 Utilities (`utils/`)

| Module | Purpose |
|--------|---------|
| `parsing.py` | `_to_date`, `_to_time`, `_parse_human_date`, `_extract_title_from_text`, etc. |
| `dates.py` | `_add_minutes`, `_duration_minutes`, `_month_bounds`, timezone helpers |
| `slots.py` | `_compute_free_slots`, `_find_first_free_slot`, `_resolve_reschedule_times` |
| `serializers.py` | `_serialize_appt`, `_serialize_reminder` |
| `matching.py` | `_fuzzy_match`, `_match_opts` |
| `db.py` | `get_db` context manager |

---

## 6. Frontend Documentation

### 6.1 React Application (`src/App.js`)

The main component manages state for:

- `query` — current chat input
- `messages` — chat history
- `appointments`, `createdAppts`, `freeSlots`, `proposals`
- `count`, `conflicts`, `reminders`, `toasts`
- `awaitingFlow` — conversational create-flow state

It renders:
- Header with brand + action buttons
- Chat panel with messages, buttons, input, mic
- Results panel with cards for appointments, free slots, proposals, etc.
- Toast stack for native/in-app reminders

### 6.2 Components

| Component | Purpose |
|-----------|---------|
| `App.js` | Main app shell; also defines `AppointmentListPanel`, the shared list/card component used for both the "Appointments" and "Created" panels |
| `MicButton.jsx` | Microphone activation button |

Several components that existed in an earlier version of the app
(`ChatLayout.jsx`, `CalendarView.jsx`, `VanillaCalendar.jsx`,
`FreeVoiceAssistant.jsx`, a `pages/CalendarPage.jsx`, and a standalone
`public/calendar/` vanilla-JS sub-app) were removed — none of them were ever
imported by `App.js`/`index.js`, and there was no router mounted to reach
them, so they were pure dead weight. See `CHANGELOG.md` (2026-08-19).

### 6.3 Custom Hooks

| Hook | Purpose |
|------|---------|
| `useKeyboardShortcuts.js` | Global shortcuts (`Cmd+N`, `Cmd+P`, `Cmd+Shift+E/I`, `Cmd+K`) |
| `useSpeech.js` | Speech-to-text integration |

### 6.4 API Client (`src/api.js`)

Axios instance configured with:
- Base URL: empty in dev (uses proxy), `http://127.0.0.1:5001` in production
- Default `Content-Type: application/json`

### 6.5 Tests (`src/App.test.js`)

Jest + React Testing Library. Mocks `./api` so tests don't need a running
backend. Covers the chat greeting/input rendering, and a regression test
for the guided create-appointment flow (types a query, clicks through
button-driven steps, asserts it doesn't crash — this is the exact path that
broke when `handleButtonClick` was accidentally defined outside the `App`
component).

```bash
cd frontend
CI=true npx react-scripts test --watchAll=false
```

---

## 7. Electron Desktop App

### 7.1 Main Process (`electron/main.js`)

Responsibilities:

- **Backend discovery** — finds the Python backend (dev vs packaged)
- **Backend startup** — creates venv, installs requirements, spawns Flask
- **Backend health checks** — polls `/health` until ready
- **Native notifications** — polls reminders, shows macOS notifications
- **Menubar tray** — shows next appointment, toggles window
- **IPC handlers** — calendar sync, spotlight index, print, backup/restore
- **Deep-linking** — handles `scheduler-ai://appointment/123`
- **Application menu** — File / View / Window with keyboard accelerators
- **Auto-restart backend** — restarts crashed backend up to 3 times
- **Backend logging** — writes stdout/stderr to `~/Library/Application Support/scheduler-ai/backend.log`
- **Navigation guard** — `will-navigate` and `setWindowOpenHandler` block the window from ever navigating away from its own origin or opening arbitrary new windows (the app never legitimately needs either)

### 7.2 Preload Script (`electron/preload.js`)

Exposes a secure API to the renderer:

```js
window.electronAPI = {
  notifyReminder,
  onReminderDismissed,
  stopAlarm,
  onAppointmentOpen,
  onNavigate,
  syncCalendar,
  indexSpotlight,
  onNativeSyncResult,
  printToPDF,
  exportBackup,
  importBackup,
  onMenuNewAppointment,
  onMenuExportBackup,
  onMenuImportBackup,
  onMenuPrintPDF,
};
```

### 7.3 Build Pipeline

```
npm run electron:build
    ├── prebuild:backend     # copies backend → frontend/backend/
    ├── prebuild:native      # swift build + copy binaries
    ├── build:web            # react-scripts build
    ├── prebuild:electron    # cp electron/main.js build/electron.js
    ├── electron-builder     # package macOS universal .app
    └── postbuild:sign       # ad-hoc sign + strip quarantine
```

---

## 8. Native macOS Integrations

### 8.1 Calendar.app Sync (`calendar-sync`)

- Swift executable using EventKit
- Creates/updates a "Scheduler AI" calendar
- Maps appointments to `EKEvent` (title, location, times, recurrence)
- Persists `appointment_id` → `eventIdentifier` mapping in `~/Library/Application Support/scheduler-ai/calendar-map.json`
- Triggered from Electron header button or menu

### 8.2 Spotlight Indexing (`spotlight-index`)

- Swift executable using CoreSpotlight
- Indexes all appointments with `CSSearchableItem`
- Supports deep links: `scheduler-ai://appointment/{id}`
- Triggered from Electron header button

### 8.3 Siri Shortcuts (`SiriIntents.appex`)

- App Intents extension
- Actions: **Next Appointment**, **Create Appointment**
- Embedded in `/Applications/Scheduler AI.app/Contents/PlugIns/`

### 8.4 Today Widget (`SchedulerWidget.appex`)

- WidgetKit extension
- Shows next upcoming appointment
- Refreshes every 15 minutes
- Embedded in `/Applications/Scheduler AI.app/Contents/PlugIns/`

### 8.5 Menubar Tray

- Tray icon in macOS menu bar
- Tooltip shows next appointment
- Click toggles window
- Right-click menu: Show, Refresh, Quit

---

## 9. API Reference

### Health

```http
GET /health
```

Response:
```json
{ "ok": true, "service": "scheduler", "time": "2026-05-14T16:02:47" }
```

### Main Query

```http
POST /query
Content-Type: application/json
```

#### Natural Language
```json
{ "query": "free time tomorrow 1-5pm for 60 min" }
```

#### Structured Actions

| Action | Payload | Response |
|--------|---------|----------|
| `today` | `{ "action": "today" }` | `{ "appointments": [...] }` |
| `this_week` | `{ "action": "this_week" }` | `{ "appointments": [...] }` |
| `next_upcoming` | `{ "action": "next_upcoming" }` | `{ "appointment": {...} }` |
| `list_by_date` | `{ "action": "list_by_date", "date": "2025-10-15" }` | `{ "appointments": [...] }` |
| `create` | `{ "action": "create", "date", "start_time", "end_time", "title" }` | `{ "created": {...} }` |
| `update` / `reschedule` | `{ "action": "update", "selector": {...}, ... }` | `{ "updated": {...} }` |
| `delete` | `{ "action": "delete", "selector": {...} }` | `{ "deleted": [...] }` |
| `free` | `{ "action": "free", "date", "start_time", "end_time", "duration_minutes" }` | `{ "free": [...], "proposals": [...] }` |
| `conflicts` | `{ "action": "conflicts", "date": "..." }` | `{ "conflicts": [[...], ...] }` |
| `count_this_month` | `{ "action": "count_this_month" }` | `{ "count": N }` |
| `reminders_due` | `{ "action": "reminders_due" }` | `{ "due_reminders": [...] }` |

### Export/Import

```http
GET /export
```
Response: `{ "appointments": [...], "exported_at": "..." }`

```http
POST /import
Content-Type: application/json
{ "appointments": [...] }
```
Response: `{ "created": N, "errors": [...] }`

```http
POST /import_ics
Content-Type: multipart/form-data
file: <.ics file>
```
Response: `{ "created": N, "errors": [...] }`

---

## 10. Environment Setup

### 10.1 Backend

```bash
cd /Users/tenalisriharsha/PycharmProjects/ai-assistant-app
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 10.2 Frontend

```bash
cd frontend
npm install
```

### 10.3 Groq API Key (optional)

The backend works fully without this — natural-language queries that don't
match a fast-path handler (`intents/nl/handlers.py`) fall back to a local
naive parser instead of calling Groq. The key only improves handling of
unusual phrasing.

For local dev convenience, create `frontend/electron/secrets.js`:

```js
module.exports = {
  GROQ_API_KEY: 'gsk_...',
};
```

This file is gitignored and — as of the 2026-08-19 security pass — is
**explicitly excluded** from packaged Electron builds (`!electron/secrets.js`
in `package.json`'s `build.files`), so the key never ships inside the
distributed `.app`. It's only loaded when running from source
(`electron:dev` or plain `npm start`); a packaged build instead reads
`GROQ_API_KEY` from `process.env` or a user-dropped
`~/Library/Application Support/scheduler-ai/secrets.json` (see
`getSecret()` in `electron/main.js`).

For the plain Flask dev server (`start-dev.sh` / `python app.py`), none of
this wiring applies — export `GROQ_API_KEY` yourself if you want it.

### 10.4 macOS Native Helpers

Requires Xcode command-line tools and Swift:

```bash
cd native/macOS-helpers
swift build
```

---

## 11. Development Workflow

### Quick Start (Dev Mode)

```bash
./start-dev.sh
```

This starts:
- Flask backend on `http://127.0.0.1:5001`
- React dev server on `http://localhost:3000`

Open `http://localhost:3000` in your browser.

### Run Backend Only

```bash
source .venv/bin/activate
PORT=5001 python app.py
```

### Run Frontend Only

```bash
cd frontend
npm start
```

### Run Electron Dev Mode

```bash
cd frontend
npm run electron:dev
```

### Build Packaged App

```bash
cd frontend
npm run electron:build
```

Output:
```
frontend/dist/mac-universal/Scheduler AI.app
frontend/dist/Scheduler AI-0.1.0-universal.dmg
```

### Run Tests

Backend (pytest, isolated from `appointments.db` via a throwaway SQLite DB —
see `tests/conftest.py`):

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt   # first time only
python -m pytest tests/ -v
```

Frontend (Jest + React Testing Library):

```bash
cd frontend
CI=true npx react-scripts test --watchAll=false
```

---

## 12. Build & Deployment

### 12.1 Signing

For local testing, ad-hoc signing is used:

```bash
codesign --deep --force --sign - "/Applications/Scheduler AI.app"
xattr -rd com.apple.quarantine "/Applications/Scheduler AI.app"
```

For distribution on macOS Sequoia, a **paid Apple Developer ID certificate** is required.

### 12.2 Universal Binary

`electron-builder` is configured to build a universal binary (`arch: ["universal"]`) that runs natively on both Apple Silicon and Intel Macs.

### 12.3 Embedded Resources

The packaged app includes:
- `backend/` — Python source + venv (created on first run)
- `native/` — compiled Swift binaries
- `PlugIns/` — SiriIntents + SchedulerWidget extensions

### 12.4 Hosted Deployment (PythonAnywhere)

As of 2026-08-22, the app also runs as a hosted, password-protected
instance at **https://tenalisriharsha.pythonanywhere.com** — separate from
local/desktop/Electron use, which is completely unaffected by any of this.

**Why PythonAnywhere**: it requires no credit card, ever, on the free
tier. Fly.io was evaluated first but ruled out — it eliminated its
permanent free tier in 2024 (now a $5 trial capped at 2 VM-hours), and its
own community forum shows a real pattern of surprise billing complaints,
with persistent volumes (which this app's SQLite database needs) called
out as a specific cost trap.

**What made this possible** (see `app.py`):
- An optional password gate, active only when the `APP_PASSWORD` env var
  is set — protects `/query`, `/export`, `/import`, `/import_ics` behind a
  session cookie. Unset (the default for local/desktop use), the app
  behaves exactly as it always has.
- `FRONTEND_BUILD_DIR` env var: when set, Flask serves the built React
  frontend itself (same-origin with the API, no CORS needed), instead of
  the tiny JSON ping `/` normally returns.
- `frontend/src/api.js` distinguishes three cases for its base URL:
  relative in dev, a relative URL for a plain web deployment like this
  one (same-origin), and the packaged Electron app's absolute
  `http://127.0.0.1:5001` (gated behind a `REACT_APP_ELECTRON` build-time
  flag, set only by `electron:build`).
- `SCHEDULER_DB_URL` (already existed, originally added for test
  isolation) points the SQLite file at PythonAnywhere's persistent home
  directory — no volume-mount config needed there, unlike a
  container-based host.

**Deployment shape**: not Docker-based — PythonAnywhere's free tier
doesn't run arbitrary containers. A WSGI config file (kept on
PythonAnywhere itself, not in this repo) points at `app.py`'s `app`
object directly and sets `APP_PASSWORD`/`SECRET_KEY`/`FRONTEND_BUILD_DIR`/
`SCHEDULER_DB_URL` (free accounts have no dashboard env-var panel). The
frontend is built locally (`npm run build:web`, no `REACT_APP_ELECTRON`
flag) and transferred via `deploy/pythonanywhere_frontend_build.zip` +
`git pull` on PythonAnywhere's end, rather than running `npm install`
there — their free tier's 512MB disk quota is too tight to safely run
CRA's build (`node_modules` alone can hit 300-500MB).

**To update the live deployment** after a code change:
1. Push your change to GitHub as normal.
2. If you touched the frontend: `cd frontend && npm run build:web` (no
   `REACT_APP_ELECTRON`), then re-zip `frontend/build/` into
   `deploy/pythonanywhere_frontend_build.zip`, commit, and push.
3. On PythonAnywhere (Bash console): `cd ~/ai-assistant-app && git pull`,
   and if the frontend changed, `cd frontend_build && unzip -o
   ../deploy/pythonanywhere_frontend_build.zip`.
4. Reload the web app from the **Web** tab.

**Known limitations of this deployment** (PythonAnywhere free tier, not
app bugs):
- The web app must be manually "renewed" (one click on the Web tab,
  emailed reminder a week ahead) at least once a month, or it goes
  offline — no data loss, just needs the click.
- Outbound internet is allowlisted on the free tier, so the optional Groq
  LLM fallback (`api.groq.com`) is unreachable there — a non-issue since
  the app already works fully on the local naive parser without it.
- 100 CPU-seconds/day quota — fine for personal single-user use.

---

## 13. File-by-File Reference

### Backend (Root Level)

| File | Purpose |
|------|---------|
| `app.py` | Flask API, request routing, action/NL/LLM dispatch |
| `crud.py` | Database operations, conflict detection, search |
| `database.py` | SQLAlchemy session management |
| `models.py` | SQLAlchemy data models |
| `openai_handler.py` | Groq LLM client + naive fallback |
| `schemas.py` | Pydantic request/response validation |
| `generate_sample_excel.py` | Generates sample data |
| `inspect_db.py` | Database inspection utility |
| `seed_data.py` | Seed data script |
| `requirements-dev.txt` | + pytest, for `tests/` |
| `CHANGELOG.md` | Dated log of what changed and why |
| `start-dev.sh` | One-command dev start |
| `start_macos.sh` | macOS launcher |
| `install_macos.sh` | Install .app to /Applications |

> Removed as dead code during the 2026-08-19 cleanup (zero references
> anywhere in the codebase): `routes.py` (a 2,715-line stale duplicate of
> `app.py`), `nl_creation_flow.py` (superseded by
> `flows/create_appointment_flow.py`), `handlers/appointments.py`,
> `excel_handler.py`, `voice_assistant.py`, plus the untracked
> `app_legacy.py` / `app1_legacy.py` / `mainapp_legacy.py` /
> `seed_datapy`. See `CHANGELOG.md` for the full rationale on each.

### Intent Packages

| File | Purpose |
|------|---------|
| `intents/nl/handlers.py` | 19 fast-path NL handlers |
| `intents/nl/__init__.py` | Dispatcher runner |
| `intents/llm/__init__.py` | LLM intent-to-action dispatch |
| `intents/reminders.py` | Reminder handlers |
| `intents/retrieve.py` | Retrieval handlers |

### Utilities

| File | Purpose |
|------|---------|
| `utils/parsing.py` | Date/time/text parsing helpers |
| `utils/dates.py` | Date arithmetic and timezone helpers |
| `utils/slots.py` | Free-slot computation |
| `utils/serializers.py` | Model serialization |
| `utils/matching.py` | Fuzzy matching |
| `utils/db.py` | DB context manager |

### Scheduler

| File | Purpose |
|------|---------|
| `scheduler/recurrence.py` | RRULE expansion |
| `scheduler/plan_utils.py` | Planning utilities |
| `scheduler/templates.py` | Schedule templates |

### Tests

| File | Purpose |
|------|---------|
| `tests/conftest.py` | Points the app at a throwaway SQLite DB (`SCHEDULER_DB_URL`), never the real `appointments.db` |
| `tests/test_reminders_due.py` | Reminder due/not-due classification + call sites use local time, not UTC |
| `tests/test_bulk_create_conflicts.py` | In-batch, cross-batch, and pre-existing conflict detection |
| `tests/test_create_flow_sessions.py` | Session isolation between clients + stale-session pruning |
| `tests/test_auth.py` | Password-gate behavior: open when `APP_PASSWORD` unset, login/logout/session cycle when set |

### Deployment

| File | Purpose |
|------|---------|
| `deploy/pythonanywhere_frontend_build.zip` | Locally-built frontend, transferred to PythonAnywhere via `git pull` (see §12.4) |

### Frontend

| File | Purpose |
|------|---------|
| `frontend/src/App.js` | Main React application + `AppointmentListPanel` |
| `frontend/src/App.test.js` | Jest/RTL tests |
| `frontend/src/api.js` | Axios API client (adds per-tab `X-Session-Id`) |
| `frontend/src/components/LoginGate.jsx` | Password screen shown when the backend reports `auth_required` |
| `frontend/src/components/MicButton.jsx` | Microphone button |
| `frontend/src/hooks/useKeyboardShortcuts.js` | Keyboard shortcuts |
| `frontend/src/hooks/useSpeech.js` | Speech-to-text |
| `frontend/electron/main.js` | Electron main process |
| `frontend/electron/preload.js` | Renderer API bridge |
| `frontend/scripts/build-native.js` | Build Swift helpers |
| `frontend/scripts/prebuild-backend.js` | Copy backend for packaging |
| `frontend/scripts/sign-macos.js` | Sign and strip quarantine |

### Native

| File | Purpose |
|------|---------|
| `native/macOS-helpers/Sources/CalendarSync/main.swift` | Calendar.app sync |
| `native/macOS-helpers/Sources/SpotlightIndex/main.swift` | Spotlight indexing |
| `native/SiriIntents/SchedulerIntents.swift` | Siri Shortcuts intents |
| `native/TodayWidget/SchedulerWidget.swift` | Widget timeline provider |
| `native/TodayWidget/SchedulerWidgetView.swift` | Widget SwiftUI view |
| `native/XCODE_SETUP.md` | Manual Xcode setup instructions |

---

## 14. Troubleshooting

### Backend won't start on port 5001

macOS AirPlay uses port 5000, but 5001 is usually free. If taken:

```bash
lsof -ti :5001 | xargs kill -9
```

Or start backend on a different port:

```bash
PORT=5002 python app.py
```

### Packaged app is killed by macOS

macOS Sequoia enforces strict code signing. For local testing:

```bash
xattr -rd com.apple.quarantine "/Applications/Scheduler AI.app"
codesign --deep --force --sign - "/Applications/Scheduler AI.app"
```

For distribution, you need an Apple Developer ID certificate.

### `npm run electron:dev` fails with "Electron ENOENT" or a "malware" notification

Two separate issues, both fixed automatically as of 2026-08-19:

1. **ENOENT** (`spawn .../Electron.app/Contents/MacOS/Electron ENOENT`) — the
   `electron` npm package's postinstall binary download was skipped or
   interrupted, so only `LICENSE`/`version` files exist in
   `node_modules/electron/dist/`, no actual `Electron.app`. Fix:
   ```bash
   node node_modules/electron/install.js
   ```
2. **A "malware" notification, and the app disappears again right after**
   — this is real, not a false alarm you can just dismiss: on newer macOS,
   the downloaded `Electron.app`'s ad-hoc/dev signature fails Apple's
   Certificate Transparency check (visible in the unified log as `AMFI: has
   no CMS blob?` / `Unrecoverable CT signature issue`), and Gatekeeper's
   enforcement daemon (`syspolicyd`) automatically deletes it —
   `xattr -rd com.apple.quarantine` does **not** fix this, since it's a
   deeper kernel-level signature check, not the quarantine flag. Fix: give
   it a valid local signature (same pattern as the packaged-app fix above):
   ```bash
   codesign --deep --force --sign - node_modules/electron/dist/Electron.app
   ```

Both are now handled automatically — `npm run electron:dev` runs
`scripts/fix-electron-dev-signing.js` first (via npm's `preelectron:dev`
hook), which re-signs the binary every time, so this shouldn't come up
again. It only re-triggers if `node_modules` gets reinstalled fresh and
the binary download itself fails, in which case run step 1 above first.

### Calendar sync asks for permission repeatedly

Grant permission in:

```
System Settings → Privacy & Security → Calendars → Scheduler AI
```

### Spotlight search doesn't show appointments

Click the **🔍 Spotlight** button in the app header to re-index.

### Siri Shortcuts / Widget don't appear

The `.appex` files must be:
1. Embedded in `/Applications/Scheduler AI.app/Contents/PlugIns/`
2. Signed with a valid Apple Development certificate
3. The app bundle must be signed consistently

Run:

```bash
codesign --force --sign - "/Applications/Scheduler AI.app/Contents/PlugIns/SiriIntents.appex"
codesign --force --sign - "/Applications/Scheduler AI.app/Contents/PlugIns/SchedulerWidget.appex"
codesign --deep --force --sign - "/Applications/Scheduler AI.app"
```

### Frontend can't reach backend

Check that:
- Backend is running on `http://127.0.0.1:5001`
- The dev proxy is set in `frontend/package.json`: `"proxy": "http://127.0.0.1:5001"`
- CORS is enabled in `app.py`

---

## 15. Known Limitations

- **Packaged app requires paid Apple Developer certificate** for distribution on macOS Sequoia
- **Siri Shortcuts / Widget** require Xcode build step and proper signing
- **Calendar sync** is one-way (Scheduler AI → Calendar.app); pull is not implemented
- **Voice input** requires microphone permission and browser support
- **Cross-timezone** support is best-effort; system timezone is used by default

---

## 16. Future Enhancements

Potential improvements:

- Two-way Calendar.app sync (pull events back into Scheduler AI)
- iCloud / Google Calendar integration
- Email/SMS reminders (currently only in-app)
- Recurring reminders
- Mobile-responsive PWA
- Dark mode
- Broader test coverage — `tests/` currently only covers the bugs fixed on
  2026-08-19 (reminder timezone, bulk-create conflicts, session isolation);
  the NL fast-path handlers, recurrence engine, and most of `crud.py` still
  have none
- Extract `App.js`'s state/handlers into `useAppointments`/`useReminders`
  hooks — deliberately scoped out of the 2026-08-19 pass as too large a
  rewrite of a ~1,400-line file with (at the time) no test coverage backing
  it; the one concrete duplication (the appointment-card markup) was
  extracted into `AppointmentListPanel` instead
- TypeScript migration

---

*Originally generated: 2026-05-14. Last reviewed/updated: 2026-08-19 — see [CHANGELOG.md](CHANGELOG.md) for what changed.*
