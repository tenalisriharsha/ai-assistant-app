# Today Widget / Notification Center Widget

These files provide a macOS WidgetKit extension for Scheduler AI.

## Features
- Shows your **next upcoming appointment** on the desktop / Notification Center
- Supports **Small** and **Medium** widget sizes
- Auto-refreshes every 15 minutes
- Deep-links back to the Scheduler AI app

## Prerequisites
- macOS 14.0+
- Xcode 15+
- Apple Developer account (free personal team works for local testing)

## Setup Steps

1. **Open the Scheduler AI Xcode project**
   After building the app once (`npm run electron:build`), you'll find:
   ```
   frontend/dist/mac-universal/Scheduler AI.app
   ```

2. **Add a Widget Extension target**
   - File → New → Target → **Widget Extension**
   - Product Name: `SchedulerWidget`
   - Make sure "Include Configuration Intent" is **unchecked**
   - Make sure "Embed in Application" points to **Scheduler AI**

3. **Copy the Swift files**
   - Drag `SchedulerWidget.swift` and `SchedulerWidgetView.swift` into the new target
   - Check "Copy items if needed" and select the `SchedulerWidget` target

4. **Add the Info.plist**
   Create `SchedulerWidget/Info.plist`:
   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
   <plist version="1.0">
   <dict>
       <key>CFBundleDevelopmentRegion</key>
       <string>$(DEVELOPMENT_LANGUAGE)</string>
       <key>CFBundleDisplayName</key>
       <string>SchedulerWidget</string>
       <key>CFBundleExecutable</key>
       <string>$(EXECUTABLE_NAME)</string>
       <key>CFBundleIdentifier</key>
       <string>$(PRODUCT_BUNDLE_IDENTIFIER)</string>
       <key>CFBundleInfoDictionaryVersion</key>
       <string>6.0</string>
       <key>CFBundleName</key>
       <string>$(PRODUCT_NAME)</string>
       <key>CFBundlePackageType</key>
       <string>XPC!</string>
       <key>CFBundleShortVersionString</key>
       <string>1.0</string>
       <key>CFBundleVersion</key>
       <string>1</string>
       <key>NSExtension</key>
       <dict>
           <key>NSExtensionPointIdentifier</key>
           <string>com.apple.widgetkit-extension</string>
       </dict>
   </dict>
   </plist>
   ```

5. **Build & Run**
   - Select your personal team in Signing & Capabilities for both the main app and widget target
   - Build (Cmd+B)
   - The widget will be embedded in the `.app` bundle

6. **Add to Notification Center**
   - Click the date/time in the menu bar
   - Click "Edit Widgets"
   - Find "Scheduler AI" in the list
   - Add the "Next Appointment" widget
