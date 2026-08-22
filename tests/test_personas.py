from __future__ import annotations

import random

import pytest

from todoy.display.characters import CHARACTERS
from todoy.display.overlay.animations import MOVEMENTS
from todoy.display.overlay.personas import (
    PERSONAS,
    EntranceAnimation,
    FlourishAnimation,
    Persona,
    persona,
)

CHAR_HEIGHT = 40.0

# Concrete movement presets a persona is allowed to name. Defensive against a
# parallel task adding "auto" to MOVEMENTS (M13 Task 33): personas must always
# resolve to a concrete preset, never "auto".
_CONCRETE_MOVEMENTS = set(MOVEMENTS) - {"auto"}

ENTRANCE_KINDS = ("walk_in", "splash", "swoop", "hop_in", "materialize")
FLOURISH_KINDS = ("none", "resurface", "swoop_dip", "hop", "blink")


def _run_entrance(
    kind: str,
    *,
    char_height: float = CHAR_HEIGHT,
    dt: float = 0.02,
    rng: random.Random | None = None,
) -> tuple[EntranceAnimation, list[tuple[float, float, float, float]]]:
    anim = EntranceAnimation(kind, char_height, rng=rng)
    trace: list[tuple[float, float, float, float]] = []
    steps = 0
    while not anim.finished and steps < 1000:
        trace.append(anim.step(dt))
        steps += 1
    return anim, trace


def _run_flourish(
    kind: str,
    *,
    char_height: float = CHAR_HEIGHT,
    dt: float = 0.02,
    rng: random.Random | None = None,
) -> tuple[FlourishAnimation, list[tuple[float, float, float, float]]]:
    anim = FlourishAnimation(kind, char_height, rng=rng)
    trace: list[tuple[float, float, float, float]] = []
    steps = 0
    while not anim.finished and steps < 1000:
        trace.append(anim.step(dt))
        steps += 1
    return anim, trace


def _dip_regions(values: list[float], threshold: float = 0.05) -> int:
    """Count distinct "decrease then recover by more than `threshold`" runs
    in `values` -- i.e. visually distinct dips, ignoring float-noise wiggles."""
    count = 0
    i = 1
    n = len(values)
    while i < n - 1:
        if values[i] < values[i - 1]:
            j = i
            while j + 1 < n and values[j + 1] <= values[j]:
                j += 1
            k = j
            while k + 1 < n and values[k + 1] >= values[k]:
                k += 1
            if values[k] - values[j] > threshold:
                count += 1
            i = k + 1
        else:
            i += 1
    return count


# --- persona catalog -----------------------------------------------------------


def test_every_character_has_a_persona() -> None:
    assert set(PERSONAS) >= set(CHARACTERS)


def test_persona_movements_are_all_concrete_presets() -> None:
    for name, p in PERSONAS.items():
        assert p.movement in _CONCRETE_MOVEMENTS, f"{name}: {p.movement!r} not concrete"


def test_persona_unknown_name_falls_back_to_ground_default() -> None:
    p = persona("this-character-does-not-exist")
    assert p == Persona(
        zone="ground", entrance="walk_in", flourish="none", banner=False, movement="walk"
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("whale", Persona("water", "splash", "resurface", False, "walk")),
        ("octopus", Persona("water", "splash", "resurface", False, "walk")),
        ("crab", Persona("water", "splash", "resurface", False, "walk")),
        ("penguin", Persona("water", "splash", "resurface", False, "walk")),
        ("frog", Persona("water", "hop_in", "hop", False, "hop")),
        ("butterfly", Persona("sky", "swoop", "swoop_dip", True, "float")),
        ("bee", Persona("sky", "swoop", "swoop_dip", True, "dash")),
        ("owl", Persona("sky", "swoop", "swoop_dip", True, "float")),
        ("duck", Persona("sky", "swoop", "swoop_dip", True, "float")),
        ("dragon", Persona("sky", "swoop", "swoop_dip", True, "float")),
        ("rabbit", Persona("ground", "hop_in", "hop", False, "hop")),
        ("ghost", Persona("ground", "materialize", "blink", False, "float")),
        ("alien", Persona("ground", "materialize", "blink", False, "walk")),
        ("robot", Persona("ground", "materialize", "blink", False, "walk")),
        ("horse", Persona("ground", "walk_in", "none", False, "gallop")),
        ("unicorn", Persona("ground", "walk_in", "none", False, "gallop")),
        ("snail", Persona("ground", "walk_in", "none", False, "walk")),
        ("turtle", Persona("ground", "walk_in", "none", False, "walk")),
        ("cat", Persona("ground", "walk_in", "none", False, "walk")),
        ("dog", Persona("ground", "walk_in", "none", False, "walk")),
    ],
)
def test_binding_assignments(name: str, expected: Persona) -> None:
    assert persona(name) == expected


