"""Selectable character-movement and bubble-entrance-effect presets.

Pure Python, stdlib only -- no AppKit/pyobjc imports here, so this module
imports and unit-tests on any platform. `CharacterMovement` is a deterministic,
dt-driven state machine: it never reads the wall clock, so a backend (macOS's
`NSTimer`-driven wander tick, or any future OS backend) is free to call
`step(dt)` on whatever cadence it likes and get reproducible, continuous
motion out.

Bubble entrance effects (`BUBBLE_EFFECTS`) are just names here -- the actual
`NSAnimationContext` implementation lives in `macos.py`, which is the only
place AppKit is involved.
"""

from __future__ import annotations

import math
import random

MOVEMENTS: tuple[str, ...] = ("walk", "hop", "float", "dash", "gallop", "still")
BUBBLE_EFFECTS: tuple[str, ...] = ("pop", "fade", "slide", "shake", "none")
MESSAGE_STYLES: tuple[str, ...] = ("bubble", "flag")

# --- tunables (implementation detail; not part of the frozen contract) -------

WALK_SPEED_PX_PER_SEC = 45.0

HOP_SPEED_PX_PER_SEC = WALK_SPEED_PX_PER_SEC
HOP_PEAK_HEIGHT_PX = 24.0
HOP_DURATION_SECONDS = 0.5
HOP_INTERVAL_RANGE_SECONDS = (2.5, 4.5)  # idle time on the ground between hops

FLOAT_SPEED_PX_PER_SEC = 18.0
FLOAT_BOB_AMPLITUDE_PX = 15.0  # y_offset oscillates across [0, 2*amplitude]
FLOAT_BOB_PERIOD_SECONDS = 3.0

DASH_BURST_SPEED_PX_PER_SEC = 220.0
DASH_PAUSE_RANGE_SECONDS = (0.6, 1.6)
DASH_BURST_RANGE_SECONDS = (0.15, 0.4)

GALLOP_SPEED_PX_PER_SEC = WALK_SPEED_PX_PER_SEC * 3.0  # ~3x walk, per contract (cycle AVERAGE)
GALLOP_HOP_PEAK_HEIGHT_PX = 12.0  # <= 14px contract bound
GALLOP_BEAT_DURATION_SECONDS = 0.09  # one short hop of the double-beat
GALLOP_BEAT_GAP_SECONDS = 0.03  # brief flat contact between the two beats
GALLOP_STRIDE_REST_SECONDS = 0.15  # longer flat contact after the double-beat
GALLOP_CYCLE_SECONDS = (
    GALLOP_BEAT_DURATION_SECONDS * 2 + GALLOP_BEAT_GAP_SECONDS + GALLOP_STRIDE_REST_SECONDS
)

# Stride-sync (M11 Task 28): a real gallop's forward reach happens while the
# horse is airborne (y_offset > 0, i.e. during the two beats), not while its
# hooves are in contact with the ground (the gap/rest flats) -- otherwise the
# sprite reads as sliding/moonwalking rather than striding. We keep the same
# per-cycle AVERAGE speed as before (GALLOP_SPEED_PX_PER_SEC, ~3x walk) but
# redistribute it: most of the horizontal distance is covered during the
# airborne beats, only a little during ground contact. The contract requires
# >= 70% of each cycle's dx airborne; 80% leaves comfortable margin.
GALLOP_AIRBORNE_DX_FRACTION = 0.8
_GALLOP_AIRBORNE_TIME_SECONDS = GALLOP_BEAT_DURATION_SECONDS * 2
_GALLOP_GROUND_TIME_SECONDS = GALLOP_CYCLE_SECONDS - _GALLOP_AIRBORNE_TIME_SECONDS
_GALLOP_AIRBORNE_TIME_FRACTION = _GALLOP_AIRBORNE_TIME_SECONDS / GALLOP_CYCLE_SECONDS
_GALLOP_GROUND_TIME_FRACTION = _GALLOP_GROUND_TIME_SECONDS / GALLOP_CYCLE_SECONDS
GALLOP_AIRBORNE_SPEED_PX_PER_SEC = (
    GALLOP_SPEED_PX_PER_SEC * GALLOP_AIRBORNE_DX_FRACTION / _GALLOP_AIRBORNE_TIME_FRACTION
)
GALLOP_GROUND_SPEED_PX_PER_SEC = (
    GALLOP_SPEED_PX_PER_SEC * (1.0 - GALLOP_AIRBORNE_DX_FRACTION) / _GALLOP_GROUND_TIME_FRACTION
)

