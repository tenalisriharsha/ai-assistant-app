import AppIntents
import Foundation

// MARK: - Next Appointment Intent

@available(macOS 14.0, *)
struct NextAppointmentIntent: AppIntent {
    static var title: LocalizedStringResource = "Next Appointment"
    static var description: IntentDescription = "Get your next upcoming appointment from Scheduler AI"
    static var openAppWhenRun: Bool = false

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        let client = SchedulerBackendClient()
        guard let appt = try? await client.fetchNextUpcoming() else {
            return .result(value: "No upcoming appointments found.")
        }
        let title = appt.title ?? appt.description ?? "Untitled"
        let date = appt.date
        let time = appt.start_time?.prefix(5) ?? ""
        let result = time.isEmpty ? "\(title) on \(date)" : "\(title) on \(date) at \(time)"
        return .result(value: result)
    }
}

// MARK: - Create Appointment Intent

@available(macOS 14.0, *)
struct CreateAppointmentIntent: AppIntent {
    static var title: LocalizedStringResource = "Create Appointment"
    static var description: IntentDescription = "Create a new appointment in Scheduler AI"
    static var openAppWhenRun: Bool = true

    @Parameter(title: "Title", requestValueDialog: "What is the appointment called?")
    var title: String

    @Parameter(title: "Date", requestValueDialog: "What date?")
    var date: String

    @Parameter(title: "Start Time", requestValueDialog: "What time does it start?", default: "09:00")
    var startTime: String

    @Parameter(title: "End Time", requestValueDialog: "What time does it end?", default: "10:00")
    var endTime: String

    @Parameter(title: "Location", requestValueDialog: "Where is it?", default: "")
    var location: String

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        let client = SchedulerBackendClient()
        do {
            let appt = try await client.createAppointment(
                title: title,
                date: date,
                startTime: startTime,
                endTime: endTime,
                location: location.isEmpty ? nil : location
            )
            return .result(value: "Created: \(appt.title ?? "Appointment") on \(appt.date)")
        } catch {
            return .result(value: "Failed to create appointment: \(error.localizedDescription)")
        }
    }
}

// MARK: - Backend Client for Intents

@available(macOS 14.0, *)
struct SchedulerBackendClient {
    let baseURL = URL(string: "http://127.0.0.1:5001")!

    func fetchNextUpcoming() async throws -> AppointmentDTO {
        var request = URLRequest(url: baseURL.appendingPathComponent("query"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: ["action": "next_upcoming"])
        let (data, _) = try await URLSession.shared.data(for: request)
        let decoded = try JSONDecoder().decode(NextUpcomingDTO.self, from: data)
        guard let appt = decoded.appointment else {
            throw URLError(.cannotDecodeContentData)
        }
        return appt
    }

    func createAppointment(title: String, date: String, startTime: String, endTime: String, location: String?) async throws -> AppointmentDTO {
        var body: [String: Any] = [
            "action": "create",
            "title": title,
            "date": date,
            "start_time": startTime,
            "end_time": endTime,
        ]
        if let location = location {
            body["location"] = location
        }
        var request = URLRequest(url: baseURL.appendingPathComponent("query"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, _) = try await URLSession.shared.data(for: request)
        return try JSONDecoder().decode(AppointmentDTO.self, from: data)
    }
}

struct NextUpcomingDTO: Codable {
    let appointment: AppointmentDTO?
}

struct AppointmentDTO: Codable {
    let id: Int
    let date: String
    let start_time: String?
    let end_time: String?
    let title: String?
    let description: String?
    let location: String?
}
