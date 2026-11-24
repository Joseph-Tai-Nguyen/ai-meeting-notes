"""Download offline speech models.

    python scripts/download_models.py vosk en          # Vosk small English (~40 MB)
    python scripts/download_models.py vosk vi de       # several languages
    python scripts/download_models.py whisper small    # pre-fetch a faster-whisper model
    python scripts/download_models.py list

Vosk models come from https://alphacephei.com/vosk/models (Apache 2.0).
Models are saved under <data_dir>/models (see MEETING_NOTES_DATA_DIR).
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from meeting_notes.config import default_data_dir, load_dotenv  # noqa: E402

VOSK_BASE = "https://alphacephei.com/vosk/models/"
VOSK_SMALL = {
    "en": "vosk-model-small-en-us-0.15",
    "vi": "vosk-model-small-vn-0.4",
    "de": "vosk-model-small-de-0.15",
    "fr": "vosk-model-small-fr-0.22",
    "es": "vosk-model-small-es-0.42",
    "it": "vosk-model-small-it-0.22",
    "pt": "vosk-model-small-pt-0.3",
    "ru": "vosk-model-small-ru-0.22",
    "zh": "vosk-model-small-cn-0.22",
    "ja": "vosk-model-small-ja-0.22",
    "ko": "vosk-model-small-ko-0.22",
    "nl": "vosk-model-small-nl-0.22",
    "hi": "vosk-model-small-hi-0.22",
}


def _progress(block: int, size: int, total: int) -> None:
    if total > 0:
        done = min(100, block * size * 100 // total)
        sys.stdout.write(f"\r  {done:3d}%  of {total // (1024 * 1024)} MB")
        sys.stdout.flush()


def download_vosk(lang: str, models_root: Path) -> None:
    name = VOSK_SMALL.get(lang)
    if not name:
        sys.exit(f"No small Vosk model mapped for '{lang}'. Known: {', '.join(VOSK_SMALL)}. "
                 f"Download manually from {VOSK_BASE} and unzip into {models_root / 'vosk' / lang}")
    dest = models_root / "vosk" / lang
    if dest.is_dir():
        print(f"Already installed: {dest}")
        return
    url = VOSK_BASE + name + ".zip"
    print(f"Downloading {url}")
    with tempfile.TemporaryDirectory() as tmp:
        zpath = Path(tmp) / "model.zip"
        urllib.request.urlretrieve(url, zpath, _progress)
        print("\n  extracting…")
        extract = Path(tmp) / "x"
        with zipfile.ZipFile(zpath) as zf:
            root = extract.resolve()
            for member in zf.infolist():
                target = (extract / member.filename).resolve()
                if root not in target.parents and target != root:
                    sys.exit(f"Unsafe path in archive: {member.filename}")
            zf.extractall(extract)
        inner = next((p for p in extract.iterdir() if p.is_dir()), extract)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(inner), str(dest))
    print(f"Installed {name} -> {dest}")


def download_whisper(size: str) -> None:
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        sys.exit('Install first: pip install -e ".[whisper]"')
    print(f"Fetching faster-whisper '{size}' into the Hugging Face cache…")
    WhisperModel(size, device="cpu", compute_type="int8")
    print("Done.")


def main(argv: list[str]) -> None:
    load_dotenv(Path.cwd() / ".env")
    models_root = default_data_dir() / "models"
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return
    kind, args = argv[0], argv[1:]
    if kind == "list":
        print("Vosk languages:", ", ".join(VOSK_SMALL))
        print("Whisper sizes: tiny, base, small, medium, large-v3 (multilingual)")
        print("Models folder:", models_root)
    elif kind == "vosk":
        for lang in args or ["en"]:
            download_vosk(lang, models_root)
    elif kind == "whisper":
        download_whisper(args[0] if args else "small")
    else:
        sys.exit(f"unknown model kind: {kind}")


if __name__ == "__main__":
    main(sys.argv[1:])
