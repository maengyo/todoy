"""Pure sprite-animation state/frame-index logic (M14 Task 35).

Everything here is plain Python -- floats, strings, dicts, `pathlib.Path` --
directly unit-testable by calling it with fabricated arguments, without
building a real `NSView`/`NSImage`/`NSWindow`. This is deliberately its own
module, separate from `macos.py` (the one file allowed to touch AppKit):
`macos.py` imports unconditionally `import AppKit` at module scope, so ANY
test that imports it -- even one exercising a function with zero AppKit
calls in its own body -- has to sit behind the repo's `pytest.importorskip
("AppKit")` skip gate and never runs on non-macOS CI. Splitting the pure
logic out here (Codex review follow-up on the first cut of Task 35, which
had all of this inline in macos.py) means its own tests
(`tests/test_spritestate.py`) run on every OS/CI, not just behind that gate.

`macos.py` imports everything it needs from here (state selection, frame
indexing, palette parsing, scale fitting, user-sprite-folder file scanning);
nothing here imports from `macos.py` or touches AppKit. It's kept separate
from `animations.py` (which owns the movement/entrance/flourish *curves*
themselves) because this module is specific to sprite *rendering* --
picking a sprite-sheet state name and frame index from those curves'
outputs, not producing the curves.
"""

from __future__ import annotations

from pathlib import Path

from todoy.display.overlay.animations import (
    FLOAT_BOB_AMPLITUDE_PX,
    GALLOP_HOP_PEAK_HEIGHT_PX,
    HOP_PEAK_HEIGHT_PX,
)

# Required sprite-sheet states (contract section 1): "idle", "walk", "jump",
# "wave". A user folder that's missing a state falls back per contract:
# jump -> walk's first frame, wave -> the whole idle animation (see
# `sprite_frames_for_state`); code sheets always carry all four (enforced
# by pixelart.py's own grid-rule tests), but the same fallback runs there
# too as a cheap defensive no-op.
SPRITE_STATES: tuple[str, ...] = ("idle", "walk", "jump", "wave")

# Code pixel-art is drawn nearest-neighbor (no smoothing) at roughly this
# multiple of its native pixel-grid size so individual pixels stay crisp
# blocks instead of blurring -- "roughly" because `fit_code_sprite_scale`
# clamps it down (never up) so the tallest frame of the tallest state never
# overflows the fixed-size character window.
SPRITE_CODE_SCALE = 5.0

# User PNG folders carry no stride metadata of their own (unlike a code
# `SpriteSheet.stride_px_per_cycle`), so the walk cycle needs *some* fixed
# world-pixel length to stride-lock against -- chosen to land in the same
# ballpark as the code packs' own values (contract's ~12-14px-wide grids at
# a handful of world-pixels per cycle) so a user's replacement walk doesn't
# read as sliding or frantic footwork by default.
DEFAULT_USER_SPRITE_STRIDE_PX_PER_CYCLE = 24.0

# Time-driven frame rates for the non-walk sprite states (walk is distance-
# /stride-locked instead -- see `sprite_walk_frame_index`). Idle matches the
# contract's explicit "~2fps"; jump/wave are faster so a short hop or wave
# flourish (well under a second) still visibly cycles more than one frame.
SPRITE_IDLE_FPS = 2.0
SPRITE_JUMP_FPS = 6.0
SPRITE_WAVE_FPS = 4.0

# `dx`/`y_offset` noise floor (float comparisons on tiny per-tick deltas) --
# well below one screen pixel, so it never misclassifies genuine motion as
# "idle" but still absorbs floating-point jitter from a perfectly `still`
# character.
SPRITE_MOTION_EPSILON_PX = 0.01

# `CharacterMovement.step`'s y_offset only rises above 0 for hop/gallop/
# float; walk/dash/still never bounce, so "jump" can only ever be triggered
# for those three via the y_offset>20%-of-peak rule below (contract section
# 3). `float`'s bob oscillates across `[0, 2*FLOAT_BOB_AMPLITUDE_PX]`, so its
# "peak" for this purpose is the full range, not just the amplitude.
SPRITE_JUMP_Y_OFFSET_RATIO = 0.2


