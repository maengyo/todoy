from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from todoy.display.characters import Character
from todoy.display.overlay.base import OverlayOptions, PanelActions, create_backend


def test_create_backend_raises_helpful_error_on_non_darwin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")

    with pytest.raises(RuntimeError) as exc_info:
        create_backend()

    assert "macOS" in str(exc_info.value)


def test_create_backend_error_mentions_install_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")

    with pytest.raises(RuntimeError) as exc_info:
        create_backend()

    assert "todoy[overlay]" in str(exc_info.value)


@pytest.mark.parametrize(
    "module_name",
    ["todoy.display.overlay", "todoy.display.overlay.base"],
)
def test_importing_overlay_package_does_not_import_appkit(module_name: str) -> None:
    # Run in a fresh subprocess (not this test process) so we get a clean
    # sys.modules unpolluted by any other test that may have imported the
    # real macos backend (or monkeypatched a fake AppKit) earlier in the run.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import {module_name}; import sys; print('AppKit' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "False"


def test_create_backend_raises_when_appkit_missing_on_darwin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setitem(sys.modules, "AppKit", None)

    with pytest.raises(RuntimeError) as exc_info:
        create_backend()

    assert "todoy[overlay]" in str(exc_info.value)


def test_overlay_options_movement_and_bubble_effect_default() -> None:
    options = OverlayOptions(
        character=Character(name="cat", emoji="🐱", ascii_art="(=^.^=)"),
        character_image=None,
        language="en",
        test_seconds=None,
    )

    assert options.movement == "walk"
    assert options.bubble_effect == "pop"
    assert options.message_style == "bubble"


def test_overlay_options_movement_and_bubble_effect_overridable() -> None:
    options = OverlayOptions(
        character=Character(name="cat", emoji="🐱", ascii_art="(=^.^=)"),
        character_image=Path("/tmp/does-not-exist.png"),
        language="ko",
        test_seconds=5.0,
        movement="hop",
        bubble_effect="shake",
        message_style="flag",
    )

    assert options.movement == "hop"
    assert options.bubble_effect == "shake"
    assert options.message_style == "flag"


# --- PanelActions: pure, AppKit-free -----------------------------------------


def _noop_panel_actions() -> PanelActions:
    return PanelActions(
        add=lambda text, at: None,
        set_done=lambda todo_id: None,
        delete=lambda todo_id: None,
        set_pinned=lambda todo_id, pinned: None,
    )


def test_panel_actions_holds_the_four_callables_and_forwards_arguments() -> None:
    calls: list[tuple[str, tuple]] = []

    actions = PanelActions(
        add=lambda text, at: calls.append(("add", (text, at))),
        set_done=lambda todo_id: calls.append(("set_done", (todo_id,))),
        delete=lambda todo_id: calls.append(("delete", (todo_id,))),
        set_pinned=lambda todo_id, pinned: calls.append(("set_pinned", (todo_id, pinned))),
    )

    actions.add("buy milk", "09:30")
    actions.set_done(1)
    actions.delete(2)
    actions.set_pinned(3, True)

    assert calls == [
        ("add", ("buy milk", "09:30")),
        ("set_done", (1,)),
        ("delete", (2,)),
        ("set_pinned", (3, True)),
    ]


def test_panel_actions_callables_return_error_string_or_none() -> None:
    actions = PanelActions(
        add=lambda text, at: "invalid time" if at == "bad" else None,
        set_done=lambda todo_id: "no such todo" if todo_id == 99 else None,
        delete=lambda todo_id: None,
        set_pinned=lambda todo_id, pinned: None,
    )

    assert actions.add("x", "bad") == "invalid time"
    assert actions.add("x", "09:30") is None
    assert actions.set_done(99) == "no such todo"
    assert actions.set_done(1) is None


def test_panel_actions_is_a_frozen_dataclass() -> None:
    actions = _noop_panel_actions()

    with pytest.raises(AttributeError):
        actions.add = lambda text, at: None  # type: ignore[method-assign]


