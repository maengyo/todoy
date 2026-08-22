"""Per-character personas: zones, entrances, flourishes, and banner style.

Pure Python, stdlib only -- no AppKit/pyobjc imports here, matching
`animations.py`. `PERSONAS` gives every catalog name in
`todoy.display.characters.CHARACTERS` a "nature": sea creatures live in the
`water` zone and pop up out of it (splash/resurface); flying characters
cruise the `sky` and drag a banner from their legs (swoop/swoop_dip); the
rest walk the `ground` as before, with a few extra flourishes for the
spookier/robotic ones (materialize/blink) and the naturally bouncy ones
(hop_in/hop).

`EntranceAnimation` and `FlourishAnimation` are deterministic, dt-driven
curve state machines -- like `CharacterMovement`, they never read the wall
clock, so a backend calls `step(dt)` on whatever cadence it likes and gets
reproducible, continuous (C0) motion out. All outputs are bounded:
`|x_off|, |y_off| <= 2.5 * char_height`, `0 <= alpha <= 1`,
`0.4 <= scale <= 1.1`. Once `.finished` is `True`, `step()` is a no-op that
returns the neutral resting state `(0.0, 0.0, 1.0, 1.0)` -- which is also
exactly the state every curve settles into at the end of its own duration,
so there is no discontinuity at the finish line.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Literal

Zone = Literal["ground", "sky", "water"]
Entrance = Literal["walk_in", "splash", "swoop", "hop_in", "materialize"]
Flourish = Literal["none", "resurface", "swoop_dip", "hop", "blink"]


@dataclass(frozen=True)
class Persona:
    """A character's nature: where it lives, how it arrives, how it flags
    attention, whether its message banner hangs below it, and its default
    movement preset."""

    zone: Zone
    entrance: Entrance
    flourish: Flourish
    banner: bool
    movement: str


# --- persona catalog ----------------------------------------------------------
# Binding assignments (frozen contract, M13 section 1):
#   water+splash+resurface: whale, octopus, crab, penguin
#   water+hop_in+hop (frog is the odd one out): frog
#   sky+swoop+swoop_dip+banner: butterfly, bee, owl, duck, dragon
#   ground+hop_in+hop: rabbit
#   ground+materialize+blink: ghost, alien, robot
#   everything else: ground+walk_in+none
#
# Movement defaults: horse+unicorn=gallop, rabbit+frog=hop, ghost+butterfly=
# float, bee=dash, snail+turtle+whale=walk, others=walk; sky characters
# default to float unless listed otherwise (bee is sky but listed as dash).

PERSONAS: dict[str, Persona] = {
    # -- water: pop up out of the water, resurface on flourish --------------
    "whale": Persona("water", "splash", "resurface", False, "walk"),
    "octopus": Persona("water", "splash", "resurface", False, "walk"),
    "crab": Persona("water", "splash", "resurface", False, "walk"),
    "penguin": Persona("water", "splash", "resurface", False, "walk"),
    "frog": Persona("water", "hop_in", "hop", False, "hop"),
    # -- sky: cruise near the top, banner hangs below on legs ----------------
    "butterfly": Persona("sky", "swoop", "swoop_dip", True, "float"),
    "bee": Persona("sky", "swoop", "swoop_dip", True, "dash"),
    "owl": Persona("sky", "swoop", "swoop_dip", True, "float"),
    "duck": Persona("sky", "swoop", "swoop_dip", True, "float"),
    "dragon": Persona("sky", "swoop", "swoop_dip", True, "float"),
    # -- ground: bouncy ------------------------------------------------------
    "rabbit": Persona("ground", "hop_in", "hop", False, "hop"),
    # -- ground: spooky/robotic materialize -----------------------------------
    "ghost": Persona("ground", "materialize", "blink", False, "float"),
    "alien": Persona("ground", "materialize", "blink", False, "walk"),
    "robot": Persona("ground", "materialize", "blink", False, "walk"),
    # -- ground: default walk-in, no flourish ---------------------------------
    "cat": Persona("ground", "walk_in", "none", False, "walk"),
    "dog": Persona("ground", "walk_in", "none", False, "walk"),
    "horse": Persona("ground", "walk_in", "none", False, "gallop"),
    "dino": Persona("ground", "walk_in", "none", False, "walk"),
    "snail": Persona("ground", "walk_in", "none", False, "walk"),
    "turtle": Persona("ground", "walk_in", "none", False, "walk"),
    "unicorn": Persona("ground", "walk_in", "none", False, "gallop"),
    "fox": Persona("ground", "walk_in", "none", False, "walk"),
    "panda": Persona("ground", "walk_in", "none", False, "walk"),
    "chick": Persona("ground", "walk_in", "none", False, "walk"),
    "hamster": Persona("ground", "walk_in", "none", False, "walk"),
}

_DEFAULT_PERSONA = Persona("ground", "walk_in", "none", False, "walk")


def persona(name: str) -> Persona:
    """Look up a character's persona by name; unknown names fall back to the
    ground/walk_in/none default (same shape as every unlisted character)."""
    return PERSONAS.get(name, _DEFAULT_PERSONA)


# --- shared curve helpers ------------------------------------------------------


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _ease_out_quad(t: float) -> float:
    """Monotonic ease-out on `[0, 1] -> [0, 1]`: fast start, gentle finish."""
    return 1.0 - (1.0 - t) ** 2


def _bump(t: float, center: float, half_width: float, depth: float) -> float:
    """A smooth, localized parabolic bump of height `depth` centered at
    `center`, zero outside `[center - half_width, center + half_width]`.
    Used to carve a single dip out of an otherwise-monotonic alpha curve."""
    if half_width <= 0.0:
        return 0.0
    offset = (t - center) / half_width
    if abs(offset) >= 1.0:
        return 0.0
    return depth * (1.0 - offset * offset)


# Neutral (x_off, y_off, alpha, scale) -- the resting state every curve
# settles into at the end of its duration, and what a finished animation's
# `step()` keeps returning afterwards.
_NEUTRAL = (0.0, 0.0, 1.0, 1.0)

# --- entrance durations (seconds; contract: 0.8-1.4s per type) -----------------

_ENTRANCE_DURATIONS: dict[Entrance, float] = {
    "walk_in": 0.9,
    "splash": 1.0,
    "swoop": 1.2,
    "hop_in": 1.1,
    "materialize": 1.2,
}

# --- flourish durations (seconds; contract: 0.6-1.0s; "none" is immediate) -----

_FLOURISH_DURATIONS: dict[Flourish, float] = {
    "none": 0.0,
    "resurface": 0.9,
    "swoop_dip": 0.7,
    "hop": 0.6,
    "blink": 0.8,
}


class _Curve:
    """Shared dt-driven, elapsed-time bookkeeping for `EntranceAnimation` and
    `FlourishAnimation`: both are "run a pure function of `t = elapsed /
    duration` until `t` reaches 1, then freeze at neutral." Subclasses only
    supply `_durations` (name -> seconds) and `_evaluate(kind, t, char_height)`."""

    _durations: dict[str, float]

    def __init__(self, kind: str, char_height: float, rng: random.Random | None = None) -> None:
        if kind not in self._durations:
            available = ", ".join(self._durations)
            raise ValueError(f"Unknown {type(self).__name__} kind: {kind}. Available: {available}")
        self.kind = kind
        self.char_height = float(char_height)
        self._rng = rng if rng is not None else random.Random()
        self._duration = self._durations[kind]
        self._elapsed = 0.0

    @property
    def finished(self) -> bool:
        return self._elapsed >= self._duration

    def step(self, dt: float) -> tuple[float, float, float, float]:
        if dt < 0:
            raise ValueError("dt must be non-negative")
        if self.finished:
            return _NEUTRAL
        self._elapsed = min(self._duration, self._elapsed + dt)
        t = 1.0 if self._duration <= 0.0 else self._elapsed / self._duration
        x_off, y_off, alpha, scale = self._evaluate(t)
        x_off = _clamp(x_off, -2.5 * self.char_height, 2.5 * self.char_height)
        y_off = _clamp(y_off, -2.5 * self.char_height, 2.5 * self.char_height)
        alpha = _clamp(alpha, 0.0, 1.0)
        scale = _clamp(scale, 0.4, 1.1)
        return (x_off, y_off, alpha, scale)

    def _evaluate(self, t: float) -> tuple[float, float, float, float]:
        raise NotImplementedError


class EntranceAnimation(_Curve):
    """Pure, dt-driven launch-entrance curves. See module docstring for the
    bounds/continuity/determinism guarantees shared with `FlourishAnimation`."""

    _durations = _ENTRANCE_DURATIONS

    def __init__(
        self, entrance: Entrance, char_height: float, rng: random.Random | None = None
    ) -> None:
        super().__init__(entrance, char_height, rng)

    def _evaluate(self, t: float) -> tuple[float, float, float, float]:
        ch = self.char_height
        ease = _ease_out_quad(t)

        if self.kind == "walk_in":
            x_start = -2.0 * ch
            return (x_start * (1.0 - ease), 0.0, 1.0, 1.0)

        if self.kind == "splash":
            y_start = -1.2 * ch
            y_peak = 0.15 * ch
            if t <= 0.7:
                tau = t / 0.7
                y = y_start + (y_peak - y_start) * _ease_out_quad(tau)
            else:
                tau = (t - 0.7) / 0.3
                y = y_peak * (1.0 - _ease_out_quad(tau))
            return (0.0, y, 1.0, 1.0)

        if self.kind == "swoop":
            y_start = 2.0 * ch
            x_lead = 0.5 * ch
            return (x_lead * (1.0 - ease), y_start * (1.0 - ease), 1.0, 1.0)

        if self.kind == "hop_in":
            x_start = -2.0 * ch
            x_off = x_start * (1.0 - ease)
            hop1_end, hop1_peak = 0.45, 0.6 * ch
            hop2_start, hop2_end, hop2_peak = 0.5, 0.8, 0.3 * ch
            if t <= hop1_end:
                tau = t / hop1_end
                y = hop1_peak * 4.0 * tau * (1.0 - tau)
            elif t <= hop2_start:
                y = 0.0
            elif t <= hop2_end:
                tau = (t - hop2_start) / (hop2_end - hop2_start)
                y = hop2_peak * 4.0 * tau * (1.0 - tau)
            else:
                y = 0.0
            return (x_off, y, 1.0, 1.0)

        # materialize: alpha 0 -> 1 and scale 0.6 -> 1, both eased, with two
        # quick alpha dips (blinks) carved out of the rising alpha envelope.
        scale = 0.6 + 0.4 * ease
        base_alpha = ease
        dip = _bump(t, 0.35, 0.08, 0.35) + _bump(t, 0.65, 0.08, 0.35)
        alpha = base_alpha - dip
        return (0.0, 0.0, alpha, scale)


class FlourishAnimation(_Curve):
    """Pure, dt-driven fire-time flourish; short (0.6-1.0s), started from and
    returning to the character's resting/cruise state. Same `step()`/
    `.finished` API as `EntranceAnimation`."""

    _durations = _FLOURISH_DURATIONS

    def __init__(
        self, flourish: Flourish, char_height: float, rng: random.Random | None = None
    ) -> None:
        super().__init__(flourish, char_height, rng)

    def _evaluate(self, t: float) -> tuple[float, float, float, float]:
        ch = self.char_height

        if self.kind == "none":
            return _NEUTRAL

        if self.kind == "resurface":
            dip_end, peak_end = 0.35, 0.75
            y_dip = -0.8 * ch
            y_peak = 0.15 * ch
            if t <= dip_end:
                tau = t / dip_end
                y = y_dip * _ease_out_quad(tau)
            elif t <= peak_end:
                tau = (t - dip_end) / (peak_end - dip_end)
                y = y_dip + (y_peak - y_dip) * _ease_out_quad(tau)
            else:
                tau = (t - peak_end) / (1.0 - peak_end)
                y = y_peak * (1.0 - _ease_out_quad(tau))
            return (0.0, y, 1.0, 1.0)

        if self.kind == "swoop_dip":
            y_dip = -0.5 * ch
            mid = 0.5
            if t <= mid:
                tau = t / mid
                y = y_dip * _ease_out_quad(tau)
            else:
                tau = (t - mid) / (1.0 - mid)
                y = y_dip * (1.0 - _ease_out_quad(tau))
            return (0.0, y, 1.0, 1.0)

        if self.kind == "hop":
            peak = 0.5 * ch
            y = peak * 4.0 * t * (1.0 - t)
            return (0.0, y, 1.0, 1.0)

        # blink: alpha starts and ends at 1, with two quick dips in between.
        dip = _bump(t, 0.3, 0.1, 0.6) + _bump(t, 0.65, 0.1, 0.6)
        alpha = 1.0 - dip
        return (0.0, 0.0, alpha, 1.0)
