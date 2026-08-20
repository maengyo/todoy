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

MOVEMENTS: tuple[str, ...] = ("walk", "hop", "float", "dash", "still")
BUBBLE_EFFECTS: tuple[str, ...] = ("pop", "fade", "slide", "shake", "none")

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
            "still": self._step_still,
        }[self.movement]

    def step(self, dt: float) -> tuple[float, float]:
        """Advance by `dt` seconds; return the new `(x, y_offset)`."""
        if dt < 0:
            raise ValueError("dt must be non-negative")
        return self._step_fn(dt)

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
