from __future__ import annotations

import random
import sys
import types
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path

import pytest

from todoy.cli import main
from todoy.config import DEFAULT_INTERVAL_MINUTES, Config, load_config, save_config
from todoy.display import sanitize_text
from todoy.models import Todo
from todoy.sources.builtin import BuiltinSource


@pytest.fixture
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "config.toml"
    monkeypatch.setenv("TODOY_CONFIG_FILE", str(path))
    return path


@pytest.fixture
def data_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config_file: Path) -> Iterator[Path]:
    path = tmp_path / "todos.json"
    monkeypatch.setenv("TODOY_DATA_FILE", str(path))
    yield path


class FakeInput:
    def __init__(self, answers: list[str]) -> None:
        self._answers = answers
        self._index = 0
        self.prompts: list[str] = []

    def __call__(self, prompt: str = "") -> str:
        self.prompts.append(prompt)
        if self._index >= len(self._answers):
            raise AssertionError(f"Unexpected prompt: {prompt}")
        answer = self._answers[self._index]
        self._index += 1
        return answer


@dataclass(frozen=True)
class FakeCharacter:
    name: str
    emoji: str
    ascii_art: str


@dataclass(frozen=True)
class FakeOverlayOptions:
    character: FakeCharacter
    character_image: Path | None
    language: str
    test_seconds: float | None
    movement: str
    bubble_effect: str
    message_style: str


class FakeReminderScheduler:
    def __init__(self, interval_minutes: int, snooze_minutes: int) -> None:
        self.interval_minutes = interval_minutes
        self.snooze_minutes = snooze_minutes


@dataclass
class FakeOverlayState:
    exit_code: int = 0
    backend_calls: int = 0
    options: FakeOverlayOptions | None = None
    scheduler: FakeReminderScheduler | None = None
    reminder_text: str | None = None


class FakeOverlayBackend:
    def __init__(self, state: FakeOverlayState) -> None:
        self._state = state

    def run(
        self,
        options: FakeOverlayOptions,
        scheduler: FakeReminderScheduler,
        get_reminder_text: Callable[[], str],
    ) -> int:
        self._state.options = options
        self._state.scheduler = scheduler
        self._state.reminder_text = get_reminder_text()
        return self._state.exit_code


def install_fake_animation_module(monkeypatch: pytest.MonkeyPatch) -> None:
    animations = types.ModuleType("todoy.display.overlay.animations")
    movements = ("walk", "hop", "float", "dash", "gallop", "still")
    bubble_effects = ("pop", "fade", "slide", "shake", "none")
    message_styles = ("bubble", "flag")

    def validate_movement(name: str) -> str:
        if name not in movements:
            available = ", ".join(movements)
            msg = f"Unknown movement: {name}. Available: {available}"
            raise ValueError(msg)
        return name

    def validate_bubble_effect(name: str) -> str:
        if name not in bubble_effects:
            available = ", ".join(bubble_effects)
            msg = f"Unknown bubble effect: {name}. Available: {available}"
            raise ValueError(msg)
        return name

    def validate_message_style(name: str) -> str:
        if name not in message_styles:
            available = ", ".join(message_styles)
            msg = f"Unknown message style: {name}. Available: {available}"
            raise ValueError(msg)
        return name

    animations.MOVEMENTS = movements
    animations.BUBBLE_EFFECTS = bubble_effects
    animations.MESSAGE_STYLES = message_styles
    animations.validate_movement = validate_movement
    animations.validate_bubble_effect = validate_bubble_effect
    animations.validate_message_style = validate_message_style
    monkeypatch.setitem(sys.modules, "todoy.display.overlay.animations", animations)


