from __future__ import annotations

import math
import random

import pytest

from todoy.display.overlay.animations import (
    BUBBLE_EFFECTS,
    DASH_BURST_SPEED_PX_PER_SEC,
    FLOAT_BOB_AMPLITUDE_PX,
    FLOAT_SPEED_PX_PER_SEC,
    GALLOP_AIRBORNE_SPEED_PX_PER_SEC,
    GALLOP_CYCLE_SECONDS,
    GALLOP_GROUND_SPEED_PX_PER_SEC,
    GALLOP_HOP_PEAK_HEIGHT_PX,
    GALLOP_SPEED_PX_PER_SEC,
    HOP_PEAK_HEIGHT_PX,
    HOP_SPEED_PX_PER_SEC,
    MESSAGE_STYLES,
    MOVEMENTS,
    TURN_DURATION_SECONDS,
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
    #
    # Since Task 29, a bounce is an eased turn (~0.3s cosine decel/accel)
    # rather than an instant reversal, and its zero-velocity midpoint --
    # where x actually touches the edge -- generally falls *between* this
    # test's fixed dt=0.05 samples rather than exactly on one of them. The
    # tolerance below (empirically, samples land within ~0.002px of an edge
    # for this seed/width) is generous slack for that grid-vs-continuous-
    # curve misalignment, not a loosened correctness bar.
    m = CharacterMovement("walk", travel_width=10.0, rng=random.Random(1))
    xs = [m.step(0.05)[0] for _ in range(400)]

    assert any(x <= 0.0 + 0.05 for x in xs)
    assert any(x >= 10.0 - 0.05 for x in xs)


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
    # bounce case densely. Outside of a turn, `facing` (== sign of
    # `direction`) must always agree with the direction `x` is actually
    # moving.
    #
    # Since Task 29 a bounce eases through a ~0.3s turn instead of
    # reversing instantly, and `direction` (and so `facing`) flips at the
    # turn's zero-velocity midpoint, which can fall *inside* a single
    # `step(dt)` call rather than exactly at its start or end -- that one
    # call's net `dx` can then reflect a mix of old- and new-direction
    # motion while `facing` (queried after `step()` returns) already
    # reports the post-flip direction. `is_turning` (before and after the
    # step) is used to exempt exactly those straddling calls; every other
    # sample -- i.e. every call fully inside one steady-motion leg -- must
    # still match exactly.
    rng = random.Random(21)
    m = CharacterMovement(movement, travel_width=30.0, rng=rng)
    dt = 0.005
    prev_x, _ = m.step(dt)
    min_x, max_x = prev_x, prev_x
    for _ in range(30_000):
        turning_before = m.is_turning
        x, _ = m.step(dt)
        turning_after = m.is_turning
        dx = x - prev_x
        if not turning_before and not turning_after:
            if dx > 1e-9:
                assert m.facing == 1
            elif dx < -1e-9:
                assert m.facing == -1
        prev_x = x
        min_x, max_x = min(min_x, x), max(max_x, x)

    if movement != "still":
        # sanity: the narrow travel width, some fast presets' eased-turn
        # zones (Task 29) now cover most of it (e.g. dash's burst speed
        # makes its steady, non-turning leg vanish at this width -- see the
        # M12 Task 29 report), so this checks the *range of x actually
        # visited* rather than sampling dx sign in the (possibly empty)
        # non-turning window: both edges' neighborhoods were reached.
        assert min_x < 5.0
        assert max_x > 25.0


def test_facing_flips_at_turn_midpoint_near_the_edge() -> None:
    # Since Task 29 a bounce is an eased ~0.3s turn, not an instant reversal
    # -- `facing` flips at the turn's zero-velocity midpoint, which this
    # test locates via `is_turning` (rather than waiting for `x` to reach
    # the edge exactly, which a fixed dt generally won't land on -- see
    # `test_walk_bounces_at_both_edges`). At the flip, `x` should already
    # be close to the edge it's turning at (within the turn's own ease
    # distance for this speed/duration, ~4.3px for walk).
    m = CharacterMovement("walk", travel_width=10.0, rng=random.Random(1))
    assert m.facing == 1
    dt = 0.005

    def run_until_flip() -> float:
        prev_facing = m.facing
        for _ in range(2000):
            x, _ = m.step(dt)
            if m.facing != prev_facing:
                assert m.is_turning  # flip happens mid-turn, not at a clamp
                return x
        raise AssertionError("facing never flipped")

    x_at_first_flip = run_until_flip()
    assert m.facing == -1  # about to head back left
    assert x_at_first_flip >= 10.0 - 5.0  # near the right edge, not mid-travel

    x_at_second_flip = run_until_flip()
    assert m.facing == 1  # about to head back right
    assert x_at_second_flip <= 0.0 + 5.0  # near the left edge


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


# --- CharacterMovement: eased edge turns (M12 Task 29) -------------------------


def _velocities_through_first_turn(
    movement: str, *, travel_width: float, dt: float, seed: int = 1, max_steps: int = 20_000
) -> tuple[list[float], list[bool]]:
    """Simulate `movement` until (and through) its first `is_turning` window,
    sampling `dx/dt` every step. Returns `(velocities, is_turning_flags)`
    covering the turn itself plus one context sample before it starts and
    one after it ends -- `is_turning_flags` lets callers tell those two
    context samples apart from the turn's own samples (e.g. `dash` can
    legitimately go flat the instant a turn completes if it's paused --
    that's its own accepted bursty gait resuming, not the turn itself being
    non-smooth; see `test_turn_velocity_decelerates_then_accelerates_with_
    no_jumps`)."""
    m = CharacterMovement(movement, travel_width=travel_width, rng=random.Random(seed))
    prev_x, _ = m.step(0.0)
    velocities: list[float] = []
    turning: list[bool] = []
    for _ in range(max_steps):
        x, _ = m.step(dt)
        velocities.append((x - prev_x) / dt)
        turning.append(m.is_turning)
        prev_x = x
        if len(turning) > 1 and turning[-2] and not turning[-1]:
            break  # just finished the first turn
    else:
        raise AssertionError("never observed a full turn within max_steps")

    start = turning.index(True)
    end = len(turning) - 1  # last False, right after the turn ended
    window = slice(max(0, start - 1), end + 1)
    return velocities[window], turning[window]


@pytest.mark.parametrize(
    ("movement", "speed", "travel_width", "max_steps"),
    [
        ("walk", WALK_SPEED_PX_PER_SEC, 200.0, 20_000),
        ("hop", HOP_SPEED_PX_PER_SEC, 200.0, 20_000),
        ("float", FLOAT_SPEED_PX_PER_SEC, 200.0, 20_000),
        ("gallop", GALLOP_AIRBORNE_SPEED_PX_PER_SEC, 200.0, 20_000),
        # dash spends most of its time paused between bursts (Codex review
        # follow-up, Minor 5 -- this preset would have caught Major 1: a
        # turn triggered near the end of a burst that freezes the instant
        # `_dash_state` flips to "pause"). A narrower width and more steps
        # than the other presets reliably finds a burst that reaches the
        # edge within `max_steps`.
        ("dash", DASH_BURST_SPEED_PX_PER_SEC, 100.0, 200_000),
    ],
)
def test_turn_velocity_decelerates_then_accelerates_with_no_jumps(
    movement: str, speed: float, travel_width: float, max_steps: int
) -> None:
    # The contract's core smoothness claim: across an edge turn, horizontal
    # velocity (dx/dt) decelerates to zero and accelerates back out in the
    # new direction -- monotonically on each side, with no discontinuous
    # jump anywhere (each step's speed changes by only a small, bounded
    # amount -- never more than a full swing from the preset's nominal
    # speed to its negation, which is what an *instant* bounce would do).
    # This holds no matter what a preset is doing around the turn -- e.g.
    # dash pausing partway through one (Major 1).
    dt = 0.001
    velocities, turning_flags = _velocities_through_first_turn(
        movement, travel_width=travel_width, dt=dt, max_steps=max_steps
    )

    assert len(velocities) > 10  # actually sampled the eased turn, not a snap

    # No step-to-step jump anywhere close to an instant reversal (2x speed).
    max_step_delta = max(abs(b - a) for a, b in zip(velocities, velocities[1:], strict=False))
    assert max_step_delta < speed  # well under a full +speed -> -speed snap

    # Never exceeds the preset's own nominal speed (the ease is a scale-down
    # of it, never an overshoot).
    assert max(abs(v) for v in velocities) <= speed + 1e-6

    # Sign flips exactly once, and each side is monotonic in magnitude:
    # decelerating while still in the old direction, then accelerating in
    # the new one. Restricted to samples strictly *inside* the turn --
    # excludes the one lead-in and one trail-out context sample the helper
    # includes, since a preset with its own start/stop gait (dash's burst/
    # pause) can legitimately go instantly flat right as the turn ends if
    # it's paused at that instant; that's dash's own accepted jerkiness
    # resuming, not the turn itself failing to be smooth.
    in_turn = [v for v, t in zip(velocities, turning_flags, strict=True) if t]
    assert len(in_turn) > 10

    signs = [1 if v > 1e-9 else (-1 if v < -1e-9 else 0) for v in in_turn]
    nonzero_signs = [s for s in signs if s != 0]
    sign_changes = sum(1 for a, b in zip(nonzero_signs, nonzero_signs[1:], strict=False) if a != b)
    assert sign_changes == 1

    flip_index = next(i for i, s in enumerate(signs) if s != signs[0] and s != 0)
    decel_leg = [abs(v) for v in in_turn[:flip_index]]
    accel_leg = [abs(v) for v in in_turn[flip_index:]]
    assert decel_leg == sorted(decel_leg, reverse=True)
    assert accel_leg == sorted(accel_leg)


def test_turn_duration_is_within_the_contract_range() -> None:
    # ~0.25-0.35s per the contract, when there's ample room to ease into (no
    # narrow-travel_width clamping -- see `_begin_turn`).
    dt = 0.0005
    velocities, _turning = _velocities_through_first_turn("walk", travel_width=400.0, dt=dt)
    turn_duration = len(velocities) * dt
    assert 0.2 <= turn_duration <= 0.4


def test_facing_flips_exactly_at_the_zero_velocity_sample() -> None:
    # The step where `facing` changes should be the one with the smallest
    # |velocity| in the whole turn -- i.e. right at the cosine profile's
    # zero crossing, not somewhere else in the ease.
    dt = 0.001
    m = CharacterMovement("walk", travel_width=100.0, rng=random.Random(1))
    prev_x, _ = m.step(0.0)
    prev_facing = m.facing
    velocities: list[float] = []
    flip_offset: int | None = None
    for _ in range(4000):
        x, _ = m.step(dt)
        velocities.append((x - prev_x) / dt)
        if m.facing != prev_facing:
            flip_offset = len(velocities) - 1
            prev_facing = m.facing
        prev_x = x
        if flip_offset is not None:
            break

    assert flip_offset is not None
    window = velocities[max(0, flip_offset - 20) : flip_offset + 21]
    closest_to_zero = min(range(len(window)), key=lambda i: abs(window[i]))
    assert window[closest_to_zero] == velocities[flip_offset]


def test_still_never_turns() -> None:
    m = CharacterMovement("still", travel_width=TRAVEL_WIDTH)
    for _ in range(200):
        m.step(0.05)
        assert not m.is_turning


@pytest.mark.parametrize("movement", [mv for mv in MOVEMENTS if mv != "still"])
def test_average_speed_is_preserved_within_five_percent_after_easing(
    movement: str,
) -> None:
    # Contract: per-preset average speed over long runs must stay within
    # +/-5% of what it was before eased turns existed -- i.e. before, a
    # bounce cost zero time; now it costs ~TURN_DURATION_SECONDS of net-zero
    # progress. Compare a huge travel_width (effectively bounce-free -- the
    # pre-Task-29 baseline) against a realistic screen-sized one (frequent
    # bounces, eased turns and all) using cumulative absolute displacement
    # over a long, fixed wall-clock run.
    dt = 0.02
    total_time = 120.0
    steps = round(total_time / dt)

    def average_abs_speed(travel_width: float) -> float:
        m = CharacterMovement(movement, travel_width=travel_width, rng=random.Random(1))
        prev_x, _ = m.step(0.0)
        total_abs_dx = 0.0
        for _ in range(steps):
            x, _ = m.step(dt)
            total_abs_dx += abs(x - prev_x)
            prev_x = x
        return total_abs_dx / (steps * dt)

    bounce_free = average_abs_speed(100_000.0)
    realistic = average_abs_speed(1300.0)  # ~a laptop screen's travel width

    assert realistic == pytest.approx(bounce_free, rel=0.05)


def test_turn_duration_constant_matches_the_contract_range() -> None:
    assert 0.25 <= TURN_DURATION_SECONDS <= 0.35


# --- CharacterMovement: eased edge turns, Codex review follow-up ---------------


def test_dash_turn_completes_through_a_pause_window() -> None:
    # Regression (Codex review, Major 1): a turn already in progress used to
    # freeze the instant `_dash_state` flipped to "pause" mid-turn -- `x`
    # and `direction` got stuck there forever (is_turning never cleared),
    # since `_step_dash` only ever advanced `_patrol` while bursting.
    # Force the exact scenario deterministically: start a turn, then flip
    # dash to "pause" (as its RNG-driven burst timer would mid-turn) and
    # confirm the turn still runs to completion under `step()`.
    m = CharacterMovement("dash", travel_width=1000.0, rng=random.Random(1))
    m._dash_state = "burst"
    m._begin_turn(DASH_BURST_SPEED_PX_PER_SEC)
    assert m.is_turning
    x_at_turn_start = m.x

    # Simulate the burst ending right as the turn began: pause, with a long
    # timer so the pause itself doesn't end mid-test.
    m._dash_state = "pause"
    m._dash_timer = 1000.0

    dt = 0.001
    saw_motion = False
    for _ in range(1000):  # 1s -- comfortably more than TURN_DURATION_SECONDS
        prev_x = m.x
        m.step(dt)
        if m.x != prev_x:
            saw_motion = True
        if not m.is_turning:
            break

    assert not m.is_turning  # the turn actually finished, not stuck forever
    assert saw_motion  # and it moved while doing so, not frozen in place
    assert m.x != x_at_turn_start  # ended up somewhere past where it began
    assert m._dash_state == "pause"  # normal pause/burst gating resumed after


def test_advance_turn_uses_the_live_speed_argument_not_a_captured_one() -> None:
    # Regression (Codex review, Major 2): `_advance_turn` used to close over
    # the speed captured once at `_begin_turn` time, so gallop's stride-sync
    # speed (airborne vs. ground) got frozen at whatever it was when the
    # turn began instead of continuing to alternate through the turn.
    #
    # Verify directly at the same turn-local instant (elapsed=0, so the same
    # `_turn_scale` from identical trigger conditions): different *live*
    # speeds passed to `_advance_turn` must produce proportionally different
    # displacement -- if the speed were captured instead of live, both calls
    # would produce identical dx regardless of what's passed in.
    m_fast = CharacterMovement("gallop", travel_width=1000.0)
    start_x = m_fast.x
    m_fast._begin_turn(GALLOP_AIRBORNE_SPEED_PX_PER_SEC)
    m_fast._advance_turn(0.01, GALLOP_AIRBORNE_SPEED_PX_PER_SEC)
    fast_dx = abs(m_fast.x - start_x)

    m_slow = CharacterMovement("gallop", travel_width=1000.0)
    start_x2 = m_slow.x
    m_slow._begin_turn(GALLOP_AIRBORNE_SPEED_PX_PER_SEC)  # same trigger -> same _turn_scale
    m_slow._advance_turn(0.01, GALLOP_GROUND_SPEED_PX_PER_SEC)  # slower *live* speed
    slow_dx = abs(m_slow.x - start_x2)

    expected_ratio = GALLOP_AIRBORNE_SPEED_PX_PER_SEC / GALLOP_GROUND_SPEED_PX_PER_SEC
    assert fast_dx == pytest.approx(slow_dx * expected_ratio, rel=1e-9)
    assert fast_dx > slow_dx * 2  # sanity: airborne speed is ~4x ground speed


def test_gallop_stride_sync_holds_through_frequent_turns() -> None:
    # Integration-level companion to the direct `_advance_turn` test above:
    # even with a travel_width narrow enough to force frequent edge turns,
    # the airborne beats must still carry most of each cycle's dx (the same
    # >=70% contract bound `test_gallop_airborne_phase_carries_most_of_the_
    # stride` checks bounce-free) -- if a turn instead froze the speed it
    # was triggered at for its whole duration, wide swings of ground-speed
    # motion happening at airborne-speed amplitude (or vice versa) would
    # distort this ratio.
    m = CharacterMovement("gallop", travel_width=400.0, rng=random.Random(3))
    dt = 0.005
    steps = round(120.0 / dt)  # 120 simulated seconds, many bounces at this width

    airborne_dx = 0.0
    ground_dx = 0.0
    prev_x, prev_y = m.step(0.0)
    for _ in range(steps):
        x, y = m.step(dt)
        dx = abs(x - prev_x)
        if y > 0.0 or prev_y > 0.0:
            airborne_dx += dx
        else:
            ground_dx += dx
        prev_x, prev_y = x, y

    total_dx = airborne_dx + ground_dx
    assert total_dx > 0.0
    assert airborne_dx / total_dx >= 0.7


def test_turn_duration_stays_in_contract_range_at_a_narrow_travel_width() -> None:
    # Regression (Codex review, Minor 3): `_turn_duration` used to shrink
    # below the contract's 0.25-0.35s band at travel widths narrower than
    # the nominal ease distance. It's now always `TURN_DURATION_SECONDS`
    # (the turn's *amplitude* is what scales down instead, via
    # `_turn_scale`) -- verify at a travel_width well below walk's ~4.3px
    # nominal ease distance that duration stays in range and `x` never
    # leaves `[0, travel_width]`.
    travel_width = 2.0  # far narrower than WALK_SPEED * TURN_DURATION_SECONDS / pi
    dt = 0.0005
    velocities, _turning = _velocities_through_first_turn(
        "walk", travel_width=travel_width, dt=dt, max_steps=5000
    )
    turn_duration = len(velocities) * dt
    assert 0.25 <= turn_duration <= 0.35

    m = CharacterMovement("walk", travel_width=travel_width, rng=random.Random(2))
    for _ in range(2000):
        x, _ = m.step(dt)
        assert 0.0 <= x <= travel_width


def test_patrol_never_drops_dt_even_with_an_adversarial_huge_step() -> None:
    # Regression (Codex review, Minor 4): `_patrol`'s internal loop used to
    # cap at 10,000 iterations and silently drop whatever `dt` remained
    # unconsumed past that -- with a narrow `travel_width` (many bounces per
    # simulated second) and a huge single `dt`, that cap is reachable.
    # `step()` must still fully account for `dt` (bounded, finite result;
    # see `_patrol`'s post-loop leftover handling) rather than silently
    # losing time and leaving `x` wherever the cap happened to land.
    m = CharacterMovement("walk", travel_width=10.0, rng=random.Random(1))
    x, y = m.step(20_000.0)  # 20,000 simulated seconds in one call

    assert math.isfinite(x)
    assert math.isfinite(y)
    assert 0.0 <= x <= 10.0

    # The state machine must still be usable afterwards -- not stuck.
    x2, _ = m.step(0.01)
    assert math.isfinite(x2)
    assert 0.0 <= x2 <= 10.0
