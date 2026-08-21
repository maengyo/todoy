"""Tests for the ASCII gait-cycle sprite gallery (src/todoy/display/sprites.py)."""

from __future__ import annotations

import pytest

from todoy.display.characters import CHARACTERS, get_character
from todoy.display.sprites import GAIT_FRAMES, STRIDE_COLUMNS, gait_frames, stride_columns


def test_every_character_frame_set_has_equal_width_frames() -> None:
    for name, frames in GAIT_FRAMES.items():
        widths = {len(frame) for frame in frames}
        assert len(widths) == 1, f"{name} frames have mismatched widths: {frames}"


def test_every_frame_is_pure_ascii_single_line() -> None:
    for name, frames in GAIT_FRAMES.items():
        for frame in frames:
            assert frame == frame.encode("ascii", "ignore").decode("ascii"), name
            assert "\n" not in frame
            assert "\r" not in frame


def test_horse_has_a_four_frame_gallop_cycle() -> None:
    horse_frames = GAIT_FRAMES["horse"]
    assert len(horse_frames) == 4
    # all frames unique -- a real animation, not padding repeats
    assert len(set(horse_frames)) == 4


def test_horse_frames_are_at_most_twelve_columns_wide() -> None:
    for frame in GAIT_FRAMES["horse"]:
        assert len(frame) <= 12


def test_horse_stride_is_at_least_six_columns_per_cycle() -> None:
    assert STRIDE_COLUMNS["horse"] >= 6
    assert stride_columns("horse") >= 6


@pytest.mark.parametrize("name", ["cat", "dog", "robot", "dino", "crab"])
def test_named_characters_have_at_least_a_two_frame_cycle(name: str) -> None:
    frames = GAIT_FRAMES[name]
    assert len(frames) >= 2
    assert len(set(frames)) >= 2  # frames actually differ -- a real cycle


def test_gait_frames_returns_dedicated_frames_when_present() -> None:
    assert gait_frames("horse") == GAIT_FRAMES["horse"]


def test_gait_frames_falls_back_to_single_ascii_art_frame() -> None:
    # "ghost" is a valid character with no dedicated gait entry.
    assert "ghost" not in GAIT_FRAMES
    assert gait_frames("ghost") == (get_character("ghost").ascii_art,)


def test_gait_frames_fallback_covers_every_character_missing_from_gait_frames() -> None:
    for name in CHARACTERS:
        if name in GAIT_FRAMES:
            continue
        frames = gait_frames(name)
        assert frames == (CHARACTERS[name].ascii_art,)


def test_gait_frames_unknown_character_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unknown character"):
        gait_frames("not-a-real-character")


def test_stride_columns_returns_dedicated_value_when_present() -> None:
    assert stride_columns("horse") == STRIDE_COLUMNS["horse"]


def test_stride_columns_fallback_is_two_for_missing_entries() -> None:
    assert "ghost" not in STRIDE_COLUMNS
    assert stride_columns("ghost") == 2


def test_stride_columns_fallback_is_two_for_unknown_names_too() -> None:
    # stride_columns performs no character-name validation -- fallback rule
    # applies uniformly, unlike gait_frames which defers to get_character.
    assert stride_columns("not-a-real-character") == 2
