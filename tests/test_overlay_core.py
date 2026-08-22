from __future__ import annotations

import random
import unicodedata
from datetime import datetime, timedelta

import pytest

from todoy.display.messages import _VOICES
from todoy.display.overlay.core import (
    AlarmClock,
    ReminderScheduler,
    build_alarm_flag_line,
    build_alarm_text,
    build_flag_line,
    build_reminder_text,
)
from todoy.models import Todo


def _display_width(text: str) -> int:
    """Mirror core's east_asian_width-based column counting for assertions."""
    return sum(2 if unicodedata.east_asian_width(ch) in {"W", "F"} else 1 for ch in text)


def _todo(
    text: str, at: str | None = None, *, id: int | None = None, source: str = "builtin"
) -> Todo:
    """Build a `Todo` with an alarm time -- a thin convenience wrapper so the
    tests below read as `_todo("회의", at="14:00")` instead of repeating the
    other three (irrelevant, defaulted) `Todo` fields everywhere.
    """
    return Todo(text=text, at=at, id=id, source=source)


class FakeClock:
    """A settable monotonic-style clock for deterministic scheduler tests."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


class FakeDateTimeClock:
    """A settable wall-clock-style clock for deterministic AlarmClock tests."""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, **kwargs: float) -> None:
        self._now += timedelta(**kwargs)

    def set(self, value: datetime) -> None:
        self._now = value


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


# --- ReminderScheduler input validation --------------------------------------


def test_scheduler_rejects_zero_interval_minutes() -> None:
    with pytest.raises(ValueError, match="reminder interval must be a positive number of minutes"):
        ReminderScheduler(interval_minutes=0, snooze_minutes=5)


def test_scheduler_rejects_negative_interval_minutes() -> None:
    with pytest.raises(ValueError, match="reminder interval must be a positive number of minutes"):
        ReminderScheduler(interval_minutes=-5, snooze_minutes=5)


def test_scheduler_rejects_zero_snooze_minutes() -> None:
    with pytest.raises(ValueError, match="snooze duration must be a positive number of minutes"):
        ReminderScheduler(interval_minutes=30, snooze_minutes=0)


def test_scheduler_rejects_negative_snooze_minutes() -> None:
    with pytest.raises(ValueError, match="snooze duration must be a positive number of minutes"):
        ReminderScheduler(interval_minutes=30, snooze_minutes=-1)


def test_scheduler_zero_interval_never_fires_continuously_once_rejected() -> None:
    # Regression for the reported bug: interval_minutes=0 used to be accepted
    # and should_fire() returned True immediately after every fired() call,
    # so reminders fired on every ~1s poll tick instead of once per interval.
    # Construction must now fail fast instead of producing that broken state.
    with pytest.raises(ValueError):
        ReminderScheduler(interval_minutes=0, snooze_minutes=5)


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


def test_build_reminder_text_passes_voice_to_taunt_headline() -> None:
    todos = [Todo(text="oil gears", id=1, source="builtin")]

    text = build_reminder_text(todos, "en", rng=random.Random(3), voice="robotic")
    headline = text.split("\n", 1)[0]

    assert headline in [line.format(count=1) for line in _VOICES["robotic"]["en"]["taunt"]]


def test_build_reminder_text_zero_todos_uses_voice_congrats() -> None:
    text = build_reminder_text([], "ko", rng=random.Random(3), voice="feline")

    assert text in [line.format(count=0) for line in _VOICES["feline"]["ko"]["congrats"]]


# --- AlarmClock ---------------------------------------------------------------


def test_alarm_fires_at_exact_scheduled_minute() -> None:
    clock = FakeDateTimeClock(datetime(2026, 8, 20, 14, 0))
    alarm = AlarmClock(snooze_minutes=5, now=clock)
    todo = _todo("회의", at="14:00")

    alarm.update([todo])

    assert alarm.due() == [todo]


def test_alarm_does_not_fire_before_scheduled_minute() -> None:
    clock = FakeDateTimeClock(datetime(2026, 8, 20, 13, 59))
    alarm = AlarmClock(snooze_minutes=5, now=clock)
    todo = _todo("회의", at="14:00")

    alarm.update([todo])

    assert alarm.due() == []


def test_alarm_missed_within_ten_minutes_fires_once_as_catch_up() -> None:
    clock = FakeDateTimeClock(datetime(2026, 8, 20, 14, 9))  # overlay woke up late
    alarm = AlarmClock(snooze_minutes=5, now=clock)
    todo = _todo("회의", at="14:00")

    alarm.update([todo])
    assert alarm.due() == [todo]

    # Does not refire on the very next tick either.
    clock.advance(seconds=1)
    alarm.update([todo])
    assert alarm.due() == []


def test_alarm_missed_by_more_than_ten_minutes_is_skipped_silently() -> None:
    clock = FakeDateTimeClock(datetime(2026, 8, 20, 14, 11))
    alarm = AlarmClock(snooze_minutes=5, now=clock)
    todo = _todo("회의", at="14:00")

    alarm.update([todo])
    assert alarm.due() == []

    # And it stays skipped forever after -- the gap only grows.
    clock.advance(hours=1)
    alarm.update([todo])
    assert alarm.due() == []


def test_alarm_fired_today_never_refires_on_later_ticks() -> None:
    clock = FakeDateTimeClock(datetime(2026, 8, 20, 14, 0))
    alarm = AlarmClock(snooze_minutes=5, now=clock)
    todo = _todo("회의", at="14:00")

    alarm.update([todo])
    assert alarm.due() == [todo]

    clock.advance(seconds=30)
    alarm.update([todo])
    assert alarm.due() == []

    clock.advance(minutes=5)
    alarm.update([todo])
    assert alarm.due() == []


def test_alarm_snooze_last_refires_after_snooze_minutes() -> None:
    clock = FakeDateTimeClock(datetime(2026, 8, 20, 14, 0))
    alarm = AlarmClock(snooze_minutes=5, now=clock)
    todo = _todo("회의", at="14:00")

    alarm.update([todo])
    assert alarm.due() == [todo]

    alarm.snooze_last()
    assert alarm.due() == []

    clock.advance(minutes=4, seconds=59)
    alarm.update([todo])
    assert alarm.due() == []  # not yet -- still inside the snooze window

    clock.advance(seconds=1)
    alarm.update([todo])
    assert alarm.due() == [todo]

    # And after re-firing via snooze, it goes back to not refiring again.
    clock.advance(seconds=1)
    alarm.update([todo])
    assert alarm.due() == []


def test_alarm_snooze_last_with_nothing_due_is_a_no_op() -> None:
    clock = FakeDateTimeClock(datetime(2026, 8, 20, 14, 0))
    alarm = AlarmClock(snooze_minutes=5, now=clock)

    alarm.snooze_last()  # must not raise

    assert alarm.due() == []


def test_alarm_snooze_last_works_several_empty_ticks_after_firing() -> None:
    # Regression: due() is only non-empty on the exact tick something fires;
    # a backend polls every ~1s, so by the time a user actually clicks
    # Snooze several ticks later, due() has long since gone back to [].
    # snooze_last() must still act on the alarm that's still on screen.
    clock = FakeDateTimeClock(datetime(2026, 8, 20, 14, 0))
    alarm = AlarmClock(snooze_minutes=5, now=clock)
    todo = _todo("회의", at="14:00")

    alarm.update([todo])
    assert alarm.due() == [todo]

    # Several more ticks pass with the alarm already fired (due() empty),
    # exactly as a real 1s-polling backend would see while the bubble sits
    # on screen waiting for a user click.
    for _ in range(5):
        clock.advance(seconds=1)
        alarm.update([todo])
        assert alarm.due() == []

    alarm.snooze_last()  # must still re-arm the todo that fired 5 ticks ago

    clock.advance(minutes=5)
    alarm.update([todo])
    assert alarm.due() == [todo]


def test_alarm_snooze_last_spanning_midnight_still_refires() -> None:
    # Regression: rollover used to wipe pending snoozes outright, and even
    # once it didn't, a same-day-only identity key would still fail to match
    # after the date changed underneath it.
    clock = FakeDateTimeClock(datetime(2026, 8, 20, 23, 58))
    alarm = AlarmClock(snooze_minutes=10, now=clock)
    todo = _todo("회의", at="23:58")

    alarm.update([todo])
    assert alarm.due() == [todo]

    alarm.snooze_last()

    clock.set(datetime(2026, 8, 21, 0, 7, 59))
    alarm.update([todo])
    assert alarm.due() == []  # not yet -- 1s short of the snooze target

    clock.set(datetime(2026, 8, 21, 0, 8, 0))
    alarm.update([todo])
    assert alarm.due() == [todo]  # fires the next day, as snoozed

    # And it still won't refire again for the (new) rest of that day.
    clock.advance(seconds=1)
    alarm.update([todo])
    assert alarm.due() == []


def test_alarm_catch_up_at_exactly_ten_minutes_still_fires() -> None:
    # The catch-up window is inclusive: "within the last 10 minutes" means
    # exactly 10:00 late still counts, 10:01 late does not (the next test).
    clock = FakeDateTimeClock(datetime(2026, 8, 20, 14, 10))
    alarm = AlarmClock(snooze_minutes=5, now=clock)
    todo = _todo("회의", at="14:00")

    alarm.update([todo])

    assert alarm.due() == [todo]


def test_alarm_catch_up_one_second_past_ten_minutes_is_skipped() -> None:
    clock = FakeDateTimeClock(datetime(2026, 8, 20, 14, 10, 1))
    alarm = AlarmClock(snooze_minutes=5, now=clock)
    todo = _todo("회의", at="14:00")

    alarm.update([todo])

    assert alarm.due() == []


def test_alarm_midnight_rollover_resets_fired_set() -> None:
    clock = FakeDateTimeClock(datetime(2026, 8, 20, 14, 0))
    alarm = AlarmClock(snooze_minutes=5, now=clock)
    todo = _todo("회의", at="14:00")

    alarm.update([todo])
    assert alarm.due() == [todo]

    clock.advance(seconds=30)
    alarm.update([todo])
    assert alarm.due() == []  # fired today already

    # Next day, same time-of-day -- a fresh alarm, must fire again.
    clock.set(datetime(2026, 8, 21, 14, 0))
    alarm.update([todo])
    assert alarm.due() == [todo]


def test_alarm_todos_without_at_are_ignored() -> None:
    clock = FakeDateTimeClock(datetime(2026, 8, 20, 14, 0))
    alarm = AlarmClock(snooze_minutes=5, now=clock)
    todo = _todo("no time set")  # at=None

    alarm.update([todo])

    assert alarm.due() == []


def test_alarm_removed_todo_does_not_fire() -> None:
    clock = FakeDateTimeClock(datetime(2026, 8, 20, 14, 0))
    alarm = AlarmClock(snooze_minutes=5, now=clock)
    todo = _todo("회의", at="14:00")

    # The todo was deleted/completed before the first tick that would have
    # seen it due -- update() is never even called with it in the list.
    alarm.update([])

    assert alarm.due() == []

    # Even if the same identity later reappears in the list mid-window, it
    # is a distinct call to update(); confirm it still behaves normally
    # (fires) rather than being permanently poisoned by the earlier absence.
    alarm.update([todo])
    assert alarm.due() == [todo]


def test_alarm_multiple_simultaneous_todos_all_fire() -> None:
    clock = FakeDateTimeClock(datetime(2026, 8, 20, 14, 0))
    alarm = AlarmClock(snooze_minutes=5, now=clock)
    first = _todo("회의", at="14:00")
    second = _todo("water plants", at="14:00")

    alarm.update([first, second])

    assert alarm.due() == [first, second]


def test_alarm_identity_includes_id_so_same_text_and_at_dont_collapse() -> None:
    # Regression: two DISTINCT builtin todos that happen to share the same
    # text and at (different ids) used to share one (date, at, text)
    # identity -- the first marked it fired and the second was silently
    # filtered out, even though it's a different todo entirely.
    clock = FakeDateTimeClock(datetime(2026, 8, 20, 14, 0))
    alarm = AlarmClock(snooze_minutes=5, now=clock)
    first = _todo("회의", at="14:00", id=1, source="builtin")
    second = _todo("회의", at="14:00", id=2, source="builtin")

    alarm.update([first, second])

    assert alarm.due() == [first, second]
    text = build_alarm_text(alarm.due(), "en")
    assert text.count("⏰ 14:00 회의") == 2


def test_alarm_identity_includes_source_for_builtin_vs_markdown_duplicates() -> None:
    # Same regression as above, but for a builtin todo and a read-only
    # (markdown) todo with identical text+at -- id is None on the markdown
    # side, so source is what disambiguates them.
    clock = FakeDateTimeClock(datetime(2026, 8, 20, 14, 0))
    alarm = AlarmClock(snooze_minutes=5, now=clock)
    builtin_todo = _todo("회의", at="14:00", id=1, source="builtin")
    markdown_todo = _todo("회의", at="14:00", id=None, source="markdown")

    alarm.update([builtin_todo, markdown_todo])

    assert alarm.due() == [builtin_todo, markdown_todo]


def test_alarm_snooze_last_re_arms_each_duplicate_todo_under_its_own_key() -> None:
    # snooze_last() must re-arm BOTH distinct todos, not collapse them onto
    # one shared snooze target either.
    clock = FakeDateTimeClock(datetime(2026, 8, 20, 14, 0))
    alarm = AlarmClock(snooze_minutes=5, now=clock)
    first = _todo("회의", at="14:00", id=1, source="builtin")
    second = _todo("회의", at="14:00", id=2, source="builtin")

    alarm.update([first, second])
    assert alarm.due() == [first, second]

    alarm.snooze_last()
    assert alarm.due() == []

    clock.advance(minutes=4, seconds=59)
    alarm.update([first, second])
    assert alarm.due() == []  # still inside the snooze window

    clock.advance(seconds=1)
    alarm.update([first, second])
    assert alarm.due() == [first, second]  # both refire together

    # And both go back to not refiring again afterward.
    clock.advance(seconds=1)
    alarm.update([first, second])
    assert alarm.due() == []


def test_alarm_clock_defaults_to_wall_clock_now() -> None:
    alarm = AlarmClock(snooze_minutes=5)

    # Just confirm no injected clock still works without raising.
    alarm.update([])

    assert alarm.due() == []


# --- build_alarm_text ----------------------------------------------------------


def test_build_alarm_text_empty_list_is_empty_string() -> None:
    assert build_alarm_text([], "en") == ""


def test_build_alarm_text_accepts_voice_keyword_for_signature_parity() -> None:
    assert build_alarm_text([], "en", voice="spooky") == ""


def test_build_alarm_text_single_due_todo_is_headline_then_text() -> None:
    todo = _todo("회의", at="14:00")

    text = build_alarm_text([todo], "en")

    assert text == "⏰ 14:00\n회의"


def test_build_alarm_text_excludes_taunt_and_only_shows_due_todos() -> None:
    todo = _todo("water plants", at="09:05")

    text = build_alarm_text([todo], "en")

    assert text == "⏰ 09:05\nwater plants"


def test_build_alarm_text_multiple_due_todos_one_combined_line_each() -> None:
    first = _todo("회의", at="14:00")
    second = _todo("water plants", at="14:00")

    text = build_alarm_text([first, second], "en")

    assert text == "⏰ 14:00 회의\n⏰ 14:00 water plants"


def test_build_alarm_text_sanitizes_control_characters() -> None:
    todo = _todo("danger\x07bell", at="09:00")

    text = build_alarm_text([todo], "en")

    assert "\x07" not in text
    assert "dangerbell" in text


def test_build_alarm_text_truncates_long_single_todo_text() -> None:
    todo = _todo("x" * 200, at="09:00")

    text = build_alarm_text([todo], "en")
    text_line = text.split("\n")[1]

    assert _display_width(text_line) <= 45
    assert text_line.endswith("…")


def test_build_alarm_text_truncates_long_multi_todo_line() -> None:
    first = _todo("x" * 200, at="09:00")
    second = _todo("y" * 200, at="09:00")

    text = build_alarm_text([first, second], "en")

    for line in text.split("\n"):
        assert _display_width(line) <= 45
        assert line.endswith("…")


# --- build_flag_line (compact fluttering flag) --------------------------------


def test_build_flag_line_zero_todos_en_is_constant_congrats() -> None:
    assert build_flag_line([], "en", rng=random.Random(1)) == "All clear 🎉"


def test_build_flag_line_zero_todos_ko_is_constant_congrats() -> None:
    assert build_flag_line([], "ko", rng=random.Random(1)) == "오늘 끝! 🎉"


def test_build_flag_line_zero_todos_is_not_drawn_from_taunt_pool() -> None:
    # Unlike build_reminder_text's congrats line, the flag's zero-todo line
    # is a fixed constant -- must not vary with rng.
    first = build_flag_line([], "en", rng=random.Random(1))
    second = build_flag_line([], "en", rng=random.Random(999))

    assert first == second == "All clear 🎉"


def test_build_flag_line_rng_is_optional() -> None:
    assert build_flag_line([], "en") == "All clear 🎉"


def test_build_flag_line_accepts_voice_keyword_for_signature_parity() -> None:
    todos = [Todo(text="write report", id=1, source="builtin")]

    assert build_flag_line(todos, "en", voice="knightly") == "1 to go: write report"


def test_build_flag_line_single_todo_en_has_no_count_suffix() -> None:
    todos = [Todo(text="write report", id=1, source="builtin")]

    text = build_flag_line(todos, "en")

    assert text == "1 to go: write report"


def test_build_flag_line_single_todo_ko_has_no_count_suffix() -> None:
    todos = [Todo(text="보고서 작성", id=1, source="builtin")]

    text = build_flag_line(todos, "ko")

    assert text == "할 일 1개: 보고서 작성"


def test_build_flag_line_includes_at_prefix_on_first_todo() -> None:
    todos = [_todo("회의", at="14:00")]

    text = build_flag_line(todos, "en")

    assert text == "1 to go: 14:00 회의"


def test_build_flag_line_multiple_todos_appends_count_suffix() -> None:
    todos = [
        Todo(text="a", id=1, source="builtin"),
        Todo(text="b", id=2, source="builtin"),
        Todo(text="c", id=3, source="builtin"),
    ]

    text = build_flag_line(todos, "en")

    assert text == "3 to go: a (+2)"


def test_build_flag_line_multiple_todos_appends_count_suffix_ko() -> None:
    todos = [
        Todo(text="a", id=1, source="builtin"),
        Todo(text="b", id=2, source="builtin"),
    ]

    text = build_flag_line(todos, "ko")

    assert text == "할 일 2개: a (+1)"


def test_build_flag_line_sanitizes_control_characters() -> None:
    todos = [Todo(text="danger\x07bell", id=1, source="builtin")]

    text = build_flag_line(todos, "en")

    assert "\x07" not in text
    assert "dangerbell" in text


def test_build_flag_line_truncates_whole_line_to_38_columns() -> None:
    todos = [Todo(text="x" * 200, id=1, source="builtin")]

    text = build_flag_line(todos, "en")

    assert _display_width(text) <= 38
    assert text.endswith("…")


def test_build_flag_line_truncates_korean_wide_text_by_display_width() -> None:
    todos = [Todo(text="가" * 30, id=1, source="builtin")]

    text = build_flag_line(todos, "en")

    assert _display_width(text) <= 38
    assert text.endswith("…")
    assert len(text) < 38


def test_build_flag_line_truncation_preserves_count_suffix() -> None:
    # The count suffix must survive truncation -- only the first todo's text
    # is shortened, never the "(+N)" tail that communicates there's more.
    todos = [
        Todo(text="x" * 200, id=1, source="builtin"),
        Todo(text="y", id=2, source="builtin"),
        Todo(text="z", id=3, source="builtin"),
    ]

    text = build_flag_line(todos, "en")

    assert _display_width(text) <= 38
    assert text.endswith(" (+2)")


# --- build_alarm_flag_line -----------------------------------------------------


def test_build_alarm_flag_line_empty_list_is_empty_string() -> None:
    assert build_alarm_flag_line([], "en") == ""


def test_build_alarm_flag_line_accepts_voice_keyword_for_signature_parity() -> None:
    assert build_alarm_flag_line([], "ko", voice="bouncy") == ""


def test_build_alarm_flag_line_single_due_todo_no_suffix() -> None:
    todo = _todo("회의", at="14:00")

    text = build_alarm_flag_line([todo], "en")

    assert text == "⏰ 14:00 회의"


def test_build_alarm_flag_line_multiple_due_appends_count_suffix() -> None:
    first = _todo("회의", at="14:00")
    second = _todo("water plants", at="14:00")

    text = build_alarm_flag_line([first, second], "en")

    assert text == "⏰ 14:00 회의 (+1)"


def test_build_alarm_flag_line_language_independent() -> None:
    todo = _todo("회의", at="14:00")

    assert build_alarm_flag_line([todo], "en") == build_alarm_flag_line([todo], "ko")


def test_build_alarm_flag_line_sanitizes_control_characters() -> None:
    todo = _todo("danger\x07bell", at="09:00")

    text = build_alarm_flag_line([todo], "en")

    assert "\x07" not in text
    assert "dangerbell" in text


def test_build_alarm_flag_line_truncates_whole_line_to_38_columns() -> None:
    todo = _todo("x" * 200, at="09:00")

    text = build_alarm_flag_line([todo], "en")

    assert _display_width(text) <= 38
    assert text.endswith("…")


def test_build_alarm_flag_line_truncation_preserves_count_suffix() -> None:
    first = _todo("x" * 200, at="09:00")
    second = _todo("y", at="09:00")

    text = build_alarm_flag_line([first, second], "en")

    assert _display_width(text) <= 38
    assert text.endswith(" (+1)")
