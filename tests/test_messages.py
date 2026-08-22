from __future__ import annotations

import random
import re

import pytest

from todoy.display.messages import (
    _VOICES,
    Language,
    resolve_language,
    taunt,
)

LANGUAGES: tuple[Language, ...] = ("en", "ko")
VOICE_NAMES = tuple(_VOICES)
NON_DEFAULT_VOICES = tuple(voice for voice in VOICE_NAMES if voice != "default")
MESSAGE_KEYS = ("taunt", "congrats")
MAX_LINE_DISPLAY_WIDTH = 44


def _display_width(text: str) -> int:
    import unicodedata

    return sum(2 if unicodedata.east_asian_width(ch) in {"W", "F"} else 1 for ch in text)


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


@pytest.mark.parametrize("voice", VOICE_NAMES)
@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("count", [0, 1, 3])
def test_taunt_is_deterministic_with_same_seed(voice: str, language: Language, count: int) -> None:
    first = taunt(count, language, rng=random.Random(42), voice=voice)
    second = taunt(count, language, rng=random.Random(42), voice=voice)

    assert first == second


@pytest.mark.parametrize("voice", VOICE_NAMES)
@pytest.mark.parametrize("language", LANGUAGES)
def test_taunt_seeded_rng_can_pick_different_lines(voice: str, language: Language) -> None:
    results = {taunt(3, language, rng=random.Random(seed), voice=voice) for seed in range(20)}

    assert len(results) > 1


# --- pool selection by count ---------------------------------------------


@pytest.mark.parametrize("voice", VOICE_NAMES)
@pytest.mark.parametrize("language", LANGUAGES)
def test_taunt_count_zero_uses_congrats_pool(voice: str, language: Language) -> None:
    for seed in range(20):
        result = taunt(0, language, rng=random.Random(seed), voice=voice)
        assert any(line.format(count=0) == result for line in _VOICES[voice][language]["congrats"])


@pytest.mark.parametrize("voice", VOICE_NAMES)
@pytest.mark.parametrize("language", LANGUAGES)
def test_taunt_count_at_least_one_uses_taunt_pool(voice: str, language: Language) -> None:
    for seed in range(20):
        result = taunt(5, language, rng=random.Random(seed), voice=voice)
        assert any(line.format(count=5) == result for line in _VOICES[voice][language]["taunt"])


# --- message pack shape ---------------------------------------------------


def test_voice_catalog_has_the_fixed_contract_set() -> None:
    assert set(_VOICES) == {
        "knightly",
        "robotic",
        "spooky",
        "bouncy",
        "salty",
        "breezy",
        "feline",
        "gamer",
        "default",
    }


@pytest.mark.parametrize("voice", NON_DEFAULT_VOICES)
@pytest.mark.parametrize("language", LANGUAGES)
def test_non_default_taunt_pool_has_at_least_four_lines(voice: str, language: Language) -> None:
    assert len(_VOICES[voice][language]["taunt"]) >= 4


@pytest.mark.parametrize("voice", NON_DEFAULT_VOICES)
@pytest.mark.parametrize("language", LANGUAGES)
def test_non_default_congrats_pool_has_at_least_three_lines(voice: str, language: Language) -> None:
    assert len(_VOICES[voice][language]["congrats"]) >= 3


@pytest.mark.parametrize("voice", VOICE_NAMES)
@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("message_key", MESSAGE_KEYS)
def test_every_line_formats_without_keyerror(
    voice: str, language: Language, message_key: str
) -> None:
    for line in _VOICES[voice][language][message_key]:
        line.format(count=7)


@pytest.mark.parametrize("voice", VOICE_NAMES)
@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("message_key", MESSAGE_KEYS)
def test_every_line_fits_the_bubble_width(voice: str, language: Language, message_key: str) -> None:
    for line in _VOICES[voice][language][message_key]:
        formatted = line.format(count=120)
        assert _display_width(formatted) <= MAX_LINE_DISPLAY_WIDTH, formatted


# --- fallback behavior -----------------------------------------------------


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("count", [0, 3])
def test_unknown_voice_falls_back_to_default_pool(language: Language, count: int) -> None:
    unknown = taunt(count, language, rng=random.Random(7), voice="not-a-voice")
    default = taunt(count, language, rng=random.Random(7), voice="default")

    assert unknown == default


def test_missing_voice_language_falls_back_to_default_language_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(_VOICES, "broken", {"en": {"taunt": ["broken {count}"]}})

    result = taunt(3, "ko", rng=random.Random(0), voice="broken")

    assert any(line.format(count=3) == result for line in _VOICES["default"]["ko"]["taunt"])


def test_missing_voice_message_key_falls_back_to_default_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(_VOICES, "broken", {"en": {"taunt": ["broken {count}"]}, "ko": {}})

    result = taunt(0, "en", rng=random.Random(0), voice="broken")

    assert any(line.format(count=0) == result for line in _VOICES["default"]["en"]["congrats"])


# --- count=1 plural-agreement regression ----------------------------------


def test_taunt_count_one_en_has_no_plural_mismatch() -> None:
    """Regression: with count=1, English lines must not read "1 things"/"1 todos"

    (hardcoded plural noun/verb agreement bug -- see coordinator note).
    """
    for voice in VOICE_NAMES:
        for count in (1, 2):
            for seed in range(50):
                line = taunt(count, "en", rng=random.Random(seed), voice=voice)
                assert not re.search(r"\b1 (things|todos|tasks|items)\b", line), line


def test_every_taunt_line_is_plural_safe_at_count_one() -> None:
    """Every English taunt line, individually formatted with count=1, must be
    free of the "1 things"/"1 todos" mismatch -- not just whichever lines a
    seeded rng happens to draw.
    """
    for voice in VOICE_NAMES:
        for line in _VOICES[voice]["en"]["taunt"]:
            formatted = line.format(count=1)
            assert not re.search(r"\b1 (things|todos|tasks|items)\b", formatted), formatted


def test_taunt_count_one_ko_is_unaffected() -> None:
    """Korean count expressions don't inflect for number, so count=1 should
    format cleanly for every ko taunt line (nothing to regress here, but
    verify explicitly)."""
    for voice in VOICE_NAMES:
        for line in _VOICES[voice]["ko"]["taunt"]:
            line.format(count=1)
