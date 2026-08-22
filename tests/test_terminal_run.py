"""Tests for the stride-locked marquee core (src/todoy/display/terminal_run.py)."""

from __future__ import annotations

import unicodedata

import pytest

from todoy.display.sprites import gait_frames, stride_columns
from todoy.display.terminal_run import TerminalRun, render_run_line

# --- an independent display-width check, deliberately not importing the
# module's own _display_width/_char_display_width helpers, so a bug in that
# private logic can't hide itself from these tests. ---


def _dw(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in {"W", "F"} else 1 for ch in text)


def _wrapped_delta_sum(xs: list[int], width_cols: int) -> int:
    """Sum consecutive (next - prev) % width_cols -- recovers true total
    advance even across modulo wraps, as long as no single step >= width_cols."""
    return sum((xs[i + 1] - xs[i]) % width_cols for i in range(len(xs) - 1))


# --------------------------------------------------------------------------
# TerminalRun.tick
# --------------------------------------------------------------------------


def test_tick_frame_index_cycles_in_order() -> None:
    run = TerminalRun(width_cols=1000, character_name="horse")
    indices = [run.tick()[0] for _ in range(8)]
    assert indices == [0, 1, 2, 3, 0, 1, 2, 3]


def test_tick_x_col_always_within_width() -> None:
    run = TerminalRun(width_cols=7, character_name="horse")
    for _ in range(50):
        _, x = run.tick()
        assert 0 <= x < 7


def test_stride_lock_exact_over_one_cycle() -> None:
    width_cols = 1000  # large enough that horse's stride never wraps here
    run = TerminalRun(width_cols=width_cols, character_name="horse")
    frame_count = len(gait_frames("horse"))
    xs = [0]
    for _ in range(frame_count):
        xs.append(run.tick()[1])
    assert _wrapped_delta_sum(xs, width_cols) == stride_columns("horse")


def test_stride_lock_exact_over_three_cycles() -> None:
    width_cols = 1000
    run = TerminalRun(width_cols=width_cols, character_name="horse")
    frame_count = len(gait_frames("horse"))
    xs = [0]
    for _ in range(frame_count * 3):
        xs.append(run.tick()[1])
    assert _wrapped_delta_sum(xs, width_cols) == stride_columns("horse") * 3


def test_stride_lock_holds_across_wraps() -> None:
    # width_cols=5 is small enough that horse's stride (8, over 4 frames of
    # step 2 each) wraps mid-cycle -- the modulo-delta-sum trick must still
    # recover the exact stride.
    width_cols = 5
    run = TerminalRun(width_cols=width_cols, character_name="horse")
    frame_count = len(gait_frames("horse"))
    xs = [0]
    saw_wrap = False
    for _ in range(frame_count * 3):
        prev = xs[-1]
        x = run.tick()[1]
        if x < prev:
            saw_wrap = True
        xs.append(x)
    assert saw_wrap, "expected at least one wrap with width_cols=5"
    assert _wrapped_delta_sum(xs, width_cols) == stride_columns("horse") * 3


def test_stride_lock_for_a_two_frame_character() -> None:
    width_cols = 1000
    run = TerminalRun(width_cols=width_cols, character_name="cat")
    frame_count = len(gait_frames("cat"))
    xs = [0]
    for _ in range(frame_count * 3):
        xs.append(run.tick()[1])
    assert _wrapped_delta_sum(xs, width_cols) == stride_columns("cat") * 3


def test_terminal_run_falls_back_for_character_missing_dedicated_gait() -> None:
    # Defensive guard: fallback to 1-frame for truly unknown character
    # (catalog names all have dedicated gait frames per M12 coverage rule).
    with pytest.raises(ValueError, match="Unknown character"):
        TerminalRun(width_cols=1000, character_name="not-a-real-character")


def test_terminal_run_unknown_character_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unknown character"):
        TerminalRun(width_cols=40, character_name="not-a-real-character")


def test_terminal_run_rejects_non_positive_width() -> None:
    with pytest.raises(ValueError):
        TerminalRun(width_cols=0, character_name="cat")


# --------------------------------------------------------------------------
# render_run_line
# --------------------------------------------------------------------------


def test_render_run_line_is_exact_width_ascii() -> None:
    line = render_run_line(
        x_col=10,
        frame="(=^.^=)",
        flag_text="3 todos left",
        width_cols=40,
        use_emoji=False,
        emoji="🐱",
    )
    assert _dw(line) == 40
    assert "\n" not in line
    assert "\r" not in line
    assert "\x1b" not in line


