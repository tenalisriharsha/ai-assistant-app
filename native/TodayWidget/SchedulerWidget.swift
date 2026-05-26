import WidgetKit
import SwiftUI

struct SchedulerEntry: TimelineEntry {
    let date: Date
    let appointment: AppointmentWidgetModel?
}

struct AppointmentWidgetModel: Codable {
    let id: Int
    let title: String
    let date: String
    let time: String
    let location: String?
}

// MARK: - Provider

@main
struct SchedulerWidget: Widget {
    let kind: String = "SchedulerWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: SchedulerProvider()) { entry in
            SchedulerWidgetView(entry: entry)
        }
        .configurationDisplayName("Next Appointment")
        .description("Shows your next upcoming Scheduler AI appointment.")
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}

// MARK: - Timeline Provider

struct SchedulerProvider: TimelineProvider {
    func placeholder(in context: Context) -> SchedulerEntry {
        SchedulerEntry(
            date: Date(),
            appointment: AppointmentWidgetModel(
                id: 0,
                title: "Team Standup",
                date: "Today",
                time: "10:00 AM",
                location: "Zoom"
            )
        )
    }

    func getSnapshot(in context: Context, completion: @escaping (SchedulerEntry) -> ()) {
        Task {
            let entry = await fetchNextAppointment()
            completion(entry)
        }
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<SchedulerEntry>) -> ()) {
        Task {
            let entry = await fetchNextAppointment()
            // Refresh every 15 minutes
            let nextUpdate = Calendar.current.date(byAdding: .minute, value: 15, to: Date())!
            let timeline = Timeline(entries: [entry], policy: .after(nextUpdate))
            completion(timeline)
        }
    }

    private func fetchNextAppointment() async -> SchedulerEntry {
        do {
            let url = URL(string: "http://127.0.0.1:5001/query")!
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: ["action": "next_upcoming"])
            let (data, _) = try await URLSession.shared.data(for: request)
            let decoded = try JSONDecoder().decode(NextUpcomingResponse.self, from: data)
            guard let appt = decoded.appointment else {
                return SchedulerEntry(date: Date(), appointment: nil)
            }
            let formatter = DateFormatter()
            formatter.dateFormat = "yyyy-MM-dd"
            let dateStr = appt.date
            let displayDate = formatter.date(from: dateStr).map { relativeDate($0) } ?? dateStr
            let timeStr = appt.start_time?.prefix(5) ?? ""
            let model = AppointmentWidgetModel(
                id: appt.id,
                title: appt.title ?? appt.description ?? "Untitled",
                date: displayDate,
                time: String(timeStr),
                location: appt.location
            )
            return SchedulerEntry(date: Date(), appointment: model)
        } catch {
            return SchedulerEntry(date: Date(), appointment: nil)
        }
    }

    private func relativeDate(_ date: Date) -> String {
        let calendar = Calendar.current
        if calendar.isDateInToday(date) { return "Today" }
        if calendar.isDateInTomorrow(date) { return "Tomorrow" }
        let formatter = DateFormatter()
        formatter.dateFormat = "EEE, MMM d"
        return formatter.string(from: date)
    }
}

struct NextUpcomingResponse: Codable {
    let appointment: AppointmentWidgetResponse?
}

struct AppointmentWidgetResponse: Codable {
    let id: Int
    let date: String
    let start_time: String?
    let title: String?
    let description: String?
    let location: String?
}
