"""Pure scheduling and message-assembly logic for the desktop overlay.

No AppKit/pyobjc imports here -- this module must import and be unit-tested
on any platform, independent of which OS backend (if any) is installed.
"""

from __future__ import annotations

import random
import time
import unicodedata
from typing import TYPE_CHECKING

from todoy.display import sanitize_text
from todoy.display.messages import taunt

if TYPE_CHECKING:
    from collections.abc import Callable

    from todoy.display.messages import Language
    from todoy.models import Todo

MAX_TODO_LINE_WIDTH = 45
MAX_TODO_LINES = 5


class ReminderScheduler:
    """Monotonic-clock reminder state machine.

    Tracks when the next reminder bubble should fire. Entirely decoupled
    from any timer/event-loop implementation -- a backend polls
    `should_fire()`/`seconds_until_fire()` on its own cadence and calls
    `fired()`/`snooze()` in response to firing or user snooze clicks.
    """

    def __init__(
        self,
        interval_minutes: int,
        snooze_minutes: int,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.interval_minutes = interval_minutes
        self.snooze_minutes = snooze_minutes
        self._now = now
        self._next_fire = self._now() + self._interval_seconds()

    def seconds_until_fire(self) -> float:
        """Seconds remaining until the next fire; never negative."""
        return max(0.0, self._next_fire - self._now())

    def should_fire(self) -> bool:
        """Whether a reminder is due right now."""
        return self._now() >= self._next_fire

    def fired(self) -> None:
        """Record that a reminder just fired; schedule the next full interval."""
        self._next_fire = self._now() + self._interval_seconds()

    def snooze(self) -> None:
        """Push the next fire out to now + snooze_minutes."""
        self._next_fire = self._now() + self._snooze_seconds()

    def _interval_seconds(self) -> float:
        return self.interval_minutes * 60

    def _snooze_seconds(self) -> float:
        return self.snooze_minutes * 60


def build_reminder_text(
    todos: list[Todo],
    language: Language,
    rng: random.Random | None = None,
) -> str:
    """Assemble the speech-bubble text: a taunt line plus up to 5 todo lines.

    With zero todos this is just the congrats taunt line. Otherwise: taunt
    line, a blank line, then up to `MAX_TODO_LINES` sanitized/truncated todo
    lines ("[#id] text" for builtin todos, "* text" for everything else),
    followed by "(+N more)" when the list was truncated.
    """
    headline = taunt(len(todos), language, rng)
    if not todos:
        return headline

    shown = todos[:MAX_TODO_LINES]
    lines = [headline, "", *(_format_todo_line(todo) for todo in shown)]

    remaining = len(todos) - len(shown)
    if remaining > 0:
        lines.append(f"(+{remaining} more)")

    return "\n".join(lines)


def _format_todo_line(todo: Todo) -> str:
    text = sanitize_text(todo.text)
    if todo.source == "builtin":
        todo_id = str(todo.id) if todo.id is not None else "?"
        line = f"[#{todo_id}] {text}"
    else:
        line = f"* {text}"
    return _truncate(line, MAX_TODO_LINE_WIDTH)


def _truncate(text: str, max_width: int) -> str:
    if _display_width(text) <= max_width:
        return text

    ellipsis = "…"
    ellipsis_width = _display_width(ellipsis)
    if max_width <= ellipsis_width:
        return ellipsis if max_width == ellipsis_width else ""

    target_width = max_width - ellipsis_width
    current_width = 0
    chars: list[str] = []
    for char in text:
        char_width = _char_display_width(char)
        if current_width + char_width > target_width:
            break
        chars.append(char)
        current_width += char_width
    return f"{''.join(chars)}{ellipsis}"


def _display_width(text: str) -> int:
    return sum(_char_display_width(char) for char in text)


def _char_display_width(char: str) -> int:
    return 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
