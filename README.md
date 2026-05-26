Scheduler AI — Natural-language calendar & reminders (React + Flask)

Scheduler AI is a lightweight, local-first calendar assistant. Type or speak what you want—“free time tomorrow 1–5pm?”, “schedule standup every Monday 10am for 3 weeks”, “rename ‘demo’ to ‘final review’”—and it does the right thing. The React UI stays in sync with a Flask backend and a simple SQL database. It supports one-off and recurring events, conflict-aware bulk creation, quick previews, reminders with toasts/notifications, and rich inline actions.

Highlights
	•	Natural-language control
	•	One-off create: “schedule an appointment today at 5:40 pm called Demo”
	•	Modify: “reschedule ‘Demo’ to tomorrow 2pm”, “rename ‘standup’ to ‘Daily Sync’”
	•	Delete: “cancel ‘gym’ tomorrow”, “delete meetings with title Review on 2025-10-12”
	•	Retrieve: “what’s after 6pm today”, “meetings next 24 hours”, “appointments between 9–11am on 2025-10-15”
	•	Search by title (today / tomorrow / this week / this month / next month / anywhere) with fuzzy matching
	•	Counts: “how many meetings this month”, “how many in the next 7 days”
	•	Free time: “free next week 1–5pm for 60 min?”
	•	Conflicts: “find conflicts today”
	•	Time-zone aware queries (optional): “between 10am–2pm PST on 2025-10-15”
	•	Recurring events (preview & create)
	•	Weekly by weekday(s): “every Thursday at 7pm until Oct 15 titled Dance”
	•	Range-bounded: “every Wednesday between Oct 1 and Oct 31 at 8pm”
	•	Count/period: “every Friday 9am for 60 minutes for 4 occurrences called Review” / “for 3 weeks”
	•	Interval: “every 2 weeks at 6pm titled Class”
	•	Preview-only: “preview every Saturday at 5pm for 2 weeks titled Chill”
	•	Conflict-aware bulk create with created_many + skipped_conflicts surfaced in the UI
	•	Smart conflict handling
	•	When a slot conflicts, the backend returns proposals (alternative free options) and the UI lets you Book this or Move here
	•	Bulk operations (“convert to recurring”, “move day”) return what moved and what was skipped due to conflicts
	•	Reminders with toasts & snooze
	•	“remind me at 3pm to call Alex”, “remind me 15 minutes before ‘Review’”
	•	In-app toast notifications with Dismiss and Snooze 10m
	•	Optional native macOS notifications if you run the Electron shell (gracefully no-ops otherwise)
	•	Reminder polling runs every 60s; delivered status is tracked
	•	Voice input
	•	Click the mic to dictate queries; transcripts are sent through the same NL flow
	•	Fast, resilient parsing
	•	Lots of LLM-independent “fast paths” for common intents (create, free time, counts, rename, reschedule, delete, retrieve ranges)
	•	Human date forms (“Oct 11”, “11th October”) & time ranges (“between 1–3pm”, “after 6pm”)
	•	Cross-midnight windows are handled safely (e.g., 10pm–1am)
	•	Clean UI that stays in sync
	•	Panels for Reminders, Appointments, Created, Free Slots, Proposed Slots, This Month (count), Conflicts
	•	Inline actions: Rename, Reschedule, Cancel
	•	Auto-scrolling chat with helpful status messages

How it works
	•	Frontend: React (src/App.js) with Axios calls to the backend, a chat-like interface, and a MicButton for speech input. It understands and renders special payloads:
	•	appointments, free, proposals, created, created_many, updated, rescheduled, count, conflicts
	•	Recurring UX: preview and skipped_conflicts are displayed, and proposals can be booked/moved in one click
	•	Reminders: reminder, reminders, due_reminders → in-app toasts; dismissing/snoozing updates the backend
	•	Backend: Flask (app.py)
	•	Single endpoint POST /query that accepts either { action: ... } or { query: "…" }
	•	Rich, LLM-independent handlers for: free time, counts, retrieve (today/tomorrow/week/month/range/next 24h), after time, between times (including cross-midnight), timezone transforms, rename, reschedule, delete, bulk move, convert to recurring, reminders (create/snooze/toggle/delete), and recurring preview/create
	•	Returns structured JSON optimized for the UI (see payloads above)
	•	Data layer: simple SQL database (via crud.py) with helpers for:
	•	Create/update/delete, conflict detection, search/fuzzy match by description, free-slot computation, bulk insertions (conflict-aware)
	•	Recurrence helpers: recurrence.py exposes utility expansions (e.g., expand range by weekdays) used by app.py for efficient preview/creation.

  Example queries to try
	•	Recurring
	•	“Schedule standup every Monday at 10 AM for 3 weeks.”
	•	“Create meeting every Thursday 7 PM until October 15 titled Dance.”
	•	“Every Friday at 9 AM for 60 minutes for 4 occurrences called Review.”
	•	“Book class every Wednesday between Oct 1 and Oct 31 at 8 PM.”
	•	“Preview every Saturday at 5 PM for 2 weeks titled Chill.”
	•	Everyday
	•	“Free tomorrow between 1–5pm for 45 minutes?”
	•	“Rename ‘demo’ to ‘final review’.”
	•	“Reschedule ‘final review’ to 2025-10-15 2pm.”
	•	“Delete meetings titled ‘Chill’ next month.”
	•	“How many meetings in the next 7 days?”
	•	“What’s after 6pm today?”
	•	“Appointments between 10pm–1am on 2025-10-20.” (cross-midnight)
	•	“Remind me at 3pm to call Alex.”
	•	“Remind me 10 minutes before ‘Review’.”

API (single endpoint)
	•	POST /query
	•	Natural language: { "query": "free tomorrow 1–5pm for 60 min" }
	•	Direct actions:
	•	{ "action": "today" }, { "action": "this_week" }, { "action": "reminders_due" }
	•	{ "action": "create", date, start_time, end_time, title }
	•	{ "action": "update" | "reschedule" | "delete", selector: {...}, ... }
	•	{ "action": "reminder_snooze" | "reminder_toggle" | "reminder_delete", id, ... }

Representative responses (UI-aware):
	•	{"appointments":[...]}, {"free":[...]}, {"proposals":[...]},
	•	{"created":{...}} / {"created_many":[...]},
	•	{"updated":{...}} / {"rescheduled":{...}},
	•	{"count": N}, {"conflicts":[[a,b],...]},
	•	{"preview":[...]}, {"skipped_conflicts":[...]}, {"message":"..."}.
