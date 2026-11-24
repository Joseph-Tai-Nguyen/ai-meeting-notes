# Packaging (roadmap P4)

Today the app runs from a Python virtualenv (`scripts/setup.*`). To ship installers:

## Windows

- PyInstaller one-folder build of `meeting_notes.cli:main` with `--add-data src/meeting_notes/web;meeting_notes/web`
  and `--add-data src/meeting_notes/prompts;meeting_notes/prompts`.
- Include the `vosk` native DLLs (PyInstaller hook: `--collect-all vosk`).
- Ship without models and download them on first run (`scripts/download_models.py` logic), or bundle the small English model.
- Optional: an Inno Setup or MSIX installer, plus a Start-menu shortcut that runs `meeting-notes --window`.

## macOS

- PyInstaller or py2app `.app` bundle. **Info.plist must contain**:
  - `NSMicrophoneUsageDescription`: "Transcribes your meetings on this Mac."
  - `NSSpeechRecognitionUsageDescription`: "Uses Apple's on-device speech recognition to transcribe meetings."
- Sign with a Developer ID and notarize, otherwise microphone and speech permissions are unreliable.
- These keys are what make the experimental `macos` engine work. A bare `python` from Terminal may be
  killed when it asks for speech-recognition permission.
- Future: bundle a small Swift ScreenCaptureKit helper for system audio (P5) and stream PCM to the app over stdout.
