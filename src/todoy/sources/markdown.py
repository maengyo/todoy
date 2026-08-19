"""Markdown-folder todo source: scans notes for checkbox / dash-bullet lines."""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path

from todoy.models import Todo
from todoy.sources.base import Source

# Matches "- [ ] text", "- [x] text", "- [X] text" (space between "]" and text
# is optional so that a marker with no following text, e.g. "- [ ]", is still
# recognized as a checkbox with empty text rather than falling through to the
# plain-dash-bullet rule).
_CHECKBOX_RE = re.compile(r"^- \[([ xX])\](.*)$")


def _parse_line(line: str) -> str | None:
    """Return the open-todo text for a markdown line, or None if not one.

    Rules (applied to the line after str.strip()):
      - "- [ ] text"            -> open todo, text
      - "- [x] text"/"- [X] ..."-> done, excluded (None)
      - "- text" (plain dash)   -> open todo, text
      - anything else           -> not a todo (None)
    Empty text after a recognized marker is treated as "not a todo".
    """
    stripped = line.strip()

    match = _CHECKBOX_RE.match(stripped)
    if match:
        box, rest = match.group(1), match.group(2)
        if box in ("x", "X"):
            return None
        text = rest.strip()
        return text or None

    if stripped.startswith("- "):
        text = stripped[2:].strip()
        return text or None

    return None


def _extract_todos(text: str) -> list[str]:
    """Return the open-todo texts found in a note's contents, in file order."""
    todos = []
    for line in text.splitlines():
        item = _parse_line(line)
        if item is not None:
            todos.append(item)
    return todos


class MarkdownSource(Source):
    """Reads open todos out of a folder of markdown notes."""

    name = "markdown"

    def __init__(
        self,
        folder: Path,
        pinned_notes: list[str] | None = None,
        today: date | None = None,
    ) -> None:
        self.folder = folder
        self.pinned_notes = pinned_notes if pinned_notes is not None else []
        self.today = today if today is not None else date.today()

    def get_todos(self) -> list[Todo]:
        seen_texts: set[str] = set()
        todos: list[Todo] = []
        pinned_paths: set[Path] = set()

        for name in self.pinned_notes:
            candidate = Path(name)
            path = candidate if candidate.is_absolute() else self.folder / candidate
            pinned_paths.add(path)
            if not path.is_file():
                continue
            self._collect(path, seen_texts, todos)

        for path in self._scan_today_files(pinned_paths):
            self._collect(path, seen_texts, todos)

        return todos

    def _collect(self, path: Path, seen_texts: set[str], todos: list[Todo]) -> None:
        text = self._read(path)
        if text is None:
            return
        for item in _extract_todos(text):
            if item not in seen_texts:
                seen_texts.add(item)
                todos.append(Todo(text=item, done=False, id=None, source=self.name))

    def _scan_today_files(self, exclude: set[Path]) -> list[Path]:
        matches: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(self.folder):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for filename in filenames:
                if not filename.endswith(".md"):
                    continue
                path = Path(dirpath) / filename
                if path in exclude:
                    continue
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    continue
                if date.fromtimestamp(mtime) == self.today:
                    matches.append(path)
        matches.sort(key=str)
        return matches

    def _read(self, path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
