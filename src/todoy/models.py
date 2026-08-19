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

        return cls(text=text, done=done, id=todo_id, source=source)
