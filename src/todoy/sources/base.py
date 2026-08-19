"""Abstract interface that every todoy source adapter implements."""

from __future__ import annotations

from abc import ABC, abstractmethod

from todoy.models import Todo


class Source(ABC):
    """A source of todos (builtin storage, a markdown vault, etc.)."""

    name: str  # class attribute, e.g. "builtin"

    @abstractmethod
    def get_todos(self) -> list[Todo]:
        """Return today's *open* (not done) todos."""
