"""Original pixel-art character pack for the macOS overlay (Task 34/M14).

Copyrighted game characters cannot be bundled, so this module defines three
ORIGINAL, MIT-clean characters as pure-Python pixel grids -- no binary
assets, just code. Each `SpriteSheet` carries a palette (single character ->
hex color, `" "` == transparent) and a set of named animation states, each a
tuple of frames, each frame a tuple of equal-length row strings drawn from
the palette.

Frames are built with small internal helpers (`_row`, `_torso_rows`, ...)
rather than typed out as one giant wall of literal strings: every row is
assembled by overlaying named segments onto a blank canvas of the frame's
exact width, so a mistyped row can never silently produce the wrong length
-- the geometry is correct by construction, not by manual counting. The
*content* of every row (which pixels are hair vs. skin vs. shirt, which
column a swinging arm's hand lands in) is still hand-composed, frame by
frame, exactly like laying out literal grids by hand.

Design notes, character by character:

- "blocky": a Minecraft-proportioned humanoid, 12 wide x 20 tall (head 6
  rows, torso+arms 4 rows, belt 3 rows, legs 7 rows). The walk cycle is a
  textbook 4-frame gait: CONTACT (feet spread wide, both planted) ->
  PASSING (feet centered, one leg shortened/lifted, torso fold shifts down
  a row -- the "1px bob") -> CONTACT-OTHER (mirrored) -> PASSING (mirrored
  support leg). Arms counter-swing opposite the forward leg: the arm on the
  side of the forward leg's *opposite* hip extends forward (reaching into
  the frame's side margin), the other tucks in against the torso.
- "slime": a squash-and-stretch blob, 14 wide x 12 tall. The walk state is
  a 4-frame hop (squash flat on the ground -> rising, leaning into the hop
  -> a tall pointed stretch at the peak, airborne -> descending, leaning
  back) rather than leg articulation, matching the character.
- "knight": a tiny knight with a trailing cape, 14 wide x 20 tall. Built on
  the same skeleton as "blocky" (helmet/torso+arms/belt/legs), with a cape
  occupying the left margin columns that billows wide on contact frames and
  tucks in tight on passing frames -- the cape's shape animates every walk
  frame, which is what "cape flow" means here.

Pure stdlib, no AppKit/pyobjc -- this module is imported by Task 35's
overlay renderer but has zero dependency on it.
"""

from __future__ import annotations

from dataclasses import dataclass

Frame = tuple[str, ...]


@dataclass(frozen=True)
class SpriteSheet:
    """A named pixel-art character: a palette plus a set of animation states.

    `states[name]` is a tuple of frames; each frame is a tuple of
    equal-length row strings drawn from `palette`'s keys (`" "` is always
    transparent and never needs a palette entry). `stride_px_per_cycle` is
    how many world-pixels the character advances per full walk cycle,
    pre-scale -- used by the overlay's stride-locked frame selection so
    walking never looks like foot-sliding.
    """

    name: str
    palette: dict[str, str]
    states: dict[str, tuple[Frame, ...]]
    stride_px_per_cycle: int


# ============================================================================
# Shared row-building helpers
# ============================================================================


def _row(width: int, *segments: tuple[int, str]) -> str:
    """A `width`-wide row of spaces with each `(start_col, text)` segment
    overlaid in order. Every row produced this way is exactly `width` long
    by construction -- there is no way to hand-miscount into a ragged grid."""
    chars = [" "] * width
    for start, text in segments:
        for i, ch in enumerate(text):
            chars[start + i] = ch
    return "".join(chars)


# ============================================================================
# "blocky" -- Minecraft-proportioned humanoid, 12 x 20
# ============================================================================

_BW, _BH = 12, 20

_BLOCKY_HEAD: Frame = (
    _row(_BW, (3, "HHHHHH")),
    _row(_BW, (3, "HSSSSH")),
    _row(_BW, (3, "SKSSKS")),
    _row(_BW, (3, "SSSSSS")),
    _row(_BW, (3, "SSKKSS")),
    _row(_BW, (3, "SSSSSS")),
)

_B_TORSO_PLAIN = "TTTTTT"
_B_TORSO_FOLD = "TTDDTT"

