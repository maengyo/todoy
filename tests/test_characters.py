from __future__ import annotations

import pytest

from todoy.display.characters import CHARACTERS, Character, get_character


def test_characters_has_at_least_four_entries() -> None:
    assert len(CHARACTERS) >= 4


def test_characters_has_at_least_fifteen_entries() -> None:
    assert len(CHARACTERS) >= 15


def test_characters_include_cat_default() -> None:
    assert "cat" in CHARACTERS


@pytest.mark.parametrize("name", list(CHARACTERS))
def test_every_character_has_nonempty_emoji(name: str) -> None:
    assert CHARACTERS[name].emoji != ""


@pytest.mark.parametrize("name", list(CHARACTERS))
def test_every_character_ascii_art_is_pure_ascii(name: str) -> None:
    ascii_art = CHARACTERS[name].ascii_art
    assert ascii_art != ""
    assert ascii_art.isascii()


@pytest.mark.parametrize("name", list(CHARACTERS))
def test_every_character_ascii_art_is_single_line(name: str) -> None:
    assert "\n" not in CHARACTERS[name].ascii_art


def test_get_character_default_returns_cat() -> None:
    assert get_character() == CHARACTERS["cat"]


def test_get_character_none_returns_cat() -> None:
    assert get_character(None) == CHARACTERS["cat"]


def test_get_character_known_name_returns_matching_character() -> None:
    assert get_character("dog") == CHARACTERS["dog"]


def test_characters_include_horse() -> None:
    assert "horse" in CHARACTERS


def test_horse_has_expected_emoji() -> None:
    assert CHARACTERS["horse"].emoji == "🐎"


NEW_CHARACTER_EMOJI = {
    "turtle": "🐢",
    "snail": "🐌",
    "penguin": "🐧",
    "frog": "🐸",
    "bee": "🐝",
    "owl": "🦉",
    "unicorn": "🦄",
    "dino": "🦖",
    "alien": "👾",
    "crab": "🦀",
}


@pytest.mark.parametrize(("name", "emoji"), list(NEW_CHARACTER_EMOJI.items()))
def test_new_character_is_registered_with_expected_emoji(name: str, emoji: str) -> None:
    assert name in CHARACTERS
    assert CHARACTERS[name].emoji == emoji


@pytest.mark.parametrize("name", list(NEW_CHARACTER_EMOJI))
def test_new_character_is_resolvable_via_get_character(name: str) -> None:
    character = get_character(name)
    assert character.name == name
    assert character.emoji == NEW_CHARACTER_EMOJI[name]


def test_all_expected_names_present() -> None:
    expected = {"cat", "dog", "ghost", "robot", "horse", *NEW_CHARACTER_EMOJI}
    assert expected == set(CHARACTERS)


def test_get_character_returns_character_dataclass_instance() -> None:
    assert isinstance(get_character("cat"), Character)


def test_get_character_unknown_name_raises_value_error_listing_available() -> None:
    with pytest.raises(ValueError, match=r"Unknown character: dragon\. Available: .*cat.*") as exc:
        get_character("dragon")

    message = str(exc.value)
    for name in CHARACTERS:
        assert name in message
