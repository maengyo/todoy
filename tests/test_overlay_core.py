from __future__ import annotations

import random
import unicodedata

import pytest

from todoy.display.overlay.core import ReminderScheduler, build_reminder_text
from todoy.models import Todo


def _display_width(text: str) -> int:
    """Mirror core's east_asian_width-based column counting for assertions."""
    return sum(2 if unicodedata.east_asian_width(ch) in {"W", "F"} else 1 for ch in text)


class FakeClock:
    """A settable monotonic-style clock for deterministic scheduler tests."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


# --- ReminderScheduler ------------------------------------------------------


def test_scheduler_initial_seconds_until_fire_equals_full_interval() -> None:
    clock = FakeClock()
    scheduler = ReminderScheduler(interval_minutes=30, snooze_minutes=5, now=clock)

    assert scheduler.seconds_until_fire() == pytest.approx(30 * 60)


def test_scheduler_should_not_fire_before_interval_elapsed() -> None:
    clock = FakeClock()
    scheduler = ReminderScheduler(interval_minutes=1, snooze_minutes=5, now=clock)

    clock.advance(59)

    assert scheduler.should_fire() is False


def test_scheduler_should_fire_once_interval_elapsed() -> None:
    clock = FakeClock()
    scheduler = ReminderScheduler(interval_minutes=1, snooze_minutes=5, now=clock)

    clock.advance(60)

    assert scheduler.should_fire() is True


def test_scheduler_seconds_until_fire_never_negative() -> None:
    clock = FakeClock()
    scheduler = ReminderScheduler(interval_minutes=1, snooze_minutes=5, now=clock)

    clock.advance(1000)

    assert scheduler.seconds_until_fire() == 0.0


def test_scheduler_fired_schedules_next_full_interval() -> None:
    clock = FakeClock()
    scheduler = ReminderScheduler(interval_minutes=1, snooze_minutes=5, now=clock)

    clock.advance(60)
    assert scheduler.should_fire() is True
    scheduler.fired()

    assert scheduler.should_fire() is False
    assert scheduler.seconds_until_fire() == pytest.approx(60)

    clock.advance(60)
    assert scheduler.should_fire() is True


def test_scheduler_snooze_schedules_snooze_minutes_from_now() -> None:
    clock = FakeClock()
    scheduler = ReminderScheduler(interval_minutes=30, snooze_minutes=5, now=clock)

    clock.advance(10)
    scheduler.snooze()

    assert scheduler.should_fire() is False
    assert scheduler.seconds_until_fire() == pytest.approx(5 * 60)


def test_scheduler_snooze_overrides_pending_fire() -> None:
    clock = FakeClock()
    scheduler = ReminderScheduler(interval_minutes=1, snooze_minutes=10, now=clock)

    clock.advance(60)
    assert scheduler.should_fire() is True

    scheduler.snooze()

    assert scheduler.should_fire() is False
    assert scheduler.seconds_until_fire() == pytest.approx(10 * 60)


def test_scheduler_uses_time_monotonic_by_default() -> None:
    scheduler = ReminderScheduler(interval_minutes=30, snooze_minutes=5)

    assert scheduler.seconds_until_fire() == pytest.approx(30 * 60, abs=1)


# --- build_reminder_text -----------------------------------------------------


def test_build_reminder_text_zero_todos_is_just_the_congrats_line() -> None:
    text = build_reminder_text([], "en", rng=random.Random(1))

    assert "\n" not in text
    assert text != ""


def test_build_reminder_text_includes_taunt_blank_line_and_todos() -> None:
    todos = [Todo(text="write report", id=1, source="builtin")]

    text = build_reminder_text(todos, "en", rng=random.Random(1))
    lines = text.split("\n")

    assert lines[1] == ""
    assert "[#1] write report" in lines[2]


def test_build_reminder_text_non_builtin_uses_bullet_prefix() -> None:
    todos = [Todo(text="water the plants", id=None, source="markdown")]

    text = build_reminder_text(todos, "en", rng=random.Random(1))

    assert "* water the plants" in text


def test_build_reminder_text_caps_at_five_lines_with_more_suffix() -> None:
    todos = [Todo(text=f"task {i}", id=i, source="builtin") for i in range(8)]

    text = build_reminder_text(todos, "en", rng=random.Random(1))

    assert "(+3 more)" in text
    todo_lines = [line for line in text.split("\n") if line.startswith("[#")]
    assert len(todo_lines) == 5


def test_build_reminder_text_no_more_suffix_when_five_or_fewer() -> None:
    todos = [Todo(text=f"task {i}", id=i, source="builtin") for i in range(5)]

    text = build_reminder_text(todos, "en", rng=random.Random(1))

    assert "more)" not in text


def test_build_reminder_text_sanitizes_control_characters() -> None:
    todos = [Todo(text="danger\x07bell", id=1, source="builtin")]

    text = build_reminder_text(todos, "en", rng=random.Random(1))

    assert "\x07" not in text
    assert "dangerbell" in text


def test_build_reminder_text_truncates_long_todo_lines() -> None:
    todos = [Todo(text="x" * 200, id=1, source="builtin")]

    text = build_reminder_text(todos, "en", rng=random.Random(1))
    todo_line = next(line for line in text.split("\n") if line.startswith("[#"))

    assert len(todo_line) <= 45
    assert todo_line.endswith("…")


def test_build_reminder_text_truncates_korean_wide_text_by_display_width() -> None:
    # Each Hangul syllable is display-width 2 (east_asian_width "W"), so 40 of
    # them (80 columns) must be truncated well before the raw-length cap of
    # 45 chars would kick in -- this exercises the display-width path, not
    # just len().
    todos = [Todo(text="가" * 40, id=1, source="builtin")]

    text = build_reminder_text(todos, "en", rng=random.Random(1))
    todo_line = next(line for line in text.split("\n") if line.startswith("[#"))

    assert _display_width(todo_line) <= 45
    assert todo_line.endswith("…")
    # Wide-char truncation must cut well short of the character-count cap
    # that would apply to narrow text, proving width (not length) was used.
    assert len(todo_line) < 45


def test_build_reminder_text_is_deterministic_with_seeded_rng() -> None:
    todos = [Todo(text="pay bills", id=1, source="builtin")]

    first = build_reminder_text(todos, "en", rng=random.Random(42))
    second = build_reminder_text(todos, "en", rng=random.Random(42))

    assert first == second


def test_build_reminder_text_korean_language() -> None:
    text = build_reminder_text([], "ko", rng=random.Random(1))

    assert text != ""
