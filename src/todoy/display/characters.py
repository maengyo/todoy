"""Selectable characters for the TUI/overlay display layer."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Character:
    """A selectable character: an emoji plus an ASCII-safe fallback."""

    name: str
    emoji: str
    ascii_art: str  # single-line, pure ASCII
    sprite: str | None = None  # pixelart.py SPRITES key, if this character has one
    voice: str = "default"


CHARACTERS: dict[str, Character] = {
    "cat": Character(name="cat", emoji="🐱", ascii_art="(=^.^=)", voice="feline"),
    "dog": Character(name="dog", emoji="🐶", ascii_art="(u . u)", voice="default"),
    "ghost": Character(name="ghost", emoji="👻", ascii_art="(o_o)", voice="spooky"),
    "robot": Character(name="robot", emoji="🤖", ascii_art="[o_o]", voice="robotic"),
    "horse": Character(name="horse", emoji="🐎", ascii_art=">>=(oo)=>>", voice="default"),
    "alien": Character(name="alien", emoji="👾", ascii_art="d[o_o]b", voice="spooky"),
    "bee": Character(name="bee", emoji="🐝", ascii_art="/\\/\\(o.o)/\\/\\", voice="breezy"),
    "crab": Character(name="crab", emoji="🦀", ascii_art="(\\/)!_!(\\/)", voice="salty"),
    "dino": Character(name="dino", emoji="🦖", ascii_art="~^~(0v0)~^~", voice="default"),
    "frog": Character(name="frog", emoji="🐸", ascii_art="(o)(o):v", voice="bouncy"),
    "owl": Character(name="owl", emoji="🦉", ascii_art=",(O)(O),", voice="breezy"),
    "penguin": Character(name="penguin", emoji="🐧", ascii_art="<('-')>", voice="salty"),
    "snail": Character(name="snail", emoji="🐌", ascii_art="~~~@(o.o)", voice="default"),
    "turtle": Character(name="turtle", emoji="🐢", ascii_art="_/=(o.o)=\\_", voice="salty"),
    "unicorn": Character(name="unicorn", emoji="🦄", ascii_art="*>>=(^.^)=>>*", voice="default"),
    "fox": Character(name="fox", emoji="🦊", ascii_art="-^(oo)^-", voice="default"),
    "panda": Character(name="panda", emoji="🐼", ascii_art="@(o.o)@", voice="default"),
    "chick": Character(name="chick", emoji="🐥", ascii_art="(^,,^)", voice="breezy"),
    "rabbit": Character(name="rabbit", emoji="🐰", ascii_art="V(o.o)V", voice="bouncy"),
    "hamster": Character(name="hamster", emoji="🐹", ascii_art="(o'v'o)", voice="default"),
    "duck": Character(name="duck", emoji="🦆", ascii_art="(o.o)=>", voice="breezy"),
    "whale": Character(name="whale", emoji="🐳", ascii_art="(o.o)=8", voice="salty"),
    "octopus": Character(name="octopus", emoji="🐙", ascii_art="~~(o.o)~~", voice="salty"),
    "butterfly": Character(name="butterfly", emoji="🦋", ascii_art="><(^.^)><", voice="breezy"),
    "dragon": Character(name="dragon", emoji="🐉", ascii_art="<(^==^)>", voice="breezy"),
    "blocky": Character(
        name="blocky",
        emoji="🟫",
        ascii_art="[#-#]",
        sprite="blocky",
        voice="gamer",
    ),
    "slime": Character(
        name="slime",
        emoji="🟩",
        ascii_art="(o_o)~",
        sprite="slime",
        voice="bouncy",
    ),
    "knight": Character(
        name="knight",
        emoji="🛡️",
        ascii_art="[o=|=o]",
        sprite="knight",
        voice="knightly",
    ),
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
