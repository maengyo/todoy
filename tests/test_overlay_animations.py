from __future__ import annotations

import math
import random

import pytest

from todoy.display.overlay.animations import (
    BUBBLE_EFFECTS,
    DASH_BURST_SPEED_PX_PER_SEC,
    FLOAT_BOB_AMPLITUDE_PX,
    GALLOP_CYCLE_SECONDS,
    GALLOP_HOP_PEAK_HEIGHT_PX,
    GALLOP_SPEED_PX_PER_SEC,
    HOP_PEAK_HEIGHT_PX,
    MESSAGE_STYLES,
    MOVEMENTS,
    WALK_SPEED_PX_PER_SEC,
    CharacterMovement,
    validate_bubble_effect,
    validate_message_style,
    validate_movement,
)

TRAVEL_WIDTH = 800.0
MAX_Y_OFFSET = 40.0


# --- presets -----------------------------------------------------------------


def test_movements_tuple_contents() -> None:
    assert MOVEMENTS == ("walk", "hop", "float", "dash", "gallop", "still")


def test_bubble_effects_tuple_contents() -> None:
    assert BUBBLE_EFFECTS == ("pop", "fade", "slide", "shake", "none")


def test_message_styles_tuple_contents() -> None:
    assert MESSAGE_STYLES == ("bubble", "flag")


# --- validate_movement / validate_bubble_effect -------------------------------


@pytest.mark.parametrize("name", MOVEMENTS)
def test_validate_movement_accepts_known_names(name: str) -> None:
    assert validate_movement(name) == name


def test_validate_movement_rejects_unknown_name() -> None:
    with pytest.raises(ValueError) as exc_info:
        validate_movement("teleport")

    assert str(exc_info.value) == (
        "Unknown movement: teleport. Available: walk, hop, float, dash, gallop, still"
    )


@pytest.mark.parametrize("name", BUBBLE_EFFECTS)
def test_validate_bubble_effect_accepts_known_names(name: str) -> None:
    assert validate_bubble_effect(name) == name


def test_validate_bubble_effect_rejects_unknown_name() -> None:
    with pytest.raises(ValueError) as exc_info:
        validate_bubble_effect("explode")

    assert str(exc_info.value) == (
        "Unknown bubble effect: explode. Available: pop, fade, slide, shake, none"
    )


@pytest.mark.parametrize("name", MESSAGE_STYLES)
def test_validate_message_style_accepts_known_names(name: str) -> None:
    assert validate_message_style(name) == name


def test_validate_message_style_rejects_unknown_name() -> None:
    with pytest.raises(ValueError) as exc_info:
        validate_message_style("banner")

    assert str(exc_info.value) == ("Unknown message style: banner. Available: bubble, flag")


# --- CharacterMovement: determinism -------------------------------------------


@pytest.mark.parametrize("movement", MOVEMENTS)
def test_step_sequence_is_deterministic_with_seeded_rng(movement: str) -> None:
    trace_a = _simulate(movement, seed=42, steps=500, dt=0.05)
    trace_b = _simulate(movement, seed=42, steps=500, dt=0.05)

    assert trace_a == trace_b


@pytest.mark.parametrize("movement", ["hop", "dash"])
def test_different_seeds_can_diverge(movement: str) -> None:
    # hop/dash use the rng to schedule timing, so different seeds should
    # (with overwhelming probability) produce a different trace somewhere.
    trace_a = _simulate(movement, seed=1, steps=500, dt=0.05)
    trace_b = _simulate(movement, seed=2, steps=500, dt=0.05)

    assert trace_a != trace_b


# --- CharacterMovement: invariants (every movement) ---------------------------


@pytest.mark.parametrize("movement", MOVEMENTS)
def test_invariants_hold_across_many_steps(movement: str) -> None:
    rng = random.Random(7)
    m = CharacterMovement(movement, travel_width=TRAVEL_WIDTH, rng=rng)

    max_speed = {
        "walk": WALK_SPEED_PX_PER_SEC,
        "hop": WALK_SPEED_PX_PER_SEC,
        "float": WALK_SPEED_PX_PER_SEC,  # float patrols slower; walk speed is a safe upper bound
        "dash": DASH_BURST_SPEED_PX_PER_SEC,
        "gallop": GALLOP_SPEED_PX_PER_SEC,
        "still": 0.0,
    }[movement]

    dt = 0.05
    prev_x, _ = m.step(dt)
    for _ in range(4000):
        x, y = m.step(dt)

        assert math.isfinite(x)
        assert math.isfinite(y)
        assert 0.0 <= x <= TRAVEL_WIDTH
        assert 0.0 <= y <= MAX_Y_OFFSET

        # continuity bound: no teleport bigger than speed*dt (plus tiny fp slack)
        assert abs(x - prev_x) <= max_speed * dt + 1e-6

        prev_x = x


@pytest.mark.parametrize("movement", MOVEMENTS)
def test_invariants_hold_with_varying_dt(movement: str) -> None:
    # Robustness against irregular tick timing (e.g. a busy run loop).
    rng = random.Random(99)
    dt_rng = random.Random(123)
    m = CharacterMovement(movement, travel_width=TRAVEL_WIDTH, rng=rng)

    for _ in range(2000):
        dt = dt_rng.uniform(0.01, 0.2)
        x, y = m.step(dt)
        assert math.isfinite(x)
        assert math.isfinite(y)
        assert 0.0 <= x <= TRAVEL_WIDTH
        assert 0.0 <= y <= MAX_Y_OFFSET


def test_step_rejects_negative_dt() -> None:
    m = CharacterMovement("walk", travel_width=TRAVEL_WIDTH)
    with pytest.raises(ValueError):
        m.step(-0.1)


