from __future__ import annotations

import math
import random

import pytest

from todoy.display.overlay.animations import (
    BUBBLE_EFFECTS,
    DASH_BURST_SPEED_PX_PER_SEC,
    FLOAT_BOB_AMPLITUDE_PX,
    GALLOP_AIRBORNE_SPEED_PX_PER_SEC,
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
        # gallop's stride-sync (Task 28) moves faster than the cycle average
        # during the airborne beats, so the per-step continuity bound has to
        # allow for that peak instantaneous speed, not the average.
        "gallop": GALLOP_AIRBORNE_SPEED_PX_PER_SEC,
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
    # Compare distance covered over several full gallop cycles (a wide
    # travel width means neither bounces off an edge). Stride-sync (Task 28)
    # concentrates gallop's dx into the airborne beats, so a *short* window
    # can land mid-cycle and skew the ratio; averaging across many cycles is
    # what the "~3x walk" contract promise is actually about.
    walk = CharacterMovement("walk", travel_width=TRAVEL_WIDTH * 10)
    gallop = CharacterMovement("gallop", travel_width=TRAVEL_WIDTH * 10)
    dt = 0.01

    walk_start_x, _ = walk.step(0.0)
    gallop_start_x, _ = gallop.step(0.0)
    for _ in range(2000):  # 20 simulated seconds, ~56 gallop cycles
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


# --- CharacterMovement: facing (M11 Task 28) ----------------------------------


def test_still_facing_is_always_plus_one() -> None:
    m = CharacterMovement("still", travel_width=TRAVEL_WIDTH)
    assert m.facing == 1
    for _ in range(50):
        m.step(0.05)
        assert m.facing == 1


@pytest.mark.parametrize("movement", MOVEMENTS)
def test_facing_starts_at_plus_one(movement: str) -> None:
    m = CharacterMovement(movement, travel_width=TRAVEL_WIDTH, rng=random.Random(3))
    assert m.facing == 1


@pytest.mark.parametrize("movement", MOVEMENTS)
def test_facing_is_always_plus_or_minus_one(movement: str) -> None:
    m = CharacterMovement(movement, travel_width=TRAVEL_WIDTH, rng=random.Random(6))
    for _ in range(500):
        m.step(0.05)
        assert m.facing in (1, -1)


@pytest.mark.parametrize("movement", MOVEMENTS)
def test_facing_matches_sign_of_horizontal_movement(movement: str) -> None:
    # A narrow travel width forces frequent edge bounces, exercising the
    # bounce case densely. `_patrol` flips `direction` (and so `facing`) the
    # instant it clamps to a boundary -- i.e. *before* the next step's
    # displacement happens in the new direction -- so the one tick that lands
    # exactly on a boundary is exempted: its displacement was still made in
    # the *old* direction, while `facing` (queried after `step()` returns)
    # already reports the new one the character is about to turn to.
    #
    # `dt` is kept well below gallop's finest internal segment (the 0.03s
    # gap) so a single `step(dt)` call can't itself straddle a bounce *and*
    # the recovery leg on the other side (gallop's stride-sync integrates
    # patrol piecewise across its beat/gap/rest segments, so a coarser dt
    # could otherwise contain more than one direction change).
    rng = random.Random(21)
    m = CharacterMovement(movement, travel_width=30.0, rng=rng)
    dt = 0.005
    prev_x, _ = m.step(dt)
    saw_positive = False
    saw_negative = False
    for _ in range(30_000):
        x, _ = m.step(dt)
        dx = x - prev_x
        at_boundary = x <= 1e-6 or x >= 30.0 - 1e-6
        if not at_boundary:
            if dx > 1e-9:
                assert m.facing == 1
                saw_positive = True
            elif dx < -1e-9:
                assert m.facing == -1
                saw_negative = True
        prev_x = x

    if movement != "still":
        # sanity: the narrow travel width should have produced movement in
        # both directions for every non-still preset (bounces guarantee it).
        assert saw_positive or saw_negative


def test_facing_flips_immediately_after_an_edge_bounce() -> None:
    m = CharacterMovement("walk", travel_width=10.0, rng=random.Random(1))
    assert m.facing == 1

    x = m.step(0.0)[0]
    for _ in range(200):
        x, _ = m.step(0.05)
        if x >= 10.0 - 1e-9:
            break
    assert x >= 10.0 - 1e-9
    assert m.facing == -1  # about to head back left

    for _ in range(200):
        x, _ = m.step(0.05)
        if x <= 0.0 + 1e-9:
            break
    assert x <= 0.0 + 1e-9
    assert m.facing == 1  # about to head back right


# --- CharacterMovement: gallop stride-sync (M11 Task 28) -----------------------


def test_gallop_airborne_phase_carries_most_of_the_stride() -> None:
    # >= 70% of each cycle's horizontal advance must happen while the
    # character is airborne (y_offset > 0) -- otherwise it reads as sliding
    # along the ground rather than striding. Sample several full cycles.
    m = CharacterMovement("gallop", travel_width=TRAVEL_WIDTH)
    dt = 0.005
    steps_per_cycle = round(GALLOP_CYCLE_SECONDS / dt)
    cycles = 8

    airborne_dx = 0.0
    ground_dx = 0.0
    prev_x, prev_y = m.step(0.0)
    for _ in range(steps_per_cycle * cycles):
        x, y = m.step(dt)
        dx = x - prev_x
        # a step is "airborne" if either end of it has y_offset > 0
        if y > 0.0 or prev_y > 0.0:
            airborne_dx += dx
        else:
            ground_dx += dx
        prev_x, prev_y = x, y

    total_dx = airborne_dx + ground_dx
    assert total_dx > 0.0
    assert airborne_dx / total_dx >= 0.7


def test_gallop_per_cycle_total_dx_matches_the_cycle_average_speed() -> None:
    # Redistributing dx toward the airborne beats must not change the total
    # ground covered per cycle -- the cycle AVERAGE speed (~3x walk, per
    # contract) stays the same as before Task 28.
    m = CharacterMovement("gallop", travel_width=TRAVEL_WIDTH * 10)
    dt = 0.005
    steps_per_cycle = round(GALLOP_CYCLE_SECONDS / dt)
    cycles = 5

    start_x, _ = m.step(0.0)
    x = start_x
    for _ in range(steps_per_cycle * cycles):
        x, _ = m.step(dt)

    total_dx = x - start_x
    expected = GALLOP_SPEED_PX_PER_SEC * GALLOP_CYCLE_SECONDS * cycles
    assert total_dx == pytest.approx(expected, rel=0.02)


def _gallop_run(dt: float, total_time: float) -> tuple[float, float, float]:
    """Simulate `gallop` for ~`total_time` seconds at a fixed `dt`. Returns
    `(avg_speed, elapsed, airborne_fraction)` -- `elapsed` is `steps * dt`
    (may differ slightly from `total_time` since `steps` is rounded), and
    `airborne_fraction` is the share of dx covered while `y_offset > 0`
    (either end of a step), per the contract's stride-sync bookkeeping.
    Travel width is huge so the run never bounces off an edge, which would
    make "net dx == avg speed * elapsed" invalid.
    """
    steps = round(total_time / dt)
    m = CharacterMovement("gallop", travel_width=GALLOP_SPEED_PX_PER_SEC * total_time * 10.0)

    airborne_dx = 0.0
    ground_dx = 0.0
    prev_x, prev_y = m.step(0.0)
    for _ in range(steps):
        x, y = m.step(dt)
        dx = x - prev_x
        if y > 0.0 or prev_y > 0.0:
            airborne_dx += dx
        else:
            ground_dx += dx
        prev_x, prev_y = x, y

    total_dx = airborne_dx + ground_dx
    elapsed = steps * dt
    return total_dx / elapsed, elapsed, airborne_dx / total_dx


@pytest.mark.parametrize("dt", [0.061, 0.067, 0.079, 0.083, 0.091])
def test_gallop_stride_sync_holds_for_a_non_cycle_aligned_dt(dt: float) -> None:
    # Regression (Codex review of Task 28): a naive "pick one speed for the
    # whole dt, based on the phase at the end of it" implementation only
    # integrates correctly when dt happens to land on a beat/gap/rest
    # boundary -- every other gallop test in this file uses dt=0.005 or
    # 0.01, which (not coincidentally) divide every one of
    # GALLOP_CYCLE_SECONDS's internal boundaries evenly and so can't expose
    # this bug. None of `dt`'s parametrized values divide the 0.09/0.03/
    # 0.15s beat/gap/rest durations evenly, so (unlike e.g. 0.007 or 0.013,
    # which happen to average out too cleanly against these particular
    # timings to reliably catch the bug) every one of them lands mid-segment
    # on most cycles and clearly separates a piecewise-correct
    # implementation (observed drift here: well under 0.05%) from the
    # single-speed-per-dt bug this guards against (observed drift: 0.07% to
    # 0.6%, i.e. 5-10x this test's tolerance) -- see the reasoning captured
    # in the M11 Task 28 report for the numbers behind this choice.
    #
    # `_step_gallop` integrates the patrol piecewise across boundaries
    # instead, so per-cycle dx (and the airborne fraction) must come out the
    # same as an aligned dt's, for ANY dt.
    baseline_avg_speed, _, _ = _gallop_run(0.005, total_time=100.0)
    avg_speed, _, airborne_fraction = _gallop_run(dt, total_time=100.0)

    assert avg_speed == pytest.approx(baseline_avg_speed, rel=0.0005)
    assert airborne_fraction >= 0.7


def _simulate(movement: str, *, seed: int, steps: int, dt: float) -> list[tuple[float, float]]:
    rng = random.Random(seed)
    m = CharacterMovement(movement, travel_width=TRAVEL_WIDTH, rng=rng)
    return [m.step(dt) for _ in range(steps)]