# Arm poses: row (relative to the torso block, 6-9) -> overlay segments.
# "hang" = resting at the side, "tuck" = pulled back against the torso
# (trailing arm mid-swing), "extend" = swung forward, reaching into the
# frame's side margin, "raise"/"raise5" = straight up overhead (jump/wave).
_B_LEFT_ARM = {
    "hang": {
        6: [(1, "D"), (2, "D")],
        7: [(1, "D"), (2, "D")],
        8: [(1, "S"), (2, "D")],
        9: [(1, "S")],
    },
    "tuck": {6: [(2, "D")], 7: [(2, "D")], 8: [], 9: []},
    "extend": {
        6: [(1, "D"), (2, "D")],
        7: [(0, "D"), (1, "D"), (2, "D")],
        8: [(0, "D"), (1, "S"), (2, "D")],
        9: [(0, "S")],
    },
    "raise5": [(1, "D"), (2, "D")],
    "raise": {6: [(1, "S"), (2, "D")], 7: [(2, "D")], 8: [(2, "D")], 9: []},
}
_B_RIGHT_ARM = {
    "hang": {
        6: [(9, "D"), (10, "D")],
        7: [(9, "D"), (10, "D")],
        8: [(9, "D"), (10, "S")],
        9: [(10, "S")],
    },
    "tuck": {6: [(9, "D")], 7: [(9, "D")], 8: [], 9: []},
    "extend": {
        6: [(9, "D"), (10, "D")],
        7: [(9, "D"), (10, "D"), (11, "D")],
        8: [(9, "D"), (10, "S"), (11, "D")],
        9: [(11, "S")],
    },
    "raise5": [(9, "D"), (10, "D")],
    "raise": {6: [(9, "D"), (10, "S")], 7: [(9, "D")], 8: [(9, "D")], 9: []},
}


def _blocky_torso(left_pose: str, right_pose: str, fold_row: int = 7) -> list[str]:
    """Rows 6-9: torso (fold line at `fold_row`) plus both arms' poses.
    The fold line moving from row 7 to row 8 between contact and passing
    walk frames *is* the "1px vertical body bob" the contract asks for."""
    out = []
    for r in range(6, 10):
        pattern = _B_TORSO_FOLD if r == fold_row else _B_TORSO_PLAIN
        segs = (
            [(3, pattern)] + _B_LEFT_ARM[left_pose].get(r, []) + _B_RIGHT_ARM[right_pose].get(r, [])
        )
        out.append(_row(_BW, *segs))
    return out


_BLOCKY_BELT: Frame = (
    _row(_BW, (3, _B_TORSO_PLAIN)),
    _row(_BW, (3, "PPPPPP")),
    _row(_BW, (3, "PPPPPP")),
)


def _blocky_legs_neutral() -> list[str]:
    return [
        _row(_BW, (3, "PPPPPP")),
        _row(_BW, (3, "PPPPPP")),
        _row(_BW, (3, "PPGGPP")),
        _row(_BW, (3, "PPPPPP")),
        _row(_BW, (3, "PPPPPP")),
        _row(_BW, (3, "KKKKKK")),
        _row(_BW, (3, "KKKKKK")),
    ]


def _blocky_legs_contact(forward_side: str) -> list[str]:
    """Both feet planted, spread wide apart -- the "contact" keyframe. The
    forward foot's boot reaches the ground (bottom row); the trailing foot's
    heel is already lifting, so its bottom row is blank."""
    rows = [
        _row(_BW, (2, "PPP"), (7, "PPP")),
        _row(_BW, (2, "PPP"), (7, "PPP")),
        _row(_BW, (2, "PGP"), (7, "PGP")),
        _row(_BW, (2, "PPP"), (7, "PPP")),
        _row(_BW, (2, "PPP"), (7, "PPP")),
        _row(_BW, (2, "KKK"), (7, "KKK")),
    ]
    rows.append(_row(_BW, (2, "KKK")) if forward_side == "left" else _row(_BW, (7, "KKK")))
    return rows


def _blocky_legs_passing(support_side: str) -> list[str]:
    """Legs centered/crossing -- the "passing" keyframe. The support leg
    reaches all the way down; the swinging leg is shortened (lifted, mid-air)."""
    rows = [
        _row(_BW, (3, "PPPPPP")),
        _row(_BW, (3, "PPPPPP")),
        _row(_BW, (3, "PPGGPP")),
        _row(_BW, (3, "PPPPPP")),
    ]
    start = 3 if support_side == "left" else 6
    rows += [_row(_BW, (start, "PPP")), _row(_BW, (start, "KKK")), _row(_BW, (start, "KKK"))]
    return rows


def _blocky_frame(head: Frame, torso: list[str], belt: Frame, legs: list[str]) -> Frame:
    return tuple(head) + tuple(torso) + tuple(belt) + tuple(legs)


