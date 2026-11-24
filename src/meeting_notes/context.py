"""AppContext - one object holding settings, storage, engines, AI and the live session."""

from __future__ import annotations

import threading
from pathlib import Path

from meeting_notes.ai import AIRouter, Analyzer, PromptLibrary, build_providers
from meeting_notes.config import SettingsStore
from meeting_notes.storage.store import MeetingStore
from meeting_notes.transcription import build_engines
from meeting_notes.transcription.base import Engine
from meeting_notes.transcription.session import LiveSession, sources_for_mode


class AppContext:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings_store = SettingsStore(self.data_dir)
        self.store = MeetingStore(self.data_dir)
        self.prompts = PromptLibrary(self.data_dir / "prompts")
        self._session: LiveSession | None = None
        self._session_lock = threading.Lock()
        self.listeners: list = []  # callables receiving (meeting_id, event)

    @property
    def settings(self):
        return self.settings_store.settings

    # Rebuilt on demand so settings changes apply immediately.
    def engines(self) -> dict[str, Engine]:
        return build_engines(self.settings.transcription, self.data_dir)

    def router(self) -> AIRouter:
        ai = self.settings.ai
        return AIRouter(build_providers(ai), ai.provider_order)

    def analyzer(self) -> Analyzer:
        return Analyzer(self.store, self.router(), self.prompts, self.settings.ai)

    # ------------------------------------------------------------ live session
    @property
    def session(self) -> LiveSession | None:
        s = self._session
        return s if s and s.status != "done" else None

    def _broadcast(self, meeting_id: str, event: dict) -> None:
        for listener in list(self.listeners):
            listener(meeting_id, event)

    def start_session(self, meeting_id: str, mode: str | None = None, engine: str | None = None,
                      language: str | None = None, file_path: str | None = None, sources=None) -> LiveSession:
        with self._session_lock:
            if self.session is not None:
                raise RuntimeError("A recording is already running. Stop it first.")
            ts = self.settings.transcription
            meeting = self.store.get(meeting_id)
            mode = mode or meeting.mode
            engines = self.engines()
            eng = engines.get(engine or ts.engine)
            if eng is None:
                raise RuntimeError(f"unknown engine: {engine}")
            ok, reason = eng.availability()
            if not ok:
                raise RuntimeError(f"{eng.label} is not available: {reason}")
            lang = language or meeting.language or ts.language
            if lang == "auto" and not eng.supports_auto_language:
                lang = ts.language if ts.language != "auto" else "en"
            if mode != meeting.mode or lang != meeting.language:
                self.store.update(meeting_id, mode=mode, language=lang)
            srcs = sources if sources is not None else sources_for_mode(mode, ts, file_path)
            session = LiveSession(self.store, meeting_id, eng, lang, srcs,
                                  on_event=lambda e, mid=meeting_id: self._broadcast(mid, e))
            session.start()
            self._session = session
            return session

    def stop_session(self) -> None:
        s = self._session
        if s is not None:
            s.stop()
