"""Pure scheduling and message-assembly logic for the desktop overlay.

No AppKit/pyobjc imports here -- this module must import and be unit-tested
on any platform, independent of which OS backend (if any) is installed.
"""

from __future__ import annotations

import random
import time
import unicodedata
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from todoy.display import sanitize_text
from todoy.display.messages import taunt

if TYPE_CHECKING:
    from collections.abc import Callable

    from todoy.display.messages import Language
    from todoy.models import Todo

MAX_TODO_LINE_WIDTH = 45
MAX_TODO_LINES = 5

# The compact `flag` message style is a single line on a small pennant, so
# its budget is much tighter than a bubble's per-line wrap width above.
FLAG_LINE_MAX_WIDTH = 38

# `build_flag_line`'s zero-todos line: a fixed constant (not drawn from the
# taunt pool, unlike `build_reminder_text`) -- there's no room for variety
# on a single-line pennant.
_FLAG_CONGRATS: dict[Language, str] = {
    "en": "All clear 🎉",
    "ko": "오늘 끝! 🎉",
}

# Bounded catch-up: a timed alarm missed while the overlay wasn't running (or
# was asleep) still fires once, but only if the app first sees it within this
# window after its scheduled time; older misses are skipped silently.
ALARM_CATCH_UP_WINDOW = timedelta(minutes=10)
ALARM_EMOJI = "⏰"

_AlarmIdentity = tuple[
    date, str, str, int | None, str
]  # (fired-on date, "HH:MM", source, id, todo text)
_SnoozeIdentity = tuple[
    str, str, int | None, str
]  # ("HH:MM", source, id, todo text) -- date-independent, see AlarmClock


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
        if interval_minutes <= 0:
            raise ValueError("reminder interval must be a positive number of minutes")
        if snooze_minutes <= 0:
            raise ValueError("snooze duration must be a positive number of minutes")

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


