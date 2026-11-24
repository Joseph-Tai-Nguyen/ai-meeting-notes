"""Post-meeting AI analysis: summaries, action items, decisions, email, Q&A, drafts.

Runs only when the user asks. Reads the stored text transcript, so it works on
any past meeting, including imported backups.
"""

from __future__ import annotations

from dataclasses import dataclass

from meeting_notes.ai.prompts import PromptLibrary, render
from meeting_notes.ai.router import AIResult, AIRouter
from meeting_notes.config import AISettings
from meeting_notes.models import Segment, format_ts, now_iso
from meeting_notes.storage.search import retrieve
from meeting_notes.storage.store import MeetingStore, StoreError

TASKS = {
    "summary": "Summary",
    "action_items": "Action items",
    "decisions": "Decisions",
    "follow_up_email": "Follow-up email",
    "speakers": "Identify speakers",
    "draft_doc": "Draft a document",
}

LANG_NAMES = {
    "en": "English", "vi": "Vietnamese", "de": "German", "fr": "French", "es": "Spanish",
    "it": "Italian", "pt": "Portuguese", "ja": "Japanese", "zh": "Chinese", "ko": "Korean",
    "ru": "Russian", "nl": "Dutch", "hi": "Hindi",
}


@dataclass
class AnalysisOutput:
    kind: str
    text: str
    provider: str
    model: str


def _chunks(segments: list[Segment], max_chars: int) -> list[list[Segment]]:
    out: list[list[Segment]] = [[]]
    size = 0
    for seg in segments:
        n = len(seg.line()) + 1
        if size + n > max_chars and out[-1]:
            out.append([])
            size = 0
        out[-1].append(seg)
        size += n
    return [c for c in out if c]


class Analyzer:
    def __init__(self, store: MeetingStore, router: AIRouter, prompts: PromptLibrary, ai: AISettings):
        self.store = store
        self.router = router
        self.prompts = prompts
        self.ai = ai

    # ------------------------------------------------------------- helpers
    def _language_instruction(self, meeting_lang: str) -> str:
        lang = self.ai.output_language or ""
        if lang:
            return f"Write the answer in {LANG_NAMES.get(lang, lang)}."
        if meeting_lang and meeting_lang not in ("auto", ""):
            return f"Write the answer in {LANG_NAMES.get(meeting_lang, meeting_lang)} (the meeting language)."
        return "Write the answer in the main language of the transcript."

    def _context_values(self, meeting_id: str, provider: str | None) -> tuple[dict[str, str], str | None]:
        meeting = self.store.get(meeting_id)
        segments = self.store.segments(meeting_id)
        notes = self.store.notes(meeting_id).strip()
        if not segments and not notes:
            raise StoreError("This meeting has no transcript or notes yet.")
        values = {
            "title": meeting.title,
            "date": meeting.created_at,
            "duration": format_ts(meeting.duration),
            "attendees": ", ".join(meeting.attendees) or "not recorded",
            "notes": notes or "(none)",
            "highlights": "\n".join(f"- [{format_ts(h.t)}] {h.label or 'highlight'}" for h in meeting.highlights) or "(none)",
            "language_instruction": self._language_instruction(meeting.language),
        }
        transcript = "\n".join(s.line() for s in segments)
        used_provider = None
        if len(transcript) > self.ai.max_chunk_chars:
            transcript, used_provider = self._condense(segments, values, provider)
        values["transcript"] = transcript or "(no transcript)"
        values["context"] = render(self.prompts.get("_context.md"), values)
        return values, used_provider

    def _condense(self, segments, values, provider) -> tuple[str, str]:
        """Map step for very long meetings: notes per chunk, then reduce."""
        parts = _chunks(segments, self.ai.max_chunk_chars)
        notes = []
        last = None
        for i, chunk in enumerate(parts, 1):
            prompt = render(self.prompts.get("tasks/chunk_summary.md"), {
                **values, "part": f"{i} of {len(parts)}", "transcript": "\n".join(s.line() for s in chunk),
            })
            last = self.router.generate(prompt, self.prompts.get("system.md"), provider)
            notes.append(f"### Part {i} ({format_ts(chunk[0].start)} - {format_ts(chunk[-1].end)})\n{last.text}")
        header = "(Transcript was long; below are condensed notes per part, with timestamps.)\n\n"
        return header + "\n\n".join(notes), last.provider if last else ""

    def _generate(self, prompt: str, provider: str | None) -> AIResult:
        return self.router.generate(prompt, self.prompts.get("system.md"), provider)

    # ---------------------------------------------------------------- tasks
    def run(self, meeting_id: str, kind: str, template: str | None = None,
            provider: str | None = None, doc_type: str = "") -> AnalysisOutput:
        if kind not in TASKS:
            raise StoreError(f"unknown analysis kind: {kind}")
        values, _ = self._context_values(meeting_id, provider)
        if kind == "summary":
            tpl = self.prompts.summary(template or "general")
        else:
            tpl = self.prompts.get(f"tasks/{kind}.md")
        if kind == "draft_doc":
            values["doc_type"] = doc_type.strip() or "project brief"
        result = self._generate(render(tpl, values), provider)
        meta = {"provider": result.provider, "model": result.model}
        if kind == "summary":
            meta["template"] = template or "general"
        if kind == "draft_doc":
            meta["doc_type"] = values["doc_type"]
        self.store.write_analysis(meeting_id, kind, result.text.strip() + "\n", meta)
        return AnalysisOutput(kind, result.text, result.provider, result.model)

    def ask(self, meeting_id: str, question: str, provider: str | None = None) -> AnalysisOutput:
        if not question.strip():
            raise StoreError("question is empty")
        values, _ = self._context_values(meeting_id, provider)
        values["question"] = question.strip()
        result = self._generate(render(self.prompts.get("tasks/ask.md"), values), provider)
        entry = f"### Q: {question.strip()}\n_{now_iso()} - {result.provider}_\n\n{result.text.strip()}\n\n"
        self.store.append_analysis(meeting_id, "qa", entry)
        meeting = self.store.get(meeting_id)
        meeting.analyses["qa"] = {"provider": result.provider, "model": result.model, "created_at": now_iso()}
        self.store.save(meeting)
        return AnalysisOutput("qa", result.text, result.provider, result.model)

    def ask_all(self, question: str, provider: str | None = None) -> dict:
        if not question.strip():
            raise StoreError("question is empty")
        excerpts = retrieve(self.store, question, k=15)
        if not excerpts:
            return {"answer": "No meeting mentions those words. Try different search terms.", "provider": "", "sources": []}
        text = "\n\n".join(
            f"--- {e.title} ({e.created_at[:10]}) [{format_ts(e.start)}]\n{e.text}" for e in excerpts
        )
        values = {"excerpts": text, "question": question.strip(),
                  "language_instruction": self._language_instruction(self.ai.output_language)}
        result = self._generate(render(self.prompts.get("tasks/ask_all.md"), values), provider)
        sources = [{"meeting_id": e.meeting_id, "title": e.title, "start": e.start} for e in excerpts]
        return {"answer": result.text, "provider": result.provider, "model": result.model, "sources": sources}
