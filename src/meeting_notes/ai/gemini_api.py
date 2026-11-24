"""Gemini via the Gemini API (Google AI Studio key).

Key: set GEMINI_API_KEY (or GOOGLE_API_KEY) in the environment or .env.
Get one at https://aistudio.google.com/apikey . Uses only the standard library.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from meeting_notes.ai.base import AIError, AIProvider

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"


def api_key() -> str:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""


class GeminiAPIProvider(AIProvider):
    name = "gemini_api"
    label = "Gemini API (AI Studio key)"

    def __init__(self, model: str = "gemini-flash-latest", timeout: int = 600):
        self._model = model or "gemini-flash-latest"
        self.timeout = timeout

    @property
    def model(self) -> str:
        return self._model

    def availability(self) -> tuple[bool, str]:
        if not api_key():
            return False, "set GEMINI_API_KEY in .env"
        return True, f"model: {self._model}"

    def generate(self, prompt: str, system: str | None = None) -> str:
        key = api_key()
        if not key:
            raise AIError("GEMINI_API_KEY is not set")
        body: dict = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        url = f"{API_ROOT}/{urllib.parse.quote(self._model)}:generateContent"
        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "x-goog-api-key": key},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:1000]
            raise AIError(f"Gemini API HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise AIError(f"Gemini API unreachable: {exc}") from exc
        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates")
            raise AIError(f"Gemini returned no answer ({reason})")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
        if not text:
            raise AIError("Gemini returned an empty answer")
        return text
