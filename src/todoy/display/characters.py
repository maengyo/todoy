"""Selectable characters for the TUI/overlay display layer."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Character:
    """A selectable character: an emoji plus an ASCII-safe fallback."""

    name: str
    emoji: str
    ascii_art: str  # single-line, pure ASCII


CHARACTERS: dict[str, Character] = {
    "cat": Character(name="cat", emoji="🐱", ascii_art="(=^.^=)"),
    "dog": Character(name="dog", emoji="🐶", ascii_art="(u . u)"),
    "ghost": Character(name="ghost", emoji="👻", ascii_art="(o_o)"),
    "robot": Character(name="robot", emoji="🤖", ascii_art="[o_o]"),
    "horse": Character(name="horse", emoji="🐎", ascii_art=">>=(oo)=>>"),
    "alien": Character(name="alien", emoji="👾", ascii_art="d[o_o]b"),
    "bee": Character(name="bee", emoji="🐝", ascii_art="/\\/\\(o.o)/\\/\\"),
    "crab": Character(name="crab", emoji="🦀", ascii_art="(\\/)!_!(\\/)"),
    "dino": Character(name="dino", emoji="🦖", ascii_art="~^~(0v0)~^~"),
    "frog": Character(name="frog", emoji="🐸", ascii_art="(o)(o):v"),
    "owl": Character(name="owl", emoji="🦉", ascii_art=",(O)(O),"),
    "penguin": Character(name="penguin", emoji="🐧", ascii_art="<('-')>"),
    "snail": Character(name="snail", emoji="🐌", ascii_art="~~~@(o.o)"),
    "turtle": Character(name="turtle", emoji="🐢", ascii_art="_/=(o.o)=\\_"),
    "unicorn": Character(name="unicorn", emoji="🦄", ascii_art="*>>=(^.^)=>>*"),
}

_DEFAULT_CHARACTER_NAME = "cat"


def get_character(name: str | None = None) -> Character:
    """Look up a character by name; `None` returns the default ("cat")."""
    lookup_name = name if name is not None else _DEFAULT_CHARACTER_NAME
    try:
        return CHARACTERS[lookup_name]
    except KeyError:
        available = ", ".join(CHARACTERS)
        msg = f"Unknown character: {lookup_name}. Available: {available}"
        raise ValueError(msg) from None