_BLOCKY_WALK: tuple[Frame, ...] = (
    _blocky_frame(  # 1. CONTACT: left leg forward, right arm forward
        _BLOCKY_HEAD, _blocky_torso("tuck", "extend", 7), _BLOCKY_BELT, _blocky_legs_contact("left")
    ),
    _blocky_frame(  # 2. PASSING: right leg swings through, arms near-neutral
        _BLOCKY_HEAD, _blocky_torso("hang", "hang", 8), _BLOCKY_BELT, _blocky_legs_passing("left")
    ),
    _blocky_frame(  # 3. CONTACT-OTHER: right leg forward, left arm forward
        _BLOCKY_HEAD,
        _blocky_torso("extend", "tuck", 7),
        _BLOCKY_BELT,
        _blocky_legs_contact("right"),
    ),
    _blocky_frame(  # 4. PASSING: left leg swings through, arms near-neutral
        _BLOCKY_HEAD, _blocky_torso("hang", "hang", 8), _BLOCKY_BELT, _blocky_legs_passing("right")
    ),
)

_BLOCKY_IDLE: tuple[Frame, ...] = (
    _blocky_frame(
        _BLOCKY_HEAD, _blocky_torso("hang", "hang", 7), _BLOCKY_BELT, _blocky_legs_neutral()
    ),
    _blocky_frame(  # breathing: fold line shifts down a row
        _BLOCKY_HEAD, _blocky_torso("hang", "hang", 8), _BLOCKY_BELT, _blocky_legs_neutral()
    ),
)


def _blocky_jump_crouch() -> Frame:
    """Anticipation: both arms tucked back, a deep, wide squat."""
    torso = []
    for r in range(6, 10):
        pattern = _B_TORSO_FOLD if r == 7 else _B_TORSO_PLAIN
        segs = [(3, pattern)] + _B_LEFT_ARM["tuck"].get(r, []) + _B_RIGHT_ARM["tuck"].get(r, [])
        torso.append(_row(_BW, *segs))
    legs = [
        _row(_BW, (2, "PPPPPPPP")),
        _row(_BW, (2, "PPGGGGPP")),
        _row(_BW, (2, "PPPPPPPP")),
        _row(_BW, (2, "PPPPPPPP")),
        _row(_BW, (2, "PPPPPPPP")),
        _row(_BW, (2, "KKKKKKKK")),
        _row(_BW, (2, "KKKKKKKK")),
    ]
    return _blocky_frame(_BLOCKY_HEAD, torso, _BLOCKY_BELT, legs)


def _blocky_jump_airborne() -> Frame:
    """Peak: both arms raised straight overhead, legs tucked up, off the ground."""
    r5 = _row(_BW, (3, "SSSSSS"), *_B_LEFT_ARM["raise5"], *_B_RIGHT_ARM["raise5"])
    torso = []
    for r in range(6, 10):
        pattern = _B_TORSO_FOLD if r == 7 else _B_TORSO_PLAIN
        segs = [(3, pattern)] + _B_LEFT_ARM["raise"].get(r, []) + _B_RIGHT_ARM["raise"].get(r, [])
        torso.append(_row(_BW, *segs))
    legs = [
        _row(_BW, (3, "PPPPPP")),
        _row(_BW, (3, "PPGGPP")),
        _row(_BW, (3, "PPPPPP")),
        _row(_BW, (3, "KKKKKK")),
        _row(_BW),
        _row(_BW),
        _row(_BW),
    ]
    return tuple(_BLOCKY_HEAD[:5]) + (r5,) + tuple(torso) + _BLOCKY_BELT + tuple(legs)


_BLOCKY_JUMP: tuple[Frame, ...] = (_blocky_jump_crouch(), _blocky_jump_airborne())


def _blocky_wave(hand_col: int) -> Frame:
    """Right arm raised overhead, waving: `hand_col` (9 or 10) is which
    column the raised hand sits in, so the two wave frames show the hand
    flicking side to side."""
    head_row5 = [" "] * _BW
    for i, ch in enumerate("SSSSSS"):
        head_row5[3 + i] = ch
    head_row5[9] = "D"
    head_row5[10] = "D"
    head_row5[hand_col] = "S"
    r5 = "".join(head_row5)

    r6_chars = [" "] * _BW
    for i, ch in enumerate(_B_TORSO_PLAIN):
        r6_chars[3 + i] = ch
    r6_chars[1] = "D"
    r6_chars[2] = "D"
    r6_chars[9] = "S" if hand_col == 9 else "D"
    r6_chars[10] = "D" if hand_col == 9 else "S"
    r6 = "".join(r6_chars)

    r7 = _row(_BW, (3, _B_TORSO_FOLD), *_B_LEFT_ARM["hang"][7], (9, "D"))
    r8 = _row(_BW, (3, _B_TORSO_PLAIN), *_B_LEFT_ARM["hang"][8], (9, "D"))
    r9 = _row(_BW, (3, _B_TORSO_PLAIN), *_B_LEFT_ARM["hang"][9])
    head = tuple(_BLOCKY_HEAD[:5]) + (r5,)
    return _blocky_frame(head, [r6, r7, r8, r9], _BLOCKY_BELT, _blocky_legs_neutral())


