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
    "ghost": (
        # Drifts side to side -- the whole silhouette shifts a column
        # within a fixed-width field, like the robot's shuffle.
        " (o_o)",
        "(o_o) ",
    ),
    "alien": (
        # Arms 'd'/'b' swap sides each frame -- a little wave.
        "d[o_o]b",
        "b[o_o]d",
    ),
    "bee": (
        # All four wings flip orientation together -- a buzzing flap.
        "/\\/\\(o.o)/\\/\\",
        "\\/\\/(o.o)\\/\\/",
    ),
    "frog": (
        # Eyes/legs twitch between hops -- colon vs semicolon.
        "(o)(o):v",
        "(o)(o);v",
    ),
    "owl": (
        # Big round eyes blink shut and the ear-tufts droop.
        ",(O)(O),",
        ".(o)(o).",
    ),
    "penguin": (
        # Flippers swing in and out -- a waddle.
        "<('-')>",
        ">('-')<",
    ),
    "snail": (
        # The shell '@' inches forward along the trail, one column at
        # a time -- about as much motion as a snail deserves.
        "~~~@(o.o)",
        "~~@~(o.o)",
    ),
    "turtle": (
        # Legs swap ends -- a slow, deliberate paddle.
        "_/=(o.o)=\\_",
        "\\_=(o.o)=/_",
    ),
    "unicorn": (
        # Cheap two-frame gallop: legs alternate reach/tuck, echoing
        # the horse's cycle at a lighter weight.
        "*>>=(^.^)=>>*",
        "*//=(^.^)=//*",
    ),
    "fox": (
        # Tail/whisker flick between trotting strides.
        "-^(oo)^-",
        "~^(oo)^~",
    ),
    "panda": (
        # Rocks side to side, chewing bamboo -- ears swap in and out
        # of the parens as the body sways.
        "@(o.o)@",
        "(@o.o@)",
    ),
    "chick": (
        # Tiny feet tap -- commas become dots between pecks.
        "(^,,^)",
        "(^..^)",
    ),
    "rabbit": (
        # 3-frame hop: crouch (ears folded) -> leap (ears up straight)
        # -> land (ears splayed wide), then repeat.
        "v(o.o)v",
        "V(o.o)V",
        "Y(o.o)Y",
    ),
    "hamster": (
        # Cheeks work a mouthful of seeds -- mouth shape alternates.
        "(o'v'o)",
        "(o'0'o)",
    ),
    "duck": (
        # Paddles forward -- a ripple trails the bill each stroke.
        "(o.o)=>",
        "(o.o)~>",
    ),
    "whale": (
        # A slow, heavy swimmer -- the spout/wake alternates shape.
        "(o.o)=8",
        "(o.o)~8",
    ),
    "octopus": (
        # Tentacle tips curl in and out as it jets through the water.
        "~~(o.o)~~",
        "~v(o.o)v~",
    ),
    "butterfly": (
        # Wings mirror open/closed each beat -- a flutter.
        "><(^.^)><",
        "<>(^.^)<>",
    ),
    "dragon": (
        # Wings/tail swap sides mid-flap.
        "<(^==^)>",
        ">(^==^)<",
    ),
    "blocky": (
        # M14: TUI/ASCII fallback for the pixel-art "blocky" character --
        # arms swap which side is raised, echoing the real sprite's
        # counter-swing.
        "[#-#]",
        "{#-#}",
    ),
    "slime": (
        # Squash/stretch, ASCII-style: the blob's silhouette characters
        # widen and narrow between hops.
        "(o_o)~",
        "<o_o>~",
    ),
    "knight": (
        # Cape flag flutters: the trailing glyph flips between '\' and '/'
        # while both frames stay a well-formed, equal-width bracketed knight.
        "[o=|=o\\]",
        "[o=|=o/]",
    ),
}

STRIDE_COLUMNS: dict[str, int] = {
    "horse": 8,
    "cat": 2,
    "dog": 2,
    "robot": 2,
    "dino": 2,
    "crab": 2,
    "ghost": 2,
    "alien": 3,
    "bee": 3,
    "frog": 4,
    "owl": 2,
    "penguin": 2,
    "snail": 1,
    "turtle": 1,
    "unicorn": 6,
    "fox": 4,
    "panda": 2,
    "chick": 2,
    "rabbit": 5,
    "hamster": 3,
    "duck": 2,
    "whale": 1,
    "octopus": 2,
    "butterfly": 3,
    "dragon": 5,
    "blocky": 2,
    "slime": 3,
    "knight": 2,
}

_FALLBACK_STRIDE = 2


def gait_frames(name: str) -> tuple[str, ...]:
    """Return the gait-cycle frames for `name`.

    Every catalog entry in CHARACTERS has a dedicated, multi-frame entry in
    GAIT_FRAMES (see the coverage test), so the fallback below -- a single
    frame built from the character's static `ascii_art` -- is unreachable
    for any valid catalog name: it only runs for a `name` that is not in
    GAIT_FRAMES, and such a name is also not in CHARACTERS, so
    `get_character(name)` raises ValueError before the fallback tuple is
    ever built. An entirely unknown character name raises ValueError, same
    as `get_character`. The fallback is kept as a defensive guard for any
    future character that is registered in CHARACTERS before its gait art
    is written.
    """
    frames = GAIT_FRAMES.get(name)
    if frames is not None:
        return frames
    return (get_character(name).ascii_art,)


def stride_columns(name: str) -> int:
    """Columns advanced per full gait cycle for `name` (fallback: 2)."""
    return STRIDE_COLUMNS.get(name, _FALLBACK_STRIDE)
