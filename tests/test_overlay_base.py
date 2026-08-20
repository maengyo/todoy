from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from todoy.display.characters import Character
from todoy.display.overlay.base import OverlayOptions, create_backend


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
    controller.configure(options, scheduler, get_reminder_text, get_todos, app)
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
