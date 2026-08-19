# Changelog

All notable changes to this project are recorded here, newest first. Each
entry is dated and, where useful, time-stamped, so we can always trace what
changed, when, and why — not just what the diff shows.

Format per entry: **what changed** → **why** → **files touched**.

---

## 2026-08-19 — Full audit fixes: critical bugs, security hardening, repo cleanup, test coverage

Context: a full end-to-end review of the backend (Flask/SQLAlchemy) and
frontend (React/Electron) surfaced several real bugs, security gaps, and a
large amount of dead/duplicated code. Fixed in priority order below.

### Critical bugs

- **Guided create-appointment flow was completely broken.**
  `handleButtonClick` and `renderCreateFlowMessage` were defined *outside*
  the `App` component (above the imports), so `handleButtonClick`
  referenced `setMessages`/`setLoading`/`api`/`applyPayload` that only
  exist inside the component — clicking any conversational button threw
  `ReferenceError`. Moved `handleButtonClick` inside `App()`; moved the
  (pure) `renderCreateFlowMessage` below the imports.
  Files: `frontend/src/App.js`

- **Backend was silently dropping the flow's `awaiting`/`buttons` fields.**
  A second, previously-unreported bug found while fixing the above:
  `app.py`'s `/query` handler explicitly whitelisted only
  `status/message/appointment/flow` when forwarding the conversational-flow
  response, so even with the frontend fixed, no buttons could ever render.
  Added `awaiting` and `buttons` to the forwarded response.
  Files: `app.py`

- **Reminders fired at the wrong time (timezone bug).** `Reminder.date`/
  `Reminder.time` are stored as naive *local* wall-clock values (same
  convention as `Appointment`), but the due-check compared them against
  `datetime.now(timezone.utc)`. On a UTC-5 machine, any reminder dated
  "today" could look overdue the instant it was created, because UTC had
  already rolled to the next calendar day. Changed all three call sites to
  use naive local `datetime.now()`.
  Files: `app.py`, `crud.py` (`get_due_reminders` default), `intents/reminders.py`

- **Bulk recurring-create could double-book itself.** `bulk_create_appointments`
  (strict/atomic path) pre-checked conflicts with a plain DB query per entry,
  but nothing in the batch is committed until the end (`autoflush=False`), so
  two overlapping entries in the *same* batch couldn't see each other and
  both got created. Ported the in-memory per-date tracking already used
  correctly in `bulk_create_appointments_lenient`.
  Files: `crud.py`

- **Conversational-flow session state was IP-keyed and unbounded.**
  `CREATE_APPT_SESSIONS` was keyed only by `request.remote_addr`, so two
  users/tabs behind the same NAT could clobber each other's in-progress
  flow, and abandoned flows were never pruned (memory leak). Added an
  `X-Session-Id` header (frontend generates a random UUID per browser tab
  via `sessionStorage`, backend prefers it over IP) plus a 15-minute
  idle-TTL pruning pass on every request.
  Files: `app.py`, `frontend/src/api.js`

### Security

- **CORS was wide open** (`CORS(app)`, any origin). Since the backend
  listens on `127.0.0.1` and is reachable by any page the user has open in
  their regular browser, and `/query` uses a JSON content-type (a CORS
  "non-simple" request, so restricting origins is actually enforceable),
  restricted to the known frontend origins: the CRA dev server, Electron
  dev, and `null` (the packaged app's `file://` origin).
  Files: `app.py`

- **Groq API key shipped inside packaged Electron builds.**
  `package.json`'s `build.files` glob had no exclusion for
  `electron/secrets.js`, so `electron-builder` bundled the live key into
  every distributed `.app`. Excluded it from the glob. While fixing this,
  found the bundled-secret loading was *already* silently broken
  (`require('./secrets')` looked in the wrong directory after `main.js` is
  copied to `build/electron.js` at build time) — fixed the require path too,
  so local dev convenience still works while distributed builds never carry
  the key.
  Files: `frontend/package.json`, `frontend/electron/main.js`

- **No Electron navigation guard.** Added `will-navigate` and
  `setWindowOpenHandler` on the `BrowserWindow` to block navigating away
  from the app's own origin or opening arbitrary new windows (defense in
  depth; the app never legitimately needs either).
  Files: `frontend/electron/main.js`