class AlarmClock:
    """Tracks which timed todos (`todo.at`) have fired today.

    Pure and injectable (a `now` callable returning `datetime`), independent
    of any timer/event-loop implementation. A backend calls `update(todos)`
    each tick with the fresh todo list, then reads `due()` for the todos that
    just became due -- each one marked fired for the rest of the day so it
    is not returned again on a later tick.

    "Fired today" identity is `(date, at, source, id, text)` -- source and id
    (not just at+text) are part of the key so two *distinct* todos that
    happen to share the same time and text (e.g. two builtin todos with
    different ids, or a builtin todo and a markdown todo with identical
    text) don't collapse into a single fired-identity and silently swallow
    one of them; `id` may be `None` for read-only (non-builtin) sources,
    where `text` is what disambiguates within that source. An alarm
    re-armed via `snooze_last()`, or a todo edited/re-added with the same
    time and text tomorrow, is a distinct identity and can fire again.

    Bounded catch-up: a todo whose `at` has already passed still fires once
    on the first tick that observes it, as long as that tick is within
    `ALARM_CATCH_UP_WINDOW` of the scheduled time (covers the overlay having
    been asleep/closed through the exact minute); older misses are skipped
    silently and never fire -- and, once skipped, are remembered for the rest
    of the day (`_skipped`) so a backward clock jump or DST fold can't walk
    the same miss back inside the catch-up window and fire it after all.
    Note: comparisons use naive local `datetime`s, so a DST fall-back (the
    wall clock repeating an hour) is the one case `_skipped` can't fully rule
    out an identity recurring within the "same" calendar day; not handled
    further here since it is a rare, self-correcting-next-day edge case.

    `due()` reflects only the current tick's newly-fired batch (empty most
    ticks); `snooze_last()` instead re-arms the most recently *non-empty*
    fired batch (`_last_fired`), which -- unlike `_due` -- survives the empty
    `update()` calls in between, so pressing Snooze several ticks after an
    alarm first showed still works.
    """

    def __init__(
        self,
        snooze_minutes: int,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.snooze_minutes = snooze_minutes
        self._now = now if now is not None else datetime.now
        self._today: date = self._now().date()
        self._fired: set[_AlarmIdentity] = set()
        self._skipped: set[_AlarmIdentity] = set()
        # Keyed by (at, source, id, text) -- NOT date -- so a snooze spanning
        # midnight (e.g. snoozed at 23:58 for 10 minutes) still matches and
        # fires at 00:08 the next day; only `_fired`/`_skipped` are
        # date-scoped and reset at rollover.
        self._snoozed_until: dict[_SnoozeIdentity, datetime] = {}
        self._due: list[Todo] = []
        self._last_fired: list[Todo] = []

    def due(self) -> list[Todo]:
        """Todos that became due on the most recent `update()` call."""
        return list(self._due)

    def update(self, todos: list[Todo]) -> None:
        """Recompute `due()` from the fresh `todos` list for "now".

        Todos without `at` are ignored. A todo missing from `todos` (e.g.
        completed or removed) simply cannot fire, whether or not it was due
        before. Rolls the fired/skipped-today sets over at midnight; pending
        snoozes are untouched by rollover (see class docstring).
        """
        now = self._now()
        today = now.date()
        if today != self._today:
            self._today = today
            self._fired.clear()
            self._skipped.clear()

        due: list[Todo] = []
        for todo in todos:
            at = todo.at
            if not at:
                continue
            identity: _AlarmIdentity = (today, at, todo.source, todo.id, todo.text)
            if identity in self._fired or identity in self._skipped:
                continue

            snooze_key: _SnoozeIdentity = (at, todo.source, todo.id, todo.text)
            snooze_target = self._snoozed_until.get(snooze_key)
            if snooze_target is not None:
                if now >= snooze_target:
                    due.append(todo)
                    self._fired.add(identity)
                    del self._snoozed_until[snooze_key]
                continue

            scheduled = _alarm_datetime(today, at)
            if scheduled is None or now < scheduled:
                continue
            if now - scheduled > ALARM_CATCH_UP_WINDOW:
                self._skipped.add(identity)  # missed by too long -- never fires today
                continue

            due.append(todo)
            self._fired.add(identity)

        self._due = due
        if due:
            self._last_fired = list(due)

    def snooze_last(self) -> None:
        """Re-arm the most recently fired alarm todos (`_last_fired`, which
        survives empty `update()` ticks since they last fired -- see class
        docstring) to fire again `snooze_minutes` from now, relative to the
        injected clock so this is safe under a fake/monotonic-style `now`.
        """
        if not self._last_fired:
            return
        now = self._now()
        today = now.date()
        target = now + timedelta(minutes=self.snooze_minutes)
        for todo in self._last_fired:
            identity: _AlarmIdentity = (today, todo.at, todo.source, todo.id, todo.text)
            self._fired.discard(identity)
            self._snoozed_until[(todo.at, todo.source, todo.id, todo.text)] = target
        self._last_fired = []
        self._due = []


def _alarm_datetime(day: date, at: str) -> datetime | None:
    """`day` at time `at` ("HH:MM"), or None if `at` is not a valid time."""
    try:
        hour_str, minute_str = at.split(":", 1)
        hour, minute = int(hour_str), int(minute_str)
    except (ValueError, AttributeError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return datetime(day.year, day.month, day.day, hour, minute)


def build_alarm_text(todos: list[Todo], language: Language, *, voice: str = "default") -> str:
    """Assemble the alarm speech-bubble text for exactly the due `todos`.

    No taunt line, no other (non-due) todos -- just the alarm(s). A single
    due todo renders as an "⏰ HH:MM" headline line followed by its (sanitized,
    width-truncated) text on its own line. Multiple simultaneous alarms each
    render as one "⏰ HH:MM text" line (also sanitized/width-truncated).
    """
    del language, voice  # reserved: alarm text has no localized copy today

    if not todos:
        return ""

    if len(todos) == 1:
        todo = todos[0]
        text = _truncate(sanitize_text(todo.text), MAX_TODO_LINE_WIDTH)
        return f"{ALARM_EMOJI} {todo.at}\n{text}"

    return "\n".join(_format_alarm_line(todo) for todo in todos)


def _format_alarm_line(todo: Todo) -> str:
    line = f"{ALARM_EMOJI} {todo.at} {sanitize_text(todo.text)}"
    return _truncate(line, MAX_TODO_LINE_WIDTH)


def build_reminder_text(
    todos: list[Todo],
    language: Language,
    rng: random.Random | None = None,
    *,
    voice: str = "default",
) -> str:
    """Assemble the speech-bubble text: a taunt line plus up to 5 todo lines.

    With zero todos this is just the congrats taunt line. Otherwise: taunt
    line, a blank line, then up to `MAX_TODO_LINES` sanitized/truncated todo
    lines ("[#id] text" for builtin todos, "* text" for everything else),
    followed by "(+N more)" when the list was truncated.
    """
    headline = taunt(len(todos), language, rng, voice=voice)
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


def build_flag_line(
    todos: list[Todo],
    language: Language,
    rng: random.Random | None = None,
    *,
    voice: str = "default",
) -> str:
    """Assemble the single-line pennant text for the compact `flag` message
    style -- the "one essential line" the character's fluttering flag rides
    with, as opposed to `build_reminder_text`'s full multi-line bubble.

    >=1 todos: "{count} to go: {first}" (en) / "할 일 {count}개: {first}"
    (ko), with a " (+{k})" suffix when there is more than one todo
    (k = count - 1). `first` is the first todo's sanitized display text,
    including its alarm-time prefix if it has one (see `_todo_display_text`)
    -- truncated with an ellipsis as needed so the WHOLE assembled line
    (count prefix, first, and suffix together) fits `FLAG_LINE_MAX_WIDTH`
    display columns.

    0 todos: `_FLAG_CONGRATS[language]`, a short fixed congrats line -- NOT
    drawn from `messages.taunt`'s pool, since a single-line pennant has no
    room for variety. `rng` is accepted but currently unused, kept in the
    signature for parity with `build_reminder_text` and to leave room for
    future variation.
    """
    del rng, voice  # reserved: currently unused, see docstring

    if not todos:
        return _FLAG_CONGRATS[language]

    count = len(todos)
    first = _todo_display_text(todos[0])
    suffix = f" (+{count - 1})" if count > 1 else ""
    prefix = f"할 일 {count}개: " if language == "ko" else f"{count} to go: "

    return _assemble_truncated_line(prefix, first, suffix, FLAG_LINE_MAX_WIDTH)


def build_alarm_flag_line(due: list[Todo], language: Language, *, voice: str = "default") -> str:
    """Assemble the single-line pennant text for a fired alarm.

    "⏰ HH:MM text" for the first due todo, with a " (+{k})" suffix when more
    than one alarm fired simultaneously (k = len(due) - 1); same
    whole-line-fits-`FLAG_LINE_MAX_WIDTH`-columns truncation rule as
    `build_flag_line`. The compact-flag counterpart of `build_alarm_text`.
    """
    del language, voice  # reserved: alarm text has no localized copy today

    if not due:
        return ""

    todo = due[0]
    prefix = f"{ALARM_EMOJI} {todo.at} "
    suffix = f" (+{len(due) - 1})" if len(due) > 1 else ""

    return _assemble_truncated_line(prefix, sanitize_text(todo.text), suffix, FLAG_LINE_MAX_WIDTH)


def _todo_display_text(todo: Todo) -> str:
    """Sanitized todo text, prefixed with its alarm time ("HH:MM text") when
    it has one -- mirrors `tui.todo_display_text`'s formatting.
    """
    text = sanitize_text(todo.text)
    if todo.at is None:
        return text
    return f"{todo.at} {text}"


def _assemble_truncated_line(prefix: str, body: str, suffix: str, max_width: int) -> str:
    """`prefix + body + suffix`, truncating `body` (with a trailing "…" if
    needed) so the WHOLE line fits `max_width` display columns -- `prefix`
    and `suffix` are never truncated, only the variable `body` in between.
    """
    overhead = _display_width(prefix) + _display_width(suffix)
    budget = max_width - overhead
    return f"{prefix}{_truncate(body, budget)}{suffix}"


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
