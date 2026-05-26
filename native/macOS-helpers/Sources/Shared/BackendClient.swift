import Foundation

public enum BackendClientError: Error {
    case invalidURL
    case httpError(Int, String)
    case decodingError(Error)
    case noData
}

public struct BackendClient {
    public let baseURL: URL
    
    public init(baseURL: URL) {
        self.baseURL = baseURL
    }
    
    public func fetchAppointments(action: String, params: [String: String] = [:]) async throws -> [Appointment] {
        let url = baseURL.appendingPathComponent("/query")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        var body: [String: Any] = ["action": action]
        for (key, value) in params {
            body[key] = value
        }
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw BackendClientError.noData
        }
        guard httpResponse.statusCode == 200 else {
            let bodyString = String(data: data, encoding: .utf8) ?? ""
            throw BackendClientError.httpError(httpResponse.statusCode, bodyString)
        }
        
        let result = try JSONDecoder().decode(AppointmentListResponse.self, from: data)
        return result.appointments ?? []
    }
    
    public func fetchAllAppointments() async throws -> [Appointment] {
        let calendar = Calendar.current
        let start = calendar.date(byAdding: .year, value: -1, to: Date())!
        let end = calendar.date(byAdding: .year, value: 2, to: Date())!
        
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        
        var all: [Appointment] = []
        var current = start
        while current <= end {
            let dateStr = formatter.string(from: current)
            let dayAppointments = try await fetchAppointments(action: "list_by_date", params: ["date": dateStr])
            all.append(contentsOf: dayAppointments)
            guard let next = calendar.date(byAdding: .day, value: 1, to: current) else { break }
            current = next
        }
        return all
    }
    
    public func fetchNextUpcoming() async throws -> Appointment? {
        let url = baseURL.appendingPathComponent("/query")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: ["action": "next_upcoming"])
        
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else {
            return nil
        }
        let result = try JSONDecoder().decode(NextUpcomingResponse.self, from: data)
        return result.appointment
    }
}
