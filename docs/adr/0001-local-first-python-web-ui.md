# ADR 0001: Local-first Python backend with a local web UI

- Status: accepted
- Date: 2026-11-24

## Context

The app must transcribe live on Windows and macOS with no AI service or internet, capture
both microphone and meeting-app audio, store data as text, and later run optional AI
analysis with Gemini (Google AI plan) or Claude Code. It will be developed mostly with
coding agents (Claude Code, Antigravity / Gemini).

## Decision

- Python backend: the offline speech engines (Vosk, faster-whisper) and OS bindings
  (pythonnet for SAPI, pyobjc for Apple Speech) are Python-native, and `soundcard`
  provides WASAPI loopback on Windows.
- UI: plain HTML, CSS and JS served by FastAPI on 127.0.0.1, optionally in a native window via pywebview.
  No JS build step.
- Separate audio streams per source instead of mixing them, to get "Me / Others" labels for free.
- Plain-text files instead of a database.
- AI through a provider router (Gemini API, Gemini CLI, Claude Code) that the user orders.

## Consequences

- Easy to run, test and change. The whole suite runs headless.
- Installers need PyInstaller or py2app work (docs/packaging.md).
- macOS system audio needs BlackHole until a ScreenCaptureKit helper exists.
- Electron or Tauri remain possible later, reusing the same local API.