_BLOCKY_WAVE: tuple[Frame, ...] = (_blocky_wave(10), _blocky_wave(9))

_BLOCKY_PALETTE: dict[str, str] = {
    "H": "#4A3222",  # hair
    "S": "#E8B08A",  # skin
    "K": "#1B1611",  # eyes / boots (near-black)
    "T": "#8B5E3C",  # shirt
    "D": "#6B4423",  # shirt shading / sleeves
    "P": "#4A4A52",  # pants
    "G": "#33333A",  # pants shading (knees)
}

BLOCKY = SpriteSheet(
    name="blocky",
    palette=_BLOCKY_PALETTE,
    states={
        "idle": _BLOCKY_IDLE,
        "walk": _BLOCKY_WALK,
        "jump": _BLOCKY_JUMP,
        "wave": _BLOCKY_WAVE,
    },
    stride_px_per_cycle=16,
)


# ============================================================================
# "slime" -- squash-and-stretch blob, 14 x 12
# ============================================================================

_SW, _SH = 14, 12


def _slime_body(
    eyes_at: tuple[int, int] | None = None, mouth_at: tuple[int, int] | None = None
) -> str:
    """A full-width (14) blob body row: dark edge columns, green fill, and
    optional eye/mouth pixels punched in."""
    chars = ["D"] + ["G"] * 12 + ["D"]
    if eyes_at:
        for c in eyes_at:
            chars[c] = "E"
    if mouth_at:
        for c in mouth_at:
            chars[c] = "D"
    return "".join(chars)


_S_BODY_PLAIN = _slime_body()
_S_BODY_EYES_CENTER = _slime_body(eyes_at=(4, 9))
_S_BODY_EYES_RIGHT = _slime_body(eyes_at=(5, 10))  # leaning into travel direction
_S_BODY_EYES_LEFT = _slime_body(eyes_at=(3, 8))  # leaning back
_S_BODY_MOUTH_CENTER = _slime_body(mouth_at=(6, 7))
_S_BODY_MOUTH_RIGHT = _slime_body(mouth_at=(7, 8))
_S_BODY_MOUTH_LEFT = _slime_body(mouth_at=(5, 6))

_S_TOP_TINY = _row(_SW, (5, "GGGG"))  # dome tip, centered
_S_TOP_HIGHLIGHT = _row(_SW, (3, "G"), (4, "HH"), (5, "GGGGG"))  # dome w/ shine
_S_ROW_WIDE = _row(_SW, (1, "GGG"), (4, "H"), (5, "GGGGGGGG"))  # wide dome w/ shine
_S_BASE_WIDE = _row(_SW, (1, "D"), (2, "G" * 10), (12, "D"))  # widest base, flat-ish
_S_BASE_NARROW = _row(_SW, (2, "D"), (3, "G" * 8), (11, "D"))  # rounded bottom corner
_S_BLANK = _row(_SW)

# The tall-stretch silhouette shared by the walk-hop peak and the jump peak.
_S_STRETCH_TOP = (
    _row(_SW, (6, "GG")),
    _row(_SW, (5, "GGGG")),
    _row(_SW, (4, "GGGGGG")),
    _row(_SW, (3, "GGGGGGGG")),
    _row(_SW, (2, "GGGGEGGGEG")),  # eyes leaning right, into the travel direction
    _row(_SW, (1, "GGGGGGDDGGGG")),  # mouth leaning right
)


def _slime_frame(*rows: str) -> Frame:
    return tuple(rows)


_SLIME_NEUTRAL = _slime_frame(
    _S_TOP_TINY,
    _S_TOP_HIGHLIGHT,
    _S_ROW_WIDE,
    _S_BODY_PLAIN,
    _S_BODY_EYES_CENTER,
    _S_BODY_PLAIN,
    _S_BODY_MOUTH_CENTER,
    _S_BODY_PLAIN,
    _S_BODY_PLAIN,
    _S_BODY_PLAIN,
    _S_BASE_WIDE,
    _S_BASE_NARROW,
)

