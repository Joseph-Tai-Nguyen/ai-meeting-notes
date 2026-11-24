"""Command line interface.

    meeting-notes                      start the app (local server + browser / window)
    meeting-notes doctor               check audio, engines and AI providers
    meeting-notes devices              list microphones and system-audio devices
    meeting-notes record --mode online --title "Weekly sync"   live transcription in the terminal
    meeting-notes transcribe call.wav  transcribe a recording
    meeting-notes list                 list meetings
    meeting-notes analyze <id> --kind summary --template standup
    meeting-notes export <id> --format md -o notes.md
    meeting-notes backup -o backup.zip / restore backup.zip
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
import webbrowser
from pathlib import Path

from meeting_notes import __version__
from meeting_notes.config import default_data_dir, load_dotenv
from meeting_notes.models import format_ts


def _ctx(args):
    from meeting_notes.context import AppContext

    return AppContext(Path(args.data_dir) if args.data_dir else default_data_dir())


def cmd_serve(args) -> int:
    import uvicorn

    from meeting_notes.server import create_app

    ctx = _ctx(args)
    host = args.host or ctx.settings.host
    port = args.port or ctx.settings.port
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}/"
    app = create_app(ctx)
    print(f"AI Meeting Notes {__version__}  data: {ctx.data_dir}\nOpen {url}")

    if args.window:
        try:
            import webview  # type: ignore  # pywebview
        except ImportError:
            print("pywebview not installed (pip install -e .[desktop]); opening the browser instead.")
            args.window = False
    if args.window:
        server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
        t = threading.Thread(target=server.run, daemon=True)
        t.start()
        webview.create_window("AI Meeting Notes", url, width=1280, height=860)
        webview.start()
        server.should_exit = True
        t.join(timeout=5)
        return 0
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


def cmd_doctor(args) -> int:
    from meeting_notes.audio.devices import list_devices

    ctx = _ctx(args)
    print(f"Data folder: {ctx.data_dir}")
    dev = list_devices()
    print("\nAudio:", "ok" if dev["available"] else f"NOT AVAILABLE - {dev.get('error')}")
    if dev["available"]:
        print(f"  default mic:     {dev.get('default_microphone')}")
        print(f"  default speaker: {dev.get('default_speaker')}")
        print(f"  system-audio devices: {len(dev['system'])}  ({dev.get('note')})")
    print("\nTranscription engines (offline):")
    for e in ctx.engines().values():
        info = e.info()
        mark = "ok " if info["available"] else "-- "
        print(f"  {mark}{info['name']:<13} {info['reason']}")
    print("\nAI providers (optional, in fallback order):")
    for p in ctx.router().status():
        mark = "ok " if p["available"] else "-- "
        print(f"  {mark}{p['name']:<13} {p['reason']}")
    return 0


def cmd_devices(args) -> int:
    from meeting_notes.audio.devices import list_devices

    print(json.dumps(list_devices(), indent=2))
    return 0


def _print_event(event: dict) -> None:
    t = event.get("type")
    if t == "segment":
        s = event["segment"]
        sys.stdout.write("\r\033[K" + f"[{format_ts(s['start'])}] {s['speaker']}: {s['text']}\n")
    elif t == "partial" and event.get("text"):
        sys.stdout.write("\r\033[K" + f"  … {event['speaker']}: {event['text'][-100:]}")
    elif t == "error":
        sys.stdout.write("\r\033[K" + f"! {event.get('source')}: {event.get('message')}\n")
    sys.stdout.flush()


def _run_session(ctx, meeting, args, file_path=None) -> int:
    ctx.listeners.append(lambda _mid, e: _print_event(e))
    session = ctx.start_session(meeting.id, args.mode, args.engine, args.language, file_path)
    print(f"Recording '{meeting.title}' ({session.engine.label}, {session.language}). Ctrl+C to stop.\n")
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    while not stop.is_set() and session.status != "done":
        stop.wait(0.3)
    session.stop()
    m = ctx.store.get(meeting.id)
    print(f"\nSaved {len(ctx.store.segments(m.id))} segments, {format_ts(m.duration)} -> {ctx.store.path(m.id)}")
    print(f"Meeting id: {m.id}")
    return 0


def cmd_record(args) -> int:
    ctx = _ctx(args)
    meeting = ctx.store.create(args.title or "", args.mode, language=args.language or ctx.settings.transcription.language)
    return _run_session(ctx, meeting, args)


def cmd_transcribe(args) -> int:
    ctx = _ctx(args)
    args.mode = "file"
    meeting = ctx.store.create(args.title or Path(args.file).stem, "file",
                               language=args.language or ctx.settings.transcription.language)
    return _run_session(ctx, meeting, args, file_path=args.file)


def cmd_list(args) -> int:
    ctx = _ctx(args)
    for m in ctx.store.list():
        print(f"{m.id}  {m.created_at[:16]}  {format_ts(m.duration)}  {m.status:<9} {m.title}")
    return 0


def cmd_analyze(args) -> int:
    ctx = _ctx(args)
    out = ctx.analyzer().run(args.meeting_id, args.kind, args.template, args.provider, args.doc_type or "")
    print(out.text)
    print(f"\n-- {out.provider} {out.model}", file=sys.stderr)
    return 0


def cmd_ask(args) -> int:
    ctx = _ctx(args)
    if args.meeting_id:
        print(ctx.analyzer().ask(args.meeting_id, args.question, args.provider).text)
    else:
        print(ctx.analyzer().ask_all(args.question, args.provider)["answer"])
    return 0


def cmd_export(args) -> int:
    from meeting_notes.storage.export import export_meeting

    ctx = _ctx(args)
    name, content = export_meeting(ctx.store, args.meeting_id, args.format)
    out = Path(args.output or name)
    out.write_text(content, encoding="utf-8")
    print(f"Wrote {out}")
    return 0


def cmd_backup(args) -> int:
    from meeting_notes.storage.export import backup_zip

    ctx = _ctx(args)
    name, data = backup_zip(ctx.data_dir)
    out = Path(args.output or name)
    out.write_bytes(data)
    print(f"Backup written: {out} ({len(data) // 1024} KB)")
    return 0


def cmd_restore(args) -> int:
    from meeting_notes.storage.export import restore_zip

    ctx = _ctx(args)
    result = restore_zip(ctx.data_dir, Path(args.file).read_bytes(), args.overwrite)
    print(f"Restored {len(result['restored'])} meetings, skipped {len(result['skipped'])} existing.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="meeting-notes", description="Local-first live meeting transcription & notes")
    p.add_argument("--data-dir", help="data folder (default: $MEETING_NOTES_DATA_DIR or ~/Documents/AIMeetingNotes)")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("serve", help="start the app (default)")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    s.add_argument("--no-browser", action="store_true")
    s.add_argument("--window", action="store_true", help="native window via pywebview")
    s.set_defaults(func=cmd_serve)

    sub.add_parser("doctor", help="check setup").set_defaults(func=cmd_doctor)
    sub.add_parser("devices", help="list audio devices").set_defaults(func=cmd_devices)

    def rec_opts(sp):
        sp.add_argument("--title")
        sp.add_argument("--engine", help="vosk | whisper | macos | windows_sapi | mock")
        sp.add_argument("--language")

    r = sub.add_parser("record", help="live transcription in the terminal")
    r.add_argument("--mode", default="online", choices=["online", "in_person", "system"])
    rec_opts(r)
    r.set_defaults(func=cmd_record)

    t = sub.add_parser("transcribe", help="transcribe a .wav recording")
    t.add_argument("file")
    rec_opts(t)
    t.set_defaults(func=cmd_transcribe)

    sub.add_parser("list", help="list meetings").set_defaults(func=cmd_list)

    a = sub.add_parser("analyze", help="AI analysis of a meeting")
    a.add_argument("meeting_id")
    a.add_argument("--kind", default="summary", choices=["summary", "action_items", "decisions", "follow_up_email", "speakers", "draft_doc"])
    a.add_argument("--template", default=None)
    a.add_argument("--doc-type", default="")
    a.add_argument("--provider", default=None, help="gemini_api | gemini_cli | claude_code (default: fallback order)")
    a.set_defaults(func=cmd_analyze)

    q = sub.add_parser("ask", help="ask AI about one meeting (--meeting) or all meetings")
    q.add_argument("question")
    q.add_argument("--meeting", dest="meeting_id")
    q.add_argument("--provider", default=None)
    q.set_defaults(func=cmd_ask)

    e = sub.add_parser("export", help="export one meeting")
    e.add_argument("meeting_id")
    e.add_argument("--format", default="md", choices=["md", "txt", "srt", "json"])
    e.add_argument("-o", "--output")
    e.set_defaults(func=cmd_export)

    b = sub.add_parser("backup", help="zip all meetings and settings")
    b.add_argument("-o", "--output")
    b.set_defaults(func=cmd_backup)

    rs = sub.add_parser("restore", help="restore meetings from a backup zip")
    rs.add_argument("file")
    rs.add_argument("--overwrite", action="store_true")
    rs.set_defaults(func=cmd_restore)
    return p


def main(argv: list[str] | None = None) -> int:
    load_dotenv(Path.cwd() / ".env")
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except AttributeError:
            pass
    if not getattr(args, "func", None):  # no sub-command -> start the app
        args.host, args.port, args.no_browser, args.window, args.func = None, None, False, False, cmd_serve
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001 - friendly CLI errors
        if args.verbose:
            raise
        print(f"error: {exc}", file=sys.stderr)
        return 1
