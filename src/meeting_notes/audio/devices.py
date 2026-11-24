"""List audio devices for the settings UI."""

from __future__ import annotations

import sys
import warnings


def list_devices() -> dict:
    from meeting_notes.audio.capture import AudioError, load_soundcard

    try:
        sc = load_soundcard()
    except AudioError as exc:
        return {"available": False, "error": str(exc), "microphones": [], "system": [], "platform": sys.platform}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            mics = sc.all_microphones()
            all_inputs = sc.all_microphones(include_loopback=True)
            default_mic = sc.default_microphone()
            default_spk = sc.default_speaker()
        except Exception as exc:  # noqa: BLE001 - backend errors vary per OS
            return {"available": False, "error": str(exc), "microphones": [], "system": [], "platform": sys.platform}

    if sys.platform == "darwin":
        # No native loopback: offer every input; virtual devices (BlackHole, Loopback) are flagged.
        system = [{"name": d.name, "virtual": any(k in d.name.lower() for k in ("blackhole", "loopback", "soundflower", "aggregate"))}
                  for d in all_inputs]
        note = "macOS: install a virtual loopback device such as BlackHole and select it here."
    else:
        system = [{"name": d.name.replace("Loopback", "").strip() or d.name, "virtual": False}
                  for d in all_inputs if getattr(d, "isloopback", False)]
        note = "Captures whatever plays on that output (speakers or headphones)."
    return {
        "available": True,
        "platform": sys.platform,
        "microphones": [{"name": d.name} for d in mics],
        "system": system,
        "default_microphone": default_mic.name if default_mic else "",
        "default_speaker": default_spk.name if default_spk else "",
        "note": note,
    }