def test_persona_of_unlisted_character_is_reachable_via_function_and_dict() -> None:
    for name in CHARACTERS:
        assert persona(name) == PERSONAS[name]


# --- M14: pixel-art characters (blocky/slime/knight) -----------------------


@pytest.mark.parametrize("name", ["blocky", "slime", "knight"])
def test_pixelart_character_has_a_persona(name: str) -> None:
    assert name in PERSONAS


@pytest.mark.parametrize("name", ["blocky", "slime", "knight"])
def test_pixelart_character_is_a_ground_walk_in_walker(name: str) -> None:
    p = persona(name)
    assert p.zone == "ground"
    assert p.entrance == "walk_in"
    assert p.movement == "walk"
    assert p.banner is False


@pytest.mark.parametrize("name", ["blocky", "slime", "knight"])
def test_pixelart_character_flourish_is_a_valid_kind(name: str) -> None:
    assert persona(name).flourish in FLOURISH_KINDS


# --- EntranceAnimation: construction --------------------------------------------


def test_entrance_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="Unknown"):
        EntranceAnimation("teleport", CHAR_HEIGHT)


def test_entrance_rejects_negative_dt() -> None:
    anim = EntranceAnimation("walk_in", CHAR_HEIGHT)
    with pytest.raises(ValueError):
        anim.step(-0.1)


# --- EntranceAnimation: shared invariants across all types ---------------------


@pytest.mark.parametrize("kind", ENTRANCE_KINDS)
def test_entrance_finishes_within_contract_duration(kind: str) -> None:
    anim, _trace = _run_entrance(kind, dt=0.01)
    assert anim.finished
    assert 0.8 <= anim._elapsed <= 1.4


@pytest.mark.parametrize("kind", ENTRANCE_KINDS)
def test_entrance_outputs_are_bounded(kind: str) -> None:
    _anim, trace = _run_entrance(kind, dt=0.01)
    for x_off, y_off, alpha, scale in trace:
        assert abs(x_off) <= 2.5 * CHAR_HEIGHT
        assert abs(y_off) <= 2.5 * CHAR_HEIGHT
        assert 0.0 <= alpha <= 1.0
        assert 0.4 <= scale <= 1.1


@pytest.mark.parametrize("kind", ENTRANCE_KINDS)
def test_entrance_ends_at_neutral_state(kind: str) -> None:
    _anim, trace = _run_entrance(kind, dt=0.01)
    x_off, y_off, alpha, scale = trace[-1]
    assert x_off == pytest.approx(0.0, abs=1e-6)
    assert y_off == pytest.approx(0.0, abs=1e-6)
    assert alpha == pytest.approx(1.0, abs=1e-6)
    assert scale == pytest.approx(1.0, abs=1e-6)


@pytest.mark.parametrize("kind", ENTRANCE_KINDS)
def test_entrance_step_after_finished_is_a_noop(kind: str) -> None:
    anim, _trace = _run_entrance(kind, dt=0.05)
    assert anim.finished
    assert anim.step(0.05) == (0.0, 0.0, 1.0, 1.0)
    assert anim.step(1.0) == (0.0, 0.0, 1.0, 1.0)
    assert anim.finished


