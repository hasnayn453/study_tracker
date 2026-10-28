# Study Tracker

Cross-platform (Windows & macOS) Python desktop application that monitors
student study sessions: tracks active working time, desktop/app usage,
idle time, desk presence (webcam), fires real-time alerts, and generates
daily progress reports.

## Architecture

```
study_tracker/
├── main.py            # entry point: wires everything together
├── config.py          # config loader (config.json) with defaults
├── storage.py         # encrypted SQLite store (Fernet at-rest encryption)
├── idle.py            # cross-platform idle-time detection
├── monitor_screen.py  # Module 1: window/app usage + idle + screenshots
├── monitor_webcam.py  # Module 2: webcam presence detection (OpenCV/Haar or MediaPipe)
├── alert.py           # Module 3: Telegram / Discord / SMTP alerts
├── reporter.py        # Module 4: daily Markdown/JSON/CSV reports + email/S3
├── tray_app.py        # background system tray UI (no main window)
├── requirements.txt   # Python dependencies
├── build.spec         # PyInstaller spec (.exe / .app)
└── config.example.json# configuration template
```

## Features

1. **Activity & screen monitoring**
   - Active window title + application name
   - Per-app usage duration, classified productive vs. non-productive
   - System idle time (keyboard/mouse inactivity)
   - Optional low-res compressed screenshots every 5 minutes while active
2. **Webcam presence detection** (local, no cloud)
   - Haar cascades (default, lightweight) or MediaPipe (optional)
   - Alerts if absent from desk > 3 minutes (configurable)
3. **Real-time alerting**
   - Telegram Bot API, Discord webhook, or SMTP email
   - Timestamp + status in every alert; per-kind cooldown to avoid spam
4. **Daily reporting & analytics**
   - Active/idle time, app breakdown, presence compliance rate
   - Markdown + JSON + CSV reports in `reports/`
   - Optional email delivery and/or AWS S3 upload

## Privacy & security

- All data stays local by default.
- The SQLite database is encrypted at rest with Fernet (AES) using a key
  stored in `config.json`. The plaintext DB only exists while the app runs;
  on shutdown it is re-encrypted to `study_tracker.db.enc`.
- No user data is transmitted unless you configure a webhook/email/S3 bucket.
- Screenshots are low-resolution (640x360 max) JPEG at quality 50.

> **Note:** For a production deployment, move the encryption key into the OS
> keychain (Windows Credential Locker / macOS Keychain) instead of
> `config.json`.

## Quick start

### 1. Create a virtual environment and install dependencies

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate
pip install -r study_tracker/requirements.txt

# macOS
python3 -m venv .venv
source .venv/bin/activate
pip install -r study_tracker/requirements.txt
pip install -r study_tracker/requirements-mac.txt   # optional: accurate idle detection
```

### 2. Configure

Copy the example config and edit it:

```bash
cp study_tracker/config.example.json study_tracker/config.json
```

Then set at least one alert channel (Telegram / Discord / email) and the
productive-app keywords you care about.

#### Telegram Bot setup
1. Message [@BotFather](https://t.me/botfather) on Telegram → `/newbot`
   → copy the **bot token**.
2. Send a message to your bot, then visit
   `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy the `chat.id`.
3. Paste both into `config.json` under `alerts.telegram`.

#### Discord webhook
1. In Discord: Server Settings → Integrations → Webhooks → New Webhook → copy
   URL into `alerts.discord.webhook_url`.

#### Email (SMTP)
Fill `alerts.email`. For Gmail use an **App Password**, not your account
password, and enable 2FA first.

### 3. Run

```bash
python study_tracker/main.py
```

A tray icon appears; monitoring starts immediately. Right-click the tray
icon to stop monitoring, generate a report now, or exit.

## Permissions (macOS)

macOS requires explicit user permission for:

| Permission | Purpose | System Setting |
|---|---|---|
| Camera | Webcam presence detection | Privacy & Security → Camera |
| Screen Recording | Screenshots + active window | Privacy & Security → Screen Recording |
| Accessibility | Active window title (pygetwindow) | Privacy & Security → Accessibility |

On a frozen `.app` bundle you should also add the `NS*` usage-description
keys (see `build.spec`) and codesign the app so the system prompts the
user rather than silently denying access.

## Build a standalone executable

Install PyInstaller:

```bash
pip install pyinstaller
```

### Windows (.exe)

```bash
cd study_tracker
pyinstaller build.spec --name StudyTracker --distpath dist/win --windowed
```

Output: `dist/win/StudyTracker/StudyTracker.exe` (one-folder). For a
single file use `--onefile` (slower startup; not recommended with
OpenCV/MediaPipe).

### macOS (.app)

```bash
cd study_tracker
pyinstaller build.spec --name StudyTracker --distpath dist/mac --windowed
```

Output: `dist/mac/StudyTracker.app`.

Codesign (required for camera/screen permissions on macOS):

```bash
codesign --sign "Developer ID Application: <TEAM_ID>" \
         --entitlements entitlements.plist \
         dist/mac/StudyTracker.app
```

## Configuration reference

| Section | Key | Default | Description |
|---|---|---|---|
| encryption | key | null | Auto-generated Fernet key |
| screen_monitoring | poll_interval | 5 | Seconds between active-window checks |
| screen_monitoring | screenshot_interval | 300 | Seconds between screenshots |
| screen_monitoring | productive_keywords | [...] | Keywords that mark an app as productive |
| idle_detection | threshold_seconds | 300 | Idle seconds before counting as idle |
| webcam | absence_threshold_seconds | 180 | Continuous absence seconds before alert |
| webcam | face_detector | haar | `haar` or `mediapipe` |
| alerts | cooldown_seconds | 60 | Minimum seconds between same-kind alerts |
| reporting | daily_report_hour | 23 | Hour for automatic daily report |
| reporting | daily_report_minute | 0 | Minute for automatic daily report |
| reporting | email_report | false | Email the markdown report daily |

## Data locations

All relative to the app folder (next to the executable/script):

- `data/study_tracker.db` + `data/study_tracker.db.enc` — encrypted database
- `data/screenshots/` — captured screenshots
- `reports/` — daily Markdown/JSON/CSV reports
- `config.json` — user configuration

## Disclaimer

This is a personal productivity / parental-awareness tool. Use it only on
devices you own or have explicit permission to monitor. It is not a
substitute for parental-control software, and it does not record audio or
keystrokes.
