import Foundation
import CoreSpotlight
import Shared

let backendURL = ProcessInfo.processInfo.environment["BACKEND_URL"]
    .flatMap(URL.init(string:))
    ?? URL(string: "http://127.0.0.1:5001")!

@main
struct SpotlightIndex {
    static func main() async {
        let args = CommandLine.arguments
        let mode = args.dropFirst().first ?? "--all"
        
        let client = BackendClient(baseURL: backendURL)
        
        switch mode {
        case "--all":
            await indexAll(client: client)
        case "--clear":
            await clearIndex()
        default:
            print("Usage: spotlight-index [--all | --clear]")
            exit(1)
        }
    }
    
    static func indexAll(client: BackendClient) async {
        print("[Spotlight] Fetching appointments...")
        do {
            let appointments = try await client.fetchAllAppointments()
            var items: [CSSearchableItem] = []
            
            for appt in appointments {
                let attributeSet = CSSearchableItemAttributeSet(contentType: .calendarEvent)
                attributeSet.title = appt.displayTitle
                attributeSet.contentDescription = [
                    appt.description,
                    appt.location,
                    appt.date,
                    [appt.start_time, appt.end_time].compactMap { $0 }.joined(separator: " - ")
                ].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " • ")
                
                attributeSet.startDate = appt.startDate
                attributeSet.endDate = appt.endDate
                attributeSet.allDay = NSNumber(value: appt.is_all_day ?? false)
                attributeSet.textContent = [appt.location, appt.notes].compactMap { $0 }.joined(separator: "\n")
                
                // Support Spotlight deep-linking back to the app
                attributeSet.relatedUniqueIdentifier = "scheduler-ai://appointment/\(appt.id)"
                
                let item = CSSearchableItem(
                    uniqueIdentifier: "appointment-\(appt.id)",
                    domainIdentifier: "com.yourco.schedulerai.appointments",
                    attributeSet: attributeSet
                )
                items.append(item)
            }
            
            let index = CSSearchableIndex.default()
            try await index.indexSearchableItems(items)
            print("[Spotlight] Indexed \(items.count) appointments.")
        } catch {
            print("[Spotlight] Indexing failed: \(error)")
        }
    }
    
    static func clearIndex() async {
        print("[Spotlight] Clearing index...")
        do {
            let index = CSSearchableIndex.default()
            try await index.deleteSearchableItems(withDomainIdentifiers: ["com.yourco.schedulerai.appointments"])
            print("[Spotlight] Index cleared.")
        } catch {
            print("[Spotlight] Clear failed: \(error)")
        }
    }
}