def test_overlay_backend_protocol_run_accepts_actions_as_fifth_positional_argument() -> None:
    """A fake backend conforming to the (structural) `OverlayBackend`
    protocol must accept `actions: PanelActions` as its 5th parameter --
    checked without importing AppKit, so this runs on any OS.
    """

    class FakeBackend:
        def run(self, options, scheduler, get_reminder_text, get_todos, actions) -> int:
            assert isinstance(actions, PanelActions)
            return 0

    options = OverlayOptions(
        character=Character(name="cat", emoji="🐱", ascii_art="(=^.^=)"),
        character_image=None,
        language="en",
        test_seconds=0.0,
    )

    exit_code = FakeBackend().run(options, object(), lambda: "", lambda: [], _noop_panel_actions())

    assert exit_code == 0


# --- macOS backend: alarm vs. interval-reminder interleaving -----------------
#
# Everything else in this file stays import-safe on any OS (see
# test_importing_overlay_package_does_not_import_appkit above); AppKit is
# only ever imported inside this one guarded test, and only on macOS with
# the `overlay` extra installed (the exact condition macOS CI runs under --
# see .github/workflows/ci.yml).


def test_backend_defers_interval_reminder_while_alarm_bubble_is_visible() -> None:
    """Regression: a due interval reminder used to REPLACE a still-visible
    alarm bubble on the very next 1s tick (the alarm's own `due()` is only
    non-empty on the tick it first fires). It must instead be held off until
    the alarm bubble clears, then resume on the next tick without needing
    the interval scheduler's own cadence to be disturbed in between.
    """
    if sys.platform != "darwin":
        pytest.skip("AppKit only available on macOS")
    pytest.importorskip("AppKit")

    import AppKit

    from todoy.display.overlay.core import ReminderScheduler
    from todoy.display.overlay.macos import _OverlayController
    from todoy.models import Todo

    class ForcedClock:
        """A settable monotonic-style clock, matching ReminderScheduler's
        `now: Callable[[], float]` -- lets should_fire() be forced True
        without waiting on real time.
        """

        def __init__(self, value: float) -> None:
            self.value = value

        def __call__(self) -> float:
            return self.value

    clock = ForcedClock(0.0)
    scheduler = ReminderScheduler(interval_minutes=1, snooze_minutes=5, now=clock)
    clock.value = 61.0  # interval elapsed -- should_fire() is now True

    reminder_calls: list[str] = []

    def get_reminder_text() -> str:
        reminder_calls.append("shown")
        return "REMINDER-MARKER"

    def get_todos() -> list[Todo]:
        # No `at` here on purpose: alarm_clock.update() must yield due()==[]
        # on every tick in this test, so the alarm branch of onReminderTick_
        # never re-triggers on its own -- isolating exactly the "already
        # fired, still visible" interleaving this test targets.
        return []

    options = OverlayOptions(
        character=Character(name="cat", emoji="🐱", ascii_art="(=^.^=)"),
        character_image=None,
        language="en",
        test_seconds=None,
    )

    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

    controller = _OverlayController.alloc().init()
    controller.configure(
        options, scheduler, get_reminder_text, get_todos, _noop_panel_actions(), app
    )
    try:
        controller.start()

        # Simulate an alarm that fired on an earlier tick and is still on
        # screen (exactly what onReminderTick_ leaves behind after showing
        # one: due() goes back to [] on the very next update()).
        controller._show_alarm([Todo(text="회의", at="09:00", id=1, source="builtin")])
        assert controller._showing_alarm is True
        assert controller.bubble_window.isVisible() is True

        # The interval reminder is due, but must not clobber the alarm.
        controller.onReminderTick_(None)

        assert reminder_calls == []
        assert controller._showing_alarm is True
        assert "⏰" in str(controller.bubble_text_field.stringValue())
        assert scheduler.should_fire() is True  # cadence left untouched

        # Once the alarm clears (auto-hide/snooze/etc.), the deferred
        # reminder resumes on the very next tick.
        controller._hide_bubble()
        controller.onReminderTick_(None)

        assert reminder_calls == ["shown"]
        assert controller._showing_alarm is False
        assert str(controller.bubble_text_field.stringValue()) == "REMINDER-MARKER"
        assert scheduler.should_fire() is False  # now properly consumed
    finally:
        controller._invalidate_all_timers()


