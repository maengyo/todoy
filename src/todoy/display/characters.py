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
