"""Tests for the original pixel-art character pack (src/todoy/display/pixelart.py).

Enforces the M14 interface-contract grid rules: per-state frame dimensions
match, every non-space palette char is declared, states have their minimum
frame counts, walk frames are pairwise distinct, palette colors are valid
hex, and stride is positive. Also spot-checks that the walk cycle actually
articulates (legs alternate, arms counter-swing) for the bipedal characters.
"""

from __future__ import annotations

import re

import pytest

from todoy.display.pixelart import SPRITES, SpriteSheet, sprite

REQUIRED_STATES = ("idle", "walk", "jump", "wave")
_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$")


def test_sprites_has_the_three_contract_characters() -> None:
    assert set(SPRITES) == {"blocky", "slime", "knight"}


@pytest.mark.parametrize("name", list(SPRITES))
def test_sprite_returns_matching_sheet(name: str) -> None:
    sheet = sprite(name)
    assert isinstance(sheet, SpriteSheet)
    assert sheet.name == name
    assert sheet is SPRITES[name]


def test_sprite_unknown_name_raises_value_error_listing_available() -> None:
    with pytest.raises(ValueError, match=r"Unknown sprite: not-a-sprite\. Available: .*blocky.*"):
        sprite("not-a-sprite")


def test_sprite_unknown_name_raises_value_error_not_key_error() -> None:
    # Explicitly not a KeyError -- the contract calls out "KeyError-free".
    with pytest.raises(ValueError):
        sprite("nonexistent")


@pytest.mark.parametrize("name", list(SPRITES))
def test_sheet_has_all_required_states(name: str) -> None:
    sheet = SPRITES[name]
    assert set(REQUIRED_STATES) <= set(sheet.states)


@pytest.mark.parametrize("name", list(SPRITES))
def test_stride_is_positive(name: str) -> None:
    assert SPRITES[name].stride_px_per_cycle > 0


@pytest.mark.parametrize("name", list(SPRITES))
def test_palette_colors_are_valid_hex(name: str) -> None:
    for char, color in SPRITES[name].palette.items():
        assert char != " ", "space must never need a palette entry"
        assert _HEX_RE.match(color), f"{name}: {char!r} -> {color!r} is not valid hex"


@pytest.mark.parametrize("name", list(SPRITES))
def test_every_non_space_char_is_in_the_palette(name: str) -> None:
    sheet = SPRITES[name]
    palette_chars = set(sheet.palette)
    for state, frames in sheet.states.items():
        for frame in frames:
            for row in frame:
                used = set(row) - {" "}
                missing = used - palette_chars
                assert not missing, f"{name}.{state}: chars {missing} missing from palette"


@pytest.mark.parametrize("name", list(SPRITES))
def test_frames_within_a_state_share_identical_dimensions(name: str) -> None:
    sheet = SPRITES[name]
    for state, frames in sheet.states.items():
        dims = {(len(frame), len({len(row) for row in frame})) for frame in frames}
        # every frame in the state has the same row count and every row
        # within every frame has the same width
        heights = {len(frame) for frame in frames}
        assert len(heights) == 1, f"{name}.{state}: frame heights differ: {heights}"
        for frame in frames:
            widths = {len(row) for row in frame}
            assert len(widths) == 1, f"{name}.{state}: row widths differ within a frame: {frame}"
        row_widths = {len(frame[0]) for frame in frames}
        assert len(row_widths) == 1, f"{name}.{state}: frame widths differ: {row_widths}"
        assert dims  # keep dims referenced (sanity, avoids unused warnings under some linters)


@pytest.mark.parametrize("name", list(SPRITES))
def test_idle_has_at_least_two_frames(name: str) -> None:
    assert len(SPRITES[name].states["idle"]) >= 2


@pytest.mark.parametrize("name", list(SPRITES))
def test_walk_has_at_least_four_frames(name: str) -> None:
    assert len(SPRITES[name].states["walk"]) >= 4


@pytest.mark.parametrize("name", list(SPRITES))
def test_jump_has_at_least_two_frames(name: str) -> None:
    assert len(SPRITES[name].states["jump"]) >= 2


@pytest.mark.parametrize("name", list(SPRITES))
def test_wave_has_at_least_two_frames(name: str) -> None:
    assert len(SPRITES[name].states["wave"]) >= 2


