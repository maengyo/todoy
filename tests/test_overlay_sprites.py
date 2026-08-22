"""Animated sprite-character rendering: AppKit integration (M14 Task 35,
macos.py).

Every test here needs `macos.py` importable, which needs pyobjc -- so, like
`test_overlay_base.py`, every test function (not the module top) does its
own `sys.platform`/`pytest.importorskip("AppKit")` skip-gate before
importing anything from `todoy.display.overlay.macos`, keeping collection
itself safe on any OS/without pyobjc installed. The PURE state/frame-index
logic these tests exercise indirectly (state precedence, stride-lock,
fallback lookup, palette/scale math) has its own direct, ungated unit tests
in `tests/test_spritestate.py` (against `todoy.display.overlay.spritestate`,
which has zero AppKit dependency and so runs on every OS/CI) -- this file
only covers the AppKit-specific wiring: real `NSImage`s, a real
`_OverlayController`, real PNG files on disk.

Two independent sprite sources are covered:
- Code pixel-art packs (`options.sprite_name`, looked up in
  `todoy.display.pixelart` -- Task 34). Rather than depend on that module's
  actual land timing/content, these tests install a FAKE
  `todoy.display.pixelart` module into `sys.modules` shaped exactly like
  the frozen contract (section 1: `SpriteSheet(name, palette, states,
  stride_px_per_cycle)`, `sprite(name) -> SpriteSheet | raises ValueError`)
  -- so this file tests macos.py's own logic against the CONTRACT, not
  against Task 34's specific characters.
- User sprite folders (`options.sprite_folder`, `<state>_<n>.png`), loaded
  from real tiny PNGs written to `tmp_path` with AppKit itself.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from todoy.display.characters import Character
from todoy.display.overlay.base import OverlayOptions, PanelActions

# --- shared test helpers -------------------------------------------------------


def _noop_panel_actions() -> PanelActions:
    return PanelActions(
        add=lambda text, at: None,
        set_done=lambda todo_id: None,
        delete=lambda todo_id: None,
        set_pinned=lambda todo_id, pinned: None,
    )


def _skip_unless_appkit() -> None:
    if sys.platform != "darwin":
        pytest.skip("AppKit only available on macOS")
    pytest.importorskip("AppKit")


def _build_controller(
    character_name: str = "cat",
    *,
    movement: str = "walk",
    sprite_name: str | None = None,
    sprite_folder: Path | None = None,
):
    """Build+start a real `_OverlayController`, same shape as
    `test_overlay_base.py`'s `_build_persona_controller` but with direct
    control over `movement`/`sprite_name`/`sprite_folder` (not available
    through that helper), which every test below needs."""
    _skip_unless_appkit()

    import AppKit

    from todoy.display.overlay.core import ReminderScheduler
    from todoy.display.overlay.macos import _OverlayController

    options = OverlayOptions(
        character=Character(name=character_name, emoji="?", ascii_art="?"),
        character_image=None,
        language="en",
        test_seconds=None,
        movement=movement,
        sprite_name=sprite_name,
        sprite_folder=sprite_folder,
    )
    scheduler = ReminderScheduler(interval_minutes=30, snooze_minutes=5)
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

    controller = _OverlayController.alloc().init()
    controller.configure(options, scheduler, lambda: "x", lambda: [], _noop_panel_actions(), app)
    controller.start()
    return controller


def _run_ticks(controller: Any, count: int) -> None:
    for _ in range(count):
        controller.onWanderTick_(None)


def _install_fake_pixelart(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    palette: dict[str, str],
    states: dict[str, tuple[tuple[str, ...], ...]],
    stride_px_per_cycle: int,
) -> None:
    """Install a fake `todoy.display.pixelart` module into `sys.modules`,
    shaped exactly per the frozen contract's section 1 API (`SpriteSheet`,
    `sprite(name)`) -- decouples these tests from Task 34's actual land
    timing/content. `macos.py` does `from todoy.display.pixelart import
    sprite as ...` INSIDE `_load_character_sprite` (a deferred import), so
    patching `sys.modules` before that call is all that's needed; no need
    to reach into macos.py itself.
    """
    sheet = types.SimpleNamespace(
        name=name, palette=palette, states=states, stride_px_per_cycle=stride_px_per_cycle
    )

    def sprite(lookup_name: str) -> Any:
        if lookup_name != name:
            raise ValueError(f"Unknown character: {lookup_name}. Available: {name}")
        return sheet

    fake_module = types.ModuleType("todoy.display.pixelart")
    fake_module.sprite = sprite  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "todoy.display.pixelart", fake_module)


# A tiny, deliberately asymmetric 3x3 pixel-art pack: palette 'X' opaque
# red, ' ' transparent. Distinct frame per state avoids any accidental
# frame-index-independent pass.
_TEST_PALETTE = {"X": "#FF0000"}
_TEST_STATES: dict[str, tuple[tuple[str, ...], ...]] = {
    "idle": (("X  ", " X ", "  X"), ("  X", " X ", "X  ")),
    "walk": (
        ("X  ", " X ", "  X"),
        (" X ", "X  ", "  X"),
        ("  X", " X ", "X  "),
        (" X ", "  X", "X  "),
    ),
    "jump": (("XXX", "   ", "   "), ("   ", "   ", "XXX")),
    "wave": (("X  ", "   ", "   "), ("  X", "   ", "   ")),
}
_TEST_STRIDE_PX_PER_CYCLE = 24


def _install_default_fake_pixelart(
    monkeypatch: pytest.MonkeyPatch, name: str = "testsprite"
) -> None:
    _install_fake_pixelart(
        monkeypatch, name, _TEST_PALETTE, _TEST_STATES, _TEST_STRIDE_PX_PER_CYCLE
    )


def _write_tiny_png(path: Path, width: int, height: int) -> None:
    """Write a real, tiny solid-color PNG at `path` using AppKit itself --
    used for the user-sprite-folder tests below, so they exercise the real
    `NSImage.initWithContentsOfFile_` load path, not a hand-rolled PNG blob.
    """
    import AppKit
    import Foundation

    bitmap = AppKit.NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(  # noqa: E501
        None, width, height, 8, 4, True, False, AppKit.NSDeviceRGBColorSpace, 0, 32
    )
    color = AppKit.NSColor.colorWithDeviceRed_green_blue_alpha_(0.2, 0.6, 0.9, 1.0)
    for y in range(height):
        for x in range(width):
            bitmap.setColor_atX_y_(color, x, y)
    data = bitmap.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {})
    ok = data.writeToFile_atomically_(str(path), True)
    assert ok, f"failed to write test PNG to {path}"
    # Silence unused-import warnings if Foundation ends up unused on some path.
    del Foundation


# --- AppKit integration: code sprite (fake pixelart module) ---------------------


def test_code_sprite_builds_cached_nsimages_for_every_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_default_fake_pixelart(monkeypatch)
    controller = _build_controller(sprite_name="testsprite")
    try:
        view = controller.char_view
        assert view is not None
        assert view.sprite_frames is not None
        assert view.sprite_pixel_perfect is True
        for state, count in (("idle", 2), ("walk", 4), ("jump", 2), ("wave", 2)):
            assert len(view.sprite_frames[state]) == count
        # 3 native px * ~5x nominal scale -> a real, drawable NSImage.
        image = view.sprite_frames["walk"][0]
        assert image.size().width > 3.0
        assert image.size().height > 3.0
    finally:
        controller._invalidate_all_timers()


def test_unknown_sprite_name_falls_back_to_emoji_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_default_fake_pixelart(monkeypatch, name="testsprite")
    controller = _build_controller(sprite_name="not-a-real-sprite-name")
    try:
        view = controller.char_view
        assert view is not None
        assert view.sprite_frames is None
        assert view.emoji == "?"
    finally:
        controller._invalidate_all_timers()


def test_character_without_any_sprite_source_leaves_sprite_frames_none() -> None:
    controller = _build_controller()
    try:
        view = controller.char_view
        assert view is not None
        assert view.sprite_frames is None
    finally:
        controller._invalidate_all_timers()


def test_walking_advances_sprite_frame_by_distance(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_default_fake_pixelart(monkeypatch)
    controller = _build_controller(movement="walk", sprite_name="testsprite")
    try:
        from todoy.display.overlay.spritestate import sprite_walk_frame_index

        _run_ticks(controller, 40)  # clear cat's ~0.9s walk_in launch entrance first
        assert controller.entrance is None
        _run_ticks(controller, 20)
        view = controller.char_view
        assert view.sprite_state == "walk"
        expected = sprite_walk_frame_index(
            controller._sprite_distance_px,
            controller._sprite_stride_px_per_cycle,
            controller._sprite_draw_scale,
            len(view.sprite_frames["walk"]),
        )
        assert view.sprite_frame_index == expected
        # Actually walking, not stuck at frame 0 the whole time.
        assert controller._sprite_distance_px > 0.0
    finally:
        controller._invalidate_all_timers()


def test_still_movement_stays_idle_and_advances_by_time(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_default_fake_pixelart(monkeypatch)
    controller = _build_controller(movement="still", sprite_name="testsprite")
    try:
        # Clear the launch entrance immediately -- "still" personas are
        # ground/walk_in by default for an unlisted character name ("cat"),
        # so a couple ticks is enough to finish the ~0.9s walk_in entrance.
        _run_ticks(controller, 40)
        view = controller.char_view
        assert view.sprite_state == "idle"
        assert controller._sprite_distance_px == pytest.approx(0.0)

        # The fix (Codex review, point 3): idle must actually ADVANCE by
        # time, not just stay classified as "idle" -- drive it through a
        # full idle-frame cycle (2 frames @ SPRITE_IDLE_FPS=2fps == 1s
        # total, 30 ticks @ 30fps) and confirm the frame index actually
        # changes, not just that the state label never moves.
        first_index = view.sprite_frame_index
        seen_indices = {first_index}
        for _ in range(30):
            controller.onWanderTick_(None)
            assert view.sprite_state == "idle"
            seen_indices.add(view.sprite_frame_index)
        assert len(seen_indices) >= 2, (
            f"idle frame index never changed across 1s of ticks: {seen_indices}"
        )
    finally:
        controller._invalidate_all_timers()


def test_jump_state_when_hop_movements_y_offset_exceeds_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_default_fake_pixelart(monkeypatch)
    controller = _build_controller(movement="hop", sprite_name="testsprite")
    try:
        # Force the hop to start right now instead of waiting out its
        # randomized 2.5-4.5s idle timer (same technique as the existing
        # `controller.movement.x = ...` direct-manipulation pattern used
        # throughout test_overlay_base.py).
        controller.movement._hopping = True
        controller.movement._hop_phase = 0.0
        controller.entrance = None  # skip the launch entrance for this check
        _run_ticks(controller, 8)  # partway up the parabola -- HOP_DURATION_SECONDS=0.5 at 30fps
        view = controller.char_view
        assert view.sprite_state == "jump"
    finally:
        controller._invalidate_all_timers()


def test_wave_state_while_a_flourish_is_active(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_default_fake_pixelart(monkeypatch)
    # ghost: materialize entrance / blink flourish -- neither is hop/splash,
    # so this isolates "flourish active -> wave" from the entrance rule.
    controller = _build_controller("ghost", sprite_name="testsprite")
    try:
        _run_ticks(controller, 60)  # clear the ~1.2s materialize entrance
        assert controller.entrance is None
        controller._start_flourish()
        assert controller.flourish is not None
        controller.onWanderTick_(None)
        view = controller.char_view
        assert view.sprite_state == "wave"
    finally:
        controller._invalidate_all_timers()


def test_jump_state_during_a_hop_in_or_splash_entrance(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_default_fake_pixelart(monkeypatch)
    # rabbit: hop_in entrance -- jump state should hold from the very first
    # frame (checked in `_build_character_window`, before any wander tick).
    controller = _build_controller("rabbit", sprite_name="testsprite")
    try:
        assert controller.entrance is not None
        view = controller.char_view
        assert view.sprite_state == "jump"
    finally:
        controller._invalidate_all_timers()


# --- AppKit integration: user sprite folders ------------------------------------


def test_user_sprite_folder_loads_idle_and_walk_and_animates(tmp_path: Path) -> None:
    _skip_unless_appkit()
    _write_tiny_png(tmp_path / "idle_1.png", 8, 8)
    _write_tiny_png(tmp_path / "idle_2.png", 8, 8)
    _write_tiny_png(tmp_path / "walk_1.png", 8, 8)
    _write_tiny_png(tmp_path / "walk_2.png", 8, 8)

    controller = _build_controller(movement="walk", sprite_folder=tmp_path)
    try:
        view = controller.char_view
        assert view is not None
        assert view.sprite_frames is not None
        assert view.sprite_pixel_perfect is False
        assert len(view.sprite_frames["idle"]) == 2
        assert len(view.sprite_frames["walk"]) == 2

        _run_ticks(controller, 30)
        assert view.sprite_state == "walk"
        assert controller._sprite_distance_px > 0.0
    finally:
        controller._invalidate_all_timers()


def test_user_sprite_folder_missing_jump_falls_back_to_first_walk_frame(tmp_path: Path) -> None:
    _skip_unless_appkit()
    from todoy.display.overlay.spritestate import sprite_frames_for_state

    _write_tiny_png(tmp_path / "idle_1.png", 6, 6)
    _write_tiny_png(tmp_path / "walk_1.png", 6, 6)
    _write_tiny_png(tmp_path / "walk_2.png", 6, 6)

    controller = _build_controller(sprite_folder=tmp_path)
    try:
        view = controller.char_view
        assert "jump" not in view.sprite_frames
        jump_frames = sprite_frames_for_state(view.sprite_frames, "jump")
        assert jump_frames == view.sprite_frames["walk"][:1]
    finally:
        controller._invalidate_all_timers()


def test_user_sprite_folder_missing_wave_falls_back_to_idle_animation(tmp_path: Path) -> None:
    _skip_unless_appkit()
    from todoy.display.overlay.spritestate import sprite_frames_for_state

    _write_tiny_png(tmp_path / "idle_1.png", 6, 6)
    _write_tiny_png(tmp_path / "idle_2.png", 6, 6)

    controller = _build_controller(sprite_folder=tmp_path)
    try:
        view = controller.char_view
        assert "wave" not in view.sprite_frames
        wave_frames = sprite_frames_for_state(view.sprite_frames, "wave")
        assert wave_frames == view.sprite_frames["idle"]
    finally:
        controller._invalidate_all_timers()


def test_user_sprite_folder_without_idle_is_rejected_falls_back_to_emoji(tmp_path: Path) -> None:
    _skip_unless_appkit()
    _write_tiny_png(tmp_path / "walk_1.png", 6, 6)

    controller = _build_controller(sprite_folder=tmp_path)
    try:
        view = controller.char_view
        assert view.sprite_frames is None
        assert view.emoji == "?"
    finally:
        controller._invalidate_all_timers()


def test_nonexistent_sprite_folder_falls_back_to_emoji(tmp_path: Path) -> None:
    _skip_unless_appkit()
    controller = _build_controller(sprite_folder=tmp_path / "does-not-exist")
    try:
        view = controller.char_view
        assert view.sprite_frames is None
    finally:
        controller._invalidate_all_timers()


def test_user_sprite_folder_scales_a_tall_image_down_to_max_height(tmp_path: Path) -> None:
    _skip_unless_appkit()
    from todoy.display.overlay.macos import CHARACTER_MAX_IMAGE_PX

    _write_tiny_png(tmp_path / "idle_1.png", 40, 200)  # native height way over the cap

    controller = _build_controller(sprite_folder=tmp_path)
    try:
        view = controller.char_view
        assert view.sprite_frames is not None
        image = view.sprite_frames["idle"][0]
        assert image.size().height <= CHARACTER_MAX_IMAGE_PX + 1e-6
        # Aspect ratio preserved (40:200 == width:height*0.2).
        assert image.size().width == pytest.approx(image.size().height * 40.0 / 200.0)
    finally:
        controller._invalidate_all_timers()


def test_sprite_folder_wins_over_sprite_name_when_both_are_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _skip_unless_appkit()
    _install_default_fake_pixelart(monkeypatch)
    _write_tiny_png(tmp_path / "idle_1.png", 6, 6)

    controller = _build_controller(sprite_name="testsprite", sprite_folder=tmp_path)
    try:
        view = controller.char_view
        # The user folder's PNG-backed frames win, not the code pack's
        # nearest-neighbor-flagged ones.
        assert view.sprite_pixel_perfect is False
        assert len(view.sprite_frames["idle"]) == 1
    finally:
        controller._invalidate_all_timers()