def sprite_movement_hop_peak_px(movement: str) -> float:
    """The current movement preset's own bounce peak (world pixels), used by
    `sprite_state_for_tick`'s y_offset>20%-of-peak "jump" rule. `walk`/
    `dash`/`still` never bounce (`CharacterMovement.step` always returns
    `y_offset == 0.0` for them) -- 0.0 here correctly means that rule can
    never fire for those, leaving `jump` reachable only via a hop/splash
    entrance for them."""
    if movement == "hop":
        return HOP_PEAK_HEIGHT_PX
    if movement == "gallop":
        return GALLOP_HOP_PEAK_HEIGHT_PX
    if movement == "float":
        # float's bob oscillates across the full [0, 2*amplitude] range, not
        # just up to the amplitude -- see FLOAT_BOB_AMPLITUDE_PX's own
        # docstring in animations.py.
        return FLOAT_BOB_AMPLITUDE_PX * 2.0
    return 0.0


def sprite_state_for_tick(
    *,
    dx: float,
    y_offset: float,
    hop_peak_px: float,
    entrance_active: bool,
    entrance_is_hop_or_splash: bool,
    flourish_active: bool,
    is_turning: bool = False,
    epsilon: float = SPRITE_MOTION_EPSILON_PX,
) -> str:
    """Per-tick sprite state (contract section 3), in priority order:

    1. A hop_in/splash launch entrance is in progress -- `jump`. (Other
       entrance kinds, e.g. walk_in's horizontal slide, don't bounce and
       fall through to the normal rules below; `CharacterMovement` is held
       at `step(0.0)` for the whole entrance regardless of kind, so `dx` is
       always 0 during one anyway -- see `_OverlayController.onWanderTick_`.)
    2. A fire-time flourish is active -- `wave`, unconditionally (contract:
       "wave during flourish active" -- even a bouncy `hop` flourish reads
       fine as a wave-pose hop, per the contract's own blocky example).
    3. The movement preset's own bounce has risen above `hop_peak_px *
       SPRITE_JUMP_Y_OFFSET_RATIO` -- `jump` (only reachable for hop/gallop/
       float, whose `hop_peak_px` is > 0; see `sprite_movement_hop_peak_px`).
       Checked before the turn/walk rules below: a mid-air turn (gallop can
       turn while airborne) should still read as jump, not idle.
    4. `is_turning` -- `idle` (Codex review follow-up: net `dx` for a tick
       is NOT a reliable walk/idle signal while an eased edge-turn
       (`CharacterMovement.is_turning`, `animations.TURN_DURATION_SECONDS`,
       ~0.25-0.35s) is in progress -- velocity swings from full speed down
       through exactly zero at the turn's midpoint and back up in the new
       direction, so per-tick `dx` can land anywhere from "clearly walking"
       to "under epsilon" to "negative" depending on exactly where a fixed
       ~1/30s tick happens to sample that cosine curve, which would flicker
       the walk frame or misfire idle/walk unpredictably from tick to tick.
       The chosen window here is the WHOLE turn, not just the exact
       zero-velocity tick: `TURN_DURATION_SECONDS` is short (a fraction of
       a second) and a character visibly pausing to turn in place reads
       fine as "idle" for that whole beat -- simpler and more robust than
       trying to isolate just the midpoint from `is_turning` alone, which
       carries no elapsed-time-within-the-turn signal to narrow further.)
    5. Genuine horizontal motion this tick (`|dx| > epsilon`) -- `walk`.
    6. Otherwise -- `idle`.
    """
    if entrance_active and entrance_is_hop_or_splash:
        return "jump"
    if flourish_active:
        return "wave"
    if hop_peak_px > 0.0 and y_offset > hop_peak_px * SPRITE_JUMP_Y_OFFSET_RATIO:
        return "jump"
    if is_turning:
        return "idle"
    if abs(dx) > epsilon:
        return "walk"
    return "idle"


def sprite_walk_frame_index(
    distance_px: float, stride_px_per_cycle: float, scale: float, frame_count: int
) -> int:
    """Stride-locked walk frame (contract section 3's exact formula): driven
    by cumulative distance traveled, never by elapsed time/tick count -- the
    same distance always lands on the same frame regardless of how many
    `step()` calls (i.e. whatever fps) it took to cover it, so there's no
    foot-sliding illusion from a variable frame rate.

    `stride_px_per_cycle` is in *pre-scale* world pixels (the pixel grid's
    own units, or `DEFAULT_USER_SPRITE_STRIDE_PX_PER_CYCLE` for a user
    folder); `scale` converts that to on-screen pixels (the same units
    `distance_px` accumulates in, from the character window's actual
    movement) -- see `fit_code_sprite_scale`.
    """
    if frame_count <= 0:
        return 0
    denom = stride_px_per_cycle * scale / frame_count
    if denom <= 0.0:
        return 0
    return int(distance_px / denom) % frame_count


