import Foundation
import EventKit
import Shared

// MARK: - Configuration

let backendURL = ProcessInfo.processInfo.environment["BACKEND_URL"]
    .flatMap(URL.init(string:))
    ?? URL(string: "http://127.0.0.1:5001")!

let mappingPath = FileManager.default
    .urls(for: .applicationSupportDirectory, in: .userDomainMask)
    .first!
    .appendingPathComponent("scheduler-ai")
    .appendingPathComponent("calendar-map.json")

// MARK: - Mapping persistence

struct CalendarMapping: Codable {
    var ekEventID: String
    var lastModified: Date
}

func loadMapping() -> [Int: CalendarMapping] {
    guard let data = try? Data(contentsOf: mappingPath) else { return [:] }
    guard let dict = try? JSONDecoder().decode([String: CalendarMapping].self, from: data) else { return [:] }
    return dict.compactMapKeys { Int($0) }
}

func saveMapping(_ mapping: [Int: CalendarMapping]) {
    let dict = mapping.mapKeys { String($0) }
    let dir = mappingPath.deletingLastPathComponent()
    try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    if let data = try? JSONEncoder().encode(dict) {
        try? data.write(to: mappingPath)
    }
}

// MARK: - EventKit helpers

func ensureCalendar(in store: EKEventStore) -> EKCalendar? {
    let calendars = store.calendars(for: .event)
    if let existing = calendars.first(where: { $0.title == "Scheduler AI" }) {
        return existing
    }
    let cal = EKCalendar(for: .event, eventStore: store)
    cal.title = "Scheduler AI"
    cal.source = store.defaultCalendarForNewEvents?.source ?? store.sources.first
    do {
        try store.saveCalendar(cal, commit: true)
        print("[CalendarSync] Created 'Scheduler AI' calendar")
        return cal
    } catch {
        print("[CalendarSync] Failed to create calendar: \(error)")
        return nil
    }
}

func ekRecurrenceRule(from rrule: String?) -> EKRecurrenceRule? {
    guard let rrule = rrule, !rrule.isEmpty else { return nil }
    // Simple iCal RRULE parsing: FREQ=DAILY;INTERVAL=1 or FREQ=WEEKLY;BYDAY=MO,WE,FR
    let freqMap: [String: EKRecurrenceFrequency] = [
        "DAILY": .daily,
        "WEEKLY": .weekly,
        "MONTHLY": .monthly,
        "YEARLY": .yearly,
    ]
    let parts = rrule.uppercased().components(separatedBy: ";")
    var freq: EKRecurrenceFrequency? = nil
    var interval = 1
    var days: [EKRecurrenceDayOfWeek] = []
    
    for part in parts {
        if part.hasPrefix("FREQ=") {
            let key = String(part.dropFirst(5))
            freq = freqMap[key]
        } else if part.hasPrefix("INTERVAL=") {
            interval = Int(String(part.dropFirst(9))) ?? 1
        } else if part.hasPrefix("BYDAY=") {
            let dayStrs = String(part.dropFirst(6)).components(separatedBy: ",")
            let dayMap: [String: EKRecurrenceDayOfWeek] = [
                "MO": EKRecurrenceDayOfWeek(.monday),
                "TU": EKRecurrenceDayOfWeek(.tuesday),
                "WE": EKRecurrenceDayOfWeek(.wednesday),
                "TH": EKRecurrenceDayOfWeek(.thursday),
                "FR": EKRecurrenceDayOfWeek(.friday),
                "SA": EKRecurrenceDayOfWeek(.saturday),
                "SU": EKRecurrenceDayOfWeek(.sunday),
            ]
            days = dayStrs.compactMap { dayMap[$0] }
        }
    }
    guard let freq = freq else { return nil }
    return EKRecurrenceRule(
        recurrenceWith: freq,
        interval: interval,
        daysOfTheWeek: days.isEmpty ? nil : days,
        daysOfTheMonth: nil,
        monthsOfTheYear: nil,
        weeksOfTheYear: nil,
        daysOfTheYear: nil,
        setPositions: nil,
        end: nil
    )
}

// MARK: - Sync logic