# --- macOS backend: compact `flag` message style ------------------------------


def _build_flag_controller(scheduler, get_todos):
    """Build+start a real `_OverlayController` configured for `message_style
    ="flag"`, wired to `scheduler`/`get_todos`. Caller invalidates timers in
    a `finally` block, same as the alarm-interleaving test above.
    """
    import AppKit

    from todoy.display.overlay.macos import _OverlayController

    options = OverlayOptions(
        character=Character(name="cat", emoji="🐱", ascii_art="(=^.^=)"),
        character_image=None,
        language="en",
        test_seconds=None,
        message_style="flag",
    )

    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

    controller = _OverlayController.alloc().init()
    controller.configure(
        options,
        scheduler,
        lambda: "UNUSED-IN-FLAG-MODE",
        get_todos,
        _noop_panel_actions(),
        app,
    )
    controller.start()
    return controller


def test_flag_shows_single_line_pennant_text_from_build_flag_line() -> None:
    if sys.platform != "darwin":
        pytest.skip("AppKit only available on macOS")
    pytest.importorskip("AppKit")

    from todoy.display.overlay.core import ReminderScheduler, build_flag_line
    from todoy.models import Todo

    todos = [Todo(text="water plants", id=1, source="builtin")]
    scheduler = ReminderScheduler(interval_minutes=30, snooze_minutes=5)
    controller = _build_flag_controller(scheduler, lambda: todos)
    try:
        controller._show_reminder()

        assert controller.bubble_window is not None
        assert controller.bubble_window.isVisible() is True
        content = controller.bubble_window.contentView()
        expected = build_flag_line(todos, "en")

        assert str(content._text.string()) == expected
        assert "\n" not in expected  # single line, per the compact-flag contract
    finally:
        controller._invalidate_all_timers()


def test_flag_click_snoozes_interval_reminder_and_hides_the_pennant() -> None:
    if sys.platform != "darwin":
        pytest.skip("AppKit only available on macOS")
    pytest.importorskip("AppKit")

    from todoy.display.overlay.core import ReminderScheduler
    from todoy.models import Todo

    class ForcedClock:
        def __init__(self, value: float) -> None:
            self.value = value

        def __call__(self) -> float:
            return self.value

    clock = ForcedClock(0.0)
    scheduler = ReminderScheduler(interval_minutes=1, snooze_minutes=5, now=clock)
    controller = _build_flag_controller(
        scheduler, lambda: [Todo(text="water plants", id=1, source="builtin")]
    )
    try:
        controller._show_reminder()
        assert controller.bubble_window.isVisible() is True

        # Programmatic click on the pennant -- no buttons on this style, the
        # whole panel is the click target.
        controller.bubble_window.contentView().mouseDown_(None)

        assert controller.bubble_window.isVisible() is False  # hidden after click
        # Scheduler's fire target moved out to snooze_minutes from "now".
        assert scheduler.should_fire() is False
        assert scheduler.seconds_until_fire() == pytest.approx(5 * 60)
    finally:
        controller._invalidate_all_timers()


