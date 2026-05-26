import WidgetKit
import SwiftUI

struct SchedulerWidgetView: View {
    var entry: SchedulerProvider.Entry

    @Environment(\.widgetFamily) var family

    var body: some View {
        if let appt = entry.appointment {
            appointmentView(appt)
        } else {
            emptyView
        }
    }

    @ViewBuilder
    private func appointmentView(_ appt: AppointmentWidgetModel) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Image(systemName: "calendar")
                    .foregroundColor(.accentColor)
                Text(appt.date)
                    .font(.caption)
                    .foregroundColor(.secondary)
                Spacer()
            }

            Text(appt.title)
                .font(family == .systemSmall ? .headline : .title3)
                .fontWeight(.semibold)
                .lineLimit(2)

            if !appt.time.isEmpty {
                Label(appt.time, systemImage: "clock")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }

            if let location = appt.location, !location.isEmpty {
                Label(location, systemImage: "mappin.and.ellipse")
                    .font(.caption2)
                    .foregroundColor(.secondary)
                    .lineLimit(1)
            }
        }
        .padding(.horizontal, family == .systemSmall ? 8 : 12)
        .padding(.vertical, family == .systemSmall ? 8 : 12)
    }

    private var emptyView: some View {
        VStack(spacing: 8) {
            Image(systemName: "calendar.badge.checkmark")
                .font(.largeTitle)
                .foregroundColor(.secondary)
            Text("No upcoming appointments")
                .font(.caption)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
        }
        .padding()
    }
}

// MARK: - Previews

#Preview(as: .systemSmall) {
    SchedulerWidgetView(
        entry: SchedulerEntry(
            date: Date(),
            appointment: AppointmentWidgetModel(
                id: 1,
                title: "Team Standup",
                date: "Today",
                time: "10:00",
                location: "Zoom"
            )
        )
    )
}

#Preview(as: .systemMedium) {
    SchedulerWidgetView(
        entry: SchedulerEntry(
            date: Date(),
            appointment: nil
        )
    )
}
