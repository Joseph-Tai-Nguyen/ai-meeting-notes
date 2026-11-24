"""Offline full-text search over meetings (titles, notes, transcripts, analyses)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from meeting_notes.models import format_ts
from meeting_notes.storage.store import MeetingStore

_WORD = re.compile(r"\w+", re.UNICODE)
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "was", "were",
    "what", "who", "when", "where", "why", "how", "did", "do", "does", "we", "i", "you", "it",
    "that", "this", "with", "about", "at", "by", "be", "our", "my", "me",
}


def terms(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.casefold()) if w not in _STOP and len(w) > 1]


@dataclass
class SearchHit:
    meeting_id: str
    title: str
    created_at: str
    snippet: str
    score: int


def _snippet(text: str, needle: str, width: int = 80) -> str:
    idx = text.casefold().find(needle)
    if idx < 0:
        return text[: width * 2].replace("\n", " ")
    start = max(0, idx - width)
    end = min(len(text), idx + len(needle) + width)
    prefix = "…" if start else ""
    suffix = "…" if end < len(text) else ""
    return prefix + text[start:end].replace("\n", " ") + suffix


def search(store: MeetingStore, query: str, limit: int = 50) -> list[SearchHit]:
    """All query words must appear somewhere in the meeting (case-insensitive)."""
    words = [w for w in query.casefold().split() if w]
    if not words:
        return []
    hits: list[SearchHit] = []
    for meeting in store.list():
        body = "\n".join(
            [meeting.title, " ".join(meeting.attendees), " ".join(meeting.tags),
             store.notes(meeting.id), store.transcript_text(meeting.id),
             *store.analyses(meeting.id).values()]
        )
        folded = body.casefold()
        if all(w in folded for w in words):
            score = sum(folded.count(w) for w in words) + (10 if all(w in meeting.title.casefold() for w in words) else 0)
            hits.append(SearchHit(meeting.id, meeting.title, meeting.created_at, _snippet(body, words[0]), score))
    hits.sort(key=lambda h: (h.score, h.created_at), reverse=True)
    return hits[:limit]


@dataclass
class Excerpt:
    meeting_id: str
    title: str
    created_at: str
    start: float
    text: str
    score: float


def retrieve(store: MeetingStore, question: str, k: int = 12, window: int = 8) -> list[Excerpt]:
    """Keyword retrieval of transcript windows for cross-meeting Q&A (no embeddings needed)."""
    q = set(terms(question))
    if not q:
        return []
    found: list[Excerpt] = []
    for meeting in store.list():
        segs = store.segments(meeting.id)
        title_bonus = 0.5 * len(q & set(terms(meeting.title)))
        notes = store.notes(meeting.id)
        if notes.strip():
            score = len(q & set(terms(notes))) + title_bonus
            if score:
                found.append(Excerpt(meeting.id, meeting.title, meeting.created_at, 0.0, "[notes] " + notes[:2000], score))
        step = max(1, window // 2)
        for i in range(0, max(1, len(segs)), step):
            chunk = segs[i : i + window]
            if not chunk:
                break
            text = "\n".join(f"[{format_ts(s.start)}] {s.speaker}: {s.text}" for s in chunk)
            score = len(q & set(terms(text))) + title_bonus
            if score:
                found.append(Excerpt(meeting.id, meeting.title, meeting.created_at, chunk[0].start, text, score))
    found.sort(key=lambda e: (e.score, e.created_at), reverse=True)
    return found[:k]
