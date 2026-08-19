"""Core data model shared by all todoy sources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Todo:
    """A single todo item, regardless of which source produced it."""

    text: str
    done: bool = False
    id: int | None = None  # assigned by builtin storage; None for read-only sources
    source: str = "builtin"  # which source produced it

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "done": self.done,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Todo:
        return cls(
            text=d["text"],
            done=d.get("done", False),
            id=d.get("id"),
            source=d.get("source", "builtin"),
        )