def install_fake_display_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    messages = types.ModuleType("todoy.display.messages")

    def resolve_language(lang: str | None = None) -> str:
        return lang if lang is not None else "en"

    def taunt(count: int, language: str, rng: random.Random | None = None) -> str:
        del rng
        return f"{language}: {count} open"

    messages.resolve_language = resolve_language
    messages.taunt = taunt
    monkeypatch.setitem(sys.modules, "todoy.display.messages", messages)

    characters = types.ModuleType("todoy.display.characters")
    available = {
        "cat": FakeCharacter(name="cat", emoji="🐱", ascii_art="(=^.^=)"),
        "robot": FakeCharacter(name="robot", emoji="🤖", ascii_art="[robot]"),
    }

    def get_character(name: str | None = None) -> FakeCharacter:
        resolved_name = name if name is not None else "cat"
        try:
            return available[resolved_name]
        except KeyError as exc:
            available_names = ", ".join(available)
            msg = f"Unknown character: {resolved_name}. Available: {available_names}"
            raise ValueError(msg) from exc

    characters.get_character = get_character
    monkeypatch.setitem(sys.modules, "todoy.display.characters", characters)
    monkeypatch.setattr("todoy.cli.get_character", get_character)
    monkeypatch.setattr("todoy.cli.resolve_language", resolve_language)


def install_fake_overlay_modules(
    monkeypatch: pytest.MonkeyPatch,
    *,
    backend_error: RuntimeError | None = None,
    exit_code: int = 0,
) -> FakeOverlayState:
    state = FakeOverlayState(exit_code=exit_code)

    core = types.ModuleType("todoy.display.overlay.core")

    def build_reminder_text(
        todos: list[Todo],
        language: str,
        rng: random.Random | None = None,
    ) -> str:
        del rng
        texts = ", ".join(sanitize_text(todo.text) for todo in todos)
        return f"{language}: {texts or 'empty'}"

    core.ReminderScheduler = FakeReminderScheduler
    core.build_reminder_text = build_reminder_text
    monkeypatch.setitem(sys.modules, "todoy.display.overlay.core", core)

    base = types.ModuleType("todoy.display.overlay.base")

    def create_backend() -> FakeOverlayBackend:
        state.backend_calls += 1
        if backend_error is not None:
            raise backend_error
        return FakeOverlayBackend(state)

    base.OverlayOptions = FakeOverlayOptions
    base.create_backend = create_backend
    monkeypatch.setitem(sys.modules, "todoy.display.overlay.base", base)

    return state


