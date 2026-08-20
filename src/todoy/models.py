"""Core data model shared by all todoy sources."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# H?H:MM — hour 1-2 digits (unpadded on input, always output zero-padded),
# minute exactly 2 digits. Range validation (0-23 / 0-59) happens after the
# regex match since the regex alone can't enforce numeric ranges.
_AT_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def parse_at(value: str) -> str:
    """Parse a 24h time string into its canonical zero-padded "HH:MM" form.

    Accepts an unpadded hour on input (e.g. "9:30") but always returns the
    padded form ("09:30"). Raises ValueError for anything that isn't a
    valid 24h time (bad shape, hour outside 0-23, minute outside 0-59).
    """
    match = _AT_RE.match(value)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
    raise ValueError(f"invalid time {value!r}, expected 'HH:MM' (24h)")


@dataclass
class Todo:
    """A single todo item, regardless of which source produced it."""

    text: str
    done: bool = False
    id: int | None = None  # assigned by builtin storage; None for read-only sources
    source: str = "builtin"  # which source produced it
    at: str | None = None  # canonical zero-padded "HH:MM" alarm time, or None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "done": self.done,
            "source": self.source,
            "at": self.at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Todo:
        if "text" not in d:
            raise ValueError("Todo dict missing required 'text' field")
        text = d["text"]
        if not isinstance(text, str):
            raise ValueError(f"Todo 'text' must be a string, got {type(text).__name__}: {text!r}")

        done = d.get("done", False)
        if not isinstance(done, bool):
            raise ValueError(f"Todo 'done' must be a bool, got {type(done).__name__}: {done!r}")

        todo_id = d.get("id")
        if todo_id is not None and (isinstance(todo_id, bool) or not isinstance(todo_id, int)):
            raise ValueError(
                f"Todo 'id' must be an int or None, got {type(todo_id).__name__}: {todo_id!r}"
            )

        source = d.get("source", "builtin")
        if not isinstance(source, str):
            raise ValueError(
                f"Todo 'source' must be a string, got {type(source).__name__}: {source!r}"
            )

        at = d.get("at")
        if at is not None:
            if not isinstance(at, str):
                raise ValueError(
                    f"Todo 'at' must be 'HH:MM' or null, got {type(at).__name__}: {at!r}"
                )
            try:
                at = parse_at(at)
            except ValueError:
                raise ValueError(
                    f"Todo 'at' must be 'HH:MM' or null, got {type(at).__name__}: {at!r}"
                ) from None

        return cls(text=text, done=done, id=todo_id, source=source, at=at)
