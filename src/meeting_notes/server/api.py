"""Local HTTP + WebSocket API (FastAPI). Binds to 127.0.0.1 only by default.

The web UI in ``meeting_notes/web`` talks to these endpoints; they are also a
convenient automation surface (see docs/api.md).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from meeting_notes import __version__
from meeting_notes.ai import TASKS, AIError
from meeting_notes.audio.devices import list_devices
from meeting_notes.calendar_ics import upcoming
from meeting_notes.context import AppContext
from meeting_notes.storage.export import EXPORT_FORMATS, backup_zip, export_meeting, restore_zip
from meeting_notes.storage.search import search
from meeting_notes.storage.store import NotFound, StoreError

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


# ------------------------------------------------------------------ schemas
class MeetingCreate(BaseModel):
    title: str = ""
    mode: str = "online"
    language: str | None = None
    attendees: list[str] = []
    tags: list[str] = []
    calendar_event: dict[str, Any] | None = None


class MeetingPatch(BaseModel):
    title: str | None = None
    attendees: list[str] | None = None
    tags: list[str] | None = None
    consent_confirmed: bool | None = None
    mode: str | None = None
    language: str | None = None


class NotesBody(BaseModel):
    text: str


class SegmentPatch(BaseModel):
    text: str | None = None
    speaker: str | None = None


class SpeakerRename(BaseModel):
    old: str
    new: str


class RecordStart(BaseModel):
    mode: str | None = None
    engine: str | None = None
    language: str | None = None
    file_path: str | None = None


class HighlightBody(BaseModel):
    label: str = ""


class AnalyzeBody(BaseModel):
    kind: str = "summary"
    template: str | None = None
    provider: str | None = None
    doc_type: str = ""


class AskBody(BaseModel):
    question: str
    provider: str | None = None


LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
CSRF_HEADER = "x-meeting-notes"


def create_app(ctx: AppContext, allowed_hosts: set[str] | None = None) -> FastAPI:
    sockets: dict[str, set[WebSocket]] = {}
    hosts = allowed_hosts or LOCAL_HOSTS

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        loop = asyncio.get_running_loop()

        def listener(meeting_id: str, event: dict) -> None:
            for ws in list(sockets.get(meeting_id, ())):
                asyncio.run_coroutine_threadsafe(_send(ws, event), loop)

        ctx.listeners.append(listener)
        try:
            yield
        finally:
            ctx.listeners.remove(listener)
            ctx.stop_session()

    app = FastAPI(title="AI Meeting Notes", version=__version__, lifespan=lifespan)
    app.state.ctx = ctx

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        # Host check blocks DNS-rebinding; the custom header on writes blocks
        # cross-site form posts from web pages open in your browser.
        host = (request.headers.get("host") or "").rsplit(":", 1)[0]
        if host not in hosts:
            return PlainTextResponse("forbidden host", status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get(CSRF_HEADER) != "1":
            return PlainTextResponse(f"missing {CSRF_HEADER} header", status_code=403)
        return await call_next(request)

    async def _send(ws: WebSocket, event: dict) -> None:
        try:
            await ws.send_json(event)
        except Exception:  # noqa: BLE001 - socket closed
            pass

    def _err(exc: Exception) -> HTTPException:
        if isinstance(exc, NotFound):
            return HTTPException(404, str(exc))
        return HTTPException(400, str(exc))

    # --------------------------------------------------------------- status
    @app.get("/api/status")
    def status() -> dict:
        s = ctx.session
        return {
            "version": __version__,
            "data_dir": str(ctx.data_dir),
            "engines": [e.info() for e in ctx.engines().values()],
            "ai_providers": ctx.router().status(),
            "summary_templates": ctx.prompts.summary_templates(),
            "analysis_kinds": TASKS,
            "export_formats": EXPORT_FORMATS,
            "session": {"meeting_id": s.meeting_id, "status": s.status, "elapsed": s.elapsed} if s else None,
        }

    @app.get("/api/devices")
    def devices() -> dict:
        return list_devices()

    @app.get("/api/settings")
    def get_settings() -> dict:
        return ctx.settings.to_dict()

    @app.put("/api/settings")
    def put_settings(patch: dict[str, Any]) -> dict:
        return ctx.settings_store.update(patch).to_dict()

    @app.get("/api/calendar/upcoming")
    def calendar() -> dict:
        return upcoming(ctx.settings.calendar_ics) if ctx.settings.calendar_ics else {"events": [], "errors": []}

    # ------------------------------------------------------------- meetings
    @app.get("/api/meetings")
    def list_meetings(q: str = "") -> list[dict]:
        if q.strip():
            return [{"id": h.meeting_id, "title": h.title, "created_at": h.created_at, "snippet": h.snippet}
                    for h in search(ctx.store, q)]
        return [{"id": m.id, "title": m.title, "created_at": m.created_at, "status": m.status,
                 "duration": m.duration, "mode": m.mode} for m in ctx.store.list()]

    @app.post("/api/meetings")
    def create_meeting(body: MeetingCreate) -> dict:
        lang = body.language or ctx.settings.transcription.language
        m = ctx.store.create(body.title, body.mode, language=lang, attendees=body.attendees,
                             tags=body.tags, calendar_event=body.calendar_event)
        return m.to_dict()

    @app.get("/api/meetings/{meeting_id}")
    def get_meeting(meeting_id: str) -> dict:
        try:
            m = ctx.store.get(meeting_id)
            return {
                "meeting": m.to_dict(),
                "notes": ctx.store.notes(meeting_id),
                "segments": [s.to_dict() for s in ctx.store.segments(meeting_id)],
                "analyses": ctx.store.analyses(meeting_id),
            }
        except StoreError as exc:
            raise _err(exc) from exc

    @app.patch("/api/meetings/{meeting_id}")
    def patch_meeting(meeting_id: str, body: MeetingPatch) -> dict:
        try:
            changes = {k: v for k, v in body.model_dump().items() if v is not None}
            return ctx.store.update(meeting_id, **changes).to_dict()
        except StoreError as exc:
            raise _err(exc) from exc

    @app.delete("/api/meetings/{meeting_id}")
    def delete_meeting(meeting_id: str) -> dict:
        s = ctx.session
        if s and s.meeting_id == meeting_id:
            raise HTTPException(409, "Stop the recording before deleting this meeting.")
        try:
            dest = ctx.store.delete(meeting_id)
            return {"trashed": True, "path": str(dest)}
        except StoreError as exc:
            raise _err(exc) from exc

    @app.put("/api/meetings/{meeting_id}/notes")
    def put_notes(meeting_id: str, body: NotesBody) -> dict:
        try:
            ctx.store.write_notes(meeting_id, body.text)
            return {"ok": True}
        except StoreError as exc:
            raise _err(exc) from exc

    @app.patch("/api/meetings/{meeting_id}/segments/{seq}")
    def patch_segment(meeting_id: str, seq: int, body: SegmentPatch) -> dict:
        try:
            return ctx.store.edit_segment(meeting_id, seq, body.text, body.speaker).to_dict()
        except StoreError as exc:
            raise _err(exc) from exc

    @app.post("/api/meetings/{meeting_id}/speakers/rename")
    def rename_speaker(meeting_id: str, body: SpeakerRename) -> dict:
        try:
            return {"renamed": ctx.store.rename_speaker(meeting_id, body.old, body.new)}
        except StoreError as exc:
            raise _err(exc) from exc

    # ------------------------------------------------------------ recording
    @app.post("/api/meetings/{meeting_id}/record/start")
    def record_start(meeting_id: str, body: RecordStart) -> dict:
        try:
            s = ctx.start_session(meeting_id, body.mode, body.engine, body.language, body.file_path)
            return {"status": s.status, "engine": s.engine.name, "language": s.language}
        except (RuntimeError, ValueError, StoreError) as exc:
            raise _err(exc) from exc

    def _active(meeting_id: str):
        s = ctx.session
        if not s or s.meeting_id != meeting_id:
            raise HTTPException(409, "This meeting is not recording.")
        return s

    @app.post("/api/meetings/{meeting_id}/record/pause")
    def record_pause(meeting_id: str) -> dict:
        s = _active(meeting_id)
        s.pause()
        return {"status": s.status}

    @app.post("/api/meetings/{meeting_id}/record/resume")
    def record_resume(meeting_id: str) -> dict:
        s = _active(meeting_id)
        s.resume()
        return {"status": s.status}

    @app.post("/api/meetings/{meeting_id}/record/stop")
    def record_stop(meeting_id: str) -> dict:
        s = _active(meeting_id)
        s.stop()
        return {"status": s.status, "duration": s.elapsed}

    @app.post("/api/meetings/{meeting_id}/highlight")
    def highlight(meeting_id: str, body: HighlightBody) -> dict:
        s = _active(meeting_id)
        return s.highlight(body.label).__dict__

    @app.websocket("/ws/meetings/{meeting_id}")
    async def ws_meeting(ws: WebSocket, meeting_id: str) -> None:
        origin = ws.headers.get("origin", "")
        origin_host = origin.split("://", 1)[-1].rsplit(":", 1)[0] if origin else ""
        if origin and origin_host not in hosts:
            await ws.close(code=1008)
            return
        await ws.accept()
        sockets.setdefault(meeting_id, set()).add(ws)
        s = ctx.session
        if s and s.meeting_id == meeting_id:
            await ws.send_json({"type": "status", "status": s.status, "elapsed": round(s.elapsed, 1)})
        try:
            while True:
                await ws.receive_text()  # keep-alive pings from the client
        except WebSocketDisconnect:
            pass
        finally:
            sockets.get(meeting_id, set()).discard(ws)

    # ------------------------------------------------------------------- AI
    @app.post("/api/meetings/{meeting_id}/analyze")
    def analyze(meeting_id: str, body: AnalyzeBody) -> dict:
        try:
            out = ctx.analyzer().run(meeting_id, body.kind, body.template, body.provider, body.doc_type)
            return {"kind": out.kind, "text": out.text, "provider": out.provider, "model": out.model}
        except (AIError, StoreError, KeyError) as exc:
            raise _err(exc) from exc

    @app.post("/api/meetings/{meeting_id}/ask")
    def ask(meeting_id: str, body: AskBody) -> dict:
        try:
            out = ctx.analyzer().ask(meeting_id, body.question, body.provider)
            return {"text": out.text, "provider": out.provider, "model": out.model}
        except (AIError, StoreError) as exc:
            raise _err(exc) from exc

    @app.post("/api/ask")
    def ask_all(body: AskBody) -> dict:
        try:
            return ctx.analyzer().ask_all(body.question, body.provider)
        except (AIError, StoreError) as exc:
            raise _err(exc) from exc

    # -------------------------------------------------------------- export
    @app.get("/api/meetings/{meeting_id}/export")
    def export(meeting_id: str, format: str = "md") -> Response:  # noqa: A002 - query name
        try:
            name, content = export_meeting(ctx.store, meeting_id, format)
        except StoreError as exc:
            raise _err(exc) from exc
        media = {"md": "text/markdown", "txt": "text/plain", "srt": "application/x-subrip", "json": "application/json"}[format]
        return PlainTextResponse(content, media_type=f"{media}; charset=utf-8",
                                 headers={"Content-Disposition": f'attachment; filename="{_ascii(name)}"'})

    @app.get("/api/backup")
    def backup() -> Response:
        name, data = backup_zip(ctx.data_dir)
        return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.post("/api/restore")
    async def restore(request: Request, overwrite: bool = False) -> dict:
        data = await request.body()
        try:
            return restore_zip(ctx.data_dir, data, overwrite)
        except StoreError as exc:
            raise _err(exc) from exc

    # ----------------------------------------------------------------- UI
    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app


def _ascii(name: str) -> str:
    return name.encode("ascii", "replace").decode().replace("?", "_").replace('"', "_")
