# Changelog

All notable changes to this project are recorded here, newest first. Each
entry is dated and, where useful, time-stamped, so we can always trace what
changed, when, and why — not just what the diff shows.

Format per entry: **what changed** → **why** → **files touched**.

---

## 2026-08-19 21:42 CDT — Full hands-on UI test pass: 3 real bugs found and fixed

Context: drove the actual React UI end-to-end in a browser (not just API
calls) — create, rename, reschedule, cancel, recurring preview/book, free
time, conflict detection, reminders (create/snooze/pause/delete), and
due-reminder toasts. Found and fixed three real, previously-unknown bugs;
everything else (documented below) worked correctly.

- **Any free-text query mentioning "today"/"this week" that didn't also
  contain one of five hardcoded keywords had its entire text silently
  discarded.** `handleQuery` classified queries by regex
  (create/modify/cancel/free/between-like); anything matching none of
  those, but containing "today" or "this week", got its whole payload
  replaced with a bare `{action:'today'}`/`{action:'this_week'}` —
  throwing away what the user actually typed. Concretely: *"remind me at
  5pm today to call Alex"* silently became "show me today's appointments"
  and never created the reminder; *"how many meetings today"* would have
  shown a full listing instead of a count. Since the backend already
  parses bare "today"/"this week" queries correctly through its own
  fast-path handlers (including the ones added earlier today), this
  frontend-side shortcut was both unsafe and redundant — removed it
  entirely; every query now goes to the backend as typed.
  Files: `frontend/src/App.js`

- **Recurring-preview responses never rendered.** `applyPayload` checked
  `typeof data.preview === 'object'` to detect a "nested payload" preview
  shape and recurse into it — but `typeof [] === 'object'` is `true` in
  JS, and *every* real backend response sets `preview` to a flat array of
  proposed slots, never a nested object. So it always recursed into the
  array itself (which has none of the fields `applyPayload` looks for) and
  silently dropped the response — "No proposals yet." in the UI even when
  the backend returned real preview slots, discovered testing *"preview
  standup every Monday at 10am for 3 weeks."* Fixed to treat an array
  `preview` as the proposals list directly.
  Files: `frontend/src/App.js`

- **Dismissing a due-reminder toast crashed with an uncaught runtime
  error, every time.** `markReminderDelivered` called
  `api.post('/query', { method, headers, body: JSON.stringify(...) })` —
  `fetch()`-style options passed as axios's *data* argument, so axios sent
  that literal object as the JSON body instead of
  `{action: 'reminder_mark_delivered', id}`. The backend always rejected
  it with a 400, uncaught, crashing the app. This had likely never worked
  since it was written.
  Files: `frontend/src/App.js`

- **Two smaller, related NL gaps found and fixed in the same pass**:
  recurring-create title extraction didn't recognize "preview" as a verb
  (`"preview standup every Monday..."` still defaulted to "New event"
  even after the earlier title-extraction fix, since only
  schedule/make/create/book were in the direct-object regex — added
  "preview"). A stray temporary `/__debug_sessions` route (added, then
  removed) was used to rule out session-state as the cause of the "today"
  bug before finding the real one.
  Files: `intents/nl/handlers.py`

- **Verified working correctly, no changes needed**: create (NL + guided
  button flow), rename/reschedule/cancel via UI buttons (including the
  native `window.prompt`/`window.confirm` dialogs), recurring
  preview→book round trip, free-time query → book a proposed slot,
  conflict detection (proposes alternatives instead of double-booking),
  reminder Snooze/Pause/Delete, Cmd+N keyboard shortcut. Export/Import
  backup and Print-to-PDF are Electron-only by design and couldn't be
  exercised in browser-only testing.

Added `frontend/src/App.test.js` regression tests for all three bugs (mocked
API, real user interaction via Testing Library), each verified to fail
against the pre-fix code before confirming the fix. Full backend suite
(20 tests) and frontend suite (5 tests) both pass; real `appointments.db`
confirmed unchanged (138 appointments / 5 reminders) after all testing —
isolated via direct cleanup of every appointment/reminder created during
the session.
Files: `frontend/src/App.test.js`

---

## 2026-08-19 20:55 CDT — Broaden NL fast-path coverage for retrieval and non-standard create phrasing

