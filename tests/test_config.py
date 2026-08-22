from __future__ import annotations

import re
import sys
import tomllib
import types
from pathlib import Path

import pytest

from todoy.config import (
    DEFAULT_INTERVAL_MINUTES,
    DEFAULT_MESSAGE_STYLE,
    DEFAULT_MOVEMENT,
    Config,
    build_sources,
    config_path,
    load_config,
    save_config,
)
from todoy.models import Todo
from todoy.sources.base import Source
from todoy.sources.builtin import BuiltinSource


def test_load_config_returns_defaults_for_missing_file(tmp_path: Path) -> None:
    config = load_config(tmp_path / "missing" / "config.toml")

    assert config == Config()
    assert config.enabled_sources == ["builtin"]
    assert config.markdown_folder is None
    assert config.markdown_pinned == []
    assert config.reminder_interval_minutes == DEFAULT_INTERVAL_MINUTES
    assert config.character == "cat"
    assert config.character_image is None
    assert config.snooze_minutes == 5
    assert config.movement == "auto"
    assert config.bubble_effect == "pop"
    assert config.message_style == "auto"
    assert config.daily_clear is False


def test_default_movement_is_auto() -> None:
    assert DEFAULT_MOVEMENT == "auto"
    assert Config().movement == "auto"


def test_default_message_style_is_auto() -> None:
    assert DEFAULT_MESSAGE_STYLE == "auto"
    assert Config().message_style == "auto"


def test_config_path_todoy_config_file_wins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    override = tmp_path / "custom.toml"
    monkeypatch.setenv("TODOY_CONFIG_FILE", str(override))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    assert config_path() == override


def test_config_path_uses_xdg_config_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TODOY_CONFIG_FILE", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    assert config_path() == tmp_path / "xdg" / "todoy" / "config.toml"


def test_config_path_falls_back_to_home_config(
    monkeypatch: pytest.MonkeyPatch, fake_home: Path
) -> None:
    monkeypatch.delenv("TODOY_CONFIG_FILE", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    assert config_path() == fake_home / ".config" / "todoy" / "config.toml"


def test_load_config_reads_schema_and_expands_markdown_folder(
    fake_home: Path, tmp_path: Path
) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
[general]
reminder_interval_minutes = 45
daily_clear = true

[sources]
enabled = ["markdown", "builtin"]

[sources.markdown]
folder = "~/notes"
pinned_notes = ["Todo.md", "nested/Work.md"]
""".lstrip(),
        encoding="utf-8",
    )

    assert load_config(path) == Config(
        enabled_sources=["markdown", "builtin"],
        markdown_folder=fake_home / "notes",
        markdown_pinned=["Todo.md", "nested/Work.md"],
        reminder_interval_minutes=45,
        daily_clear=True,
    )


def test_load_config_reads_display_schema_and_expands_image_path(
    fake_home: Path, tmp_path: Path
) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
[display]
character = "robot"
character_image = "~/robot.png"
snooze_minutes = 9
message_style = "flag"
""".lstrip(),
        encoding="utf-8",
    )

    assert load_config(path) == Config(
        character="robot",
        character_image=fake_home / "robot.png",
        snooze_minutes=9,
        message_style="flag",
    )


def test_load_config_uses_animation_defaults_for_old_display_configs(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
[display]
character = "robot"
""".lstrip(),
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.character == "robot"
    assert config.movement == "auto"
    assert config.bubble_effect == "pop"
    assert config.message_style == "auto"


def test_load_config_preserves_explicit_walk_movement(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
[display]
movement = "walk"
""".lstrip(),
        encoding="utf-8",
    )

    assert load_config(path).movement == "walk"


