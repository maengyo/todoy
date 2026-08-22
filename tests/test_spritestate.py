"""Pure sprite-animation state/frame-index logic (M14 Task 35).

`todoy.display.overlay.spritestate` has zero AppKit/pyobjc dependency (see
its module docstring), so -- unlike `tests/test_overlay_sprites.py`, which
covers the AppKit-integration side and sits behind the repo's usual
`pytest.importorskip("AppKit")` skip gate -- every test in this file is
ungated and runs on every OS/CI, including wherever pyobjc isn't installed.
This split is itself a Codex review follow-up on the first cut of Task 35,
which had all of this logic (and its tests) inline in macos.py, silently
never exercised on non-macOS CI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from todoy.display.overlay.spritestate import (
    fit_code_sprite_scale,
    fit_scale_to_max_height,
    parse_palette_color,
    scan_user_sprite_state_files,
    sprite_frames_for_state,
    sprite_movement_hop_peak_px,
    sprite_state_for_tick,
    sprite_time_frame_index,
    sprite_walk_frame_index,
)

# --- sprite_movement_hop_peak_px -------------------------------------------------


def test_hop_peak_px_for_hop_gallop_float_and_others() -> None:
    from todoy.display.overlay.animations import (
        FLOAT_BOB_AMPLITUDE_PX,
        GALLOP_HOP_PEAK_HEIGHT_PX,
        HOP_PEAK_HEIGHT_PX,
    )

    assert sprite_movement_hop_peak_px("hop") == HOP_PEAK_HEIGHT_PX
    assert sprite_movement_hop_peak_px("gallop") == GALLOP_HOP_PEAK_HEIGHT_PX
    assert sprite_movement_hop_peak_px("float") == pytest.approx(FLOAT_BOB_AMPLITUDE_PX * 2.0)
    assert sprite_movement_hop_peak_px("walk") == 0.0
    assert sprite_movement_hop_peak_px("dash") == 0.0
    assert sprite_movement_hop_peak_px("still") == 0.0


# --- sprite_state_for_tick: precedence -------------------------------------------


def test_state_is_jump_during_hop_or_splash_entrance_regardless_of_dx_or_y() -> None:
    state = sprite_state_for_tick(
        dx=0.0,
        y_offset=0.0,
        hop_peak_px=0.0,
        entrance_active=True,
        entrance_is_hop_or_splash=True,
        flourish_active=False,
    )
    assert state == "jump"


def test_state_is_idle_during_a_non_bouncing_entrance() -> None:
    # walk_in/swoop/materialize: entrance active, but not hop_in/splash --
    # falls through to the normal rules (dx==0/y_offset==0 here -> idle).
    state = sprite_state_for_tick(
        dx=0.0,
        y_offset=0.0,
        hop_peak_px=0.0,
        entrance_active=True,
        entrance_is_hop_or_splash=False,
        flourish_active=False,
    )
    assert state == "idle"


def test_state_is_wave_whenever_flourish_is_active_even_with_high_y_offset() -> None:
    state = sprite_state_for_tick(
        dx=5.0,
        y_offset=100.0,
        hop_peak_px=24.0,
        entrance_active=False,
        entrance_is_hop_or_splash=False,
        flourish_active=True,
    )
    assert state == "wave"


def test_state_is_jump_when_y_offset_exceeds_twenty_percent_of_hop_peak() -> None:
    below = sprite_state_for_tick(
        dx=0.0,
        y_offset=4.7,
        hop_peak_px=24.0,
        entrance_active=False,
        entrance_is_hop_or_splash=False,
        flourish_active=False,
    )
    above = sprite_state_for_tick(
        dx=0.0,
        y_offset=4.9,
        hop_peak_px=24.0,
        entrance_active=False,
        entrance_is_hop_or_splash=False,
        flourish_active=False,
    )
    assert below == "idle"  # 4.7 < 24*0.2 == 4.8
    assert above == "jump"  # 4.9 > 4.8


def test_state_is_walk_when_moving_and_idle_when_still() -> None:
    walking = sprite_state_for_tick(
        dx=1.5,
        y_offset=0.0,
        hop_peak_px=0.0,
        entrance_active=False,
        entrance_is_hop_or_splash=False,
        flourish_active=False,
    )
    still = sprite_state_for_tick(
        dx=0.0,
        y_offset=0.0,
        hop_peak_px=0.0,
        entrance_active=False,
        entrance_is_hop_or_splash=False,
        flourish_active=False,
    )
    assert walking == "walk"
    assert still == "idle"


# --- sprite_state_for_tick: is_turning (Codex review follow-up) -----------------
#
# Net per-tick `dx` alone is not a reliable walk/idle signal while an eased
# edge-turn is in progress: velocity sweeps from full speed down through
# exactly zero at the turn's midpoint and back up in the new direction, so a
# fixed ~1/30s tick can sample `dx` anywhere from "clearly walking" to
# "under epsilon" to "small and negative" depending on exactly where in that
# cosine curve it lands -- which would flicker the walk frame or misfire
# idle/walk from tick to tick. `is_turning` (from `CharacterMovement`, which
# already tracks exactly this) forces `idle` for the WHOLE turn instead.


def test_state_is_idle_while_turning_even_with_a_large_dx() -> None:
    # A tick landing near full deceleration/acceleration speed mid-turn can
    # still report a large dx -- is_turning must still win.
    state = sprite_state_for_tick(
        dx=40.0,
        y_offset=0.0,
        hop_peak_px=0.0,
        entrance_active=False,
        entrance_is_hop_or_splash=False,
        flourish_active=False,
        is_turning=True,
    )
    assert state == "idle"


def test_state_is_idle_while_turning_with_dx_near_zero_at_the_midpoint() -> None:
    state = sprite_state_for_tick(
        dx=0.0002,
        y_offset=0.0,
        hop_peak_px=0.0,
        entrance_active=False,
        entrance_is_hop_or_splash=False,
        flourish_active=False,
        is_turning=True,
    )
    assert state == "idle"


def test_state_is_idle_while_turning_with_a_small_negative_dx() -> None:
    # Just past the midpoint, velocity in the OLD direction briefly reads
    # negative relative to steady patrol -- still idle, not "walking
    # backwards" for one flickering tick.
    state = sprite_state_for_tick(
        dx=-0.3,
        y_offset=0.0,
        hop_peak_px=0.0,
        entrance_active=False,
        entrance_is_hop_or_splash=False,
        flourish_active=False,
        is_turning=True,
    )
    assert state == "idle"


def test_state_is_jump_takes_priority_over_is_turning() -> None:
    # A mid-air turn (gallop can turn while airborne, per animations.py's
    # own _patrol/_advance_turn) should still read as jump, not idle.
    state = sprite_state_for_tick(
        dx=0.0,
        y_offset=10.0,
        hop_peak_px=12.0,  # gallop's own peak -- 10.0 > 12*0.2==2.4
        entrance_active=False,
        entrance_is_hop_or_splash=False,
        flourish_active=False,
        is_turning=True,
    )
    assert state == "jump"


def test_state_is_wave_takes_priority_over_is_turning() -> None:
    state = sprite_state_for_tick(
        dx=0.0,
        y_offset=0.0,
        hop_peak_px=0.0,
        entrance_active=False,
        entrance_is_hop_or_splash=False,
        flourish_active=True,
        is_turning=True,
    )
    assert state == "wave"


def test_state_is_turning_defaults_to_false_and_walk_still_works() -> None:
    # is_turning has a default -- existing (pre-review) callers that don't
    # pass it at all keep working exactly as before.
    state = sprite_state_for_tick(
        dx=1.5,
        y_offset=0.0,
        hop_peak_px=0.0,
        entrance_active=False,
        entrance_is_hop_or_splash=False,
        flourish_active=False,
    )
    assert state == "walk"


def test_scripted_dx_and_turning_sequence_stays_idle_for_the_whole_turn_window() -> None:
    """A scripted per-tick (dx, is_turning) sequence modeling one full
    patrol-walk -> edge-turn -> patrol-walk cycle, as if sampled straight
    from a real `CharacterMovement("walk", ...)` run: steady positive dx
    while walking, then several turn ticks with `is_turning=True` and dx
    swinging from a large positive value down through ~0 and slightly
    negative (the cosine ease crossing its zero-velocity midpoint) before
    the turn ends and steady dx resumes in the new (now negative, since the
    character reversed direction) sign. Every turning tick must resolve to
    "idle", and walking resumes correctly on both sides of it."""
    sequence = [
        # (dx, is_turning, expected_state)
        (1.5, False, "walk"),
        (1.5, False, "walk"),
        (1.4, True, "idle"),  # turn begins: still decelerating but eased in
        (0.8, True, "idle"),
        (0.05, True, "idle"),  # right at the zero-velocity midpoint
        (-0.05, True, "idle"),  # just past it
        (-0.8, True, "idle"),
        (-1.4, True, "idle"),  # turn ends: accelerating in the new direction
        (-1.5, False, "walk"),  # steady patrol resumes, now the other way
        (-1.5, False, "walk"),
    ]
    for dx, is_turning, expected in sequence:
        state = sprite_state_for_tick(
            dx=dx,
            y_offset=0.0,
            hop_peak_px=0.0,
            entrance_active=False,
            entrance_is_hop_or_splash=False,
            flourish_active=False,
            is_turning=is_turning,
        )
        assert state == expected, f"dx={dx}, is_turning={is_turning}: got {state!r}"


# --- sprite_walk_frame_index: stride-lock ----------------------------------------


def test_walk_frame_index_is_stride_locked_same_distance_same_frame_regardless_of_step_count() -> (
    None
):
    """The contract's core "no foot sliding" guarantee: the SAME total
    distance must land on the SAME frame whether it was covered in one big
    step or many small ones (i.e. independent of fps/tick count)."""
    stride, scale, n = 24.0, 5.0, 4
    total_distance = 137.0

    one_big_step = sprite_walk_frame_index(total_distance, stride, scale, n)

    accumulated = 0.0
    for _ in range(137):  # 137 steps of 1.0px each == the same total distance
        accumulated += 1.0
    many_small_steps = sprite_walk_frame_index(accumulated, stride, scale, n)

    assert one_big_step == many_small_steps


def test_walk_frame_index_cycles_through_every_frame_as_distance_grows() -> None:
    stride, scale, n = 24.0, 5.0, 4
    cycle_px = stride * scale  # one full walk cycle's worth of screen pixels
    frame_px = cycle_px / n

    seen = {sprite_walk_frame_index(frame_px * i + 0.1, stride, scale, n) for i in range(n)}
    assert seen == {0, 1, 2, 3}
    # And it wraps back to frame 0 one full cycle later.
    assert sprite_walk_frame_index(cycle_px + 0.1, stride, scale, n) == 0


def test_walk_frame_index_handles_degenerate_inputs_without_crashing() -> None:
    assert sprite_walk_frame_index(100.0, 24.0, 5.0, 0) == 0
    assert sprite_walk_frame_index(100.0, 0.0, 5.0, 4) == 0
    assert sprite_walk_frame_index(100.0, 24.0, 0.0, 4) == 0


# --- sprite_time_frame_index ------------------------------------------------------


def test_time_frame_index_advances_by_elapsed_time_not_call_count() -> None:
    # At 2fps, 1.0s elapsed should be frame index 2 regardless of how many
    # individual calls led there -- the function takes elapsed time, not a
    # call counter, so this is really just confirming the formula.
    assert sprite_time_frame_index(1.0, 2.0, 5) == 2
    assert sprite_time_frame_index(0.0, 2.0, 5) == 0
    assert sprite_time_frame_index(100.0, 2.0, 0) == 0


# --- sprite_frames_for_state: fallback -------------------------------------------


def test_frames_for_state_returns_direct_match_when_present() -> None:
    frames = {"idle": ["i0", "i1"], "walk": ["w0", "w1", "w2", "w3"]}
    assert sprite_frames_for_state(frames, "walk") == ["w0", "w1", "w2", "w3"]


def test_frames_for_state_jump_falls_back_to_first_walk_frame_only() -> None:
    frames = {"idle": ["i0"], "walk": ["w0", "w1", "w2", "w3"]}
    assert sprite_frames_for_state(frames, "jump") == ["w0"]


def test_frames_for_state_wave_falls_back_to_the_whole_idle_animation() -> None:
    frames = {"idle": ["i0", "i1", "i2"]}
    assert sprite_frames_for_state(frames, "wave") == ["i0", "i1", "i2"]


def test_frames_for_state_falls_all_the_way_back_to_idle() -> None:
    frames = {"idle": ["i0"]}
    assert sprite_frames_for_state(frames, "jump") == ["i0"]  # no walk either
    assert sprite_frames_for_state(frames, "walk") == ["i0"]  # no walk at all


# --- parse_palette_color -----------------------------------------------------------


def test_parse_palette_color_six_and_eight_digit_hex() -> None:
    assert parse_palette_color("#FF0000") == (255, 0, 0, 255)
    assert parse_palette_color("00FF00") == (0, 255, 0, 255)
    assert parse_palette_color("#0000FF80") == (0, 0, 255, 128)


def test_parse_palette_color_rejects_invalid_length() -> None:
    with pytest.raises(ValueError):
        parse_palette_color("#FFF")


# --- fit_code_sprite_scale / fit_scale_to_max_height -----------------------------


def test_fit_code_sprite_scale_uses_nominal_when_grid_is_small() -> None:
    states = {"idle": (("XX", "XX"),)}  # 2 rows tall
    assert fit_code_sprite_scale(states, 5.0, 110.0) == 5.0


def test_fit_code_sprite_scale_clamps_down_for_a_tall_grid() -> None:
    rows = tuple("X" for _ in range(30))  # 30 rows tall
    states = {"idle": (rows,)}
    scale = fit_code_sprite_scale(states, 5.0, 110.0)
    assert scale == pytest.approx(110.0 / 30.0)
    assert scale < 5.0


def test_fit_scale_to_max_height_never_upscales() -> None:
    assert fit_scale_to_max_height(10.0, 96.0) == 1.0


def test_fit_scale_to_max_height_downscales_a_tall_image() -> None:
    assert fit_scale_to_max_height(192.0, 96.0) == pytest.approx(0.5)


# --- scan_user_sprite_state_files --------------------------------------------------


def test_scan_user_sprite_state_files_finds_contiguous_frames(tmp_path: Path) -> None:
    (tmp_path / "idle_1.png").write_bytes(b"x")
    (tmp_path / "idle_2.png").write_bytes(b"x")
    (tmp_path / "idle_4.png").write_bytes(b"x")  # gap at 3 -- never reached

    found = scan_user_sprite_state_files(tmp_path, "idle")
    assert [p.name for p in found] == ["idle_1.png", "idle_2.png"]


def test_scan_user_sprite_state_files_empty_when_no_files(tmp_path: Path) -> None:
    assert scan_user_sprite_state_files(tmp_path, "jump") == []
