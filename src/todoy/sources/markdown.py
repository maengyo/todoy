"""Markdown-folder todo source: scans notes for checkbox / dash-bullet lines."""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path

from todoy.models import Todo, parse_at
from todoy.sources.base import Source

# Matches "- [ ] text", "- [x] text", "- [X] text" (space between "]" and text
# is optional so that a marker with no following text, e.g. "- [ ]", is still
# recognized as a checkbox with empty text rather than falling through to the
# plain-dash-bullet rule).
_CHECKBOX_RE = re.compile(r"^- \[([ xX])\](.*)$")


def _split_leading_time_token(text: str) -> tuple[str | None, str]:
    """Split a leading "HH:MM"/"H:MM" time token off of todo text.

    If the first whitespace-delimited token in `text` is a valid 24h time,
    return (canonical "HH:MM", remaining text with the token removed).
    Otherwise the token isn't a time (or isn't valid), so the text is
    returned unchanged with at=None.
    """
    parts = text.split(None, 1)
    if not parts:
        return None, text

    try:
        at = parse_at(parts[0])
    except ValueError:
        return None, text

    rest = parts[1].strip() if len(parts) > 1 else ""
    return at, rest


def _parse_line(line: str) -> tuple[str, str | None] | None:
    """Return (text, at) for a markdown line's open todo, or None if not one.

    Rules (applied to the line after str.strip()):
      - "- [ ] text"            -> open todo, text
      - "- [x] text"/"- [X] ..."-> done, excluded (None)
      - "- text" (plain dash)   -> open todo, text
      - anything else           -> not a todo (None)
    Empty text after a recognized marker is treated as "not a todo".

    If the marker's text starts with a valid "H?H:MM" time token, that
    token becomes `at` and is stripped from `text`. A line that is ONLY a
    time token (nothing left after stripping it) is treated as "not a
    todo", same as any other empty-text line.
    """
    stripped = line.strip()

    match = _CHECKBOX_RE.match(stripped)
    if match:
        box, rest = match.group(1), match.group(2)
        if box in ("x", "X"):
            return None
        raw_text = rest.strip()
    elif stripped.startswith("- "):
        raw_text = stripped[2:].strip()
    else:
        return None

    if not raw_text:
        return None

    at, text = _split_leading_time_token(raw_text)
    return (text, at) if text else None


def _extract_todos(text: str) -> list[tuple[str, str | None]]:
    """Return the open-todo (text, at) pairs found in a note, in file order."""
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
        for item_text, item_at in _extract_todos(text):
            if item_text not in seen_texts:
                seen_texts.add(item_text)
                todos.append(
                    Todo(text=item_text, done=False, id=None, source=self.name, at=item_at)
                )

    def _scan_today_files(self, exclude: set[Path]) -> list[Path]:
        # Symlinked files are excluded here (but not from `exclude`, i.e. pinned
        # notes) so a `.md` symlink planted inside the scanned folder can't be
        # used to read arbitrary files outside it; pinned notes are explicit,
        # user-designated config entries where absolute paths (and thus
        # symlinks) are already allowed by contract.
        matches: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(self.folder):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for filename in filenames:
                if not filename.endswith(".md"):
                    continue
                path = Path(dirpath) / filename
                if path in exclude:
                    continue
                if path.is_symlink() or not path.is_file():
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