def test_flag_click_snoozes_alarm_via_alarm_clock_and_hides_the_pennant() -> None:
    if sys.platform != "darwin":
        pytest.skip("AppKit only available on macOS")
    pytest.importorskip("AppKit")

    from datetime import datetime

    from todoy.display.overlay.core import AlarmClock, ReminderScheduler
    from todoy.models import Todo

    class FakeDateTimeClock:
        def __init__(self, start: datetime) -> None:
            self._now = start

        def __call__(self) -> datetime:
            return self._now

    scheduler = ReminderScheduler(interval_minutes=30, snooze_minutes=5)
    controller = _build_flag_controller(scheduler, lambda: [])
    try:
        # Drive alarm_clock the same way onReminderTick_ does (update() then
        # due()) so _last_fired is populated for real, instead of poking at
        # it directly -- then exercise the click handler on top of that.
        fake_clock = FakeDateTimeClock(datetime(2026, 8, 20, 14, 0))
        controller.alarm_clock = AlarmClock(scheduler.snooze_minutes, now=fake_clock)
        todo = Todo(text="회의", at="14:00", id=1, source="builtin")
        controller.alarm_clock.update([todo])
        due = controller.alarm_clock.due()
        assert due == [todo]

        controller._show_alarm(due)
        assert controller._showing_alarm is True
        assert controller.alarm_clock._last_fired == [todo]
        assert controller.bubble_window.isVisible() is True

        controller.bubble_window.contentView().mouseDown_(None)

        assert controller.bubble_window.isVisible() is False  # hidden after click
        # snooze_last() re-armed the fired alarm and cleared _last_fired --
        # the same alarm-aware branch the bubble's Snooze button takes.
        assert controller.alarm_clock._last_fired == []
    finally:
        controller._invalidate_all_timers()


def test_flag_auto_hide_timer_uses_ten_seconds_not_thirty() -> None:
    if sys.platform != "darwin":
        pytest.skip("AppKit only available on macOS")
    pytest.importorskip("AppKit")

    from todoy.display.overlay.core import ReminderScheduler
    from todoy.display.overlay.macos import FLAG_AUTO_HIDE_SECONDS

    scheduler = ReminderScheduler(interval_minutes=30, snooze_minutes=5)
    controller = _build_flag_controller(scheduler, lambda: [])
    try:
        controller._show_reminder()

        # NSTimer.timeInterval() reads back as 0 for non-repeating timers
        # (documented Apple behavior) -- fireDate vs. now is the actual
        # scheduled delay.
        assert controller.hide_timer is not None
        seconds_until_fire = controller.hide_timer.fireDate().timeIntervalSinceNow()
        assert seconds_until_fire == pytest.approx(FLAG_AUTO_HIDE_SECONDS, abs=1.0)
        assert FLAG_AUTO_HIDE_SECONDS == 10.0
    finally:
        controller._invalidate_all_timers()


def test_bubble_auto_hide_timer_still_uses_thirty_seconds() -> None:
    # Regression: flag's shorter auto-hide must not leak into bubble mode.
    if sys.platform != "darwin":
        pytest.skip("AppKit only available on macOS")
    pytest.importorskip("AppKit")

    import AppKit

    from todoy.display.overlay.core import ReminderScheduler
    from todoy.display.overlay.macos import BUBBLE_AUTO_HIDE_SECONDS, _OverlayController

    scheduler = ReminderScheduler(interval_minutes=30, snooze_minutes=5)
    options = OverlayOptions(
        character=Character(name="cat", emoji="🐱", ascii_art="(=^.^=)"),
        character_image=None,
        language="en",
        test_seconds=None,
    )
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    controller = _OverlayController.alloc().init()
    controller.configure(options, scheduler, lambda: "x", lambda: [], _noop_panel_actions(), app)
    try:
        controller.start()
        controller._show_reminder()

        assert controller.hide_timer is not None
        seconds_until_fire = controller.hide_timer.fireDate().timeIntervalSinceNow()
        assert seconds_until_fire == pytest.approx(BUBBLE_AUTO_HIDE_SECONDS, abs=1.0)
        assert BUBBLE_AUTO_HIDE_SECONDS == 30.0
    finally:
        controller._invalidate_all_timers()