_SLIME_IDLE: tuple[Frame, ...] = (
    _SLIME_NEUTRAL,
    _slime_frame(  # wobble: dome tip flattens, base spreads wider
        _S_BLANK,
        _S_TOP_HIGHLIGHT,
        _S_ROW_WIDE,
        _S_BODY_PLAIN,
        _S_BODY_EYES_CENTER,
        _S_BODY_PLAIN,
        _S_BODY_MOUTH_CENTER,
        _S_BODY_PLAIN,
        _S_BODY_PLAIN,
        _S_BODY_PLAIN,
        _S_BASE_WIDE,
        _S_BASE_WIDE,
    ),
)

_SLIME_WALK: tuple[Frame, ...] = (
    _slime_frame(  # 1. SQUASH: flat on the ground, leaning back (trailing)
        _S_BLANK,
        _S_BLANK,
        _S_BLANK,
        _S_BASE_WIDE,
        _S_BODY_PLAIN,
        _S_BODY_EYES_LEFT,
        _S_BODY_MOUTH_CENTER,
        _S_BODY_PLAIN,
        _S_BODY_PLAIN,
        _S_BODY_PLAIN,
        _S_BASE_WIDE,
        _S_BASE_NARROW,
    ),
    _slime_frame(  # 2. RISE: back to the dome shape, leaning forward
        _S_TOP_TINY,
        _S_TOP_HIGHLIGHT,
        _S_ROW_WIDE,
        _S_BODY_PLAIN,
        _S_BODY_EYES_RIGHT,
        _S_BODY_PLAIN,
        _S_BODY_MOUTH_RIGHT,
        _S_BODY_PLAIN,
        _S_BODY_PLAIN,
        _S_BODY_PLAIN,
        _S_BASE_WIDE,
        _S_BASE_NARROW,
    ),
    _slime_frame(  # 3. STRETCH: tall and narrow, airborne at the hop's peak
        *_S_STRETCH_TOP,
        _S_BODY_PLAIN,
        _S_BODY_PLAIN,
        _S_BASE_WIDE,
        _S_BASE_NARROW,
        _row(_SW, (3, "D"), (4, "GGGGGG"), (10, "D")),
        _S_BLANK,
    ),
    _slime_frame(  # 4. DESCEND: dome shape again, leaning back for landing
        _S_TOP_TINY,
        _S_TOP_HIGHLIGHT,
        _S_ROW_WIDE,
        _S_BODY_PLAIN,
        _S_BODY_EYES_LEFT,
        _S_BODY_PLAIN,
        _S_BODY_MOUTH_LEFT,
        _S_BODY_PLAIN,
        _S_BODY_PLAIN,
        _S_BODY_PLAIN,
        _S_BASE_WIDE,
        _S_BASE_NARROW,
    ),
)

_SLIME_JUMP: tuple[Frame, ...] = (
    _slime_frame(  # deep squash -- lower/flatter than any walk frame
        _S_BLANK,
        _S_BLANK,
        _S_BLANK,
        _S_BLANK,
        _S_BASE_WIDE,
        _S_BODY_PLAIN,
        _S_BODY_EYES_LEFT,
        _S_BODY_MOUTH_CENTER,
        _S_BODY_PLAIN,
        _S_BODY_PLAIN,
        _S_BASE_WIDE,
        _S_BASE_NARROW,
    ),
    _slime_frame(  # taller stretch -- 2 blank rows of ground clearance vs. 1 in walk
        *_S_STRETCH_TOP,
        _S_BODY_PLAIN,
        _S_BODY_PLAIN,
        _S_BASE_WIDE,
        _S_BASE_NARROW,
        _S_BLANK,
        _S_BLANK,
    ),
)

_SLIME_WAVE: tuple[Frame, ...] = (
    _slime_frame(  # lean right
        _row(_SW, (6, "GGGG")),
        _row(_SW, (4, "GGGGGGGG")),
        _row(_SW, (2, "GGGGGGGGGGGG")),
        _S_BODY_PLAIN,
        _S_BODY_EYES_RIGHT,
        _S_BODY_PLAIN,
        _S_BODY_MOUTH_RIGHT,
        _S_BODY_PLAIN,
        _S_BODY_PLAIN,
        _S_BODY_PLAIN,
        _S_BASE_WIDE,
        _S_BASE_NARROW,
    ),
    _slime_frame(  # lean left
        _row(_SW, (4, "GGGG")),
        _row(_SW, (2, "GGGGGGGG")),
        _row(_SW, (0, "GGGGGGGGGGGG")),
        _S_BODY_PLAIN,
        _S_BODY_EYES_LEFT,
        _S_BODY_PLAIN,
        _S_BODY_MOUTH_LEFT,
        _S_BODY_PLAIN,
        _S_BODY_PLAIN,
        _S_BODY_PLAIN,
        _S_BASE_WIDE,
        _S_BASE_NARROW,
    ),
)

