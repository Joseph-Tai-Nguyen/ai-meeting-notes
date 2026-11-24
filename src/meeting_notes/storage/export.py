"""Export a meeting (md / txt / srt / json) and back up / restore all data as a zip."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from meeting_notes.models import format_ts
from meeting_notes.storage.store import MeetingStore, StoreError

EXPORT_FORMATS = ("md", "txt", "srt", "json")

ANALYSIS_TITLES = {
    "summary": "Summary",
    "action_items": "Action items",
    "decisions": "Decisions",
    "follow_up_email": "Follow-up email",
    "speakers": "Speakers",
    "draft_doc": "Draft document",
    "qa": "Questions & answers",
}


def _srt_ts(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def export_meeting(store: MeetingStore, meeting_id: str, fmt: str) -> tuple[str, str]:
    """Return (filename, content) for one meeting."""
    if fmt not in EXPORT_FORMATS:
        raise StoreError(f"unsupported format {fmt!r}; use one of {EXPORT_FORMATS}")
    meeting = store.get(meeting_id)
    segments = store.segments(meeting_id)
    notes = store.notes(meeting_id)
    analyses = store.analyses(meeting_id)
    base = f"{meeting.created_at[:10]} {meeting.title}".strip()
    safe = "".join(c if c.isalnum() or c in " -_." else "_" for c in base)[:100].strip() or meeting.id

    if fmt == "json":
        payload = {
            "meeting": meeting.to_dict(),
            "notes": notes,
            "segments": [s.to_dict() for s in segments],
            "analyses": analyses,
        }
        return f"{safe}.json", json.dumps(payload, indent=2, ensure_ascii=False)

    if fmt == "srt":
        blocks = []
        for i, seg in enumerate(segments, 1):
            end = seg.end if seg.end > seg.start else seg.start + 2
            blocks.append(f"{i}\n{_srt_ts(seg.start)} --> {_srt_ts(end)}\n{seg.speaker}: {seg.text}\n")
        return f"{safe}.srt", "\n".join(blocks)

    md = fmt == "md"
    h1, h2 = ("# ", "## ") if md else ("", "")
    out = [f"{h1}{meeting.title}", ""]
    out.append(f"Date: {meeting.created_at}")
    out.append(f"Duration: {format_ts(meeting.duration)}")
    if meeting.attendees:
        out.append(f"Attendees: {', '.join(meeting.attendees)}")
    out.append("")
    for kind in ("summary", "action_items", "decisions", "follow_up_email", "draft_doc", "speakers", "qa"):
        if kind in analyses:
            out += [f"{h2}{ANALYSIS_TITLES.get(kind, kind)}", "", analyses[kind].strip(), ""]
    if notes.strip():
        out += [f"{h2}My notes", "", notes.strip(), ""]
    if meeting.highlights:
        out += [f"{h2}Highlights", ""]
        out += [f"- [{format_ts(h.t)}] {h.label or 'Highlight'}" for h in meeting.highlights]
        out.append("")
    out += [f"{h2}Transcript", ""]
    for seg in segments:
        out.append(f"**[{format_ts(seg.start)}] {seg.speaker}:** {seg.text}" if md else seg.line())
        if md:
            out.append("")
    return f"{safe}.{fmt}", "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------- backup zip
def backup_zip(data_dir: Path) -> tuple[str, bytes]:
    """Zip meetings/, prompts/ (user overrides) and settings.json. Models and trash are skipped."""
    data_dir = Path(data_dir)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for sub in ("meetings", "prompts"):
            root = data_dir / sub
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                if path.is_file() and not path.name.endswith(".tmp"):
                    zf.write(path, path.relative_to(data_dir).as_posix())
        settings = data_dir / "settings.json"
        if settings.is_file():
            zf.write(settings, "settings.json")
        zf.writestr("BACKUP_INFO.txt", f"AI Meeting Notes backup\ncreated: {datetime.now().isoformat()}\n")
    name = f"ai-meeting-notes-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    return name, buf.getvalue()


def restore_zip(data_dir: Path, data: bytes, overwrite: bool = False) -> dict[str, list[str]]:
    """Restore meetings (and prompt overrides) from a backup zip.

    Existing meetings are skipped unless ``overwrite`` is true. Settings are not
    restored automatically (they are machine specific); they are written to
    ``settings.restored.json`` for manual review.
    """
    data_dir = Path(data_dir).resolve()
    restored: set[str] = set()
    skipped: set[str] = set()
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise StoreError("not a valid zip file") from exc
    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = PurePosixPath(info.filename)
            if name.is_absolute() or ".." in name.parts or not name.parts:
                continue
            top = name.parts[0]
            if top == "settings.json":
                (data_dir / "settings.restored.json").write_bytes(zf.read(info))
                continue
            if top not in ("meetings", "prompts") or len(name.parts) < 2:
                continue
            if top == "meetings":
                mid = name.parts[1]
                if mid in skipped:
                    continue
                if mid not in restored:
                    if (data_dir / "meetings" / mid).exists() and not overwrite:
                        skipped.add(mid)
                        continue
                    restored.add(mid)
            dest = (data_dir / Path(*name.parts)).resolve()
            if data_dir not in dest.parents:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(info))
    return {"restored": sorted(restored), "skipped": sorted(skipped)}
