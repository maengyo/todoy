from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from todoy.display.characters import Character
from todoy.display.overlay.base import OverlayOptions, PanelActions, create_backend
from todoy.display.overlay.personas import persona as lookup_persona


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


# --- macOS backend: persona wiring -- zones, banner, entrance, flourish -----
#
# M13 Task 32: `_OverlayController` looks up `personas.persona(character.
# name)` once at configure-time and wires it into character placement (zone),
# message-window placement (bubble-below-sky / banner-below), the launch
# entrance, and the fire-time flourish. These tests exercise the wiring
# itself (against real persona assignments from Task 31's frozen catalog),
# not the pure curve math in `personas.py`, which has its own test module.


def _build_persona_controller(
    character_name: str,
    *,
    message_style: str = "bubble",
    bubble_effect: str = "pop",
    get_todos=lambda: [],
):
    """Skip on non-macOS/no-pyobjc; otherwise build+start a real
    `_OverlayController` for `character_name` (looked up against the real
    `personas.PERSONAS` catalog) with a fast reminder-check cadence not
    needed here -- caller invalidates timers in a `finally` block, same as
    the other controller-builder helpers above.
    """
    if sys.platform != "darwin":
        pytest.skip("AppKit only available on macOS")
    pytest.importorskip("AppKit")

    import AppKit

    from todoy.display.overlay.core import ReminderScheduler
    from todoy.display.overlay.macos import _OverlayController

    options = OverlayOptions(
        character=Character(name=character_name, emoji="?", ascii_art="?"),
        character_image=None,
        language="en",
        test_seconds=None,
        message_style=message_style,
        bubble_effect=bubble_effect,
    )
    scheduler = ReminderScheduler(interval_minutes=30, snooze_minutes=5)
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

    controller = _OverlayController.alloc().init()
    controller.configure(options, scheduler, lambda: "x", get_todos, _noop_panel_actions(), app)
    controller.start()
    return controller


def _run_ticks(controller, count: int) -> None:
    """Drive `count` synthetic 30fps wander ticks (the same cadence
    `WANDER_TICK_SECONDS` schedules for real) without a real NSTimer/run
    loop -- used to fast-forward past a launch entrance in tests."""
    for _ in range(count):
        controller.onWanderTick_(None)


def test_controller_persona_matches_the_real_catalog_lookup() -> None:
    controller = _build_persona_controller("whale")
    try:
        assert controller.persona == lookup_persona("whale")
        assert controller.persona.zone == "water"
        assert controller.persona.entrance == "splash"
        assert controller.persona.flourish == "resurface"
        assert controller.persona.banner is False
    finally:
        controller._invalidate_all_timers()


def test_sky_zone_cruise_line_sits_near_the_top_of_the_screen() -> None:
    from todoy.display.overlay.macos import CHARACTER_WINDOW_SIZE

    controller = _build_persona_controller("butterfly")
    try:
        assert controller.persona.zone == "sky"
        screen_frame = controller._screen_frame()
        cruise_y = controller._character_zone_y(screen_frame, 0.0)
        # `_sky_top_margin()` is derived from the REAL screen's menu bar
        # clearance (Codex review follow-up), so this compares against it
        # directly rather than a fixed constant -- see
        # `test_menu_bar_clearance_px_uses_the_real_frame_vs_visible_frame_gap`
        # for the underlying pure-function coverage, and
        # `test_sky_top_margin_reflects_an_injected_menu_bar_height` for an
        # end-to-end check with a specific (37px) clearance.
        expected_cruise_y = (
            screen_frame.origin.y
            + screen_frame.size.height
            - CHARACTER_WINDOW_SIZE
            - controller._sky_top_margin()
        )
        assert cruise_y == pytest.approx(expected_cruise_y)
        # Well above the vertical midpoint of the screen -- "near the top".
        assert cruise_y > screen_frame.origin.y + screen_frame.size.height / 2.0
    finally:
        controller._invalidate_all_timers()