_SLIME_PALETTE: dict[str, str] = {
    "G": "#7CC142",  # body
    "D": "#4E8A29",  # edge/outline shading
    "E": "#1B1611",  # eyes
    "H": "#C8F0A0",  # highlight/shine
}

SLIME = SpriteSheet(
    name="slime",
    palette=_SLIME_PALETTE,
    states={
        "idle": _SLIME_IDLE,
        "walk": _SLIME_WALK,
        "jump": _SLIME_JUMP,
        "wave": _SLIME_WAVE,
    },
    stride_px_per_cycle=10,
)


# ============================================================================
# "knight" -- tiny knight with a cape, 14 x 20
# ============================================================================

_KW, _KH = 14, 20

_KNIGHT_HELMET: Frame = (
    _row(_KW, (4, "AAYYAA")),
    _row(_KW, (4, "YAAAAY")),
    _row(_KW, (4, "AAEEAA")),
    _row(_KW, (4, "ASSSSA")),
    _row(_KW, (4, "AASSAA")),
    _row(_KW, (4, "BBBBBB")),
)

_K_TORSO_PLAIN = "AAAAAA"
_K_TORSO_FOLD = "AABBAA"

_K_LEFT_ARM = {
    "hang": {
        6: [(2, "B"), (3, "B")],
        7: [(2, "B"), (3, "B")],
        8: [(2, "G"), (3, "B")],
        9: [(2, "G")],
    },
    "tuck": {6: [(3, "B")], 7: [(3, "B")], 8: [], 9: []},
    "extend": {
        6: [(2, "B"), (3, "B")],
        7: [(1, "B"), (2, "B"), (3, "B")],
        8: [(1, "B"), (2, "G"), (3, "B")],
        9: [(1, "G")],
    },
    "raise5": [(2, "B"), (3, "B")],
    "raise": {6: [(2, "G"), (3, "B")], 7: [(3, "B")], 8: [(3, "B")], 9: []},
}
_K_RIGHT_ARM = {
    "hang": {
        6: [(10, "B"), (11, "B")],
        7: [(10, "B"), (11, "B")],
        8: [(10, "B"), (11, "G")],
        9: [(11, "G")],
    },
    "tuck": {6: [(10, "B")], 7: [(10, "B")], 8: [], 9: []},
    "extend": {
        6: [(10, "B"), (11, "B")],
        7: [(10, "B"), (11, "B"), (12, "B")],
        8: [(10, "B"), (11, "G"), (12, "B")],
        9: [(12, "G")],
    },
    "raise5": [(10, "B"), (11, "B")],
    "raise": {6: [(10, "G"), (11, "B")], 7: [(10, "B")], 8: [(10, "B")], 9: []},
}

# Cape shapes: col0/col1 -> {row: char}. "wide" billows in both columns
# (contact frames -- the cape flares out mid-stride); "tucked" only fills
# the inner column (passing frames -- the cape trails in close). This is
# what makes the cape visibly *flow* across the walk cycle rather than
# sitting static.
_K_CAPE_WIDE_0 = {r: "C" for r in range(6, 13)}
_K_CAPE_WIDE_1 = {r: "C" for r in range(6, 13)}
_K_CAPE_TUCKED_1 = {r: "C" for r in range(6, 13)}
_K_CAPE_JUMP_0 = {r: "C" for r in range(5, 13)}
_K_CAPE_JUMP_1 = {r: "C" for r in range(5, 13)}


def _knight_torso(
    left_pose: str,
    right_pose: str,
    fold_row: int = 7,
    cape0: dict[int, str] | None = None,
    cape1: dict[int, str] | None = None,
) -> list[str]:
    out = []
    for r in range(6, 10):
        pattern = _K_TORSO_FOLD if r == fold_row else _K_TORSO_PLAIN
        segs = (
            [(4, pattern)] + _K_LEFT_ARM[left_pose].get(r, []) + _K_RIGHT_ARM[right_pose].get(r, [])
        )
        if cape0 and r in cape0:
            segs.append((0, cape0[r]))
        if cape1 and r in cape1:
            segs.append((1, cape1[r]))
        out.append(_row(_KW, *segs))
    return out


def _knight_belt(cape0: dict[int, str] | None = None, cape1: dict[int, str] | None = None) -> Frame:
    out = []
    for r, fill in zip((10, 11, 12), ("AAAAAA", "YYYYYY", "BBBBBB"), strict=True):
        segs = [(4, fill)]
        if cape0 and r in cape0:
            segs.append((0, cape0[r]))
        if cape1 and r in cape1:
            segs.append((1, cape1[r]))
        out.append(_row(_KW, *segs))
    return tuple(out)