Follow-up to the previous entry's sweep. Without a Groq API key (the
default for local dev), these phrasings had zero fast-path coverage and
fell through to the much weaker naive local parser, which either errored
outright or silently misread the request:

- **"what's on my calendar this week" / "what do I have tomorrow" / "my
  schedule this month" / "show me today's appointments"** — no existing
  handler matched retrieval phrasing without a "titled/called/named X"
  title filter (the `handle_nl_title_*` handlers all require one). Added
  `handle_nl_show_timeframe`.
- **"what are my reminders"** — nothing listed reminders via free text at
  all (only "remind me..." to create one). Added `handle_nl_list_reminders`.
- **"schedule a call with the dentist tomorrow at 3pm for 30 minutes"** —
  `handle_nl_create_fallback` required the literal word "appointment" or
  "meeting" in the sentence; without it, the naive parser took over and
  treated the whole sentence as a date-only lookup, silently creating
  nothing. Broadened the trigger to also accept a create verb plus an
  actual time/date signal, and added a direct-object title fallback so it
  extracts "call with the dentist" instead of defaulting to "New
  appointment".

One self-inflicted bug caught before commit: the first version of
`handle_nl_show_timeframe` excluded any query containing the word
"schedule" (to avoid misreading create requests as retrieval) — which
also rejected "my schedule this month" itself, since "schedule" appears
there as a noun. Fixed by only applying that exclusion when the query
doesn't already contain the unambiguous "my calendar/schedule/
appointments/agenda" possessive phrase.

Verified with a full sweep of both the newly-covered phrases and the
project's own README example queries (rename, free-time, structured
create, recurring create) to confirm zero regressions — plus a live
browser check of the create-without-"appointment" case end-to-end.
Locked in with `tests/test_nl_coverage_broadening.py` (7 tests, all
passing).
Files: `intents/nl/handlers.py`, `intents/nl/__init__.py`

---

## 2026-08-19 20:40 CDT — Fix NL cancel/delete silently deleting the wrong appointment

Context: ran a systematic sweep of free-form natural-language queries
across every advertised capability (create, recurring create, reschedule,
rename, delete, retrieve, free-time, reminders) to actually verify the
app's core NL functionality, rather than just the specific bugs fixed
earlier today. Found two real, previously-unknown bugs.

- **`handle_nl_delete_cancel` could silently delete the wrong
  appointment.** It only recognizes a title via "titled X"/"called
  X"/"named X" patterns; a bare "cancel <name>" doesn't match any of
  those, so title extraction fails — and the no-date fallback then
  searched the next 7 days with **no title filter at all**, deleting
  whichever appointment happened to be alone in that window, regardless
  of whether it had anything to do with what was asked. Concretely:
  `"cancel Dentist Checkup"` (a title that never existed) deleted an
  unrelated real appointment 5 days out and reported success. Fixed by
  only widening the no-date search to a week when a title was actually
  extracted (filtered by it there too); with no title at all, the search
  now stays capped at today rather than blindly guessing across a wider
  window.
  Files: `intents/nl/handlers.py`

- **Recurring-create defaulted every appointment's title to "New
  event"** for the direct phrasing "schedule `<title>` every ..." —
  including the project's own advertised example query, *"Schedule
  standup every Monday at 10 AM for 3 weeks."* Title extraction only
  recognized "titled/called/named X"; added a fallback that reads the
  direct object between the create verb and "every".
  Files: `intents/nl/handlers.py`

- Added `tests/test_nl_delete_cancel.py` covering the exact bug
  scenario, the legitimate today-only no-title convenience case, and
  the legitimate title-driven week-wide search. Verified the first test
  actually fails against the pre-fix code before confirming the fix.

Also confirmed (not bugs, existing design limits worth knowing about):
without a Groq API key configured, several common retrieval phrasings
("what's on my calendar this week", "what are my reminders") and
creates that don't include the literal word "appointment"/"meeting"
(e.g. "schedule a call with the dentist tomorrow") fall through to the
naive local fallback parser, which has much narrower coverage than the
LLM tier — this matches the documented "minimal local fallback" design,
not a regression, but worth knowing if free-form phrasing seems to be
silently ignored.

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