def test_menu_bar_clearance_px_uses_the_real_frame_vs_visible_frame_gap() -> None:
    """Pure-function coverage (Codex review follow-up: the sky cruise
    clearance used to hardcode a 24px guess; it's now derived from the
    screen's actual `frame()` vs `visibleFrame()` gap) -- module-level and
    struct-only, so this needs no real/faked `NSScreen` object, just two
    fake rects representing a screen with a taller (37px) menu bar/notch.
    """
    if sys.platform != "darwin":
        pytest.skip("AppKit only available on macOS")
    pytest.importorskip("AppKit")

    import Foundation

    from todoy.display.overlay.macos import _menu_bar_clearance_px

    screen_frame = Foundation.NSMakeRect(0, 0, 1440, 900)
    visible_frame = Foundation.NSMakeRect(0, 0, 1440, 900 - 37)  # 37px reserved at the top

    assert _menu_bar_clearance_px(screen_frame, visible_frame) == pytest.approx(37.0)


def test_menu_bar_clearance_px_is_zero_when_frames_match() -> None:
    if sys.platform != "darwin":
        pytest.skip("AppKit only available on macOS")
    pytest.importorskip("AppKit")

    import Foundation

    from todoy.display.overlay.macos import _menu_bar_clearance_px

    frame = Foundation.NSMakeRect(0, 0, 1440, 900)
    assert _menu_bar_clearance_px(frame, frame) == 0.0


def test_sky_top_margin_reflects_an_injected_menu_bar_height() -> None:
    """End-to-end (not just the pure function above): with `_sky_top_
    margin` wired to a 37px menu-bar clearance, the sky cruise line moves
    to match -- confirms `_character_zone_y` actually calls through to it
    rather than the fixed constant it used to use. `NSScreen.mainScreen`
    itself can't be monkeypatched (pyobjc raises on reassigning native
    selectors), so this patches the controller's own `_sky_top_margin`
    instance method instead -- a plain `@objc.python_method`, safe to
    override per-instance like any other Python attribute (already relied
    on elsewhere, e.g. swapping `controller.alarm_clock`).
    """
    from todoy.display.overlay.macos import (
        CHARACTER_WINDOW_SIZE,
        SKY_TOP_BUFFER_PX,
        _menu_bar_clearance_px,
    )

    controller = _build_persona_controller("butterfly")
    try:
        injected_margin = 37.0 + SKY_TOP_BUFFER_PX
        controller._sky_top_margin = lambda: injected_margin

        screen_frame = controller._screen_frame()
        cruise_y = controller._character_zone_y(screen_frame, 0.0)
        expected_cruise_y = (
            screen_frame.origin.y
            + screen_frame.size.height
            - CHARACTER_WINDOW_SIZE
            - injected_margin
        )
        assert cruise_y == pytest.approx(expected_cruise_y)

        # Sanity: the injected margin really does correspond to a taller
        # (37px) menu bar via the same pure function production code uses.
        import Foundation

        full = Foundation.NSMakeRect(0, 0, 1440, 900)
        visible = Foundation.NSMakeRect(0, 0, 1440, 900 - 37)
        assert _menu_bar_clearance_px(full, visible) == pytest.approx(37.0)
    finally:
        controller._invalidate_all_timers()


def test_sky_zone_bob_is_applied_downward_from_the_cruise_line() -> None:
    controller = _build_persona_controller("butterfly")
    try:
        screen_frame = controller._screen_frame()
        at_rest = controller._character_zone_y(screen_frame, 0.0)
        bobbing = controller._character_zone_y(screen_frame, 10.0)
        assert bobbing < at_rest  # a positive y_offset dips DOWN from the cruise line
    finally:
        controller._invalidate_all_timers()


def test_ground_zone_bob_is_still_applied_upward_from_the_baseline() -> None:
    # Regression: ground/water personas must keep their pre-M13 behavior --
    # the movement preset's y_offset LIFTS the character up off the bottom.
    controller = _build_persona_controller("cat")
    try:
        assert controller.persona.zone == "ground"
        screen_frame = controller._screen_frame()
        at_rest = controller._character_zone_y(screen_frame, 0.0)
        lifted = controller._character_zone_y(screen_frame, 10.0)
        assert lifted > at_rest
    finally:
        controller._invalidate_all_timers()


def test_bubble_message_goes_below_a_sky_character() -> None:
    controller = _build_persona_controller("butterfly", message_style="bubble")
    try:
        _run_ticks(controller, 90)  # fast-forward past the launch entrance
        controller._show_reminder()

        assert controller.char_window is not None
        assert controller.bubble_window is not None
        char_frame = controller.char_window.frame()
        bubble_frame = controller.bubble_window.frame()
        assert bubble_frame.origin.y < char_frame.origin.y
    finally:
        controller._invalidate_all_timers()