# Phase boundaries (seconds into one gallop cycle) of the four segments, in
# order: beat 1 (airborne) -> gap (ground) -> beat 2 (airborne) -> rest
# (ground, wraps back to 0). Shared by `_step_gallop`'s y-offset formula and
# its piecewise speed integration below.
_GALLOP_BEAT1_END = GALLOP_BEAT_DURATION_SECONDS
_GALLOP_GAP_END = _GALLOP_BEAT1_END + GALLOP_BEAT_GAP_SECONDS
_GALLOP_BEAT2_END = _GALLOP_GAP_END + GALLOP_BEAT_DURATION_SECONDS


def _gallop_segment(phase: float) -> tuple[float, bool]:
    """For `phase` (seconds into one gallop cycle, `0 <= phase < GALLOP_CYCLE_SECONDS`),
    return `(segment_end, airborne)`: where the current beat/gap/rest segment ends and
    whether it's an airborne (beat) or ground-contact (gap/rest) segment."""
    if phase < _GALLOP_BEAT1_END:
        return _GALLOP_BEAT1_END, True
    if phase < _GALLOP_GAP_END:
        return _GALLOP_GAP_END, False
    if phase < _GALLOP_BEAT2_END:
        return _GALLOP_BEAT2_END, True
    return GALLOP_CYCLE_SECONDS, False


MAX_Y_OFFSET_PX = 40.0


def validate_movement(name: str) -> str:
    """Return `name` unchanged if it is a known movement, else raise ValueError."""
    if name not in MOVEMENTS:
        raise ValueError(f"Unknown movement: {name}. Available: {', '.join(MOVEMENTS)}")
    return name


def validate_bubble_effect(name: str) -> str:
    """Return `name` unchanged if it is a known bubble effect, else raise ValueError."""
    if name not in BUBBLE_EFFECTS:
        raise ValueError(f"Unknown bubble effect: {name}. Available: {', '.join(BUBBLE_EFFECTS)}")
    return name


def validate_message_style(name: str) -> str:
    """Return `name` unchanged if it is a known message style, else raise ValueError."""
    if name not in MESSAGE_STYLES:
        raise ValueError(f"Unknown message style: {name}. Available: {', '.join(MESSAGE_STYLES)}")
    return name


