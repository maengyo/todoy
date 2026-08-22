"""Pure-geometry tests for the riding-along bubble (M15 Task 39).

`bubblelayout` never imports AppKit, so everything here runs ungated on
every OS -- the same split as `test_overlay_animations.py`/`test_spritestate.py`.
"""

from __future__ import annotations

import pytest

from todoy.display.overlay.bubblelayout import (
    bubble_text_height,
    clamp_bubble_x,
    tail_offset_x,
)

# --- clamp_bubble_x ----------------------------------------------------------


def test_clamp_bubble_x_centers_on_the_character_mid_screen() -> None:
    assert clamp_bubble_x(700.0, 320.0, 0.0, 1440.0) == pytest.approx(540.0)


def test_clamp_bubble_x_pins_at_the_left_edge() -> None:
    # Character near the left edge: centering would put the origin at -110.
    assert clamp_bubble_x(50.0, 320.0, 0.0, 1440.0) == pytest.approx(0.0)


def test_clamp_bubble_x_pins_at_the_right_edge() -> None:
    # Centering would put the right edge past the screen; pinned instead.
    assert clamp_bubble_x(1400.0, 320.0, 0.0, 1440.0) == pytest.approx(1120.0)


def test_clamp_bubble_x_respects_a_nonzero_screen_origin() -> None:
    # Secondary display whose frame starts at x=1440.
    assert clamp_bubble_x(1500.0, 320.0, 1440.0, 2880.0) == pytest.approx(1440.0)
    assert clamp_bubble_x(2100.0, 320.0, 1440.0, 2880.0) == pytest.approx(1940.0)


def test_clamp_bubble_x_screen_narrower_than_bubble_pins_left() -> None:
    assert clamp_bubble_x(100.0, 320.0, 0.0, 200.0) == pytest.approx(0.0)


# --- tail_offset_x -----------------------------------------------------------

WIDTH = 320.0
TAIL = 22.0
MARGIN = 28.0


def test_tail_tip_sits_under_the_character_when_centered() -> None:
    # Bubble centered on the character: tip lands mid-panel.
    tip = tail_offset_x(700.0, 700.0 - WIDTH / 2.0, WIDTH, TAIL, MARGIN)
    assert tip == pytest.approx(WIDTH / 2.0)


def test_tail_tip_chases_a_character_left_of_center() -> None:
    # Window pinned at x=0, character center at x=100 -> tip at local 100.
    assert tail_offset_x(100.0, 0.0, WIDTH, TAIL, MARGIN) == pytest.approx(100.0)


def test_tail_tip_clamps_at_the_left_margin_when_pinned() -> None:
    # Character far left of the pinned window: tip stops at `margin`.
    assert tail_offset_x(5.0, 0.0, WIDTH, TAIL, MARGIN) == pytest.approx(MARGIN)


def test_tail_tip_clamps_at_the_right_margin_when_pinned() -> None:
    # Character far right of the pinned window: tip stops at
    # `width - tail_width - margin` (per the interface contract).
    tip = tail_offset_x(2000.0, 1120.0, WIDTH, TAIL, MARGIN)
    assert tip == pytest.approx(WIDTH - TAIL - MARGIN)


def test_tail_tip_degenerate_narrow_bubble_centers() -> None:
    # Bubble narrower than tail + margins: fall back to the panel center.
    assert tail_offset_x(0.0, 0.0, 60.0, 40.0, 20.0) == pytest.approx(30.0)


# --- bubble_text_height ------------------------------------------------------


def test_bubble_text_height_passes_through_mid_band() -> None:
    assert bubble_text_height(80.0, 22.0, 132.0) == pytest.approx(80.0)


def test_bubble_text_height_clamps_to_the_one_line_minimum() -> None:
    assert bubble_text_height(10.0, 22.0, 132.0) == pytest.approx(22.0)


def test_bubble_text_height_clamps_to_the_legacy_maximum() -> None:
    assert bubble_text_height(500.0, 22.0, 132.0) == pytest.approx(132.0)