def test_bubble_message_still_goes_above_a_ground_character() -> None:
    # Regression: only sky characters flip the bubble below.
    controller = _build_persona_controller("cat", message_style="bubble")
    try:
        _run_ticks(controller, 90)
        controller._show_reminder()

        char_frame = controller.char_window.frame()
        bubble_frame = controller.bubble_window.frame()
        assert bubble_frame.origin.y > char_frame.origin.y
    finally:
        controller._invalidate_all_timers()


def test_banner_persona_hangs_the_flag_panel_below_the_character() -> None:
    from todoy.display.overlay.macos import _BannerPanelView

    controller = _build_persona_controller(
        "butterfly",
        message_style="flag",
        get_todos=lambda: [],
    )
    try:
        assert controller.persona.banner is True
        _run_ticks(controller, 90)
        controller._show_reminder()

        assert isinstance(controller.flag_view, _BannerPanelView)
        char_frame = controller.char_window.frame()
        banner_frame = controller.bubble_window.frame()
        # Hangs BELOW the character (its top edge sits at/near the
        # character's feet), not above it on a pole.
        assert banner_frame.origin.y < char_frame.origin.y
        assert banner_frame.origin.y + banner_frame.size.height <= char_frame.origin.y + 1.0
        # Still screen-clamped, per contract ("flag/banner clamped").
        screen_frame = controller._screen_frame()
        assert banner_frame.origin.x >= screen_frame.origin.x - 1.0
        assert (
            banner_frame.origin.x + banner_frame.size.width
            <= screen_frame.origin.x + screen_frame.size.width + 1.0
        )
    finally:
        controller._invalidate_all_timers()


def test_non_banner_persona_keeps_the_pole_above_flag() -> None:
    # Regression: personas without persona.banner keep the pre-M13 pole-
    # above pennant, not the new banner-below panel.
    from todoy.display.overlay.macos import _FlagPanelView

    controller = _build_persona_controller("cat", message_style="flag")
    try:
        assert controller.persona.banner is False
        _run_ticks(controller, 90)
        controller._show_reminder()

        assert isinstance(controller.flag_view, _FlagPanelView)
        char_frame = controller.char_window.frame()
        flag_frame = controller.bubble_window.frame()
        assert flag_frame.origin.y > char_frame.origin.y
    finally:
        controller._invalidate_all_timers()


def test_launch_entrance_runs_then_movement_resumes() -> None:
    """The persona's EntranceAnimation runs at launch; movement is held
    still (x never advances) while it's in progress, and resumes once it
    finishes -- contract section 2: "movement starts once finished."
    """
    controller = _build_persona_controller("whale")
    try:
        assert controller.entrance is not None  # running immediately at launch
        assert controller.movement is not None
        x_during_entrance = controller.movement.x

        _run_ticks(controller, 5)  # a few ticks -- still well inside 0.8-1.4s
        assert controller.entrance is not None
        assert controller.movement.x == pytest.approx(x_during_entrance)  # held still

        _run_ticks(controller, 90)  # >3s -- comfortably past any entrance duration
        assert controller.entrance is None  # finished

        x_after_finish = controller.movement.x
        _run_ticks(controller, 5)
        assert controller.movement.x != pytest.approx(x_after_finish)  # walking again
    finally:
        controller._invalidate_all_timers()


def test_flourish_starts_on_show_message_once_entrance_has_finished() -> None:
    controller = _build_persona_controller("whale")  # flourish == "resurface"
    try:
        _run_ticks(controller, 90)  # past the entrance
        assert controller.entrance is None

        controller._show_reminder()
        assert controller.flourish is not None

        # Additive: the message window/timers are unaffected by the flourish.
        assert controller.bubble_window is not None
        assert controller.bubble_window.isVisible() is True
        assert controller.hide_timer is not None
    finally:
        controller._invalidate_all_timers()


