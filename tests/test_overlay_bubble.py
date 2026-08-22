"""macOS-gated tests for the compact, riding-along `bubble` style (M15
Task 39): dynamic per-fire height, per-tick ride-along for both ground and
sky zones, edge clamping with a character-chasing tail, and the shake
effect re-expressed on the content view instead of the window frame.

Everything here drives `_OverlayController` methods directly (no real
`app.run()` loop), the same pattern as `test_overlay_base.py`'s persona
tests. Skipped on any non-macOS platform or when pyobjc isn't installed;
AppKit is only imported inside the gated helper so collection never touches
it on Linux/Windows CI.
"""

from __future__ import annotations

import sys

import pytest

from todoy.display.characters import Character
from todoy.display.overlay.base import OverlayOptions, PanelActions
from todoy.models import Todo


def _noop_panel_actions() -> PanelActions:
    return PanelActions(
        add=lambda text, at: None,
        set_done=lambda todo_id: None,
        delete=lambda todo_id: None,
        set_pinned=lambda todo_id, pinned: None,
    )


def _build_bubble_controller(
    character_name: str,
    *,
    bubble_effect: str = "pop",
    reminder_text: str = "Hey! 1 thing left\n\n[ ] water the plant",
    get_todos=lambda: [],
):
    """Skip on non-macOS/no-pyobjc; otherwise build+start a real
    `_OverlayController` with `message_style="bubble"`. Caller invalidates
    timers in a `finally` block, same as the other controller helpers.
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
        message_style="bubble",
        bubble_effect=bubble_effect,
    )
    scheduler = ReminderScheduler(interval_minutes=30, snooze_minutes=5)
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

    controller = _OverlayController.alloc().init()
    controller.configure(
        options, scheduler, lambda: reminder_text, get_todos, _noop_panel_actions(), app
    )
    controller.start()
    return controller


def _run_ticks(controller, count: int) -> None:
    for _ in range(count):
        controller.onWanderTick_(None)


# --- dynamic height ----------------------------------------------------------


def test_one_todo_bubble_is_visibly_shorter_than_the_old_fixed_height() -> None:
    controller = _build_bubble_controller("whale")
    try:
        from todoy.display.overlay.macos import (
            BUBBLE_BUTTON_ROW_HEIGHT,
            BUBBLE_PADDING,
            BUBBLE_TAIL_HEIGHT,
            BUBBLE_TEXT_MAX_HEIGHT,
        )

        _run_ticks(controller, 90)  # past the entrance
        controller._show_reminder()

        old_fixed_height = (
            BUBBLE_TEXT_MAX_HEIGHT + BUBBLE_BUTTON_ROW_HEIGHT + BUBBLE_PADDING * 2
        ) + BUBBLE_TAIL_HEIGHT
        frame = controller.bubble_window.frame()
        # A 3-line reminder must come out well under the old 132px text
        # slab -- "visibly shorter" per the contract, not off-by-slack.
        assert frame.size.height < old_fixed_height - 40.0
    finally:
        controller._invalidate_all_timers()


def test_long_reminder_text_height_is_capped_at_the_legacy_maximum() -> None:
    many_lines = "So many things!\n\n" + "\n".join(f"[ ] chore number {i}" for i in range(12))
    controller = _build_bubble_controller("whale", reminder_text=many_lines)
    try:
        from todoy.display.overlay.macos import (
            BUBBLE_BUTTON_ROW_HEIGHT,
            BUBBLE_PADDING,
            BUBBLE_TAIL_HEIGHT,
            BUBBLE_TEXT_MAX_HEIGHT,
        )

        _run_ticks(controller, 90)
        controller._show_reminder()

        max_height = (
            BUBBLE_TEXT_MAX_HEIGHT + BUBBLE_BUTTON_ROW_HEIGHT + BUBBLE_PADDING * 2
        ) + BUBBLE_TAIL_HEIGHT
        assert controller.bubble_window.frame().size.height == pytest.approx(max_height)
    finally:
        controller._invalidate_all_timers()


def test_each_fire_rebuilds_the_bubble_window_sized_to_its_own_text() -> None:
    texts = iter(
        [
            "One line only",
            "Lots to do!\n\n" + "\n".join(f"[ ] item {i}" for i in range(8)),
        ]
    )
    current = {"text": "One line only"}

    def reminder_text() -> str:
        return current["text"]

    controller = _build_bubble_controller("whale")
    controller.get_reminder_text = reminder_text
    try:
        _run_ticks(controller, 90)

        current["text"] = next(texts)
        controller._show_reminder()
        first_window = controller.bubble_window
        short_height = first_window.frame().size.height

        controller._hide_bubble()
        current["text"] = next(texts)
        controller._show_reminder()
        tall_height = controller.bubble_window.frame().size.height

        assert controller.bubble_window is not first_window  # rebuilt fresh
        assert tall_height > short_height + 40.0
    finally:
        controller._invalidate_all_timers()


# --- ride-along --------------------------------------------------------------


def test_bubble_tracks_a_moving_ground_character_every_tick() -> None:
    controller = _build_bubble_controller("whale")
    try:
        _run_ticks(controller, 90)
        controller._show_reminder()

        moved = False
        previous_x = controller.bubble_window.frame().origin.x
        for _ in range(30):
            controller.onWanderTick_(None)
            char_frame = controller.char_window.frame()
            bubble_frame = controller.bubble_window.frame()
            expected_x = (
                char_frame.origin.x + char_frame.size.width / 2 - bubble_frame.size.width / 2
            )
            # abs=1.0 throughout: on a 1x (non-Retina) backing store --
            # like CI's macOS runners -- AppKit snaps fractional window
            # frame origins to whole device pixels, so exact equality is
            # environment-dependent.
            assert bubble_frame.origin.x == pytest.approx(expected_x, abs=1.0)
            # Above the character, glued to it vertically as well.
            assert bubble_frame.origin.y == pytest.approx(
                char_frame.origin.y + char_frame.size.height + 6.0,  # BUBBLE_GAP_ABOVE_CHARACTER
                abs=1.0,
            )
            if bubble_frame.origin.x != previous_x:
                moved = True
            previous_x = bubble_frame.origin.x
        assert moved  # the whale really was walking -- not a vacuous pass
    finally:
        controller._invalidate_all_timers()


def test_bubble_tracks_a_sky_character_below_it_with_the_tail_on_top() -> None:
    controller = _build_bubble_controller("butterfly")
    try:
        _run_ticks(controller, 90)
        controller._show_reminder()

        assert controller.bubble_panel_view is not None
        assert controller.bubble_panel_view.tail_at_top is True

        for _ in range(30):
            controller.onWanderTick_(None)
            char_frame = controller.char_window.frame()
            bubble_frame = controller.bubble_window.frame()
            expected_x = (
                char_frame.origin.x + char_frame.size.width / 2 - bubble_frame.size.width / 2
            )
            # abs=1.0: whole-device-pixel frame snapping on 1x backing
            # stores (CI runners) -- see the ground-tracking test above.
            assert bubble_frame.origin.x == pytest.approx(expected_x, abs=1.0)
            # Below the sky character, riding along vertically too.
            assert bubble_frame.origin.y == pytest.approx(
                char_frame.origin.y - bubble_frame.size.height - 6.0,  # BUBBLE_GAP_BELOW_CHARACTER
                abs=1.0,
            )
    finally:
        controller._invalidate_all_timers()


def test_ground_bubble_keeps_the_tail_below_the_panel() -> None:
    controller = _build_bubble_controller("whale")
    try:
        _run_ticks(controller, 90)
        controller._show_reminder()
        assert controller.bubble_panel_view is not None
        assert controller.bubble_panel_view.tail_at_top is False
    finally:
        controller._invalidate_all_timers()


def test_bubble_pinned_at_the_screen_edge_keeps_the_tail_chasing_the_character() -> None:
    controller = _build_bubble_controller("whale")
    try:
        from todoy.display.overlay.bubblelayout import tail_offset_x
        from todoy.display.overlay.macos import BUBBLE_TAIL_MARGIN, BUBBLE_TAIL_WIDTH

        _run_ticks(controller, 90)
        assert controller.movement is not None

        # Force the character against the right edge of its travel range.
        controller.movement.x = controller.movement.travel_width
        controller.onWanderTick_(None)
        controller._show_reminder()

        screen_frame = controller._screen_frame()
        was_clamped = False
        for _ in range(15):
            controller.onWanderTick_(None)
            char_frame = controller.char_window.frame()
            bubble_frame = controller.bubble_window.frame()

            # Never leaves the screen...
            assert bubble_frame.origin.x >= screen_frame.origin.x - 0.01
            assert (
                bubble_frame.origin.x + bubble_frame.size.width
                <= screen_frame.origin.x + screen_frame.size.width + 0.01
            )

            char_center = char_frame.origin.x + char_frame.size.width / 2
            centered_x = char_center - bubble_frame.size.width / 2
            if bubble_frame.origin.x < centered_x - 0.5:
                was_clamped = True

            # ...and the drawn tail tip keeps pointing at the character
            # (clamped into the panel body per `tail_offset_x`).
            expected_tip = tail_offset_x(
                char_center,
                bubble_frame.origin.x,
                bubble_frame.size.width,
                BUBBLE_TAIL_WIDTH,
                BUBBLE_TAIL_MARGIN,
            )
            assert controller.bubble_panel_view.tail_tip_x == pytest.approx(expected_tip, abs=0.2)

        assert was_clamped  # clamping was actually exercised, not vacuous
    finally:
        controller._invalidate_all_timers()


# --- entrance effects vs ride-along -----------------------------------------


def test_bubble_shake_wiggles_the_content_not_the_window_frame() -> None:
    controller = _build_bubble_controller("whale", bubble_effect="shake")
    try:
        _run_ticks(controller, 90)
        controller._show_reminder()

        # Mid-shake: the offset lives on the content view's bounds origin.
        assert controller._shake_offset_px != 0.0
        view = controller.bubble_panel_view
        assert view.bounds().origin.x == pytest.approx(-controller._shake_offset_px)

        # The window frame itself stays at the ride-along base -- the
        # frame is owned by the tick, never by the shake. abs=1.0: AppKit
        # snaps fractional frame origins to whole device pixels on a 1x
        # backing store (CI's non-Retina runners), so exact equality is
        # environment-dependent; the shake amplitude is 8px, so a 1px
        # tolerance still cleanly distinguishes "not shaken".
        base = controller._message_base_origin
        frame = controller.bubble_window.frame()
        assert frame.origin.x == pytest.approx(base.x, abs=1.0)

        # Cancelling (what a hide/new fire does) restores the content.
        controller._cancel_bubble_shake()
        assert view.bounds().origin.x == pytest.approx(0.0)
    finally:
        controller._invalidate_all_timers()


def test_flag_shake_still_offsets_the_window_frame() -> None:
    # "Flag style: unchanged" -- its pre-M15 frame-offset shake stays.
    if sys.platform != "darwin":
        pytest.skip("AppKit only available on macOS")
    pytest.importorskip("AppKit")

    import AppKit

    from todoy.display.overlay.core import ReminderScheduler
    from todoy.display.overlay.macos import _OverlayController

    options = OverlayOptions(
        character=Character(name="whale", emoji="?", ascii_art="?"),
        character_image=None,
        language="en",
        test_seconds=None,
        message_style="flag",
        bubble_effect="shake",
    )
    scheduler = ReminderScheduler(interval_minutes=30, snooze_minutes=5)
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    controller = _OverlayController.alloc().init()
    controller.configure(options, scheduler, lambda: "x", lambda: [], _noop_panel_actions(), app)
    controller.start()
    try:
        _run_ticks(controller, 90)
        controller._show_reminder()

        assert controller._shake_offset_px != 0.0
        base = controller._message_base_origin
        frame = controller.bubble_window.frame()
        expected = controller._clamp_x_to_screen(
            base.x + controller._shake_offset_px, frame.size.width
        )
        # AppKit may snap the frame origin to the backing store's pixel
        # grid, so allow up to a point of rounding.
        assert frame.origin.x == pytest.approx(expected, abs=1.0)
    finally:
        controller._invalidate_all_timers()


def test_bubble_snooze_and_quit_buttons_survive_the_rebuild() -> None:
    # Auto-hide/buttons semantics unchanged: every rebuilt bubble still
    # carries a wired Snooze and Quit button.
    controller = _build_bubble_controller("whale")
    try:
        import AppKit

        _run_ticks(controller, 90)
        controller._show_reminder()

        buttons = [
            v for v in controller.bubble_panel_view.subviews() if isinstance(v, AppKit.NSButton)
        ]
        titles = sorted(str(b.title()) for b in buttons)
        assert titles == ["Quit", "Snooze 5m"]
        assert {str(b.action()) for b in buttons} == {"onSnoozeClicked:", "onQuitClicked:"}
        assert controller.hide_timer is not None
    finally:
        controller._invalidate_all_timers()


def test_alarm_bubble_also_gets_a_dynamic_compact_height() -> None:
    controller = _build_bubble_controller("whale")
    try:
        from todoy.display.overlay.macos import (
            BUBBLE_BUTTON_ROW_HEIGHT,
            BUBBLE_PADDING,
            BUBBLE_TAIL_HEIGHT,
            BUBBLE_TEXT_MAX_HEIGHT,
        )

        _run_ticks(controller, 90)
        controller._show_alarm([Todo(text="standup", id=1, source="builtin", at="09:30")])

        old_fixed_height = (
            BUBBLE_TEXT_MAX_HEIGHT + BUBBLE_BUTTON_ROW_HEIGHT + BUBBLE_PADDING * 2
        ) + BUBBLE_TAIL_HEIGHT
        assert controller.bubble_window.frame().size.height < old_fixed_height - 40.0
        assert controller._showing_alarm is True
    finally:
        controller._invalidate_all_timers()
