# Security & Privacy Policy

## Design Guarantees

Ghost Macro Recorder is built to operate strictly as a user-initiated local desktop automation utility:

- **100% Offline**: No network sockets, HTTP requests, analytics, telemetry, or remote updates.
- **Official Win32 Hotkey API (`RegisterHotKey`)**: Global hotkeys (`F9`, `F10`, `F12`, etc.) use Windows `RegisterHotKey` / `WM_HOTKEY` rather than an always-on low-level keyboard hook (`WH_KEYBOARD_LL`), so general typing is never monitored when idle.
- **Explicit Recording & Visual Indicators**: Mouse/keyboard listeners are active **only** while the user has explicitly started a recording session, reflected in both the main UI status bar and the system tray icon.
- **Target-Window Isolation**: In `Target Window Only` scope, a target window must be selected before recording starts, and input from other applications is ignored.
- **Sensitive & Password Window Exclusion**: The recorder automatically skips OS security/credential prompts (`consent.exe`, `CredentialUIBroker.exe`, `LockApp.exe`, `LogonUI.exe`), password-manager apps, and focused Win32 `ES_PASSWORD` controls.
- **No Privilege Escalation or Security Bypass**: The app respects Windows User Interface Privilege Isolation (UIPI), UAC, and Smart App Control boundaries and never attempts to elevate itself or bypass OS security policies.
- **Validated Local Persistence**: Macro `.json` files are only written when explicitly saved by the user and are schema-validated (file size, event count, event type allowlist, and numeric bounds) on load.

## Reporting a Vulnerability

If you discover a security issue, please open a private security advisory on the project's GitHub repository rather than posting exploit details in public issues.