def test_flourish_is_deferred_not_dropped_while_the_entrance_is_in_progress() -> None:
    """Regression (Codex review, M13 Task 32 follow-up): an alarm CAN
    genuinely fire while the launch entrance is still running -- the 1s
    reminder-check tick races a 0.8-1.4s entrance, and an alarm's timing
    isn't bounded by `FIRST_FIRE_DELAY_SECONDS` the way the guaranteed
    first interval reminder is. The flourish used to be silently dropped
    in that race (`self.flourish` stayed `None` forever for that fire);
    it must instead be deferred and started the instant the entrance
    finishes.
    """
    controller = _build_persona_controller("whale")  # flourish == "resurface"
    try:
        assert controller.entrance is not None  # still running right after start()

        controller._show_reminder()

        # Not started yet (must not fight the entrance for the window
        # frame) -- but queued, not dropped.
        assert controller.flourish is None
        assert controller._pending_flourish is True

        # Tick one at a time until the entrance finishes, then check the
        # very next state -- not a large fixed batch, which could run
        # right past the (much shorter) flourish's own completion too and
        # make this assertion pass or fail for the wrong reason.
        for _ in range(90):
            controller.onWanderTick_(None)
            if controller.entrance is None:
                break
        else:
            raise AssertionError("entrance never finished")

        assert controller._pending_flourish is False  # queue was drained
        assert controller.flourish is not None  # ...by actually starting it
    finally:
        controller._invalidate_all_timers()


def test_flourish_pending_flag_is_not_set_when_no_entrance_is_running() -> None:
    # Regression guard: the deferred-flourish bookkeeping must stay inert
    # in the (overwhelmingly common) case where the entrance has already
    # finished by the time something fires.
    controller = _build_persona_controller("whale")
    try:
        _run_ticks(controller, 90)
        assert controller.entrance is None

        controller._show_reminder()

        assert controller.flourish is not None  # started immediately
        assert controller._pending_flourish is False
    finally:
        controller._invalidate_all_timers()


def test_none_flourish_persona_never_sets_an_active_flourish() -> None:
    controller = _build_persona_controller("cat")  # flourish == "none"
    try:
        assert controller.persona.flourish == "none"
        _run_ticks(controller, 90)

        controller._show_reminder()

        assert controller.flourish is None  # "none" finishes immediately
    finally:
        controller._invalidate_all_timers()


def test_flourish_ticks_offset_the_character_window_without_moving_the_bubble() -> None:
    controller = _build_persona_controller("whale")
    try:
        _run_ticks(controller, 90)
        controller._show_reminder()
        assert controller.flourish is not None

        bubble_origin_before = controller.bubble_window.frame().origin
        char_y_before = controller.char_window.frame().origin.y

        _run_ticks(controller, 3)

        char_y_after = controller.char_window.frame().origin.y
        assert char_y_after != pytest.approx(char_y_before)  # resurface dips/pops the window
        # The (already-shown) message window itself doesn't get relocated by
        # a flourish tick -- only an explicit refresh (flag ride-along, or a
        # new show) moves it.
        bubble_origin_after = controller.bubble_window.frame().origin
        assert bubble_origin_after.x == pytest.approx(bubble_origin_before.x)
        assert bubble_origin_after.y == pytest.approx(bubble_origin_before.y)
    finally:
        controller._invalidate_all_timers()


# --- macOS backend: flag ride-along must not fight the entrance effect ------
#
# Regression (user report, M13 Task 32 follow-up): "고래를 보면 메시지가
# 캐릭터를 안따라가" ("the message doesn't follow the whale"). Reproduced
# LIVE (a real `NSApplication.run()` loop, real NSTimers -- see the task
# report for the harness) with whale (a water persona, banner=False) +
# `flag` style + the default `pop` bubble_effect: `pop`/`slide` used to
# drive the message window's FRAME through `NSAnimationContext`'s
# `.animator()` proxy, which -- unlike a plain `setFrame_display_` call --
# schedules a real, wall-clock-timed Core Animation frame interpolation on
# `bubble_window` that runs for `BUBBLE_EFFECT_DURATION_SECONDS`
# independent of how many more `setFrameOrigin_` calls happen in between.
# Every ~33ms `onWanderTick_` ride-along tick for `flag` calls
# `setFrameOrigin_` directly to reposition the flag under the (constantly
# walking) whale -- and lost the fight: the window's `frame()` kept
# reporting the *animating* value, not the ride-along's latest direct set,
# so the flag visibly froze/lagged for ~0.22s after every fire before
# snapping back into alignment (up to ~9.5px measured live). Fixed by
# downgrading `pop`/`slide` to `fade`'s alpha-only entrance for a
# riding-along (`flag`) style: frame is set once, directly, to the final
# target -- never interpolated -- so nothing is left to fight the
# ride-along.
#
# The tests below check the fix mechanism deterministically (the window's
# frame is set to its full final size immediately, with no leftover
# `pop`-style 0.85 scale-down, for a `flag`-style message) rather than the
# emergent runtime symptom itself: reproducing the Core Animation race
# needs a real, wall-clock-timed `NSApplication.run()` loop (confirmed
# manually via a standalone harness -- a bare `time.sleep()`, or even
# pumping `NSRunLoop.currentRunLoop()` directly, between manually-invoked
# `onWanderTick_` calls does NOT reproduce it outside of `app.run()`'s own
# loop), which would make an in-suite test slow and CI-flaky.


