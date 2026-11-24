"""Load prompt templates (built-in, overridable from <data_dir>/prompts)."""

from __future__ import annotations

import re
from pathlib import Path

BUILTIN_DIR = Path(__file__).resolve().parent.parent / "prompts"
_LABEL_RE = re.compile(r"^<!--\s*label:\s*(.+?)\s*-->\s*\n?")
_NAME_RE = re.compile(r"^[a-z0-9_]{1,40}$")
_VAR_RE = re.compile(r"\{\{(\w+)\}\}")


class PromptLibrary:
    def __init__(self, user_dir: Path | None = None):
        self.user_dir = Path(user_dir) if user_dir else None

    def _read(self, rel: str) -> str:
        if self.user_dir:
            p = self.user_dir / rel
            if p.is_file():
                return p.read_text(encoding="utf-8")
        p = BUILTIN_DIR / rel
        if not p.is_file():
            raise KeyError(f"prompt template not found: {rel}")
        return p.read_text(encoding="utf-8")

    def get(self, rel: str) -> str:
        return _LABEL_RE.sub("", self._read(rel), count=1)

    def summary_templates(self) -> list[dict]:
        names: dict[str, Path] = {}
        for root in [BUILTIN_DIR, self.user_dir]:
            if root and (root / "summary").is_dir():
                for p in sorted((root / "summary").glob("*.md")):
                    if _NAME_RE.match(p.stem):
                        names[p.stem] = p
        out = []
        for name in names:
            m = _LABEL_RE.match(self._read(f"summary/{name}.md"))
            out.append({"name": name, "label": m.group(1) if m else name.replace("_", " ").title()})
        out.sort(key=lambda t: (t["name"] != "general", t["label"]))
        return out

    def summary(self, name: str) -> str:
        if not _NAME_RE.match(name or ""):
            raise KeyError(f"invalid template name: {name!r}")
        return self.get(f"summary/{name}.md")


def render(template: str, values: dict[str, str]) -> str:
    """Replace {{name}} placeholders; unknown placeholders become empty."""
    return _VAR_RE.sub(lambda m: str(values.get(m.group(1), "")), template).strip() + "\n"
