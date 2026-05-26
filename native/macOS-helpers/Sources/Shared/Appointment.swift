import Foundation

public struct Appointment: Codable, Identifiable {
    public let id: Int
    public let date: String
    public let start_time: String?
    public let end_time: String?
    public let description: String?
    public let title: String?
    public let location: String?
    public let notes: String?
    public let recurrence_rule: String?
    public let tentative: Bool?
    public let is_all_day: Bool?
    public let external_id: String?
    
    public init(
        id: Int,
        date: String,
        start_time: String? = nil,
        end_time: String? = nil,
        description: String? = nil,
        title: String? = nil,
        location: String? = nil,
        notes: String? = nil,
        recurrence_rule: String? = nil,
        tentative: Bool? = nil,
        is_all_day: Bool? = nil,
        external_id: String? = nil
    ) {
        self.id = id
        self.date = date
        self.start_time = start_time
        self.end_time = end_time
        self.description = description
        self.title = title
        self.location = location
        self.notes = notes
        self.recurrence_rule = recurrence_rule
        self.tentative = tentative
        self.is_all_day = is_all_day
        self.external_id = external_id
    }
    
    public var displayTitle: String {
        title ?? description ?? "Untitled"
    }
    
    public var startDate: Date? {
        guard let startTime = start_time else { return nil }
        return Appointment.parseDateTime(date: date, time: startTime)
    }
    
    public var endDate: Date? {
        guard let endTime = end_time else { return nil }
        return Appointment.parseDateTime(date: date, time: endTime)
    }
    
    private static func parseDateTime(date: String, time: String) -> Date? {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone.current
        formatter.dateFormat = "yyyy-MM-dd HH:mm:ss"
        return formatter.date(from: "\(date) \(time)")
    }
}

public struct AppointmentListResponse: Codable {
    public let appointments: [Appointment]?
}

public struct NextUpcomingResponse: Codable {
    public let appointment: Appointment?
}
