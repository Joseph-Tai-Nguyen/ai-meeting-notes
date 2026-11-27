# Requirements

Product requirements, the Notion AI Meeting Notes feature mapping, and status.
(Python package dependencies are in `pyproject.toml` / `requirements.txt`.)

Status legend: ✅ done · 🧪 experimental · 🟡 partial · ⬜ planned

## 1. Must-have: live transcription without AI services

| ID | Requirement | Status | Where |
|---|---|---|---|
| T1 | Live transcription on the local machine, with no network or AI API | ✅ | `transcription/` |
| T2 | Online meetings (Teams, Zoom, Meet, …) with **speakers or headphones**: capture mic + computer audio | ✅ Windows (WASAPI loopback) · 🟡 macOS (via BlackHole) | `audio/capture.py` |
| T3 | Offline / in-person meetings: microphone only | ✅ | mode `in_person` |
| T4 | Computer audio only (webinar, playback) | ✅ | mode `system` |
| T5 | Live partial text plus committed segments with timestamps | ✅ Vosk · 🟡 Whisper (per sentence) | `LiveSession` |
| T6 | Speaker labels: "Me" vs "Others" by source; rename speakers afterwards | ✅ | `session.py`, `store.rename_speaker` |
| T7 | Pause / resume / stop; continue a meeting later on the same timeline | ✅ | `LiveSession` |
| T8 | Use built-in OS speech engines | ✅ Windows SAPI (en-US verified) · 🧪 macOS Speech | `windows_engine.py`, `macos_engine.py` |
| T9 | Multiple languages (en, vi, de, fr, es, ja, zh, …); auto-detect with Whisper | ✅ | settings, `download_models.py` |
| T10 | Transcribe an existing recording (.wav) | ✅ | `meeting-notes transcribe` |
| T11 | Audio level meters to confirm capture works | ✅ | UI |
| T12 | Crash-safe: transcript survives an app crash | ✅ | append-only `transcript.jsonl` |

## 2. Note taking

| ID | Requirement | Status |
|---|---|---|
| N1 | Free-form notes beside the live transcript, autosaved | ✅ |
| N2 | ★ Highlight a moment during the meeting (optional label) | ✅ |
| N3 | Edit transcript lines inline | ✅ |
| N4 | Meeting title and attendees; created from a calendar event | ✅ |
| N5 | Consent reminder and a "participants informed" flag | ✅ |
| N6 | Full-text search across all meetings (offline) | ✅ |
| N7 | Tags and folders | 🟡 tags stored, no UI yet |

## 3. AI analysis (optional, after the meeting)

| ID | Requirement | Status |
|---|---|---|
| A1 | Summary with templates: general, standup, 1:1, sales call, interview, lecture, brainstorm, project review; user-defined templates | ✅ |
| A2 | Action items with owners and due dates | ✅ |
| A3 | Decisions | ✅ |
| A4 | Follow-up email draft | ✅ |
| A5 | Draft a document (PRD, proposal, strategy…) from the meeting | ✅ |
| A6 | Q&A about one meeting, with timestamps | ✅ |
| A7 | Q&A across all meetings (keyword retrieval + citations) | ✅ |
| A8 | Infer who the speakers are | ✅ |
| A9 | Providers: Gemini API key, Antigravity CLI (`agy`, Google AI plan), Claude Code fallback; order configurable | ✅ |
| A10 | Very long meetings: map-reduce condensation | ✅ |
| A11 | Output language selectable | ✅ |
| A12 | Streaming AI output in the UI | ⬜ |
| A13 | Semantic (embedding) search for cross-meeting Q&A | ⬜ |

## 4. Data, export, backup

| ID | Requirement | Status |
|---|---|---|
| D1 | Plain-text storage (JSON / JSONL / Markdown), one folder per meeting | ✅ |
| D2 | Export a meeting: Markdown, text, SRT, JSON | ✅ |
| D3 | Backup everything to zip; restore (skip or overwrite existing) | ✅ |
| D4 | Delete goes to a recoverable trash folder | ✅ |
| D5 | Configurable data folder (`MEETING_NOTES_DATA_DIR`) | ✅ |
| D6 | Scheduled automatic backups to a chosen folder (e.g. OneDrive / iCloud) | ⬜ |

## 5. Integrations

| ID | Requirement | Status |
|---|---|---|
| I1 | Calendar: upcoming events from ICS links (Google, Outlook); detects Teams / Zoom / Meet links | ✅ (recurring events with the `calendar` extra) |
| I2 | Reminder notification before a calendar meeting to start notes | ⬜ |
| I3 | Auto-detect that a Teams / Zoom call started and offer to record | ⬜ |
| I4 | Send recap to Slack / email (opt-in, with confirmation) | ⬜ (copy and `mailto` workaround today) |
| I5 | Export to Notion / Google Docs | ⬜ |

## 6. Platform & packaging

| ID | Requirement | Status |
|---|---|---|
| P1 | Windows 10/11 | ✅ |
| P2 | macOS 13+ | 🟡 (mic ✅, system audio via BlackHole, native engine needs a packaged app) |
| P3 | Native window (pywebview) | ✅ optional |
| P4 | One-click installers (PyInstaller / signed .app) | ⬜ see docs/packaging.md |
| P5 | macOS ScreenCaptureKit system-audio capture (no BlackHole) | ⬜ |
| P6 | Tray icon / global hotkey for Start / Stop / Highlight | ⬜ |

## 7. Non-functional

- **Privacy**: audio is never stored, the server binds to localhost, and AI calls happen only on user action and send only text.
- **Performance**: transcription must keep up with real time on a typical laptop CPU. Vosk small models are the light default. With Whisper on CPU, choose `base` or `small` (or use a GPU). Not yet benchmarked: add measurements here.
- **Reliability**: one recognizer thread per source; a device error on one source does not stop the others.
- **Accessibility**: keyboard reachable controls, works in light and dark mode.
- **Testability**: the full suite runs without audio hardware, network or AI (`pytest`).

## 8. Roadmap (suggested order)

1. P4 packaging (PyInstaller for Windows, signed `.app` for macOS with the Info.plist privacy keys) → unblocks the `macos` engine.
2. P5 ScreenCaptureKit audio helper for macOS.
3. I2/I3 meeting reminders and call detection.
4. A12 streaming AI output, A13 local embeddings search.
5. I4/I5 opt-in sharing integrations.
6. Speaker diarization inside the "Others" stream (offline, e.g. pyannote or sherpa-onnx), as an optional extra.
