"""Stride-locked terminal marquee: character movement + fixed-width line render.

`TerminalRun` advances a character one gait frame per `tick()`, always moving
left to right and wrapping like a ticker (no direction flips, so ASCII art
never appears to run backwards). Horizontal travel is stride-locked: over one
full gait cycle the character advances exactly `stride_columns(name)`
columns, distributed as integer per-frame steps so the sum is exact (no
rounding drift across repeated cycles).

`render_run_line` composes one exact-width terminal line: the sprite/emoji at
its current column, with the flag text trailing two columns behind it (to its
left). Both are clipped, not wrapped, at the line edges. The result never
contains ANSI escapes, "\\n", or "\\r" -- callers own line control (see
interface-contract.md section 2).
"""

from __future__ import annotations

import unicodedata

from todoy.display import sanitize_text
from todoy.display.sprites import gait_frames, stride_columns

FLAG_GAP_COLUMNS = 2


class TerminalRun:
    """Stride-locked marquee state for one character on a fixed-width line."""

    def __init__(self, width_cols: int, character_name: str) -> None:
        if width_cols < 1:
            msg = f"width_cols must be >= 1, got {width_cols}"
            raise ValueError(msg)

        self.width_cols = width_cols
        self.character_name = character_name
        self.frames: tuple[str, ...] = gait_frames(character_name)
        self.stride_columns: int = stride_columns(character_name)

        self._frame_count = len(self.frames)
        self._cycle_pos = 0
        self._x = 0

    def tick(self) -> tuple[int, int]:
        """Advance one gait frame; return (frame_index, x_col) for that frame.

        The step taken on this tick is the exact per-frame share of
        `stride_columns` for the frame at the current cycle position
        (Bresenham-style distribution: `step(i) = i*stride//n - prior`), so
        summing the steps across one full cycle (n calls) equals
        `stride_columns` exactly, and across k cycles equals k * stride
        exactly -- no rounding drift.
        """
        frame_index = self._cycle_pos
        step = self._step_for(frame_index)
        self._x = (self._x + step) % self.width_cols
        self._cycle_pos = (self._cycle_pos + 1) % self._frame_count
        return frame_index, self._x

    def _step_for(self, cycle_pos: int) -> int:
        n = self._frame_count
        stride = self.stride_columns
        prior = (cycle_pos * stride) // n
        upto = ((cycle_pos + 1) * stride) // n
        return upto - prior


def render_run_line(
    x_col: int,
    frame: str,
    flag_text: str,
    width_cols: int,
    use_emoji: bool,
    emoji: str,
) -> str:
    """Render one exact-`width_cols`-display-width marquee line (no ANSI/newlines).

    The sprite (`frame`, or `emoji` when `use_emoji`) is placed starting at
    display column `x_col`. `flag_text` trails `FLAG_GAP_COLUMNS` columns
    behind it on the left. Both are clipped (not wrapped) at the line edges;
    a character that would only partially fit is dropped whole rather than
    split, so wide (East-Asian-width) glyphs never render half-visible.
    """
    if width_cols < 1:
        return ""

    sprite = sanitize_text(emoji if use_emoji else frame)
    flag = sanitize_text(flag_text)

    sprite_col = x_col % width_cols
    flag_width = _display_width(flag)
    flag_start_col = sprite_col - FLAG_GAP_COLUMNS - flag_width

    canvas: list[str] = [" "] * width_cols
    _place(canvas, flag, flag_start_col)
    _place(canvas, sprite, sprite_col)
    return "".join(canvas)


def _place(canvas: list[str], text: str, start_col: int) -> None:
    """Draw `text` onto `canvas` (one cell per display column) at `start_col`.

    Characters that would start before column 0 or would only partially fit
    before `len(canvas)` are dropped whole (clipped), never split.
    """
    width_cols = len(canvas)
    col = start_col
    for char in text:
        char_width = _char_display_width(char)
        if col >= width_cols:
            break
        if col < 0:
            col += char_width
            continue
        if col + char_width > width_cols:
            break
        for offset in range(char_width):
            _clear_cell(canvas, col + offset)
        canvas[col] = char
        if char_width == 2:
            canvas[col + 1] = ""
        col += char_width


def _clear_cell(canvas: list[str], index: int) -> None:
    """Blank cell `index`, cleaning up any wide-char head/continuation pairing."""
    if canvas[index] == "":
        # This cell is the continuation half of a wide char one to the left.
        canvas[index - 1] = " "
        canvas[index] = " "
        return
    if index + 1 < len(canvas) and canvas[index + 1] == "":
        # This cell is a wide-char head; its continuation would dangle.
        canvas[index + 1] = " "
    canvas[index] = " "


def _display_width(text: str) -> int:
    return sum(_char_display_width(char) for char in text)


def _char_display_width(char: str) -> int:
    return 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