def test_render_run_line_is_exact_width_with_korean_flag_text() -> None:
    line = render_run_line(
        x_col=20,
        frame="(=^.^=)",
        flag_text="할 일 3개 남음",
        width_cols=40,
        use_emoji=False,
        emoji="🐱",
    )
    assert _dw(line) == 40
    assert "\n" not in line
    assert "\r" not in line


def test_render_run_line_is_exact_width_in_emoji_mode() -> None:
    line = render_run_line(
        x_col=20,
        frame="(=^.^=)",
        flag_text="3 todos left",
        width_cols=40,
        use_emoji=True,
        emoji="🐱",
    )
    assert _dw(line) == 40
    assert "🐱" in line
    assert "(=^.^=)" not in line


def test_render_run_line_uses_emoji_glyph_when_use_emoji() -> None:
    line = render_run_line(
        x_col=5,
        frame="XXX",
        flag_text="",
        width_cols=30,
        use_emoji=True,
        emoji="🐎",
    )
    assert "🐎" in line
    assert "XXX" not in line


def test_render_run_line_flag_trails_two_columns_behind_sprite() -> None:
    width_cols = 40
    x_col = 20
    frame = "AB"
    flag_text = "FLAG"
    line = render_run_line(
        x_col=x_col,
        frame=frame,
        flag_text=flag_text,
        width_cols=width_cols,
        use_emoji=False,
        emoji="",
    )
    assert len(line) == width_cols
    assert line[x_col : x_col + len(frame)] == frame
    # a two-column gap directly precedes the sprite ...
    assert line[x_col - 2 : x_col] == "  "
    # ... and the flag text sits immediately behind that gap.
    flag_start = x_col - 2 - len(flag_text)
    assert line[flag_start : flag_start + len(flag_text)] == flag_text
    # nothing else on the line.
    assert line[:flag_start] == " " * flag_start
    assert line[x_col + len(frame) :] == " " * (width_cols - x_col - len(frame))


def test_render_run_line_clips_sprite_at_right_edge() -> None:
    width_cols = 10
    line = render_run_line(
        x_col=8,
        frame="ABCDE",
        flag_text="",
        width_cols=width_cols,
        use_emoji=False,
        emoji="",
    )
    assert len(line) == width_cols
    # only the columns that fit (8, 9) can show sprite chars; "CDE" (which
    # would land at columns 10-12, off the line) must not appear.
    assert "CDE" not in line
    assert line[8:10] == "AB"


def test_render_run_line_clips_flag_at_left_edge() -> None:
    width_cols = 30
    line = render_run_line(
        x_col=1,
        frame="X",
        flag_text="A LONG FLAG MESSAGE",
        width_cols=width_cols,
        use_emoji=False,
        emoji="",
    )
    assert _dw(line) == width_cols
    # flag_start_col = 1 - 2 - 20 = -21, entirely off the left edge: no flag
    # characters can appear anywhere on the clipped line, and clipping must
    # not wrap the tail of the flag around to the right side of the line.
    assert "FLAG MESSAGE" not in line
    assert line[1] == "X"


def test_render_run_line_wide_sprite_clipped_at_right_edge_not_split() -> None:
    # a wide (2-column) emoji placed one column from the right edge cannot
    # fit -- it must be dropped whole, never rendered as a single stray
    # column (which would desync the East-Asian-width accounting).
    width_cols = 10
    line = render_run_line(
        x_col=9,
        frame="Z",
        flag_text="",
        width_cols=width_cols,
        use_emoji=True,
        emoji="🐱",
    )
    assert _dw(line) == width_cols
    assert "🐱" not in line


def test_render_run_line_no_ansi_or_newlines_even_if_inputs_carry_them() -> None:
    line = render_run_line(
        x_col=5,
        frame="A\nB\rC",
        flag_text="evil\x1b]0;x\x07 text",
        width_cols=30,
        use_emoji=False,
        emoji="",
    )
    assert "\n" not in line
    assert "\r" not in line
    assert "\x1b" not in line
    assert "\x07" not in line
    assert _dw(line) == 30


def test_render_run_line_zero_width_is_empty() -> None:
    assert (
        render_run_line(
            x_col=0,
            frame="X",
            flag_text="Y",
            width_cols=0,
            use_emoji=False,
            emoji="",
        )
        == ""
    )
