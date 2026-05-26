# Siri Shortcuts Integration (App Intents)

These files provide Siri Shortcuts support for Scheduler AI.

## Prerequisites
- macOS 14.0+
- Xcode 15+
- Apple Developer account (free personal team works for local testing)

## Setup Steps

1. **Open the Scheduler AI Xcode project**
   After building the app once (`npm run electron:build`), you'll find the Xcode project at:
   ```
   frontend/dist/mac-universal/Scheduler AI.app
   ```
   Or open the `.app` bundle directly in Xcode: right-click → Show Package Contents.

2. **Add an App Intents Extension target**
   - File → New → Target → **App Intents Extension**
   - Product Name: `SchedulerSiriIntents`
   - Starting Point: **None**
   - Make sure "Embed in Application" points to **Scheduler AI**

3. **Copy the Swift files**
   - Drag `SchedulerIntents.swift` and `IntentHandler.swift` into the new target
   - Check "Copy items if needed" and make sure the `SchedulerSiriIntents` target is selected

4. **Add the Info.plist**
   Create `SchedulerSiriIntents/Info.plist`:
   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
   <plist version="1.0">
   <dict>
       <key>NSExtension</key>
       <dict>
           <key>NSExtensionPointIdentifier</key>
           <string>com.apple.appintents</string>
       </dict>
   </dict>
   </plist>
   ```

5. **Build & Sign**
   - Select your personal team in Signing & Capabilities
   - Build (Cmd+B)
   - The extension will be embedded in the `.app` bundle

6. **Test in Shortcuts app**
   - Open the Shortcuts app on your Mac
   - Create a new shortcut
   - Search for "Next Appointment" or "Create Appointment"
   - The Scheduler AI actions should appear

## Available Intents

| Intent | Example Phrase |
|--------|---------------|
| `NextAppointmentIntent` | "Hey Siri, what's my next meeting?" |
| `CreateAppointmentIntent` | "Hey Siri, schedule a dentist appointment on Friday at 2pm" |
