"""ASCII gait-cycle sprites for the terminal marquee runner (`todoy run`).

Each entry in GAIT_FRAMES is a tuple of single-line, pure-ASCII frames for one
character, cycled in order to animate a walk/gallop. All frames belonging to
the same character share the exact same display width (they are pure ASCII
here, so display width == character count), so swapping frames never causes
the marquee line to jitter horizontally.

The horse gets the star treatment: a proper 4-frame gallop where the legs
visibly GATHER (tucked under the body) -> REACH (front legs stretch forward)
-> EXTEND (hind legs drive back while front legs plant -- the "flying" phase
of a real gallop) -> LAND (hind legs sweep under to plant while front legs
lift back into a tuck), then the cycle repeats. Reading left to right, the
head/eyes "(oo)" stay fixed in the middle while the leg glyphs on either side
change shape each frame -- that shape change, not any change in string
length, is what sells the motion (see stride_columns() for the actual
horizontal travel, which is handled separately by TerminalRun).
"""

from __future__ import annotations

from todoy.display.characters import get_character

GAIT_FRAMES: dict[str, tuple[str, ...]] = {
    # Horse: 4-frame gallop. Body "=(oo)=" is fixed in the middle; hind legs
    # sit to the left, front legs to the right (character faces/travels
    # right). Every frame is exactly 10 columns wide.
    "horse": (
        ",,=(oo)=,,",  # 1. GATHER  -- all four legs tucked under the body
        ",,=(oo)=//",  # 2. REACH   -- front legs stretch forward
        "\\\\=(oo)=__",  # 3. EXTEND  -- hind legs drive back, front legs plant
        "__=(oo)=,,",  # 4. LAND    -- hind legs sweep under, front legs lift/tuck
    ),
    "cat": (
        "/=^.^=\\",
        "\\=^.^=/",
    ),
    "dog": (
        "/u . u\\",
        "\\u . u/",
    ),
    "robot": (
        " [o_o]",
        "[o_o] ",
    ),
    "dino": (
        "~^~(0v0)~^~",
        "^~^(0v0)^~^",
    ),
    "crab": (
        "(\\/)!_!(\\/)",
        "(/\\)!_!(/\\)",
    ),
}

STRIDE_COLUMNS: dict[str, int] = {
    "horse": 8,
    "cat": 2,
    "dog": 2,
    "robot": 2,
    "dino": 2,
    "crab": 2,
}

_FALLBACK_STRIDE = 2


def gait_frames(name: str) -> tuple[str, ...]:
    """Return the gait-cycle frames for `name`.

    Falls back to a single frame built from the character's static
    `ascii_art` when `name` has no dedicated entry in GAIT_FRAMES (still a
    valid character -- just no bespoke gait art yet). An entirely unknown
    character name raises ValueError, same as `get_character`.
    """
    frames = GAIT_FRAMES.get(name)
    if frames is not None:
        return frames
    return (get_character(name).ascii_art,)


def stride_columns(name: str) -> int:
    """Columns advanced per full gait cycle for `name` (fallback: 2)."""
    return STRIDE_COLUMNS.get(name, _FALLBACK_STRIDE)
