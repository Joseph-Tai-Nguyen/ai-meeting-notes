# AI Meeting Notes

Local-first live transcription and meeting notes for **Windows and macOS**,
inspired by Notion AI Meeting Notes.

- **Live transcription with no AI service and no internet.** Speech-to-text runs
  on your computer (Vosk, Whisper, or the speech engine built into the OS).
- **Works with any meeting app.** Teams, Zoom, Google Meet, Webex, Slack huddles:
  the app captures your microphone *and* the computer's audio output, so it works
  whether you use speakers or headphones. Your voice is labelled **Me** and the
  remote side **Others**.
- **In-person meetings too.** Microphone-only mode for a meeting in a room.
- **Your notes next to the transcript.** Type notes while you listen, mark
  moments with ★ Highlight, fix words, rename speakers.
- **AI analysis afterwards, only when you ask.** Summaries in several templates,
  action items, decisions, follow-up email, a draft PRD or proposal, Q&A on one
  meeting or across all meetings. It uses **Gemini** (your Google AI plan through the
  Gemini CLI, or a Gemini API key) and falls back to **Claude Code**.
- **Plain text storage.** JSON, JSONL and Markdown files in one folder per meeting. Export as
  Markdown, text, SRT subtitles or JSON, and back everything up as a zip. Audio is never saved.

## Quick start

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

```powershell
.\.venv\Scripts\meeting-notes
```

macOS:

```bash
bash scripts/setup.sh && .venv/bin/meeting-notes
```

The setup script creates `.venv`, installs the app, copies `.env.example` to
`.env`, downloads the small English Vosk model (~40 MB) and runs
`meeting-notes doctor`. The app then opens at <http://127.0.0.1:8765>
(add `--window` for a native window: `pip install -e ".[desktop]"`).

Manual install:

```bash
python -m venv .venv && .venv/Scripts/activate        # macOS: source .venv/bin/activate
pip install -e ".[audio,vosk,calendar,dev]"
python scripts/download_models.py vosk en              # or: vosk vi / vosk de ...
meeting-notes doctor
meeting-notes
```

### macOS: capturing Teams / Zoom audio

macOS has no system-audio loopback that a Python app can use without extra
software. Install the free virtual device **BlackHole** (`brew install blackhole-2ch`),
create a Multi-Output Device (your speakers or headphones + BlackHole) and pick
BlackHole as **Computer-audio device** in Settings. Step by step:
[docs/audio-capture.md](docs/audio-capture.md). Microphone-only (in-person) mode needs none of this.

## Using it

1. **+ New meeting**, or click an upcoming calendar event (set an ICS link in Settings).
2. Choose the audio source:
   - **Online meeting**: microphone + computer audio ("Me" / "Others")
   - **In-person**: microphone only
   - **Computer audio only**: webinars, or a recording playing on the computer
3. Pick the engine and language, then press **● Start**. **Pause**, **Resume**,
   **★ Highlight** and **■ Stop** work while recording. Press Start again to continue later.
4. Type notes in the **Notes** tab during the meeting.
5. Afterwards, in **Summary**, choose what to generate and press **Generate**.
   Use **Ask** for questions about this meeting, or **Ask across meetings** in the sidebar.
6. **Export** a meeting, or **Settings › Download backup** for everything.

Let participants know a meeting is being transcribed. The app shows a consent
reminder and records that you confirmed it.

### Transcription engines (all offline)

| Engine | Platforms | Notes |
|---|---|---|
| `vosk` (default) | Win / Mac / Linux | Real-time streaming with live partial text, low CPU. Small model per language (`scripts/download_models.py vosk <lang>`) |
| `whisper` | Win / Mac / Linux | faster-whisper. Best accuracy, 99 languages, auto-detect. Text appears after each sentence. `pip install -e ".[whisper]"` |
| `windows_sapi` | Windows | Built-in Windows speech recognizer. No model download; text appears after each pause; accuracy below Whisper. `pip install -e ".[windows]"` (included by `setup.ps1`) |
| `macos` | macOS | Apple Speech framework, on-device. Needs the packaged app for privacy permissions (experimental) |
| `mock` | all | Test engine: marks where speech was detected, with no recognition |

### AI providers (optional)

Tried in order, and the next one is used if a provider is missing or fails. Change the order in Settings.

| Provider | Setup |
|---|---|
| `gemini_api` | `GEMINI_API_KEY=...` in `.env` ([AI Studio key](https://aistudio.google.com/apikey)) |
| `gemini_cli` | `npm install -g @google/gemini-cli`, run `gemini` once and sign in with the Google account that has your Google AI plan |
| `claude_code` | Install [Claude Code](https://docs.claude.com/en/docs/claude-code) and sign in (`claude`) |

Only text (transcript, notes and title) is sent to the provider you choose, and only when you press Generate or Ask.

## Command line

```text
meeting-notes                         start the app
meeting-notes doctor                  check audio devices, engines, AI providers
meeting-notes record --mode online    live transcription in the terminal (Ctrl+C stops)
meeting-notes transcribe call.wav     transcribe a .wav recording
meeting-notes list
meeting-notes analyze <id> --kind summary --template standup [--provider gemini_cli]
meeting-notes ask "What did we decide about pricing?" [--meeting <id>]
meeting-notes export <id> --format md|txt|srt|json -o file
meeting-notes backup -o backup.zip  /  meeting-notes restore backup.zip
```

## Data

Default folder: `~/Documents/AIMeetingNotes` (override with `MEETING_NOTES_DATA_DIR`,
for example `./data` while developing).

```text
meetings/<id>/meeting.json        title, date, mode, attendees, highlights, AI metadata
meetings/<id>/transcript.jsonl    one segment per line, written live (safe if the app crashes)
meetings/<id>/transcript.md       readable transcript
meetings/<id>/notes.md            your notes
meetings/<id>/analysis/*.md       AI outputs (summary.md, action_items.md, qa.md, ...)
prompts/                          your own prompt templates (they override the built-in ones)
trash/                            deleted meetings (recoverable)
settings.json
```

## Development

```bash
pip install -e ".[audio,vosk,dev]"
pytest
ruff check src tests scripts
meeting-notes --data-dir ./data serve --no-browser
```

Project docs: [project_context.md](project_context.md) (what and why),
[requirements.md](requirements.md) (features and roadmap),
[docs/architecture.md](docs/architecture.md), [docs/api.md](docs/api.md),
[docs/audio-capture.md](docs/audio-capture.md), [docs/packaging.md](docs/packaging.md).
AI coding agents: [AGENTS.md](AGENTS.md) (shared rules), [CLAUDE.md](CLAUDE.md) (Claude Code),
[GEMINI.md](GEMINI.md) (Gemini CLI / Antigravity).

## License

GPL-3.0-or-later. See [LICENSE](LICENSE). This project is not affiliated with Notion.