def test_flag_pop_effect_sets_the_full_frame_immediately_not_a_scaled_one() -> None:
    """`pop` normally starts at an 0.85-scaled-down frame and animates up
    to the target over `BUBBLE_EFFECT_DURATION_SECONDS` via `.animator()`
    -- for `flag` (which rides along with the character every tick), that
    got downgraded to `fade`'s behavior: the frame is set directly to the
    FULL target size immediately, matching what `bubble_effect="none"`
    does. Compares two controllers built identically except for
    `bubble_effect`, so this doesn't hardcode any pixel geometry.
    """
    pop_controller = _build_persona_controller("whale", message_style="flag", bubble_effect="pop")
    none_controller = _build_persona_controller("whale", message_style="flag", bubble_effect="none")
    try:
        _run_ticks(pop_controller, 90)
        _run_ticks(none_controller, 90)
        pop_controller._show_reminder()
        none_controller._show_reminder()

        pop_frame = pop_controller.bubble_window.frame()
        none_frame = none_controller.bubble_window.frame()
        assert pop_frame.size.width == pytest.approx(none_frame.size.width)
        assert pop_frame.size.height == pytest.approx(none_frame.size.height)
        assert pop_frame.origin.x == pytest.approx(none_frame.origin.x)
        assert pop_frame.origin.y == pytest.approx(none_frame.origin.y)
    finally:
        pop_controller._invalidate_all_timers()
        none_controller._invalidate_all_timers()


def test_flag_bubble_style_pop_effect_still_scales_the_frame() -> None:
    # Regression guard: the downgrade is specific to a riding-along
    # (`flag`) style -- `bubble` (shown once, then held in place) keeps its
    # normal `pop` scale-in unchanged.
    controller = _build_persona_controller("whale", message_style="bubble", bubble_effect="pop")
    try:
        _run_ticks(controller, 90)
        controller._show_reminder()

        frame = controller.bubble_window.frame()
        # `pop`'s starting frame is the target scaled to 0.85 -- smaller
        # than the target on both axes at the instant it first appears.
        # (The `.animator()` frame animation then grows it back out over
        # BUBBLE_EFFECT_DURATION_SECONDS, which we don't need to wait out
        # here -- only the untouched starting behavior matters.)
        from todoy.display.overlay.macos import BUBBLE_HEIGHT, BUBBLE_TAIL_HEIGHT, BUBBLE_WIDTH

        target_height = BUBBLE_HEIGHT + BUBBLE_TAIL_HEIGHT
        assert frame.size.width < BUBBLE_WIDTH
        assert frame.size.height < target_height
    finally:
        controller._invalidate_all_timers()


def test_flag_tracks_a_moving_water_persona_across_direct_ticks() -> None:
    """Baseline ride-along coverage (not the CA-race regression above,
    which needs real wall-clock time to reproduce -- see the section
    comment): across many direct, synchronous `onWanderTick_` calls, the
    `flag` window's x should track the whale's x every tick.
    """
    controller = _build_persona_controller("whale", message_style="flag")
    try:
        _run_ticks(controller, 90)
        controller._show_reminder()

        for _ in range(30):
            controller.onWanderTick_(None)
            char_frame = controller.char_window.frame()
            bubble_frame = controller.bubble_window.frame()
            expected_unclamped = (
                char_frame.origin.x + char_frame.size.width / 2 - bubble_frame.size.width / 2
            )
            expected = controller._clamp_x_to_screen(expected_unclamped, bubble_frame.size.width)
            assert bubble_frame.origin.x == pytest.approx(expected, abs=0.5)
    finally:
        controller._invalidate_all_timers()


