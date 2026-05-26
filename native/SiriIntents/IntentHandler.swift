import AppIntents

// MARK: - App Intents Extension Entry Point

// This file registers the intents with the system.
// When you add an App Intents Extension target in Xcode, this becomes the
// IntentHandler that the system calls.

@available(macOS 14.0, *)
class SchedulerIntentProvider: AppIntentProvider {
    override func intents() -> [any AppIntent.Type] {
        return [
            NextAppointmentIntent.self,
            CreateAppointmentIntent.self,
        ]
    }
}