@pytest.mark.parametrize("kind", ENTRANCE_KINDS)
def test_entrance_deterministic_with_seeded_rng(kind: str) -> None:
    _anim_a, trace_a = _run_entrance(kind, dt=0.03, rng=random.Random(99))
    _anim_b, trace_b = _run_entrance(kind, dt=0.03, rng=random.Random(99))
    assert trace_a == trace_b


# --- EntranceAnimation: per-type shape checks -----------------------------------


def test_walk_in_moves_x_only_from_offscreen_to_zero() -> None:
    anim, trace = _run_entrance("walk_in", dt=0.01)
    xs = [p[0] for p in trace]
    ys = [p[1] for p in trace]
    assert xs[0] < 0.0  # starts off-screen (negative x offset)
    assert all(y == 0.0 for y in ys)
    assert all(p[2] == 1.0 and p[3] == 1.0 for p in trace)


def test_splash_has_exactly_one_overshoot_above_baseline_before_settling() -> None:
    _anim, trace = _run_entrance("splash", dt=0.01)
    ys = [p[1] for p in trace]
    assert ys[0] < 0.0  # starts below the baseline (underwater)

    above_baseline = [y > 1e-9 for y in ys]
    runs = 0
    prev = False
    for is_above in above_baseline:
        if is_above and not prev:
            runs += 1
        prev = is_above
    assert runs == 1
    assert ys[-1] == pytest.approx(0.0, abs=1e-6)


def test_swoop_starts_high_above_cruise_and_eases_down() -> None:
    _anim, trace = _run_entrance("swoop", dt=0.01)
    ys = [p[1] for p in trace]
    xs = [p[0] for p in trace]
    assert ys[0] > 0.0  # starts above cruise height
    assert ys[0] == max(ys)  # monotonically eases down, never re-climbs above start
    assert ys[-1] == pytest.approx(0.0, abs=1e-6)
    assert xs[0] != 0.0  # slight x lead-in