def test_load_config_treats_empty_display_image_as_none(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
[display]
character_image = ""
""".lstrip(),
        encoding="utf-8",
    )

    assert load_config(path).character_image is None


def test_load_config_wraps_corrupt_toml_with_path(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[general\n", encoding="utf-8")

    with pytest.raises(ValueError, match=f"Corrupt config file at {re.escape(str(path))}:"):
        load_config(path)


@pytest.mark.parametrize(
    "body",
    [
        """
[general]
reminder_interval_minutes = "x"
""",
        """
[general]
daily_clear = "yes"
""",
        """
[general]
daily_clear = 1
""",
        """
[sources]
enabled = "builtin"
""",
        """
[sources.markdown]
folder = 123
""",
        """
[sources.markdown]
pinned_notes = ["Todo.md", 123]
""",
        """
display = "not-a-table"
""",
        """
[display]
character = 123
""",
        """
[display]
character_image = 123
""",
        """
[display]
snooze_minutes = "soon"
""",
        """
[display]
movement = 123
""",
        """
[display]
bubble_effect = false
""",
        """
[display]
message_style = ["flag"]
""",
    ],
)
def test_load_config_wraps_wrong_types_with_path(tmp_path: Path, body: str) -> None:
    path = tmp_path / "config.toml"
    path.write_text(body.lstrip(), encoding="utf-8")

    with pytest.raises(ValueError, match=f"Corrupt config file at {re.escape(str(path))}:"):
        load_config(path)


def test_save_config_creates_parent_dirs_and_round_trips_escaped_strings(
    tmp_path: Path,
) -> None:
    config = Config(
        enabled_sources=["builtin", "markdown"],
        markdown_folder=Path('C:\\Users\\me\\Notes "daily"'),
        markdown_pinned=['Todo "now".md', "nested\\Inbox.md"],
        reminder_interval_minutes=15,
    )
    path = tmp_path / "nested" / "config.toml"

    assert save_config(config, path) == path
    assert load_config(path) == config


def test_save_config_round_trips_del_control_character(tmp_path: Path) -> None:
    config = Config(
        enabled_sources=["builtin", "markdown"],
        markdown_folder=Path("notes\x7ftail"),
        markdown_pinned=["Pinned.md"],
    )
    path = tmp_path / "config.toml"

    save_config(config, path)

    assert load_config(path) == config


def test_save_config_round_trips_display_settings(tmp_path: Path) -> None:
    config = Config(
        character="robot",
        character_image=tmp_path / "robot.png",
        snooze_minutes=12,
        movement="dash",
        bubble_effect="shake",
        message_style="flag",
    )
    path = tmp_path / "config.toml"

    save_config(config, path)

    text = path.read_text(encoding="utf-8")
    assert "[display]" in text
    assert 'character = "robot"' in text
    assert tomllib.loads(text)["display"]["character_image"] == str(tmp_path / "robot.png")
    assert "snooze_minutes = 12" in text
    assert 'movement = "dash"' in text
    assert 'bubble_effect = "shake"' in text
    assert 'message_style = "flag"' in text
    assert load_config(path) == config


def test_save_config_round_trips_animation_display_settings(tmp_path: Path) -> None:
    config = Config(movement="float", bubble_effect="slide", message_style="flag")
    path = tmp_path / "config.toml"

    save_config(config, path)

    text = path.read_text(encoding="utf-8")
    assert "[display]" in text
    assert 'movement = "float"' in text
    assert 'bubble_effect = "slide"' in text
    assert 'message_style = "flag"' in text
    assert load_config(path) == config


def test_save_config_round_trips_daily_clear_when_true(tmp_path: Path) -> None:
    config = Config(daily_clear=True)
    path = tmp_path / "config.toml"

    save_config(config, path)

    text = path.read_text(encoding="utf-8")
    assert "[general]" in text
    assert "daily_clear = true" in text
    assert load_config(path) == config


def test_save_config_omits_default_daily_clear(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"

    save_config(Config(), path)

    assert "daily_clear" not in path.read_text(encoding="utf-8")


def test_save_config_omits_auto_movement_when_effective_default(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"

    save_config(Config(character="robot", movement="auto"), path)

    text = path.read_text(encoding="utf-8")
    assert "[display]" in text
    assert "movement" not in text
    assert load_config(path) == Config(character="robot")


def test_save_config_round_trips_message_style_default_and_explicit_values(
    tmp_path: Path,
) -> None:
    auto_path = tmp_path / "auto.toml"

    save_config(Config(character="robot", message_style="auto"), auto_path)

    auto_text = auto_path.read_text(encoding="utf-8")
    assert "[display]" in auto_text
    assert "message_style" not in auto_text
    assert load_config(auto_path) == Config(character="robot")

    for style in ("bubble", "flag"):
        path = tmp_path / f"{style}.toml"
        config = Config(character="robot", message_style=style)

        save_config(config, path)

        text = path.read_text(encoding="utf-8")
        assert f'message_style = "{style}"' in text
        assert load_config(path) == config


def test_save_config_omits_default_animation_keys_from_nondefault_display_table(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.toml"

    save_config(Config(character="robot"), path)

    text = path.read_text(encoding="utf-8")
    assert "[display]" in text
    assert 'character = "robot"' in text
    assert "movement" not in text
    assert "bubble_effect" not in text
    assert "message_style" not in text
    assert load_config(path) == Config(character="robot")


def test_save_config_omits_markdown_table_when_markdown_is_not_enabled(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"

    save_config(Config(), path)

    assert "[sources.markdown]" not in path.read_text(encoding="utf-8")


def test_save_config_omits_display_table_when_display_settings_are_default(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.toml"

    save_config(Config(), path)

    assert "[display]" not in path.read_text(encoding="utf-8")


def test_build_sources_builds_builtin_without_importing_markdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(sys.modules, "todoy.sources.markdown", raising=False)

    sources = build_sources(Config(enabled_sources=["builtin"]))

    assert len(sources) == 1
    assert isinstance(sources[0], BuiltinSource)
    assert sources[0].name == "builtin"
    assert "todoy.sources.markdown" not in sys.modules


def test_build_sources_orders_builtin_before_markdown_with_lazy_import(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class FakeMarkdownSource(Source):
        name = "markdown"

        def __init__(self, folder: Path, pinned_notes: list[str] | None = None) -> None:
            self.folder = folder
            self.pinned_notes = pinned_notes

        def get_todos(self) -> list[Todo]:
            return []

    fake_module = types.ModuleType("todoy.sources.markdown")
    fake_module.MarkdownSource = FakeMarkdownSource
    monkeypatch.setitem(sys.modules, "todoy.sources.markdown", fake_module)

    config = Config(
        enabled_sources=["markdown", "builtin"],
        markdown_folder=tmp_path / "notes",
        markdown_pinned=["Todo.md"],
    )

    sources = build_sources(config)

    assert [source.name for source in sources] == ["builtin", "markdown"]
    assert isinstance(sources[0], BuiltinSource)
    assert isinstance(sources[1], FakeMarkdownSource)
    assert sources[1].folder == tmp_path / "notes"
    assert sources[1].pinned_notes == ["Todo.md"]


def test_build_sources_rejects_unknown_source_name() -> None:
    with pytest.raises(ValueError, match="Unknown source name: other"):
        build_sources(Config(enabled_sources=["builtin", "other"]))


def test_build_sources_rejects_markdown_without_folder() -> None:
    with pytest.raises(
        ValueError,
        match="^markdown source enabled but no folder configured$",
    ):
        build_sources(Config(enabled_sources=["markdown"]))
