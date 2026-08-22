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

# Eased edge turns (M12 Task 29): instead of reversing direction the instant
# `x` hits a travel-range boundary, `_patrol` pre-triggers a turn phase this
# many seconds before the edge so a cosine-shaped deceleration reaches
# exactly `x == 0` / `x == travel_width` at the turn's zero-velocity
# midpoint, then a mirror-image acceleration carries the character back into
# the range in the new direction. See `_patrol`/`_begin_turn`/`_advance_turn`
# for the mechanics; the shape guarantees velocity (direction * speed) never
# jumps (C1-continuous) and `x` never leaves `[0, travel_width]`.
TURN_DURATION_SECONDS = 0.3  # contract: ~0.25-0.35s


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

        # Eased edge turns (Task 29) -- see `_patrol`/`_begin_turn`.
        self._turning = False
        self._turn_elapsed = 0.0
        self._turn_duration = 0.0
        # Multiplier in [0, 1] applied to whatever *live* speed `_advance_turn`
        # is fed each call (Codex review follow-up, Major 2): normally 1.0
        # (full nominal speed), reduced only when a narrow `travel_width`
        # left less room than the nominal ease distance at trigger time, so
        # the fixed-duration turn still lands on the edge without overshoot.
        self._turn_scale = 1.0
        self._turn_pre_direction = 1.0

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

    @property
    def is_turning(self) -> bool:
        """True while an eased edge-turn (Task 29) is in progress. Exposed
        mainly for tests that need to exempt the turn window from
        steady-state assumptions (e.g. "dx sign always matches facing" --
        no longer true for the one `step()` call whose dt straddles the
        turn's zero-velocity midpoint)."""
        return self._turning

    # --- shared helpers ------------------------------------------------------

    def _patrol(self, dt: float, speed: float) -> None:
        """Move `self.x` by `direction * speed * dt`, easing smoothly through
        a `TURN_DURATION_SECONDS`-long turn at each edge instead of bouncing
        instantly (Task 29). The turn is *pre-triggered*: steady motion stops
        early enough that a cosine-shaped deceleration reaches exactly
        `x == 0` or `x == travel_width` at the turn's zero-velocity midpoint,
        then a mirror-image acceleration carries the character back into the
        travel range in the new direction -- so `x` never leaves
        `[0, travel_width]` and velocity is continuous throughout (no jumps).

        `speed` is treated as the *live* nominal speed for this call --
        `_step_gallop` calls this piecewise with a different speed per
        beat/gap/rest segment, and that segment speed keeps driving the
        turn's amplitude even mid-turn (Codex review follow-up, Major 2), so
        stride-sync's airborne/ground dx proportions hold through a turn
        just like they do outside of one.
        """
        if self.travel_width <= 0.0:
            self.x = 0.0
            self._turning = False
            return
        if speed <= 0.0:
            return

        remaining = dt
        iterations = 0
        while remaining > 1e-12 and iterations < 10_000:
            iterations += 1
            if self._turning:
                remaining = self._advance_turn(remaining, speed)
                continue

            # Distance still available before steady motion must give way to
            # the eased turn (so the turn's own decel distance lands exactly
            # on the edge; see `_begin_turn`).
            trigger_distance = speed * TURN_DURATION_SECONDS / math.pi
            room = self.travel_width - self.x if self.direction > 0.0 else self.x
            edge_room = max(0.0, room - trigger_distance)

            if edge_room <= 1e-9:
                self._begin_turn(speed)
                continue

            time_to_trigger = edge_room / speed
            step = min(remaining, time_to_trigger)
            self.x += self.direction * speed * step
            remaining -= step

        if remaining > 1e-9:
            # Adversarial dt/travel_width combo exhausted the iteration cap
            # (Codex review follow-up, Minor 4) -- never silently drop the
            # remainder. A turn still in progress always finishes in one
            # more step regardless of how large `remaining` is (its duration
            # is bounded by `TURN_DURATION_SECONDS`), so finish that first;
            # whatever's left after is spent as plain motion at the current
            # speed so `step()`'s dt is always fully consumed.
            if self._turning:
                remaining = self._advance_turn(remaining, speed)
            if remaining > 1e-9:
                self.x += self.direction * speed * remaining
                self.x = min(self.travel_width, max(0.0, self.x))

    def _advance_active_turn(self, dt: float, speed: float) -> None:
        """Advance an in-progress turn by `dt`, using `speed` as the live
        amplitude reference -- regardless of whatever gating the caller
        applies to *starting* new steady motion (e.g. `dash`'s pause state,
        which never calls `_patrol` at all while paused). A turn already
        under way must still finish on schedule: freezing it mid-ease would
        strand `x`/`direction` mid-turn and violate the turn-duration/
        C1-continuity contract the instant the pause ends and motion resumes
        elsewhere (Codex review follow-up, Major 1). No-op if no turn is
        currently in progress."""
        remaining = dt
        iterations = 0
        while self._turning and remaining > 1e-12 and iterations < 10_000:
            iterations += 1
            remaining = self._advance_turn(remaining, speed)

    def _begin_turn(self, speed: float) -> None:
        """Start an eased turn. `TURN_DURATION_SECONDS` (the contract's
        ~0.25-0.35s) is always honored -- even at a narrow `travel_width`
        where less room than the nominal ease distance (`speed *
        TURN_DURATION_SECONDS / pi`) remains ahead. In that case it's the
        turn's *amplitude* that's scaled down (via `_turn_scale`), not its
        duration, so the same-duration cosine profile's decel distance still
        fits in the room actually available -- `x` never overshoots the edge
        (Codex review follow-up, Minor 3). A small velocity step at
        turn-onset is the accepted trade-off in that narrow-width-only
        corner case (real screen widths never come close to triggering it)."""
        room_left = self.travel_width - self.x if self.direction > 0.0 else self.x
        room_left = max(0.0, room_left)
        nominal_distance = speed * TURN_DURATION_SECONDS / math.pi
        scale = min(1.0, room_left / nominal_distance)

        self._turn_pre_direction = self.direction
        self._turn_elapsed = 0.0
        self._turn_duration = TURN_DURATION_SECONDS
        self._turn_scale = scale

        if scale <= 1e-9:
            # No room at all to ease into (degenerate travel_width) -- flip
            # in place; there's nothing to animate.
            self.direction = -self.direction
            self._turning = False
            return
        self._turning = True

    def _advance_turn(self, remaining: float, speed: float) -> float:
        """Advance the in-progress turn by up to `remaining` seconds
        (finishing it early if `remaining` covers the rest of it). The
        velocity profile is `speed * _turn_scale * cos(pi * t /
        turn_duration)` for `t` in `[0, turn_duration]`, relative to the
        direction the character was heading when the turn began: it
        decelerates from `+speed * _turn_scale` through 0 at the midpoint,
        then accelerates to `-speed * _turn_scale` (i.e. that amplitude, in
        the new direction). `speed` is read fresh on every call rather than
        captured once at turn-start, so a caller like `_step_gallop` that
        varies its per-segment speed keeps driving the turn's amplitude
        through the whole ease, not just at its start (Major 2). `direction`
        (and so `facing`) flips the instant elapsed time crosses the
        midpoint -- exactly where velocity is zero. Returns the leftover,
        unconsumed `remaining`."""
        time_left = self._turn_duration - self._turn_elapsed
        step = min(remaining, time_left)

        t0 = self._turn_elapsed
        t1 = t0 + step
        omega = math.pi / self._turn_duration
        amplitude = speed * self._turn_scale
        # integral of amplitude * cos(omega * t) dt from t0 to t1
        dx = (amplitude / omega) * (math.sin(omega * t1) - math.sin(omega * t0))
        self.x += self._turn_pre_direction * dx
        # Not just fp safety: a live `speed` that differs from the one that
        # triggered the turn (gallop's segment speed can change mid-turn)
        # means the decel distance may no longer land exactly on the edge --
        # this is the backstop that keeps `x` in bounds regardless.
        self.x = min(self.travel_width, max(0.0, self.x))

        midpoint = self._turn_duration / 2.0
        if t0 < midpoint <= t1:
            self.direction = -self._turn_pre_direction

        self._turn_elapsed = t1
        if self._turn_elapsed >= self._turn_duration - 1e-9:
            self._turning = False

        return remaining - step

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
        else:
            # Paused: no *new* movement should start, but a turn triggered
            # during the burst that just ended must still finish -- see
            # `_advance_active_turn` (Codex review follow-up, Major 1).
            self._advance_active_turn(dt, DASH_BURST_SPEED_PX_PER_SEC)

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