def test_flag_tracks_a_moving_water_persona_through_repeated_fires() -> None:
    """Ride-along must keep working across MULTIPLE fire cycles -- each
    fire rebuilds `bubble_window` as a brand new `NSPanel` (see
    `_build_flag_window`), so a bug that only shows up after a rebuild
    (e.g. `_message_base_origin`/`flag_view` not refreshed for the new
    window) wouldn't be caught by a single-fire test (Codex review
    follow-up, M13 Task 32).
    """
    controller = _build_persona_controller("whale", message_style="flag")
    try:
        _run_ticks(controller, 90)  # past the entrance

        seen_windows = []
        for _cycle in range(3):
            controller._show_reminder()
            seen_windows.append(controller.bubble_window)

            for _ in range(10):
                controller.onWanderTick_(None)
                char_frame = controller.char_window.frame()
                bubble_frame = controller.bubble_window.frame()
                expected_unclamped = (
                    char_frame.origin.x + char_frame.size.width / 2 - bubble_frame.size.width / 2
                )
                expected = controller._clamp_x_to_screen(
                    expected_unclamped, bubble_frame.size.width
                )
                assert bubble_frame.origin.x == pytest.approx(expected, abs=0.5)

            controller._hide_bubble()  # so the next _show_reminder() rebuilds fresh

        # Sanity: each fire really did rebuild a distinct window object --
        # confirms this test actually exercised the rebuild path 3 times,
        # not the same window reused.
        assert len({id(w) for w in seen_windows}) == 3
    finally:
        controller._invalidate_all_timers()


def test_flag_tracks_a_water_persona_launched_near_the_right_edge_clamped() -> None:
    """Near a screen edge, the flag's unclamped centered-under-character x
    would extend past the screen -- `_clamp_x_to_screen` pulls it back in,
    and ride-along must keep matching THAT clamped target every tick, not
    drift once clamping kicks in (Codex review follow-up, M13 Task 32).
    """
    from todoy.models import Todo

    # A long todo -> a wide flag panel (near FLAG_MAX_WIDTH) -- needed so
    # centering it under a character pinned at the right edge actually
    # overflows the screen; the default short reminder text produces a
    # panel narrow enough (FLAG_MIN_WIDTH) that it never would.
    long_todo = [Todo(text="a" * 80, id=1, source="builtin")]
    controller = _build_persona_controller(
        "whale", message_style="flag", get_todos=lambda: long_todo
    )
    try:
        _run_ticks(controller, 90)  # past the entrance
        assert controller.movement is not None

        # Force the character right up against the right edge of its
        # travel range, then apply that via a tick.
        controller.movement.x = controller.movement.travel_width
        controller.onWanderTick_(None)

        char_frame = controller.char_window.frame()
        screen_frame = controller._screen_frame()
        # Sanity: really is (within a tick's worth of eased-turn drift) at
        # the right edge -- one `onWanderTick_` call already begins easing
        # the bounce the instant `movement.x` starts at the travel-range
        # boundary, so this can't be an exact equality.
        assert char_frame.origin.x + char_frame.size.width >= (
            screen_frame.origin.x + screen_frame.size.width - 10.0
        )

        controller._show_reminder()

        was_clamped = False
        for _ in range(15):
            controller.onWanderTick_(None)
            char_frame = controller.char_window.frame()
            bubble_frame = controller.bubble_window.frame()
            expected_unclamped = (
                char_frame.origin.x + char_frame.size.width / 2 - bubble_frame.size.width / 2
            )
            expected = controller._clamp_x_to_screen(expected_unclamped, bubble_frame.size.width)
            if expected < expected_unclamped - 0.5:
                was_clamped = True
            # Tracks the (possibly-clamped) expected position every tick,
            # near the edge (still turning) and after (moving back inward).
            assert bubble_frame.origin.x == pytest.approx(expected, abs=0.5)

        assert was_clamped  # confirms clamping was actually exercised, not vacuous
    finally:
        controller._invalidate_all_timers()