def test_hop_in_enters_from_x_offset_with_two_decaying_hops() -> None:
    _anim, trace = _run_entrance("hop_in", dt=0.005)
    xs = [p[0] for p in trace]
    ys = [p[1] for p in trace]
    assert xs[0] < 0.0  # enters from an x offset

    dip_regions = _dip_regions([-y for y in ys], threshold=1.0)
    # two decaying hops read as two "dips" in -y (i.e. two humps in y)
    assert dip_regions == 2

    peak1 = max(ys[: len(ys) // 2])
    peak2 = max(ys[len(ys) // 2 :])
    assert peak1 > peak2 > 0.0  # second hop decays relative to the first


def test_materialize_alpha_and_scale_ramp_up_with_two_blink_dips() -> None:
    _anim, trace = _run_entrance("materialize", dt=0.01)
    xs = [p[0] for p in trace]
    ys = [p[1] for p in trace]
    alphas = [p[2] for p in trace]
    scales = [p[3] for p in trace]

    assert all(x == 0.0 for x in xs)
    assert all(y == 0.0 for y in ys)
    assert alphas[0] < 0.1
    assert alphas[-1] == pytest.approx(1.0, abs=1e-6)
    assert scales[0] == pytest.approx(0.6, abs=0.05)
    assert scales[-1] == pytest.approx(1.0, abs=1e-6)
    assert _dip_regions(alphas) == 2


# --- FlourishAnimation: construction ---------------------------------------------


def test_flourish_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="Unknown"):
        FlourishAnimation("explode", CHAR_HEIGHT)


def test_flourish_rejects_negative_dt() -> None:
    anim = FlourishAnimation("hop", CHAR_HEIGHT)
    with pytest.raises(ValueError):
        anim.step(-0.1)


def test_flourish_none_is_immediately_finished() -> None:
    anim = FlourishAnimation("none", CHAR_HEIGHT)
    assert anim.finished
    assert anim.step(0.5) == (0.0, 0.0, 1.0, 1.0)


# --- FlourishAnimation: shared invariants across all types ----------------------


@pytest.mark.parametrize("kind", FLOURISH_KINDS)
def test_flourish_finishes_within_contract_duration(kind: str) -> None:
    anim, _trace = _run_flourish(kind, dt=0.01)
    assert anim.finished
    if kind == "none":
        assert anim._elapsed == 0.0
    else:
        assert 0.6 <= anim._elapsed <= 1.0


@pytest.mark.parametrize("kind", FLOURISH_KINDS)
def test_flourish_outputs_are_bounded(kind: str) -> None:
    _anim, trace = _run_flourish(kind, dt=0.01)
    for x_off, y_off, alpha, scale in trace:
        assert abs(x_off) <= 2.5 * CHAR_HEIGHT
        assert abs(y_off) <= 2.5 * CHAR_HEIGHT
        assert 0.0 <= alpha <= 1.0
        assert 0.4 <= scale <= 1.1


@pytest.mark.parametrize("kind", FLOURISH_KINDS)
def test_flourish_ends_at_neutral_state(kind: str) -> None:
    _anim, trace = _run_flourish(kind, dt=0.01)
    if not trace:  # "none" finishes before any step is recorded
        return
    x_off, y_off, alpha, scale = trace[-1]
    assert x_off == pytest.approx(0.0, abs=1e-6)
    assert y_off == pytest.approx(0.0, abs=1e-6)
    assert alpha == pytest.approx(1.0, abs=1e-6)
    assert scale == pytest.approx(1.0, abs=1e-6)


@pytest.mark.parametrize("kind", FLOURISH_KINDS)
def test_flourish_step_after_finished_is_a_noop(kind: str) -> None:
    anim, _trace = _run_flourish(kind, dt=0.05)
    assert anim.finished
    assert anim.step(0.05) == (0.0, 0.0, 1.0, 1.0)
    assert anim.step(1.0) == (0.0, 0.0, 1.0, 1.0)
    assert anim.finished


@pytest.mark.parametrize("kind", FLOURISH_KINDS)
def test_flourish_deterministic_with_seeded_rng(kind: str) -> None:
    _anim_a, trace_a = _run_flourish(kind, dt=0.03, rng=random.Random(7))
    _anim_b, trace_b = _run_flourish(kind, dt=0.03, rng=random.Random(7))
    assert trace_a == trace_b


# --- FlourishAnimation: per-type shape checks ------------------------------------


def test_resurface_dips_then_overshoots() -> None:
    _anim, trace = _run_flourish("resurface", dt=0.01)
    ys = [p[1] for p in trace]
    min_idx = ys.index(min(ys))
    max_idx = ys.index(max(ys))
    assert ys[min_idx] < 0.0  # dips below baseline first
    assert ys[max_idx] > 0.0  # then overshoots above baseline
    assert min_idx < max_idx  # dip happens before the overshoot
    assert ys[-1] == pytest.approx(0.0, abs=1e-6)


def test_swoop_dip_is_a_brief_single_dip_and_return() -> None:
    _anim, trace = _run_flourish("swoop_dip", dt=0.01)
    ys = [p[1] for p in trace]
    assert min(ys) < 0.0
    assert max(ys) <= 1e-9  # never rises above baseline
    assert ys[-1] == pytest.approx(0.0, abs=1e-6)
    assert _dip_regions(ys, threshold=1.0) == 1


def test_hop_is_a_single_hop() -> None:
    _anim, trace = _run_flourish("hop", dt=0.01)
    ys = [p[1] for p in trace]
    assert min(ys) >= 0.0
    assert max(ys) > 0.0
    assert ys[-1] == pytest.approx(0.0, abs=1e-6)
    assert _dip_regions([-y for y in ys], threshold=1.0) == 1


def test_blink_dips_alpha_twice_and_returns_to_one() -> None:
    _anim, trace = _run_flourish("blink", dt=0.01)
    alphas = [p[2] for p in trace]
    assert alphas[-1] == pytest.approx(1.0, abs=1e-6)
    assert _dip_regions(alphas) == 2