def test_zero_travel_width_does_not_crash() -> None:
    for movement in MOVEMENTS:
        m = CharacterMovement(movement, travel_width=0.0, rng=random.Random(5))
        for _ in range(50):
            x, y = m.step(0.05)
            assert x == 0.0
            assert 0.0 <= y <= MAX_Y_OFFSET


# --- CharacterMovement: per-movement behavior ----------------------------------


def test_still_stays_put() -> None:
    m = CharacterMovement("still", travel_width=TRAVEL_WIDTH)
    first_x, first_y = m.step(0.05)

    for _ in range(200):
        x, y = m.step(0.05)
        assert x == first_x
        assert y == 0.0
    assert first_y == 0.0


def test_hop_leaves_the_ground_periodically() -> None:
    m = CharacterMovement("hop", travel_width=TRAVEL_WIDTH, rng=random.Random(3))
    y_values = [m.step(0.05)[1] for _ in range(400)]  # 20 simulated seconds

    assert max(y_values) > 5.0  # actually left the ground at some point
    assert max(y_values) <= HOP_PEAK_HEIGHT_PX + 1e-6
    assert any(y == 0.0 for y in y_values)  # and returned to the ground


def test_float_has_smooth_continuous_vertical_motion() -> None:
    m = CharacterMovement("float", travel_width=TRAVEL_WIDTH, rng=random.Random(11))
    dt = 0.05
    y_values = [m.step(dt)[1] for _ in range(400)]

    # varies (it's bobbing, not frozen)
    assert max(y_values) - min(y_values) > 5.0
    assert max(y_values) <= FLOAT_BOB_AMPLITUDE_PX * 2 + 1e-6

    # smooth: consecutive samples never jump by more than a small bound
    max_step_delta = max(abs(b - a) for a, b in zip(y_values, y_values[1:], strict=False))
    assert max_step_delta < 5.0


def test_dash_alternates_pause_and_burst() -> None:
    m = CharacterMovement("dash", travel_width=TRAVEL_WIDTH, rng=random.Random(17))
    dt = 0.05
    xs = [m.step(dt)[0] for _ in range(800)]  # 40 simulated seconds
    deltas = [b - a for a, b in zip(xs, xs[1:], strict=False)]

    still_steps = sum(1 for d in deltas if d == 0.0)
    moving_steps = sum(1 for d in deltas if d != 0.0)

    assert still_steps > 10  # real pauses happened
    assert moving_steps > 10  # real bursts happened

    # bursts move noticeably faster per-step than a walk-speed patrol would
    fastest_step = max(abs(d) for d in deltas)
    assert fastest_step > WALK_SPEED_PX_PER_SEC * dt


def test_walk_bounces_at_both_edges() -> None:
    # A narrow travel width forces multiple bounces quickly, so we can see
    # the direction reverse without simulating forever.
    m = CharacterMovement("walk", travel_width=10.0, rng=random.Random(1))
    xs = [m.step(0.05)[0] for _ in range(400)]

    assert any(x <= 0.0 + 1e-6 for x in xs)
    assert any(x >= 10.0 - 1e-6 for x in xs)


def test_gallop_is_noticeably_faster_than_walk() -> None:
    # Compare distance covered in a short burst, well before either would
    # reach the (very wide) travel-width edge and bounce.
    walk = CharacterMovement("walk", travel_width=TRAVEL_WIDTH)
    gallop = CharacterMovement("gallop", travel_width=TRAVEL_WIDTH)
    dt = 0.05

    walk_start_x, _ = walk.step(0.0)
    gallop_start_x, _ = gallop.step(0.0)
    for _ in range(20):
        walk_x, _ = walk.step(dt)
        gallop_x, _ = gallop.step(dt)

    walk_distance = walk_x - walk_start_x
    gallop_distance = gallop_x - gallop_start_x

    assert gallop_distance == pytest.approx(walk_distance * 3.0, rel=0.05)


def test_gallop_double_beat_cadence_peaks_stay_low() -> None:
    m = CharacterMovement("gallop", travel_width=TRAVEL_WIDTH, rng=random.Random(4))
    dt = 0.01
    y_values = [m.step(dt)[1] for _ in range(1000)]  # 10 simulated seconds

    assert max(y_values) > 5.0  # it does leave the ground
    assert max(y_values) <= GALLOP_HOP_PEAK_HEIGHT_PX + 1e-6  # but stays low
    assert GALLOP_HOP_PEAK_HEIGHT_PX <= 14.0  # contract bound
    assert any(y == 0.0 for y in y_values)  # flat contact happens


def test_gallop_has_two_beats_per_cycle() -> None:
    # Sample one full gallop cycle densely and count distinct "hop" peaks
    # (local maxima above a low threshold) -- should read as a double-beat.
    m = CharacterMovement("gallop", travel_width=TRAVEL_WIDTH, rng=random.Random(9))
    dt = 0.005
    steps = round(GALLOP_CYCLE_SECONDS / dt)  # exactly one full cadence cycle
    y_values = [m.step(dt)[1] for _ in range(steps)]

    threshold = GALLOP_HOP_PEAK_HEIGHT_PX * 0.5
    above = [y > threshold for y in y_values]
    # count rising edges (False -> True transitions) as distinct beats
    beats = sum(1 for prev, cur in zip(above, above[1:], strict=False) if cur and not prev)
    assert beats == 2


def _simulate(movement: str, *, seed: int, steps: int, dt: float) -> list[tuple[float, float]]:
    rng = random.Random(seed)
    m = CharacterMovement(movement, travel_width=TRAVEL_WIDTH, rng=rng)
    return [m.step(dt) for _ in range(steps)]