### Repo hygiene

- Untracked the accidental root-level `node_modules/` (5,354 files) from
  git — a stray `npm install` unrelated to the real `frontend/` app.
- Deleted the 68MB Vosk speech-recognition model (`vosk-model-small-en-us-0.15/`);
  its only consumer, `voice_assistant.py`, was dead code (see below).
- Untracked (not deleted from disk) `appointments.bak.sqlite`,
  `appointments.before-merge.sqlite`, `appointments.before-seed.sqlite` —
  already covered by `.gitignore` but committed before that rule existed.
- Deleted dead/orphaned files with zero references anywhere in the
  codebase: `routes.py` (2,715-line stale duplicate of `app.py`),
  `nl_creation_flow.py` (superseded by `flows/create_appointment_flow.py`),
  `handlers/appointments.py`, `excel_handler.py`, `voice_assistant.py`,
  `app_legacy.py`, `app1_legacy.py`, `mainapp_legacy.py`, `seed_datapy`.
- Deleted four unreachable React components and one unreachable page
  (`CalendarView.jsx`, `VanillaCalendar.jsx`, `CalendarPage.jsx`,
  `ChatLayout.jsx`, `FreeVoiceAssistant.jsx`) and the orphaned vanilla-JS
  calendar sub-app (`frontend/public/calendar/`, 19 files) — none were
  imported by `App.js`/`index.js` and there was no router mounted.
- Updated `frontend/scripts/prebuild-backend.js` to stop referencing the
  now-deleted backend files, and regenerated `frontend/backend/` (the
  tracked packaging copy) so it matches root.
- Removed duplicate stacked `@app.get('/')` / `@app.errorhandler(400)`
  decorators in `app.py` (harmless but signaled copy-paste drift).
- **Not done** (deliberately): rewriting git history to purge the old
  Vosk-model/sqlite blobs already committed — needs `git filter-repo`/BFG
  + a force-push, which is destructive enough to leave as an explicit,
  separate decision rather than doing it silently.
- **Blocked by the permission classifier**: deleting the stray root
  `package.json`/`package-lock.json` (treated as a dependency-manifest
  change requiring explicit confirmation). Still pending — run
  `git rm package.json package-lock.json` to finish this one.

### Test coverage

- Added a backend test suite (`tests/`, pytest) covering the three fixed
  bugs above: reminder due/not-due classification and call-site timezone
  convention, bulk-create in-batch conflict rejection, and create-flow
  session isolation + stale-session pruning. Isolated from the real
  database via a new `SCHEDULER_DB_URL` env-var override in `models.py`
  (defaults to the existing behavior when unset).
- Verified each new test actually catches its bug by temporarily
  reintroducing the original bug, watching the test fail, then restoring
  the fix.
- Fixed the frontend's untouched Create-React-App boilerplate test
  (`App.test.js` asserted text — "learn react" — that doesn't exist in this
  app) and added a real regression test for the `handleButtonClick`
  scoping bug (mocks the API, clicks through the guided flow, asserts it
  doesn't crash and advances correctly).
- Added `requirements-dev.txt` (pytest) so backend tests don't bloat the
  production `requirements.txt`.
  Files: `tests/conftest.py`, `tests/test_reminders_due.py`,
  `tests/test_bulk_create_conflicts.py`, `tests/test_create_flow_sessions.py`,
  `requirements-dev.txt`, `models.py`, `frontend/src/App.test.js`

### Code quality

- Extracted the duplicated appointment-card list markup (previously
  copy-pasted for the "Appointments" and "Created" panels) into one
  `AppointmentListPanel` component.
  Files: `frontend/src/App.js`

---