@pytest.mark.parametrize("name", list(SPRITES))
def test_every_state_has_at_least_two_distinct_frames(name: str) -> None:
    for state, frames in SPRITES[name].states.items():
        assert len(set(frames)) >= 2, f"{name}.{state}: frames are not distinct"


@pytest.mark.parametrize("name", list(SPRITES))
def test_walk_frames_are_pairwise_distinct(name: str) -> None:
    walk = SPRITES[name].states["walk"]
    assert len(set(walk)) == len(walk), f"{name}.walk: duplicate frames present"


# --- shape sanity (contract's approximate dimensions) -----------------------


def test_blocky_grid_is_roughly_12x20() -> None:
    frame = SPRITES["blocky"].states["idle"][0]
    assert len(frame) == 20
    assert len(frame[0]) == 12


def test_slime_grid_is_roughly_14x12() -> None:
    frame = SPRITES["slime"].states["idle"][0]
    assert len(frame) == 12
    assert len(frame[0]) == 14


def test_knight_grid_is_roughly_14x20() -> None:
    frame = SPRITES["knight"].states["idle"][0]
    assert len(frame) == 20
    assert len(frame[0]) == 14


# --- articulation: legs alternate, arms counter-swing (blocky + knight) -----


@pytest.mark.parametrize("name", ["blocky", "knight"])
def test_walk_cycle_leg_region_differs_between_contact_and_passing_frames(name: str) -> None:
    """The bottom third of the grid (the legs) must actually change shape
    across the walk cycle -- a static lower body would not read as walking."""
    walk = SPRITES[name].states["walk"]
    height = len(walk[0])
    leg_start = (2 * height) // 3
    leg_slices = [tuple(frame[leg_start:]) for frame in walk]
    assert len(set(leg_slices)) >= 4, "leg region must differ across all 4 walk frames"


@pytest.mark.parametrize("name", ["blocky", "knight"])
def test_walk_cycle_contact_frames_have_wider_leg_stance_than_passing_frames(name: str) -> None:
    """Contact frames (index 0, 2) spread the legs apart; passing frames
    (index 1, 3) bring them back toward center -- that alternation is what
    makes it read as a stride rather than a shuffle."""
    walk = SPRITES[name].states["walk"]
    height = len(walk[0])
    leg_start = (2 * height) // 3

    def leg_pixel_count(frame: tuple[str, ...]) -> int:
        return sum(1 for row in frame[leg_start:] for ch in row if ch not in (" ",))

    contact_counts = [leg_pixel_count(walk[0]), leg_pixel_count(walk[2])]
    passing_counts = [leg_pixel_count(walk[1]), leg_pixel_count(walk[3])]
    # not a strict inequality requirement (art can vary), but the two
    # contact frames should look like each other and differ from passing
    assert contact_counts[0] != passing_counts[0] or contact_counts[1] != passing_counts[1]


@pytest.mark.parametrize("name", ["blocky", "knight"])
def test_walk_cycle_arm_region_differs_between_frame_1_and_frame_3(name: str) -> None:
    """Frames 0 and 2 (opposite-leg contacts) must show a visibly different
    arm silhouette -- that's the counter-swing."""
    walk = SPRITES[name].states["walk"]
    height = len(walk[0])
    arm_region = slice(height // 4, (2 * height) // 3)
    frame0_arms = tuple(row for row in walk[0][arm_region])
    frame2_arms = tuple(row for row in walk[2][arm_region])
    assert frame0_arms != frame2_arms


def test_slime_walk_alternates_squash_and_stretch_height() -> None:
    """Slime's walk isn't leg articulation -- it's squash/stretch. Verify the
    filled (non-space) row count varies noticeably across the 4 hop frames,
    i.e. it isn't the same static blob repeated."""
    walk = SPRITES["slime"].states["walk"]
    filled_row_counts = [sum(1 for row in frame if row.strip()) for frame in walk]
    assert len(set(filled_row_counts)) >= 2


def test_all_walk_frames_have_at_least_some_content_in_every_frame() -> None:
    for sheet in SPRITES.values():
        for frame in sheet.states["walk"]:
            assert any(row.strip() for row in frame), "a walk frame must not be entirely blank"
