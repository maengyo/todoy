"""Configuration loading, saving, and source construction."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from todoy.sources.base import Source
from todoy.sources.builtin import BuiltinSource

DEFAULT_INTERVAL_MINUTES = 30
DEFAULT_CHARACTER = "cat"
DEFAULT_SNOOZE_MINUTES = 5
DEFAULT_MOVEMENT = "walk"
DEFAULT_BUBBLE_EFFECT = "pop"
DEFAULT_MESSAGE_STYLE = "bubble"
DEFAULT_DAILY_CLEAR = False


@dataclass
class Config:
    enabled_sources: list[str] = field(default_factory=lambda: ["builtin"])
    markdown_folder: Path | None = None
    markdown_pinned: list[str] = field(default_factory=list)
    reminder_interval_minutes: int = DEFAULT_INTERVAL_MINUTES
    character: str = DEFAULT_CHARACTER
    character_image: Path | None = None
    snooze_minutes: int = DEFAULT_SNOOZE_MINUTES
    movement: str = DEFAULT_MOVEMENT
    bubble_effect: str = DEFAULT_BUBBLE_EFFECT
    message_style: str = DEFAULT_MESSAGE_STYLE
    daily_clear: bool = DEFAULT_DAILY_CLEAR


def config_path() -> Path:
    """Return the default todoy config path using the documented precedence."""
    env_override = os.environ.get("TODOY_CONFIG_FILE")
    if env_override:
        return Path(env_override)

    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        base = Path(xdg_config_home)
    else:
        base = Path.home() / ".config"

    return base / "todoy" / "config.toml"


def load_config(path: Path | None = None) -> Config:
    """Load config from TOML, returning defaults when the file is absent."""
    resolved_path = path if path is not None else config_path()
    if not resolved_path.exists():
        return Config()

    try:
        with resolved_path.open("rb") as f:
            data = tomllib.load(f)
        return _config_from_toml(data)
    except (tomllib.TOMLDecodeError, OSError, TypeError, ValueError) as e:
        raise ValueError(f"Corrupt config file at {resolved_path}: {e}") from e


def save_config(config: Config, path: Path | None = None) -> Path:
    """Write config as TOML, creating parent directories as needed."""
    resolved_path = path if path is not None else config_path()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path.write_text(_config_to_toml(config), encoding="utf-8")
    return resolved_path


def build_sources(config: Config) -> list[Source]:
    """Build enabled sources in the contract-defined order."""
    known_sources = {"builtin", "markdown"}
    for source_name in config.enabled_sources:
        if source_name not in known_sources:
            raise ValueError(f"Unknown source name: {source_name}")

    sources: list[Source] = []
    if "builtin" in config.enabled_sources:
        sources.append(BuiltinSource())

    if "markdown" in config.enabled_sources:
        if config.markdown_folder is None:
            raise ValueError("markdown source enabled but no folder configured")

        from todoy.sources.markdown import MarkdownSource

        sources.append(
            MarkdownSource(config.markdown_folder, pinned_notes=list(config.markdown_pinned))
        )

    return sources


def _config_from_toml(data: dict[str, Any]) -> Config:
    general = _optional_table(data, "general")
    reminder_interval_minutes = general.get(
        "reminder_interval_minutes",
        DEFAULT_INTERVAL_MINUTES,
    )
    if isinstance(reminder_interval_minutes, bool) or not isinstance(
        reminder_interval_minutes, int
    ):
        raise ValueError("general.reminder_interval_minutes must be an int")
    daily_clear = general.get("daily_clear", DEFAULT_DAILY_CLEAR)
    if not isinstance(daily_clear, bool):
        raise ValueError("general.daily_clear must be a bool")

    sources = _optional_table(data, "sources")
    enabled_sources = _string_list(sources.get("enabled", ["builtin"]), "sources.enabled")

    markdown = _optional_table(sources, "markdown")
    markdown_folder = _optional_path(markdown.get("folder"), "sources.markdown.folder")
    markdown_pinned = _string_list(
        markdown.get("pinned_notes", []),
        "sources.markdown.pinned_notes",
    )

    display = _optional_table(data, "display")
    character = _string(display.get("character", DEFAULT_CHARACTER), "display.character")
    character_image = _optional_display_image_path(
        display.get("character_image"),
        "display.character_image",
    )
    snooze_minutes = display.get("snooze_minutes", DEFAULT_SNOOZE_MINUTES)
    if isinstance(snooze_minutes, bool) or not isinstance(snooze_minutes, int):
        raise ValueError("display.snooze_minutes must be an int")
    movement = _string(display.get("movement", DEFAULT_MOVEMENT), "display.movement")
    bubble_effect = _string(
        display.get("bubble_effect", DEFAULT_BUBBLE_EFFECT),
        "display.bubble_effect",
    )
    message_style = _string(
        display.get("message_style", DEFAULT_MESSAGE_STYLE),
        "display.message_style",
    )

    return Config(
        enabled_sources=enabled_sources,
        markdown_folder=markdown_folder,
        markdown_pinned=markdown_pinned,
        reminder_interval_minutes=reminder_interval_minutes,
        character=character,
        character_image=character_image,
        snooze_minutes=snooze_minutes,
        movement=movement,
        bubble_effect=bubble_effect,
        message_style=message_style,
        daily_clear=daily_clear,
    )


def _optional_table(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be a table")
    return value


def _optional_path(value: Any, key: str) -> Path | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return Path(value).expanduser()


def _optional_display_image_path(value: Any, key: str) -> Path | None:
    if value in (None, ""):
        return None
    return _optional_path(value, key)


def _string(value: Any, key: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _string_list(value: Any, key: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list of strings")
    if not all(isinstance(item, str) for item in value):
        raise ValueError(f"{key} must be a list of strings")
    return list(value)


def _config_to_toml(config: Config) -> str:
    lines = [
        "[general]",
        f"reminder_interval_minutes = {config.reminder_interval_minutes}",
    ]
    if config.daily_clear:
        lines.append("daily_clear = true")
    lines.extend(
        [
            "",
            "[sources]",
            f"enabled = {_toml_string_array(config.enabled_sources)}",
        ]
    )

    if _should_emit_markdown_table(config):
        lines.extend(
            [
                "",
                "[sources.markdown]",
            ]
        )
        if config.markdown_folder is not None:
            lines.append(f"folder = {_toml_string(str(config.markdown_folder))}")
        lines.append(f"pinned_notes = {_toml_string_array(config.markdown_pinned)}")

    if _should_emit_display_table(config):
        lines.extend(
            [
                "",
                "[display]",
                f"character = {_toml_string(config.character)}",
                f"character_image = {_toml_string(_display_image_value(config))}",
                f"snooze_minutes = {config.snooze_minutes}",
            ]
        )
        if config.movement != DEFAULT_MOVEMENT:
            lines.append(f"movement = {_toml_string(config.movement)}")
        if config.bubble_effect != DEFAULT_BUBBLE_EFFECT:
            lines.append(f"bubble_effect = {_toml_string(config.bubble_effect)}")
        if config.message_style != DEFAULT_MESSAGE_STYLE:
            lines.append(f"message_style = {_toml_string(config.message_style)}")

    return "\n".join(lines) + "\n"


def _should_emit_markdown_table(config: Config) -> bool:
    return (
        "markdown" in config.enabled_sources
        or config.markdown_folder is not None
        or bool(config.markdown_pinned)
    )


def _should_emit_display_table(config: Config) -> bool:
    return (
        config.character != DEFAULT_CHARACTER
        or config.character_image is not None
        or config.snooze_minutes != DEFAULT_SNOOZE_MINUTES
        or config.movement != DEFAULT_MOVEMENT
        or config.bubble_effect != DEFAULT_BUBBLE_EFFECT
        or config.message_style != DEFAULT_MESSAGE_STYLE
    )


def _display_image_value(config: Config) -> str:
    if config.character_image is None:
        return ""
    return str(config.character_image)


def _toml_string_array(values: list[str]) -> str:
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"


def _toml_string(value: str) -> str:
    escaped_chars: list[str] = []
    for char in value:
        if char == "\\":
            escaped_chars.append("\\\\")
        elif char == '"':
            escaped_chars.append('\\"')
        elif char == "\b":
            escaped_chars.append("\\b")
        elif char == "\t":
            escaped_chars.append("\\t")
        elif char == "\n":
            escaped_chars.append("\\n")
        elif char == "\f":
            escaped_chars.append("\\f")
        elif char == "\r":
            escaped_chars.append("\\r")
        elif ord(char) < 0x20 or ord(char) == 0x7F:
            escaped_chars.append(f"\\u{ord(char):04x}")
        else:
            escaped_chars.append(char)
    return '"' + "".join(escaped_chars) + '"'