def sprite_time_frame_index(elapsed_seconds: float, fps: float, frame_count: int) -> int:
    """Time-driven frame index for idle/jump/wave (contract: idle "~2fps") --
    `elapsed_seconds` is a free-running animation clock (`_OverlayController.
    _sprite_time`, incremented every wander tick regardless of state), not
    reset on state entry/exit, so switching states never jumps or stutters
    the underlying clock -- only which `fps`/`frame_count` reads it changes.
    """
    if frame_count <= 0:
        return 0
    return int(elapsed_seconds * fps) % frame_count


def sprite_frames_for_state(frames: dict[str, list], state: str) -> list:
    """Look up `state`'s frame list in `frames`, applying the contract's
    missing-state fallback (user sprite folders; a no-op for a complete code
    `SpriteSheet`, which always has all four states): `jump` -> the walk
    animation's first frame only (a static "airborne" pose, not a whole
    borrowed animation); `wave` -> the entire idle animation (reused as-is,
    so an un-waved character just looks like it's idling through the
    flourish). Falls all the way back to `idle` if even that isn't there
    (e.g. a state other than idle/walk/jump/wave, which never happens from
    `sprite_state_for_tick` but keeps this total for any caller)."""
    direct = frames.get(state)
    if direct:
        return direct
    if state == "jump":
        walk = frames.get("walk")
        if walk:
            return walk[:1]
    if state == "wave":
        idle = frames.get("idle")
        if idle:
            return idle
    return frames.get("idle", [])


def parse_palette_color(value: str) -> tuple[int, int, int, int]:
    """Parse a pixel-art palette entry ("#RRGGBB" or "#RRGGBBAA") into an
    (r, g, b, a) 0-255 tuple. Raises ValueError on anything else -- callers
    only ever feed this `SpriteSheet.palette` values, which pixelart.py's
    own tests already validate as hex, so a ValueError here would mean a
    genuinely malformed sheet slipped through."""
    s = value.lstrip("#")
    if len(s) == 6:
        r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
        return (r, g, b, 255)
    if len(s) == 8:
        r, g, b, a = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), int(s[6:8], 16)
        return (r, g, b, a)
    raise ValueError(f"Invalid palette color: {value!r}")


def fit_code_sprite_scale(
    states: dict[str, tuple[tuple[str, ...], ...]], nominal_scale: float, max_px: float
) -> float:
    """The uniform nearest-neighbor draw scale for a code `SpriteSheet`:
    `nominal_scale` (~5x, `SPRITE_CODE_SCALE`), clamped DOWN (never up) so
    the tallest frame across every state never overflows `max_px` (the
    character window's fixed size) -- e.g. contract's knight (~20 rows
    tall) at a flat 5x would be 100px, still under the 110px window, but
    this stays correct for any future/custom sheet regardless of grid size.
    One scale for the whole sheet (not one per state) keeps a character's
    apparent size consistent across state transitions (walk -> jump ->
    idle) instead of visibly resizing."""
    max_native_h = 0
    for state_frames in states.values():
        for frame in state_frames:
            max_native_h = max(max_native_h, len(frame))
    if max_native_h <= 0:
        return nominal_scale
    return min(nominal_scale, max_px / max_native_h)


def fit_scale_to_max_height(max_native_height: float, max_height_px: float) -> float:
    """The uniform draw scale for a user sprite folder: shrinks (never
    upscales -- matches `_load_character_image`'s existing character_image
    behavior) so the tallest loaded frame is at most `max_height_px`
    (`CHARACTER_MAX_IMAGE_PX`, contract: "scale to <=96px height preserving
    aspect"). A single scale for every frame of every state, derived from
    the tallest one, keeps aspect ratio exact (uniform x/y multiplier) and
    keeps every state's apparent size consistent with the others.
    """
    if max_native_height <= 0:
        return 1.0
    return min(1.0, max_height_px / max_native_height)


def scan_user_sprite_state_files(folder: Path, state: str) -> list[Path]:
    """`<state>_<n>.png` files in `folder` for `state`, 1-indexed and
    contiguous from `_1` -- stops at the first gap (so `idle_1.png`,
    `idle_2.png`, `idle_4.png` yields only the first two; a user fixing the
    gap just has to renumber, not hunt for a skipped-index bug)."""
    paths: list[Path] = []
    n = 1
    while True:
        candidate = folder / f"{state}_{n}.png"
        if not candidate.is_file():
            break
        paths.append(candidate)
        n += 1
    return paths
