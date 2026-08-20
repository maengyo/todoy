from __future__ import annotations

import random
import re

import pytest

from todoy.display.messages import (
    _CONGRATS_LINES,
    _TAUNT_LINES,
    Language,
    resolve_language,
    taunt,
)

LANGUAGES: tuple[Language, ...] = ("en", "ko")


def _clear_lang_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for env_var in ("TODOY_LANG", "LANG", "LC_ALL"):
        monkeypatch.delenv(env_var, raising=False)


# --- resolve_language precedence ---------------------------------------


def test_resolve_language_defaults_to_en_when_nothing_set(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_lang_env(monkeypatch)

    assert resolve_language() == "en"


def test_resolve_language_explicit_arg_wins_over_everything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_lang_env(monkeypatch)
    monkeypatch.setenv("TODOY_LANG", "ko")
    monkeypatch.setenv("LANG", "ko_KR.UTF-8")

    assert resolve_language("en") == "en"


def test_resolve_language_explicit_ko_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_lang_env(monkeypatch)
    monkeypatch.setenv("TODOY_LANG", "en")
    monkeypatch.setenv("LANG", "en_US.UTF-8")

    assert resolve_language("ko") == "ko"


def test_resolve_language_todoy_lang_env_wins_over_lang(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_lang_env(monkeypatch)
    monkeypatch.setenv("TODOY_LANG", "ko")
    monkeypatch.setenv("LANG", "en_US.UTF-8")

    assert resolve_language() == "ko"


def test_resolve_language_invalid_todoy_lang_falls_through_to_lang(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_lang_env(monkeypatch)
    monkeypatch.setenv("TODOY_LANG", "fr")
    monkeypatch.setenv("LANG", "ko_KR.UTF-8")

    assert resolve_language() == "ko"


def test_resolve_language_lang_ko_prefix_selects_ko(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_lang_env(monkeypatch)
    monkeypatch.setenv("LANG", "ko_KR.UTF-8")

    assert resolve_language() == "ko"


def test_resolve_language_lc_all_ko_prefix_selects_ko(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_lang_env(monkeypatch)
    monkeypatch.setenv("LC_ALL", "ko_KR.UTF-8")

    assert resolve_language() == "ko"


def test_resolve_language_non_ko_lang_falls_back_to_en(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_lang_env(monkeypatch)
    monkeypatch.setenv("LANG", "en_US.UTF-8")

    assert resolve_language() == "en"


# --- taunt determinism ---------------------------------------------------


@pytest.mark.parametrize("language", LANGUAGES)
def test_taunt_is_deterministic_with_same_seed(language: Language) -> None:
    first = taunt(3, language, rng=random.Random(42))
    second = taunt(3, language, rng=random.Random(42))

    assert first == second


@pytest.mark.parametrize("language", LANGUAGES)
def test_taunt_seeded_rng_can_pick_different_lines(language: Language) -> None:
    results = {taunt(3, language, rng=random.Random(seed)) for seed in range(20)}

    assert len(results) > 1


# --- pool selection by count ---------------------------------------------


@pytest.mark.parametrize("language", LANGUAGES)
def test_taunt_count_zero_uses_congrats_pool(language: Language) -> None:
    for seed in range(20):
        result = taunt(0, language, rng=random.Random(seed))
        assert any(line.format(count=0) == result for line in _CONGRATS_LINES[language])


@pytest.mark.parametrize("language", LANGUAGES)
def test_taunt_count_at_least_one_uses_taunt_pool(language: Language) -> None:
    for seed in range(20):
        result = taunt(5, language, rng=random.Random(seed))
        assert any(line.format(count=5) == result for line in _TAUNT_LINES[language])


# --- message pack shape ---------------------------------------------------


@pytest.mark.parametrize("language", LANGUAGES)
def test_taunt_pool_has_at_least_five_lines(language: Language) -> None:
    assert len(_TAUNT_LINES[language]) >= 5


@pytest.mark.parametrize("language", LANGUAGES)
def test_congrats_pool_has_at_least_three_lines(language: Language) -> None:
    assert len(_CONGRATS_LINES[language]) >= 3


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_taunt_line_formats_without_keyerror(language: Language) -> None:
    for line in _TAUNT_LINES[language]:
        line.format(count=7)


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_congrats_line_formats_without_keyerror(language: Language) -> None:
    for line in _CONGRATS_LINES[language]:
        line.format(count=0)


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_taunt_line_mentions_count_placeholder(language: Language) -> None:
    for line in _TAUNT_LINES[language]:
        assert "{count}" in line


# --- count=1 plural-agreement regression ----------------------------------


def test_taunt_count_one_en_has_no_plural_mismatch() -> None:
    """Regression: with count=1, English lines must not read "1 things"/"1 todos"

    (hardcoded plural noun/verb agreement bug -- see coordinator note).
    """
    for seed in range(50):
        line = taunt(1, "en", rng=random.Random(seed))
        assert not re.search(r"\b1 (things|todos)\b", line), line


def test_every_taunt_line_is_plural_safe_at_count_one() -> None:
    """Every English taunt line, individually formatted with count=1, must be
    free of the "1 things"/"1 todos" mismatch -- not just whichever lines a
    seeded rng happens to draw.
    """
    for line in _TAUNT_LINES["en"]:
        formatted = line.format(count=1)
        assert not re.search(r"\b1 (things|todos)\b", formatted), formatted


def test_taunt_count_one_ko_is_unaffected() -> None:
    """Korean count expressions don't inflect for number, so count=1 should
    format cleanly for every ko taunt line (nothing to regress here, but
    verify explicitly)."""
    for line in _TAUNT_LINES["ko"]:
        formatted = line.format(count=1)
        assert "1" in formatted
