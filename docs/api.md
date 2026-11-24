# Local API

Base URL `http://127.0.0.1:8765`. Every non-GET request needs the header `x-meeting-notes: 1`.
Interactive docs are at `/docs` (FastAPI).

| Method | Path | Body / query | Purpose |
|---|---|---|---|
| GET | `/api/status` | | engines, AI providers, templates, active session |
| GET | `/api/devices` | | microphones and computer-audio devices |
| GET / PUT | `/api/settings` | partial settings JSON | read / update settings.json |
| GET | `/api/calendar/upcoming` | | events from ICS feeds |
| GET | `/api/meetings` | `?q=` | list or full-text search |
| POST | `/api/meetings` | `{title, mode, language, attendees, calendar_event}` | create |
| GET | `/api/meetings/{id}` | | meeting + notes + segments + analyses |
| PATCH | `/api/meetings/{id}` | `{title, attendees, tags, consent_confirmed, mode, language}` | update |
| DELETE | `/api/meetings/{id}` | | move to trash |
| PUT | `/api/meetings/{id}/notes` | `{text}` | save notes |
| PATCH | `/api/meetings/{id}/segments/{seq}` | `{text?, speaker?}` | edit a line |
| POST | `/api/meetings/{id}/speakers/rename` | `{old, new}` | rename a speaker everywhere |
| POST | `/api/meetings/{id}/record/start` | `{mode?, engine?, language?, file_path?}` | start / continue |
| POST | `/api/meetings/{id}/record/pause` · `resume` · `stop` | | control |
| POST | `/api/meetings/{id}/highlight` | `{label}` | mark the current moment |
| WS | `/ws/meetings/{id}` | | live events (see below) |
| POST | `/api/meetings/{id}/analyze` | `{kind, template?, provider?, doc_type?}` | AI analysis |
| POST | `/api/meetings/{id}/ask` | `{question, provider?}` | Q&A on one meeting |
| POST | `/api/ask` | `{question, provider?}` | Q&A across meetings |
| GET | `/api/meetings/{id}/export` | `?format=md\|txt\|srt\|json` | download |
| GET | `/api/backup` | | zip of all data |
| POST | `/api/restore` | raw zip body, `?overwrite=true` | restore |

WebSocket events:

```json
{"type": "status",  "status": "recording", "elapsed": 12.3}
{"type": "partial", "source": "system", "speaker": "Others", "text": "so the plan is"}
{"type": "segment", "segment": {"seq": 4, "start": 10.2, "end": 12.9, "speaker": "Others", "text": "So the plan is to ship Friday.", "source": "system", "edited": false}}
{"type": "level",   "source": "mic", "rms": 0.021}
{"type": "error",   "source": "system", "message": "No loopback device for output: ..."}
```
