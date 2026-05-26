# Xcode Setup Guide — Manual Steps You Must Do

This guide covers everything that **cannot** be automated from VS Code / terminal and requires you to use Xcode's GUI.

---

## Step 1: Create a Free Apple Developer Signing Identity

Before the packaged app will run on macOS Sequoia, it must be signed.

### 1.1 Open Xcode
```bash
open -a Xcode
```

### 1.2 Add your Apple ID
- Xcode → Settings → **Accounts** tab (or press `Cmd + ,` then click Accounts)
- Click **+** → Add Apple ID
- Sign in with your Apple ID

### 1.3 Create a certificate
- In the Accounts list, select your Apple ID
- Click **Manage Certificates...**
- Click **+** → **Apple Development**
- Close the window

### 1.4 Verify it worked
Run this in Terminal:
```bash
security find-identity -v -p codesigning
```
You should see something like:
```
  1) ABC123... "Apple Development: your@email.com (TEAMID)"
     1 valid identities found
```

---

## Step 2: Build the Packaged App (from Terminal)

Once you have a signing identity:

```bash
cd /Users/tenalisriharsha/PycharmProjects/ai-assistant-app/frontend
npm run electron:build
```

This will:
1. Build the Swift native helpers (Calendar sync, Spotlight)
2. Build the React frontend
3. Package everything into `Scheduler AI.app`
4. Sign the app and strip quarantine

The output will be at:
```
frontend/dist/mac-universal/Scheduler AI.app
```

### If the build fails with signing errors
Run the setup helper:
```bash
./scripts/setup-macos-signing.sh
```

---

## Step 3: Grant Calendar Permission (One-Time)

The first time you click **"📅 Sync Calendar"**, macOS will ask for permission.

1. Click **"Allow"** in the system dialog
2. If you miss it, go to:
   - **System Settings → Privacy & Security → Calendars**
   - Find **Scheduler AI** and turn it **ON**

---

## Step 4: Add Siri Shortcuts (Optional)

### 4.1 Open the built app in Xcode
```bash
open "frontend/dist/mac-universal/Scheduler AI.app"
```

Or right-click the `.app` → **Show Package Contents** → drag `Scheduler AI.app` onto the Xcode dock icon.

### 4.2 Add the App Intents Extension
- File → New → Target
- Select **App Intents Extension**
- Product Name: `SchedulerSiriIntents`
- Starting Point: **None**
- Make sure "Embed in Application" = **Scheduler AI**

### 4.3 Copy the Swift files
- In Finder, go to `native/SiriIntents/`
- Drag `SchedulerIntents.swift` and `IntentHandler.swift` into the Xcode project navigator under the `SchedulerSiriIntents` folder
- ✅ Check "Copy items if needed"
- ✅ Select the `SchedulerSiriIntents` target

### 4.4 Add Info.plist
- Right-click `SchedulerSiriIntents` folder in Xcode → New File → **Property List**
- Name it `Info.plist`
- Replace contents with:
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

### 4.5 Sign & Build
- Select your personal team in **Signing & Capabilities** for both targets
- Press **Cmd+B**

### 4.6 Test
- Open the **Shortcuts** app on your Mac
- Create a new shortcut
- Search for **"Next Appointment"**
- Run it

---

## Step 5: Add Today Widget (Optional)

### 5.1 Add the Widget Extension target
- File → New → Target
- Select **Widget Extension**
- Product Name: `SchedulerWidget`
- ❌ Uncheck "Include Configuration Intent"
- Make sure "Embed in Application" = **Scheduler AI**

### 5.2 Copy the Swift files
- In Finder, go to `native/TodayWidget/`
- Drag `SchedulerWidget.swift` and `SchedulerWidgetView.swift` into the Xcode project navigator under the `SchedulerWidget` folder
- ✅ Check "Copy items if needed"
- ✅ Select the `SchedulerWidget` target

### 5.3 Add Info.plist
- Right-click `SchedulerWidget` folder in Xcode → New File → **Property List**
- Name it `Info.plist`
- Replace contents with:
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

### 5.4 Sign & Build
- Select your personal team in **Signing & Capabilities** for both targets
- Press **Cmd+B**

### 5.5 Add to Notification Center
- Click the **date/time** in the menu bar
- Click **Edit Widgets**
- Find **Scheduler AI** in the list
- Drag the **"Next Appointment"** widget to your Notification Center

---

## Troubleshooting

### "Scheduler AI.app is damaged and can't be opened"
Run:
```bash
xattr -rd com.apple.quarantine "/Applications/Scheduler AI.app"
```

### "Calendar access denied"
System Settings → Privacy & Security → Calendars → Enable **Scheduler AI**

### Widget/Siri doesn't appear
- Make sure you selected your personal team in Signing & Capabilities
- The bundle ID must be unique (e.g., `com.yourco.schedulerai.widget`)
- Rebuild the app after adding extensions

### Spotlight search doesn't show appointments
- Click **🔍 Spotlight** button in the app header
- Or run in terminal:
  ```bash
  ./native/macOS-helpers/.build/debug/spotlight-index --all
  ```

### Calendar sync doesn't work
- Make sure backend is running on port 5001
- Grant Calendar permission (Step 3)
- Check logs: `~/Library/Application Support/scheduler-ai/backend.log`