def _knight_legs_neutral() -> list[str]:
    return [
        _row(_KW, (4, "AAAAAA")),
        _row(_KW, (4, "AAAAAA")),
        _row(_KW, (4, "AABBAA")),
        _row(_KW, (4, "AAAAAA")),
        _row(_KW, (4, "AAAAAA")),
        _row(_KW, (4, "GGGGGG")),
        _row(_KW, (4, "GGGGGG")),
    ]


def _knight_legs_contact(forward_side: str) -> list[str]:
    rows = [
        _row(_KW, (3, "AAA"), (8, "AAA")),
        _row(_KW, (3, "AAA"), (8, "AAA")),
        _row(_KW, (3, "ABA"), (8, "ABA")),
        _row(_KW, (3, "AAA"), (8, "AAA")),
        _row(_KW, (3, "AAA"), (8, "AAA")),
        _row(_KW, (3, "GGG"), (8, "GGG")),
    ]
    rows.append(_row(_KW, (3, "GGG")) if forward_side == "left" else _row(_KW, (8, "GGG")))
    return rows


def _knight_legs_passing(support_side: str) -> list[str]:
    rows = [
        _row(_KW, (4, "AAAAAA")),
        _row(_KW, (4, "AAAAAA")),
        _row(_KW, (4, "AABBAA")),
        _row(_KW, (4, "AAAAAA")),
    ]
    start = 4 if support_side == "left" else 7
    rows += [_row(_KW, (start, "AAA")), _row(_KW, (start, "GGG")), _row(_KW, (start, "GGG"))]
    return rows


def _knight_frame(helmet: Frame, torso: list[str], belt: Frame, legs: list[str]) -> Frame:
    return tuple(helmet) + tuple(torso) + tuple(belt) + tuple(legs)


_KNIGHT_WALK: tuple[Frame, ...] = (
    _knight_frame(  # 1. CONTACT: left leg forward, cape billowed wide
        _KNIGHT_HELMET,
        _knight_torso("tuck", "extend", 7, _K_CAPE_WIDE_0, _K_CAPE_WIDE_1),
        _knight_belt(_K_CAPE_WIDE_0, _K_CAPE_WIDE_1),
        _knight_legs_contact("left"),
    ),
    _knight_frame(  # 2. PASSING: right leg swings through, cape tucks in
        _KNIGHT_HELMET,
        _knight_torso("hang", "hang", 8, None, _K_CAPE_TUCKED_1),
        _knight_belt(None, _K_CAPE_TUCKED_1),
        _knight_legs_passing("left"),
    ),
    _knight_frame(  # 3. CONTACT-OTHER: right leg forward, cape billowed wide
        _KNIGHT_HELMET,
        _knight_torso("extend", "tuck", 7, _K_CAPE_WIDE_0, _K_CAPE_WIDE_1),
        _knight_belt(_K_CAPE_WIDE_0, _K_CAPE_WIDE_1),
        _knight_legs_contact("right"),
    ),
    _knight_frame(  # 4. PASSING: left leg swings through, cape tucks in
        _KNIGHT_HELMET,
        _knight_torso("hang", "hang", 8, None, _K_CAPE_TUCKED_1),
        _knight_belt(None, _K_CAPE_TUCKED_1),
        _knight_legs_passing("right"),
    ),
)

_KNIGHT_IDLE: tuple[Frame, ...] = (
    _knight_frame(
        _KNIGHT_HELMET,
        _knight_torso("hang", "hang", 7, None, _K_CAPE_TUCKED_1),
        _knight_belt(None, _K_CAPE_TUCKED_1),
        _knight_legs_neutral(),
    ),
    _knight_frame(  # breathing: fold line shifts down a row
        _KNIGHT_HELMET,
        _knight_torso("hang", "hang", 8, None, _K_CAPE_TUCKED_1),
        _knight_belt(None, _K_CAPE_TUCKED_1),
        _knight_legs_neutral(),
    ),
)


def _knight_jump_crouch() -> Frame:
    torso = []
    for r in range(6, 10):
        pattern = _K_TORSO_FOLD if r == 7 else _K_TORSO_PLAIN
        segs = [(4, pattern)] + _K_LEFT_ARM["tuck"].get(r, []) + _K_RIGHT_ARM["tuck"].get(r, [])
        torso.append(_row(_KW, *segs))
    legs = [
        _row(_KW, (3, "AAAAAAAA")),
        _row(_KW, (3, "AABBBBAA")),
        _row(_KW, (3, "AAAAAAAA")),
        _row(_KW, (3, "AAAAAAAA")),
        _row(_KW, (3, "AAAAAAAA")),
        _row(_KW, (3, "GGGGGGGG")),
        _row(_KW, (3, "GGGGGGGG")),
    ]
    return _knight_frame(_KNIGHT_HELMET, torso, _knight_belt(), legs)