class CharacterMovement:
    """Deterministic, dt-driven movement state machine (no wall clock inside).

    `step(dt)` advances the simulation by `dt` seconds and returns the new
    `(x, y_offset)` position, where `x` is horizontal offset from the left
    edge of the travel range (`0 <= x <= travel_width`) and `y_offset` is
    vertical lift above the resting position (`0 <= y_offset <= 40`).

    Timing-based presets (`hop`, `dash`) draw from the injected `rng` so a
    caller can get a fully reproducible trace by seeding it; presets that
    don't need randomness (`walk`, `float`, `still`) are deterministic by
    construction.
    """

    def __init__(
        self,
        movement: str,
        *,
        travel_width: float,
        rng: random.Random | None = None,
    ) -> None:
        self.movement = validate_movement(movement)
        self.travel_width = max(0.0, float(travel_width))
        self._rng = rng if rng is not None else random.Random()

        self.direction = 1.0
        self.x = self.travel_width * 0.3
        self._elapsed = 0.0

        self._hopping = False
        self._hop_phase = 0.0
        self._hop_timer = self._rng.uniform(*HOP_INTERVAL_RANGE_SECONDS)

        self._dash_state = "pause"
        self._dash_timer = self._rng.uniform(*DASH_PAUSE_RANGE_SECONDS)

        if self.movement == "still":
            self.x = self.travel_width / 2.0

        self._step_fn = {
            "walk": self._step_walk,
            "hop": self._step_hop,
            "float": self._step_float,
            "dash": self._step_dash,
            "gallop": self._step_gallop,
            "still": self._step_still,
        }[self.movement]

    def step(self, dt: float) -> tuple[float, float]:
        """Advance by `dt` seconds; return the new `(x, y_offset)`."""
        if dt < 0:
            raise ValueError("dt must be non-negative")
        return self._step_fn(dt)

    @property
    def facing(self) -> int:
        """+1 when the character is moving/should draw facing right, -1 for
        left. Backed by `self.direction`, which `_patrol` already latches to
        the current travel direction and flips the instant an edge bounce
        happens -- `facing` just exposes its sign. `still` never patrols, so
        it stays at the +1 `direction` is initialized to, per contract."""
        return 1 if self.direction >= 0.0 else -1

    # --- shared helpers ------------------------------------------------------

    def _patrol(self, dt: float, speed: float) -> None:
        """Move `self.x` by `direction * speed * dt`, bouncing at both edges."""
        if self.travel_width <= 0.0:
            self.x = 0.0
            return

        self.x += self.direction * speed * dt
        if self.x <= 0.0:
            self.x = 0.0
            self.direction = 1.0
        elif self.x >= self.travel_width:
            self.x = self.travel_width
            self.direction = -1.0

    # --- presets ---------------------------------------------------------------

    def _step_walk(self, dt: float) -> tuple[float, float]:
        self._patrol(dt, WALK_SPEED_PX_PER_SEC)
        return (self.x, 0.0)

    def _step_hop(self, dt: float) -> tuple[float, float]:
        self._patrol(dt, HOP_SPEED_PX_PER_SEC)

        if self._hopping:
            self._hop_phase += dt
            t = min(1.0, self._hop_phase / HOP_DURATION_SECONDS)
            y = HOP_PEAK_HEIGHT_PX * 4.0 * t * (1.0 - t)
            if t >= 1.0:
                self._hopping = False
                self._hop_phase = 0.0
                self._hop_timer = self._rng.uniform(*HOP_INTERVAL_RANGE_SECONDS)
                y = 0.0
        else:
            y = 0.0
            self._hop_timer -= dt
            if self._hop_timer <= 0.0:
                self._hopping = True
                self._hop_phase = 0.0

        return (self.x, y)

    def _step_float(self, dt: float) -> tuple[float, float]:
        self._patrol(dt, FLOAT_SPEED_PX_PER_SEC)
        self._elapsed += dt
        phase = 2.0 * math.pi * self._elapsed / FLOAT_BOB_PERIOD_SECONDS
        y = FLOAT_BOB_AMPLITUDE_PX + FLOAT_BOB_AMPLITUDE_PX * math.sin(phase)
        # clamp for float-precision safety only; the formula's range is exact
        y = min(MAX_Y_OFFSET_PX, max(0.0, y))
        return (self.x, y)

    def _step_dash(self, dt: float) -> tuple[float, float]:
        if self._dash_state == "burst":
            self._patrol(dt, DASH_BURST_SPEED_PX_PER_SEC)

        self._dash_timer -= dt
        if self._dash_timer <= 0.0:
            if self._dash_state == "pause":
                self._dash_state = "burst"
                self._dash_timer = self._rng.uniform(*DASH_BURST_RANGE_SECONDS)
            else:
                self._dash_state = "pause"
                self._dash_timer = self._rng.uniform(*DASH_PAUSE_RANGE_SECONDS)

        return (self.x, 0.0)

    def _step_still(self, dt: float) -> tuple[float, float]:
        return (self.x, 0.0)

    def _step_gallop(self, dt: float) -> tuple[float, float]:
        # Stride-sync: cover most of the cycle's ground during the airborne
        # beats, only a little while hooves are down (see the constants'
        # docstring above) -- same per-cycle average as before. A single
        # `step(dt)` call can straddle a beat/gap/rest boundary (e.g. a dt
        # that doesn't evenly divide the cycle), so the patrol has to be
        # integrated piecewise, segment by segment, rather than picking one
        # speed for the whole dt -- otherwise per-cycle dx (and the airborne
        # fraction) would drift depending on how dt happens to align with
        # the cycle, instead of staying exact for any dt.
        phase = self._elapsed % GALLOP_CYCLE_SECONDS
        remaining = dt
        iterations = 0
        while remaining > 1e-12 and iterations < 100_000:
            iterations += 1
            segment_end, airborne = _gallop_segment(phase)
            step = min(remaining, segment_end - phase)
            if step <= 0.0:
                # `phase` sits exactly at (or fp-past) a boundary -- move
                # into the next segment without consuming any of `dt`.
                phase = segment_end % GALLOP_CYCLE_SECONDS
                continue
            speed = GALLOP_AIRBORNE_SPEED_PX_PER_SEC if airborne else GALLOP_GROUND_SPEED_PX_PER_SEC
            self._patrol(step, speed)
            phase += step
            remaining -= step
            if phase >= GALLOP_CYCLE_SECONDS - 1e-12:
                phase -= GALLOP_CYCLE_SECONDS

        self._elapsed += dt
        final_phase = self._elapsed % GALLOP_CYCLE_SECONDS

        if final_phase < _GALLOP_BEAT1_END:
            t = final_phase / GALLOP_BEAT_DURATION_SECONDS
            y = GALLOP_HOP_PEAK_HEIGHT_PX * 4.0 * t * (1.0 - t)
        elif final_phase < _GALLOP_GAP_END:
            y = 0.0
        elif final_phase < _GALLOP_BEAT2_END:
            t = (final_phase - _GALLOP_GAP_END) / GALLOP_BEAT_DURATION_SECONDS
            y = GALLOP_HOP_PEAK_HEIGHT_PX * 4.0 * t * (1.0 - t)
        else:
            y = 0.0

        y = min(GALLOP_HOP_PEAK_HEIGHT_PX, max(0.0, y))
        return (self.x, y)