def test_flag_flutter_notch_offset_varies_across_samples() -> None:
    if sys.platform != "darwin":
        pytest.skip("AppKit only available on macOS")
    pytest.importorskip("AppKit")

    from todoy.display.overlay.macos import FLAG_FLUTTER_AMPLITUDE_PX, _flutter_notch_offset

    samples = [_flutter_notch_offset(t) for t in (0.0, 0.02, 0.05, 0.09, 0.14)]

    assert len({round(s, 9) for s in samples}) > 1  # not a constant
    assert all(abs(s) <= FLAG_FLUTTER_AMPLITUDE_PX + 1e-9 for s in samples)


def test_flag_show_starts_flutter_timer_and_offset_changes_over_ticks() -> None:
    if sys.platform != "darwin":
        pytest.skip("AppKit only available on macOS")
    pytest.importorskip("AppKit")

    from todoy.display.overlay.core import ReminderScheduler
    from todoy.models import Todo

    scheduler = ReminderScheduler(interval_minutes=30, snooze_minutes=5)
    controller = _build_flag_controller(
        scheduler, lambda: [Todo(text="water plants", id=1, source="builtin")]
    )
    try:
        controller._show_reminder()

        assert controller.flutter_timer is not None
        view = controller.flag_view
        assert view is not None

        first_offset = view.flutter_offset
        controller._flutter_start -= 0.05  # simulate elapsed time without a real sleep
        controller._apply_flutter_frame()

        assert view.flutter_offset != first_offset  # the flutter visibly changed
    finally:
        controller._invalidate_all_timers()


def test_status_item_right_click_menu_contains_quit_todoy_in_flag_style() -> None:
    if sys.platform != "darwin":
        pytest.skip("AppKit only available on macOS")
    pytest.importorskip("AppKit")

    from todoy.display.overlay.core import ReminderScheduler

    scheduler = ReminderScheduler(interval_minutes=30, snooze_minutes=5)
    controller = _build_flag_controller(scheduler, lambda: [])
    try:
        _assert_status_menu_has_quit_todoy(controller)
    finally:
        controller._invalidate_all_timers()


def test_status_item_right_click_menu_contains_quit_todoy_in_bubble_style_too() -> None:
    # Regression: the Quit menu is built once in _build_status_item, shared
    # by both message styles -- confirm it's not accidentally flag-only.
    if sys.platform != "darwin":
        pytest.skip("AppKit only available on macOS")
    pytest.importorskip("AppKit")

    import AppKit

    from todoy.display.overlay.core import ReminderScheduler
    from todoy.display.overlay.macos import _OverlayController

    scheduler = ReminderScheduler(interval_minutes=30, snooze_minutes=5)
    options = OverlayOptions(
        character=Character(name="cat", emoji="🐱", ascii_art="(=^.^=)"),
        character_image=None,
        language="en",
        test_seconds=None,
        # message_style defaults to "bubble" -- deliberately not overridden.
    )
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    controller = _OverlayController.alloc().init()
    controller.configure(options, scheduler, lambda: "x", lambda: [], _noop_panel_actions(), app)
    try:
        controller.start()
        assert controller.options.message_style == "bubble"
        _assert_status_menu_has_quit_todoy(controller)
    finally:
        controller._invalidate_all_timers()


def _assert_status_menu_has_quit_todoy(controller) -> None:
    assert controller.status_menu is not None
    titles = [
        str(controller.status_menu.itemAtIndex_(i).title())
        for i in range(controller.status_menu.numberOfItems())
    ]
    assert "Quit todoy" in titles

    quit_item = controller.status_menu.itemAtIndex_(titles.index("Quit todoy"))
    assert str(quit_item.action()) == "onQuitClicked:"
    assert quit_item.target() is controller


# --- macOS backend: flag pennant width must fit its widest legal text -------
#
# Regression for a Codex review finding on Task 25: FLAG_MAX_WIDTH used to be
# clamped well below the pixel width some legal (<=38-display-column)
# build_flag_line/build_alarm_flag_line outputs actually render at, so the
# widest lines got visually clipped -- violating "width fits the text +
# padding". This scans every printable-ASCII single-character repeat (the
# empirical worst case -- see the comment on FLAG_MAX_WIDTH) through both
# builders and both languages, measures each with the REAL flag font via
# _build_flag_attributed_text, and asserts none of them would be clamped.