def _knight_jump_airborne() -> Frame:
    r5 = _row(_KW, (4, "BBBBBB"), *_K_LEFT_ARM["raise5"], *_K_RIGHT_ARM["raise5"], (1, "C"))
    torso = []
    for r in range(6, 10):
        pattern = _K_TORSO_FOLD if r == 7 else _K_TORSO_PLAIN
        segs = [(4, pattern)] + _K_LEFT_ARM["raise"].get(r, []) + _K_RIGHT_ARM["raise"].get(r, [])
        if r in _K_CAPE_JUMP_0:
            segs.append((0, _K_CAPE_JUMP_0[r]))
        if r in _K_CAPE_JUMP_1:
            segs.append((1, _K_CAPE_JUMP_1[r]))
        torso.append(_row(_KW, *segs))
    belt = _knight_belt(_K_CAPE_JUMP_0, _K_CAPE_JUMP_1)
    legs = [
        _row(_KW, (4, "AAAAAA")),
        _row(_KW, (4, "AABBAA")),
        _row(_KW, (4, "AAAAAA")),
        _row(_KW, (4, "GGGGGG")),
        _row(_KW),
        _row(_KW),
        _row(_KW),
    ]
    return tuple(_KNIGHT_HELMET[:5]) + (r5,) + tuple(torso) + belt + tuple(legs)


_KNIGHT_JUMP: tuple[Frame, ...] = (_knight_jump_crouch(), _knight_jump_airborne())


def _knight_wave(blade_col: int) -> Frame:
    """Right arm raised with a drawn sword; `blade_col` (10 or 11) is which
    column the blade tip sits in, so the two frames show a small swing."""
    r4 = _row(_KW, (4, "ASSSSA"), (blade_col, "W"))
    r5 = _row(_KW, (4, "BBBBBB"), (blade_col, "W"))
    r6 = _row(_KW, (4, _K_TORSO_PLAIN), *_K_LEFT_ARM["hang"][6], (10, "Y"), (11, "B"), (0, "C"))
    r7 = _row(_KW, (4, _K_TORSO_FOLD), *_K_LEFT_ARM["hang"][7], (10, "B"), (0, "C"))
    r8 = _row(_KW, (4, _K_TORSO_PLAIN), *_K_LEFT_ARM["hang"][8], (10, "B"), (0, "C"))
    r9 = _row(_KW, (4, _K_TORSO_PLAIN), *_K_LEFT_ARM["hang"][9], (0, "C"))
    helmet = tuple(_KNIGHT_HELMET[:4]) + (r4, r5)
    return _knight_frame(
        helmet, [r6, r7, r8, r9], _knight_belt(None, _K_CAPE_TUCKED_1), _knight_legs_neutral()
    )


_KNIGHT_WAVE: tuple[Frame, ...] = (_knight_wave(10), _knight_wave(11))

_KNIGHT_PALETTE: dict[str, str] = {
    "A": "#9AA5AD",  # armor plate
    "B": "#5B6670",  # armor shading
    "S": "#E8B08A",  # face
    "E": "#1B1611",  # eyes (visor slit)
    "C": "#A5323C",  # cape
    "Y": "#D4AF37",  # gold trim
    "G": "#3A3F44",  # gauntlets / boots
    "W": "#E8ECEF",  # sword blade
}

KNIGHT = SpriteSheet(
    name="knight",
    palette=_KNIGHT_PALETTE,
    states={
        "idle": _KNIGHT_IDLE,
        "walk": _KNIGHT_WALK,
        "jump": _KNIGHT_JUMP,
        "wave": _KNIGHT_WAVE,
    },
    stride_px_per_cycle=16,
)


# ============================================================================
# Catalog
# ============================================================================

SPRITES: dict[str, SpriteSheet] = {
    "blocky": BLOCKY,
    "slime": SLIME,
    "knight": KNIGHT,
}


def sprite(name: str) -> SpriteSheet:
    """Look up a pixel-art sprite sheet by name.

    Raises `ValueError` (never `KeyError`) listing the available names."""
    try:
        return SPRITES[name]
    except KeyError:
        available = ", ".join(SPRITES)
        msg = f"Unknown sprite: {name}. Available: {available}"
        raise ValueError(msg) from None
