"""Calendar sync via ICS (iCalendar) feeds - read only, no OAuth.

Works with the "secret address in iCal format" of Google Calendar, a published
Outlook / Microsoft 365 calendar (.ics link) or any exported .ics file.
Recurring events are expanded when ``recurring-ical-events`` is installed
(pip install -e .[calendar]); otherwise only single events are shown.
"""

from __future__ import annotations

import re
import threading
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_CACHE: dict[str, tuple[float, str]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 300

MEETING_APPS = {
    "teams": ("teams.microsoft.com", "teams.live.com"),
    "zoom": ("zoom.us", "zoom.com"),
    "meet": ("meet.google.com",),
    "webex": ("webex.com",),
}
_URL_RE = re.compile(r"https?://[^\s<>\"']+")


@dataclass
class CalendarEvent:
    uid: str
    title: str
    start: str
    end: str
    location: str = ""
    attendees: list[str] = field(default_factory=list)
    join_url: str = ""
    app: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _fetch(src: str) -> str:
    with _CACHE_LOCK:
        hit = _CACHE.get(src)
        if hit and time.time() - hit[0] < _CACHE_TTL:
            return hit[1]
    if src.startswith(("http://", "https://", "webcal://")):
        url = "https://" + src[len("webcal://"):] if src.startswith("webcal://") else src
        req = urllib.request.Request(url, headers={"User-Agent": "ai-meeting-notes"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            text = resp.read().decode("utf-8", "replace")
    else:
        text = Path(src).expanduser().read_text(encoding="utf-8", errors="replace")
    with _CACHE_LOCK:
        _CACHE[src] = (time.time(), text)
    return text


def _detect_app(*texts: str) -> tuple[str, str]:
    for text in texts:
        for url in _URL_RE.findall(text or ""):
            for app, hosts in MEETING_APPS.items():
                if any(h in url for h in hosts):
                    return app, url
    return "", ""


def _as_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.astimezone()
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day).astimezone()
    raise ValueError(value)


# ------------------------------------------------------------ minimal parser
def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _parse_dt(params: str, value: str) -> datetime:
    value = value.strip()
    if "VALUE=DATE" in params.upper() or len(value) == 8:
        return datetime.strptime(value[:8], "%Y%m%d").astimezone()
    if value.endswith("Z"):
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    tzid = re.search(r"TZID=([^;:]+)", params)
    naive = datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    if tzid:
        try:
            from zoneinfo import ZoneInfo

            return naive.replace(tzinfo=ZoneInfo(tzid.group(1).strip('"')))
        except Exception:  # noqa: BLE001 - Windows TZ names are not IANA names
            pass
    return naive.astimezone()


def _unescape(v: str) -> str:
    return v.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _parse_basic(text: str) -> list[dict]:
    events, cur = [], None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            cur = {"attendees": []}
        elif line == "END:VEVENT" and cur is not None:
            events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            head, value = line.split(":", 1)
            name, _, params = head.partition(";")
            name = name.upper()
            if name in ("DTSTART", "DTEND"):
                try:
                    cur[name] = _parse_dt(params, value)
                except ValueError:
                    pass
            elif name == "ATTENDEE":
                cn = re.search(r"CN=\"?([^;:\"]+)", params)
                cur["attendees"].append(cn.group(1) if cn else value.replace("mailto:", "").replace("MAILTO:", ""))
            elif name in ("SUMMARY", "LOCATION", "DESCRIPTION", "UID", "URL", "RRULE", "STATUS"):
                cur[name] = _unescape(value)
    return events


def _events_basic(text: str, start: datetime, end: datetime) -> list[CalendarEvent]:
    out = []
    for e in _parse_basic(text):
        s = e.get("DTSTART")
        if not s or e.get("STATUS", "").upper() == "CANCELLED":
            continue
        en = e.get("DTEND") or s + timedelta(hours=1)
        if en < start or s > end:
            continue
        app, url = _detect_app(e.get("LOCATION", ""), e.get("URL", ""), e.get("DESCRIPTION", ""))
        out.append(CalendarEvent(e.get("UID", ""), e.get("SUMMARY", "Untitled event"), s.isoformat(), en.isoformat(),
                                 e.get("LOCATION", ""), e["attendees"], url, app))
    return out


def _events_full(text: str, start: datetime, end: datetime) -> list[CalendarEvent] | None:
    try:
        import icalendar  # type: ignore
        import recurring_ical_events  # type: ignore
    except ImportError:
        return None
    cal = icalendar.Calendar.from_ical(text)
    out = []
    for ev in recurring_ical_events.of(cal).between(start, end):
        if str(ev.get("STATUS", "")).upper() == "CANCELLED":
            continue
        s = _as_dt(ev.decoded("DTSTART"))
        en = _as_dt(ev.decoded("DTEND")) if ev.get("DTEND") else s + timedelta(hours=1)
        attendees = ev.get("ATTENDEE", [])
        if not isinstance(attendees, list):
            attendees = [attendees]
        names = [str(a.params.get("CN") or str(a).replace("mailto:", "")) for a in attendees]
        loc, url, desc = str(ev.get("LOCATION", "")), str(ev.get("URL", "")), str(ev.get("DESCRIPTION", ""))
        app, join = _detect_app(loc, url, desc)
        out.append(CalendarEvent(str(ev.get("UID", "")), str(ev.get("SUMMARY", "Untitled event")),
                                 s.isoformat(), en.isoformat(), loc, names, join, app))
    return out


def upcoming(sources: list[str], hours_back: int = 2, hours_ahead: int = 24 * 7) -> dict:
    now = datetime.now().astimezone()
    start, end = now - timedelta(hours=hours_back), now + timedelta(hours=hours_ahead)
    events: list[CalendarEvent] = []
    errors: list[str] = []
    for src in sources:
        try:
            text = _fetch(src)
            found = _events_full(text, start, end)
            events.extend(found if found is not None else _events_basic(text, start, end))
        except Exception as exc:  # noqa: BLE001 - report per feed, keep others
            errors.append(f"{src[:40]}…: {exc}")
    events.sort(key=lambda e: e.start)
    return {"events": [e.to_dict() for e in events], "errors": errors}