def test_flag_max_width_fits_every_widest_legal_line() -> None:
    if sys.platform != "darwin":
        pytest.skip("AppKit only available on macOS")
    pytest.importorskip("AppKit")

    import string

    from todoy.display.overlay.core import build_alarm_flag_line, build_flag_line
    from todoy.display.overlay.macos import (
        FLAG_MAX_WIDTH,
        FLAG_NOTCH_DEPTH,
        FLAG_TEXT_PADDING_LEFT,
        FLAG_TEXT_PADDING_RIGHT,
        _build_flag_attributed_text,
    )
    from todoy.models import Todo

    worst_content_width = 0.0
    worst_line = ""
    candidate_chars = [c for c in string.printable if c.isprintable() and c != " "]
    for ch in candidate_chars:
        long_text = ch * 100  # long enough that every builder truncates it
        for language in ("en", "ko"):
            for line in (
                build_flag_line([Todo(text=long_text, id=1, source="builtin")], language),
                build_alarm_flag_line(
                    [Todo(text=long_text, at="23:59", id=1, source="builtin")], language
                ),
                # Multi-todo variant: a long first todo plus a "(+N)" suffix.
                build_flag_line(
                    [
                        Todo(text=long_text, id=1, source="builtin"),
                        Todo(text="x", id=2, source="builtin"),
                        Todo(text="y", id=3, source="builtin"),
                    ],
                    language,
                ),
            ):
                text_width = _build_flag_attributed_text(line).size().width
                content_width = (
                    text_width + FLAG_TEXT_PADDING_LEFT + FLAG_TEXT_PADDING_RIGHT + FLAG_NOTCH_DEPTH
                )
                if content_width > worst_content_width:
                    worst_content_width = content_width
                    worst_line = line

    assert worst_content_width <= FLAG_MAX_WIDTH, (
        f"widest legal line {worst_line!r} needs {worst_content_width:.1f}px of "
        f"content width, which exceeds FLAG_MAX_WIDTH={FLAG_MAX_WIDTH} and would "
        f"be clamped/clipped"
    )


def test_flag_window_grows_to_fit_a_long_line_without_clamping() -> None:
    """End-to-end (not just the measurement scan above): a real long todo
    actually produces a window wide enough for its text, with entrance
    animation disabled so the frame reflects the final size immediately.
    """
    if sys.platform != "darwin":
        pytest.skip("AppKit only available on macOS")
    pytest.importorskip("AppKit")

    import AppKit

    from todoy.display.overlay.core import ReminderScheduler
    from todoy.display.overlay.macos import (
        FLAG_NOTCH_DEPTH,
        FLAG_TEXT_PADDING_LEFT,
        FLAG_TEXT_PADDING_RIGHT,
        _OverlayController,
    )
    from todoy.models import Todo

    scheduler = ReminderScheduler(interval_minutes=30, snooze_minutes=5)
    options = OverlayOptions(
        character=Character(name="cat", emoji="🐱", ascii_art="(=^.^=)"),
        character_image=None,
        language="en",
        test_seconds=None,
        message_style="flag",
        bubble_effect="none",  # so window.frame() is the final size immediately
    )
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    controller = _OverlayController.alloc().init()
    long_todo = Todo(text="%" * 100, id=1, source="builtin")
    controller.configure(
        options, scheduler, lambda: "x", lambda: [long_todo], _noop_panel_actions(), app
    )
    try:
        controller.start()
        controller._show_reminder()

        view = controller.flag_view
        assert view is not None
        text_width = view._text.size().width
        content_width = (
            text_width + FLAG_TEXT_PADDING_LEFT + FLAG_TEXT_PADDING_RIGHT + (FLAG_NOTCH_DEPTH)
        )

        window_width = controller.bubble_window.frame().size.width
        assert window_width >= content_width - 1.0  # not clamped narrower than its text
    finally:
        controller._invalidate_all_timers()
