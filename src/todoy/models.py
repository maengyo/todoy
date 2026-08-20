"""Core data model shared by all todoy sources."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

# H?H:MM — hour 1-2 digits (unpadded on input, always output zero-padded),
# minute exactly 2 digits. Range validation (0-23 / 0-59) happens after the
# regex match since the regex alone can't enforce numeric ranges.
# NOTE: [0-9] (not \d) — \d matches any Unicode decimal digit (e.g. full-width
# "０-９"), which int() would also happily parse, silently accepting
# non-ASCII-digit input as a valid time. [0-9] restricts this to ASCII only.
_AT_RE = re.compile(r"^([0-9]{1,2}):([0-9]{2})$")

# YYYY-MM-DD — every component zero-padded to a fixed width. Whether the
# month/day combination names a real calendar date (leap years, 30 vs 31 day
# months, etc.) is checked after the regex match by constructing a real
# date() object. [0-9] (not \d) for the same ASCII-only reason as _AT_RE above.
_DATE_RE = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})$")


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


def parse_date(value: str) -> str:
    """Validate a canonical "YYYY-MM-DD" date string.

    Raises ValueError for anything that isn't an exact, zero-padded
    'YYYY-MM-DD' string naming a real calendar date.
    """
    match = _DATE_RE.match(value)
    if match:
        year, month, day = (int(g) for g in match.groups())
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            pass
    raise ValueError(f"invalid date {value!r}, expected 'YYYY-MM-DD'")


@dataclass
class Todo:
    """A single todo item, regardless of which source produced it."""

    text: str
    done: bool = False
    id: int | None = None  # assigned by builtin storage; None for read-only sources
    source: str = "builtin"  # which source produced it
    at: str | None = None  # canonical zero-padded "HH:MM" alarm time, or None
    pinned: bool = False  # pinned todos survive the daily sweep regardless of age
    created: str | None = None  # canonical "YYYY-MM-DD"; None for read-only sources

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "done": self.done,
            "source": self.source,
            "at": self.at,
            "pinned": self.pinned,
            "created": self.created,
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

        pinned = d.get("pinned", False)
        if not isinstance(pinned, bool):
            raise ValueError(
                f"Todo 'pinned' must be a bool, got {type(pinned).__name__}: {pinned!r}"
            )

        created = d.get("created")
        if created is not None:
            if not isinstance(created, str):
                raise ValueError(
                    f"Todo 'created' must be 'YYYY-MM-DD' or null, "
                    f"got {type(created).__name__}: {created!r}"
                )
            try:
                created = parse_date(created)
            except ValueError:
                raise ValueError(
                    f"Todo 'created' must be 'YYYY-MM-DD' or null, "
                    f"got {type(created).__name__}: {created!r}"
                ) from None

        return cls(
            text=text,
            done=done,
            id=todo_id,
            source=source,
            at=at,
            pinned=pinned,
            created=created,
        )