@main
struct CalendarSync {
    static func main() async {
        let args = CommandLine.arguments
        let mode = args.dropFirst().first ?? "--push"
        
        let store = EKEventStore()
        
        if #available(macOS 14.0, *) {
            let granted = try? await store.requestFullAccessToEvents()
            guard granted == true else {
                print("[CalendarSync] Calendar access denied")
                exit(1)
            }
        } else {
            let granted = try? await store.requestAccess(to: .event)
            guard granted == true else {
                print("[CalendarSync] Calendar access denied")
                exit(1)
            }
        }
        
        guard let calendar = ensureCalendar(in: store) else {
            print("[CalendarSync] Could not get or create calendar")
            exit(1)
        }
        
        let client = BackendClient(baseURL: backendURL)
        
        switch mode {
        case "--push":
            await push(store: store, calendar: calendar, client: client)
        case "--pull":
            await pull(store: store, calendar: calendar, client: client)
        case "--sync":
            await push(store: store, calendar: calendar, client: client)
            await pull(store: store, calendar: calendar, client: client)
        default:
            print("Usage: calendar-sync [--push | --pull | --sync]")
            exit(1)
        }
    }
    
    static func push(store: EKEventStore, calendar: EKCalendar, client: BackendClient) async {
        print("[CalendarSync] Pushing appointments to Calendar.app...")
        var mapping = loadMapping()
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withFullDate, .withTime, .withColonSeparatorInTime]
        
        do {
            let appointments = try await client.fetchAllAppointments()
            let existingEventIDs = Set(mapping.values.map(\.ekEventID))
            var seenIDs = Set<String>()
            
            for appt in appointments {
                guard let start = appt.startDate, let end = appt.endDate else { continue }
                
                let event: EKEvent
                if let existing = mapping[appt.id],
                   let ev = store.event(withIdentifier: existing.ekEventID) {
                    event = ev
                } else {
                    event = EKEvent(eventStore: store)
                    event.calendar = calendar
                }
                
                event.title = appt.displayTitle
                event.location = appt.location
                event.notes = appt.notes
                event.startDate = start
                event.endDate = end
                if let isAllDay = appt.is_all_day, isAllDay {
                    event.isAllDay = true
                }
                if let tentative = appt.tentative, tentative {
                    event.availability = .tentative
                }
                if let rrule = ekRecurrenceRule(from: appt.recurrence_rule) {
                    event.recurrenceRules = [rrule]
                } else {
                    event.recurrenceRules = nil
                }
                
                do {
                    try store.save(event, span: .thisEvent, commit: false)
                    mapping[appt.id] = CalendarMapping(
                        ekEventID: event.eventIdentifier,
                        lastModified: Date()
                    )
                    seenIDs.insert(event.eventIdentifier)
                    print("[CalendarSync] Synced: \(appt.displayTitle)")
                } catch {
                    print("[CalendarSync] Failed to save event for \(appt.displayTitle): \(error)")
                }
            }
            
            // Remove orphaned events
            let orphaned = existingEventIDs.subtracting(seenIDs)
            for eventID in orphaned {
                if let ev = store.event(withIdentifier: eventID) {
                    try? store.remove(ev, span: .thisEvent, commit: false)
                }
            }
            mapping = mapping.filter { seenIDs.contains($0.value.ekEventID) }
            
            try store.commit()
            saveMapping(mapping)
            print("[CalendarSync] Push complete. Synced \(appointments.count) appointments.")
        } catch {
            print("[CalendarSync] Push failed: \(error)")
        }
    }
    
    static func pull(store: EKEventStore, calendar: EKCalendar, client: BackendClient) async {
        print("[CalendarSync] Pulling from Calendar.app is not yet implemented.")
        print("[CalendarSync] Use --push to export Scheduler AI → Calendar.app")
    }
}

extension Dictionary {
    func compactMapKeys<T: Hashable>(_ transform: (Key) throws -> T?) rethrows -> [T: Value] {
        var result: [T: Value] = [:]
        for (key, value) in self {
            if let newKey = try transform(key) {
                result[newKey] = value
            }
        }
        return result
    }
    
    func mapKeys<T: Hashable>(_ transform: (Key) throws -> T) rethrows -> [T: Value] {
        var result: [T: Value] = [:]
        for (key, value) in self {
            result[try transform(key)] = value
        }
        return result
    }
}
