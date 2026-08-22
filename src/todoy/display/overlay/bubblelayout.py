"""Pure geometry for the riding-along speech bubble (M15 Task 39).

No AppKit imports here -- this module is unit-tested on every OS (the same
split as `animations`/`spritestate`): `macos.py` feeds it plain floats from
the live window/screen frames and applies the returned values back to the
real `NSWindow`/`NSBezierPath`.

Coordinate conventions match AppKit's: x grows rightward, and every value
is in points. `clamp_bubble_x` works in SCREEN coordinates (where should
the bubble window's left edge go); `tail_offset_x` works in the bubble
window's own LOCAL coordinates (where inside the panel should the drawn
tail's tip sit so it keeps pointing at the character even when the window
is pinned at a screen edge and can no longer center on it).
"""

from __future__ import annotations


def clamp_bubble_x(
    char_center_x: float,
    bubble_width: float,
    screen_min_x: float,
    screen_max_x: float,
) -> float:
    """The bubble window's origin x: centered on the character, clamped so
    the window stays fully within `[screen_min_x, screen_max_x]`.

    When the screen is narrower than the bubble (degenerate, but possible
    with a huge bubble on a tiny virtual display), pin to the left edge --
    same tie-break as `macos._clamp_x_to_screen`.
    """
    x = char_center_x - bubble_width / 2.0
    min_x = screen_min_x
    max_x = screen_max_x - bubble_width
    if max_x < min_x:
        return min_x
    return min(max(x, min_x), max_x)


def tail_offset_x(
    char_center_x: float,
    bubble_origin_x: float,
    bubble_width: float,
    tail_width: float,
    margin: float,
) -> float:
    """The tail tip's x within the bubble body, pointing at the character.

    Unclamped this is simply the character's center translated into the
    bubble window's local coordinates (`char_center_x - bubble_origin_x`);
    when the window is pinned at a screen edge and can't center on the
    character anymore, the tip chases the character as far as
    `[margin, bubble_width - tail_width - margin]` allows, so the tail
    never escapes the panel body or collides with its rounded corners.
    """
    lo = margin
    hi = bubble_width - tail_width - margin
    if hi < lo:
        # Degenerate (bubble narrower than tail + margins): center the tip.
        return bubble_width / 2.0
    tip = char_center_x - bubble_origin_x
    return min(max(tip, lo), hi)


def bubble_text_height(measured_height: float, min_h: float, max_h: float) -> float:
    """Clamp a measured text height into the bubble's allowed band."""
    return min(max(measured_height, min_h), max_h)