def test_init_wizard_builtin_only_writes_default_config(
    config_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_input = FakeInput(["n", "", "", ""])
    monkeypatch.setattr("builtins.input", fake_input)

    exit_code = main(["init"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert fake_input.prompts == [
        "Enable markdown source? [y/N]",
        "Reminder interval in minutes [30]:",
        "Character [cat/dog/ghost/robot] (default cat):",
        "Custom character image path (optional):",
    ]
    assert captured.out == f"Config written to {config_file}\n"
    assert captured.err == ""
    assert load_config(config_file) == Config()


def test_init_wizard_with_markdown_writes_folder_and_pinned_notes(
    tmp_path: Path,
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    notes_folder = tmp_path / "notes"
    notes_folder.mkdir()
    fake_input = FakeInput(
        [
            "y",
            str(notes_folder),
            "Pinned.md, nested/Now.md",
            "45",
            "",
            "",
        ]
    )
    monkeypatch.setattr("builtins.input", fake_input)

    exit_code = main(["init"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert fake_input.prompts == [
        "Enable markdown source? [y/N]",
        "Notes folder path:",
        "Pinned notes (comma-separated, optional):",
        "Reminder interval in minutes [30]:",
        "Character [cat/dog/ghost/robot] (default cat):",
        "Custom character image path (optional):",
    ]
    assert captured.out == f"Config written to {config_file}\n"
    assert captured.err == ""
    assert load_config(config_file) == Config(
        enabled_sources=["builtin", "markdown"],
        markdown_folder=notes_folder,
        markdown_pinned=["Pinned.md", "nested/Now.md"],
        reminder_interval_minutes=45,
    )


def test_init_wizard_overwrite_no_aborts(
    config_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_file.write_text("existing config\n", encoding="utf-8")
    fake_input = FakeInput(["n"])
    monkeypatch.setattr("builtins.input", fake_input)

    exit_code = main(["init"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert fake_input.prompts == [f"Config already exists at {config_file}. Overwrite? [y/N]"]
    assert captured.out == "Aborted.\n"
    assert captured.err == ""
    assert config_file.read_text(encoding="utf-8") == "existing config\n"


def test_init_wizard_invalid_interval_reprompts_once_then_defaults(
    config_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_input = FakeInput(["n", "soon", "later", "", ""])
    monkeypatch.setattr("builtins.input", fake_input)

    exit_code = main(["init"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert fake_input.prompts == [
        "Enable markdown source? [y/N]",
        "Reminder interval in minutes [30]:",
        "Reminder interval in minutes [30]:",
        "Character [cat/dog/ghost/robot] (default cat):",
        "Custom character image path (optional):",
    ]
    assert captured.out == f"Config written to {config_file}\n"
    assert captured.err == ""
    assert load_config(config_file).reminder_interval_minutes == DEFAULT_INTERVAL_MINUTES


def test_init_wizard_writes_custom_display_settings(
    fake_home: Path,
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_input = FakeInput(["n", "15", "robot", "~/robot.png"])
    monkeypatch.setattr("builtins.input", fake_input)

    exit_code = main(["init"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert fake_input.prompts == [
        "Enable markdown source? [y/N]",
        "Reminder interval in minutes [30]:",
        "Character [cat/dog/ghost/robot] (default cat):",
        "Custom character image path (optional):",
    ]
    assert captured.out == f"Config written to {config_file}\n"
    assert captured.err == ""
    assert load_config(config_file) == Config(
        reminder_interval_minutes=15,
        character="robot",
        character_image=fake_home / "robot.png",
    )
    text = config_file.read_text(encoding="utf-8")
    assert "movement" not in text
    assert "bubble_effect" not in text
    assert "message_style" not in text


def test_init_wizard_invalid_character_reprompts_once_then_defaults(
    config_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_input = FakeInput(["n", "", "dragon", "koala", ""])
    monkeypatch.setattr("builtins.input", fake_input)

    exit_code = main(["init"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert fake_input.prompts == [
        "Enable markdown source? [y/N]",
        "Reminder interval in minutes [30]:",
        "Character [cat/dog/ghost/robot] (default cat):",
        "Character [cat/dog/ghost/robot] (default cat):",
        "Custom character image path (optional):",
    ]
    assert captured.out == f"Config written to {config_file}\n"
    assert captured.err == ""
    assert load_config(config_file).character == "cat"


def test_add_prints_contract_message_and_persists(
    data_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["add", "buy milk"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "Added #1: buy milk\n"
    assert captured.err == ""
    assert BuiltinSource().list_todos(include_done=True)[0].text == "buy milk"
    assert data_file.exists()


def test_done_prints_contract_message(data_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["add", "finish report"])
    capsys.readouterr()

    exit_code = main(["done", "1"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "Done #1: finish report\n"
    assert captured.err == ""
    assert BuiltinSource().list_todos() == []
    assert data_file.exists()


def test_done_unknown_id_prints_stderr_and_exits_1(
    data_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["done", "999"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == "No todo with id 999\n"
    assert not data_file.exists()


def test_list_empty_prints_contract_message(
    data_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["list"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "No todos for today 🎉\n"
    assert captured.err == ""
    assert not data_file.exists()


def test_list_corrupt_data_file_prints_stderr_and_exits_1(
    data_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_file.write_text("not json", encoding="utf-8")

    exit_code = main(["list"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert f"Corrupt todos file at {data_file}:" in captured.err
    assert "Traceback" not in captured.err


def test_list_prints_open_todos_in_order(
    data_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["add", "first"])
    main(["add", "second"])
    capsys.readouterr()

    exit_code = main(["list"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "  1. first\n  2. second\n"
    assert captured.err == ""
    assert data_file.exists()


def test_list_all_marks_done_items(data_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["add", "open task"])
    main(["add", "completed task"])
    main(["done", "2"])
    capsys.readouterr()

    exit_code = main(["list", "--all"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "  1. open task\n  2. [x] completed task\n"
    assert captured.err == ""
    assert data_file.exists()


def test_list_uses_missing_config_as_builtin_default(
    data_file: Path, config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["add", "default config task"])
    capsys.readouterr()

    exit_code = main(["list"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "  1. default config task\n"
    assert captured.err == ""
    assert data_file.exists()
    assert not config_file.exists()


def test_list_renders_markdown_source_after_builtin_block(
    tmp_path: Path,
    data_file: Path,
    config_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    notes_folder = tmp_path / "notes"
    notes_folder.mkdir()
    (notes_folder / "Pinned.md").write_text(
        "- markdown task\x1b]0;pwned\x07\n- [x] done markdown\n",
        encoding="utf-8",
    )
    save_config(
        Config(
            enabled_sources=["builtin", "markdown"],
            markdown_folder=notes_folder,
            markdown_pinned=["Pinned.md"],
        ),
        config_file,
    )
    main(["add", "builtin task"])
    capsys.readouterr()

    exit_code = main(["list"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "  1. builtin task\n  - markdown task]0;pwned\n"
    assert captured.err == ""
    assert data_file.exists()


def test_list_config_error_prints_stderr_and_exits_1(
    data_file: Path, config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_file.write_text('[sources]\nenabled = ["not-a-source"]\n', encoding="utf-8")

    exit_code = main(["list"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == "Unknown source name: not-a-source\n"
    assert "Traceback" not in captured.err
    assert not data_file.exists()


def test_sanitize_todo_text_strips_control_characters() -> None:
    assert sanitize_text("evil\x1b]0;pwned\x07") == "evil]0;pwned"


def test_todo_text_is_sanitized_in_add_list_and_done_output(
    data_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    hostile_text = "evil\x1b]0;pwned\x07"
    safe_text = "evil]0;pwned"

    add_exit_code = main(["add", hostile_text])
    add_output = capsys.readouterr()
    list_exit_code = main(["list"])
    list_output = capsys.readouterr()
    done_exit_code = main(["done", "1"])
    done_output = capsys.readouterr()

    assert add_exit_code == 0
    assert add_output.out == f"Added #1: {safe_text}\n"
    assert add_output.err == ""
    assert list_exit_code == 0
    assert list_output.out == f"  1. {safe_text}\n"
    assert list_output.err == ""
    assert done_exit_code == 0
    assert done_output.out == f"Done #1: {safe_text}\n"
    assert done_output.err == ""
    assert data_file.exists()


def test_tui_prints_aggregated_builtin_and_markdown_todos(
    tmp_path: Path,
    data_file: Path,
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fake_display_modules(monkeypatch)
    notes_folder = tmp_path / "notes"
    notes_folder.mkdir()
    (notes_folder / "Pinned.md").write_text("- markdown task\n", encoding="utf-8")
    save_config(
        Config(
            enabled_sources=["builtin", "markdown"],
            markdown_folder=notes_folder,
            markdown_pinned=["Pinned.md"],
        ),
        config_file,
    )
    main(["add", "builtin task"])
    capsys.readouterr()

    exit_code = main(["tui", "--character", "robot", "--lang", "ko"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "\n".join(
        [
            ".-------------------.",
            "| ko: 2 open        |",
            "| [#1] builtin task |",
            "| * markdown task   |",
            "`-------------------'",
            "  /",
            "🤖",
            "",
        ]
    )
    assert captured.err == ""
    assert data_file.exists()


def test_tui_brief_ascii_flag_forces_ascii_character(
    data_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fake_display_modules(monkeypatch)
    main(["add", "buy milk"])
    main(["add", "read docs"])
    capsys.readouterr()

    exit_code = main(["tui", "--brief", "--ascii"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "(=^.^=) 2 todos: buy milk (+1 more)\n"
    assert captured.err == ""
    assert data_file.exists()


def test_tui_unknown_character_prints_stderr_and_exits_1(
    data_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fake_display_modules(monkeypatch)

    exit_code = main(["tui", "--character", "dragon\x1b[31m"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == "Unknown character: dragon[31m. Available: cat, robot\n"
    assert "\x1b" not in captured.err
    assert "\x07" not in captured.err
    assert not data_file.exists()


def test_tui_unknown_character_with_osc_sequence_sanitizes_stderr(
    data_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["tui", "--character", "dragon\x1b]0;x\x07"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "Unknown character: dragon]0;x. Available: cat, dog, ghost, robot" in captured.err
    assert "\x1b" not in captured.err
    assert "\x07" not in captured.err
    assert not data_file.exists()


def test_tui_config_error_prints_stderr_and_exits_1(
    data_file: Path,
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fake_display_modules(monkeypatch)
    config_file.write_text('[sources]\nenabled = ["not-a-source"]\n', encoding="utf-8")

    exit_code = main(["tui"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == "Unknown source name: not-a-source\n"
    assert "Traceback" not in captured.err
    assert not data_file.exists()


def test_overlay_once_prints_reminder_text_without_backend(
    tmp_path: Path,
    data_file: Path,
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    notes_folder = tmp_path / "notes"
    notes_folder.mkdir()
    (notes_folder / "Pinned.md").write_text("- markdown task\n", encoding="utf-8")
    save_config(
        Config(
            enabled_sources=["builtin", "markdown"],
            markdown_folder=notes_folder,
            markdown_pinned=["Pinned.md"],
        ),
        config_file,
    )
    main(["add", "builtin task"])
    capsys.readouterr()
    install_fake_animation_module(monkeypatch)
    monkeypatch.delitem(sys.modules, "todoy.display.overlay.core", raising=False)
    monkeypatch.delitem(sys.modules, "todoy.display.overlay.base", raising=False)

    exit_code = main(["overlay", "--once", "--lang", "ko"])

    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert exit_code == 0
    assert len(lines) == 4
    assert lines[0]
    assert lines[1:] == ["", "[#1] builtin task", "* markdown task"]
    assert captured.err == ""
    assert (
        sys.modules["todoy.display.overlay.core"].build_reminder_text.__module__
        == "todoy.display.overlay.core"
    )
    assert "todoy.display.overlay.base" not in sys.modules
    assert data_file.exists()


def test_overlay_backend_runtime_error_prints_stderr_and_exits_1(
    data_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fake_display_modules(monkeypatch)
    install_fake_animation_module(monkeypatch)
    state = install_fake_overlay_modules(
        monkeypatch,
        backend_error=RuntimeError("todoy overlay currently supports macOS only"),
    )

    exit_code = main(["overlay"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == "todoy overlay currently supports macOS only\n"
    assert state.backend_calls == 1
    assert not data_file.exists()


def test_overlay_gui_wires_config_env_and_backend_exit_code(
    tmp_path: Path,
    data_file: Path,
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fake_display_modules(monkeypatch)
    install_fake_animation_module(monkeypatch)
    state = install_fake_overlay_modules(monkeypatch, exit_code=23)
    image_path = tmp_path / "robot.png"
    save_config(
        Config(
            reminder_interval_minutes=99,
            character="robot",
            character_image=image_path,
            snooze_minutes=8,
        ),
        config_file,
    )
    monkeypatch.setenv("TODOY_OVERLAY_TEST_SECONDS", "1.5")
    main(["add", "builtin task"])
    capsys.readouterr()

    exit_code = main(["overlay", "--interval", "7", "--lang", "ko"])

    captured = capsys.readouterr()
    assert exit_code == 23
    assert captured.out == ""
    assert captured.err == ""
    assert state.backend_calls == 1
    assert state.options is not None
    assert state.options.character.name == "robot"
    assert state.options.character_image == image_path
    assert state.options.language == "ko"
    assert state.options.test_seconds == 1.5
    assert state.options.movement == "walk"
    assert state.options.bubble_effect == "pop"
    assert state.options.message_style == "bubble"
    assert state.scheduler is not None
    assert state.scheduler.interval_minutes == 7
    assert state.scheduler.snooze_minutes == 8
    assert state.reminder_text == "ko: builtin task"
    assert data_file.exists()


def test_overlay_gui_uses_animation_values_from_config(
    data_file: Path,
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fake_display_modules(monkeypatch)
    install_fake_animation_module(monkeypatch)
    state = install_fake_overlay_modules(monkeypatch)
    save_config(Config(movement="float", bubble_effect="fade", message_style="flag"), config_file)

    exit_code = main(["overlay"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""
    assert captured.err == ""
    assert state.options is not None
    assert state.options.movement == "float"
    assert state.options.bubble_effect == "fade"
    assert state.options.message_style == "flag"


def test_overlay_flags_override_animation_values_from_config(
    data_file: Path,
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fake_display_modules(monkeypatch)
    install_fake_animation_module(monkeypatch)
    state = install_fake_overlay_modules(monkeypatch)
    save_config(Config(movement="float", bubble_effect="fade", message_style="flag"), config_file)

    exit_code = main(
        ["overlay", "--movement", "hop", "--bubble-effect", "shake", "--message-style", "bubble"]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""
    assert captured.err == ""
    assert state.options is not None
    assert state.options.movement == "hop"
    assert state.options.bubble_effect == "shake"
    assert state.options.message_style == "bubble"


def test_overlay_accepts_gallop_movement_flag(
    data_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fake_display_modules(monkeypatch)
    install_fake_animation_module(monkeypatch)
    state = install_fake_overlay_modules(monkeypatch)

    exit_code = main(["overlay", "--movement", "gallop"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""
    assert captured.err == ""
    assert state.options is not None
    assert state.options.movement == "gallop"
    assert not data_file.exists()


def test_overlay_character_flag_overrides_config_and_wires_real_character(
    data_file: Path,
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fake_animation_module(monkeypatch)
    state = install_fake_overlay_modules(monkeypatch)
    save_config(Config(character="robot"), config_file)

    exit_code = main(["overlay", "--character", "horse"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""
    assert captured.err == ""
    assert state.options is not None
    assert state.options.character.name == "horse"
    assert not data_file.exists()


def test_overlay_unknown_character_prints_stderr_and_exits_1(
    data_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fake_animation_module(monkeypatch)
    state = install_fake_overlay_modules(monkeypatch)

    exit_code = main(["overlay", "--character", "nope"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "Unknown character: nope." in captured.err
    assert "\x1b" not in captured.err
    assert "\x07" not in captured.err
    assert state.backend_calls == 0
    assert not data_file.exists()


def test_overlay_rejects_invalid_cli_animation_choice(
    data_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["overlay", "--movement", "crawl"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "invalid choice: 'crawl'" in captured.err
    assert "--movement" in captured.err
    assert not data_file.exists()


def test_overlay_rejects_invalid_cli_message_style_choice(
    data_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["overlay", "--message-style", "scroll"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "invalid choice: 'scroll'" in captured.err
    assert "--message-style" in captured.err
    assert not data_file.exists()


@pytest.mark.parametrize(
    ("config_body", "expected_message"),
    [
        (
            '[display]\nmovement = "crawl\\u001b]0;x\\u0007"\n',
            "Unknown movement: crawl]0;x. Available: walk, hop, float, dash, gallop, still\n",
        ),
        (
            '[display]\nbubble_effect = "burst\\u001b]0;x\\u0007"\n',
            "Unknown bubble effect: burst]0;x. Available: pop, fade, slide, shake, none\n",
        ),
        (
            '[display]\nmessage_style = "scroll\\u001b]0;x\\u0007"\n',
            "Unknown message style: scroll]0;x. Available: bubble, flag\n",
        ),
    ],
)
def test_overlay_rejects_invalid_config_animation_value_with_sanitized_stderr(
    data_file: Path,
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    config_body: str,
    expected_message: str,
) -> None:
    install_fake_display_modules(monkeypatch)
    install_fake_animation_module(monkeypatch)
    install_fake_overlay_modules(monkeypatch)
    config_file.write_text(config_body, encoding="utf-8")

    exit_code = main(["overlay"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == expected_message
    assert "\x1b" not in captured.err
    assert "\x07" not in captured.err
    assert not data_file.exists()


animations_spec = find_spec("todoy.display.overlay.animations")


def _real_message_style_validator_available() -> bool:
    try:
        from todoy.display.overlay import animations

        return animations.validate_message_style is not None
    except (AttributeError, ImportError):
        return False


@pytest.mark.skipif(animations_spec is None, reason="todoy.display.overlay.animations unavailable")
def test_real_overlay_animation_validators_reject_bad_input() -> None:
    from todoy.display.overlay import animations

    with pytest.raises(ValueError, match="^Unknown movement: crawl\\. Available:"):
        animations.validate_movement("crawl")
    with pytest.raises(ValueError, match="^Unknown bubble effect: burst\\. Available:"):
        animations.validate_bubble_effect("burst")


@pytest.mark.skipif(
    not _real_message_style_validator_available(),
    reason="todoy.display.overlay.animations.validate_message_style unavailable",
)
def test_real_overlay_message_style_validator_rejects_bad_input() -> None:
    from todoy.display.overlay import animations

    with pytest.raises(ValueError, match="^Unknown message style: scroll\\. Available:"):
        animations.validate_message_style("scroll")
