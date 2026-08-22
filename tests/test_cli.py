from __future__ import annotations

import os
import random
import signal
import subprocess
import sys
import time
import types
from argparse import Namespace
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
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


def pinned_todo(text: str, *, todo_id: int = 1, at: str | None = None) -> Todo:
    todo = Todo(text=text, id=todo_id, at=at)
    todo.pinned = True
    return todo


@dataclass(frozen=True)
class FakeCharacter:
    name: str
    emoji: str
    ascii_art: str
    sprite: str | None = None
    voice: str = "default"


@dataclass(frozen=True)
class FakeOverlayOptions:
    character: FakeCharacter
    character_image: Path | None
    language: str
    test_seconds: float | None
    movement: str
    bubble_effect: str
    message_style: str
    sprite_name: str | None = None
    sprite_folder: Path | None = None
    voice: str = "default"


@dataclass(frozen=True)
class FakePersona:
    movement: str
    banner: bool


@dataclass(frozen=True)
class FakePanelActions:
    add: Callable[[str, str | None], str | None]
    set_done: Callable[[int], str | None]
    delete: Callable[[int], str | None]
    set_pinned: Callable[[int, bool], str | None]


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
    reminder_inputs: list[tuple[list[str], str, str]] = field(default_factory=list)
    todos: list[Todo] | None = None
    actions: FakePanelActions | None = None


class FakeOverlayBackend:
    def __init__(self, state: FakeOverlayState) -> None:
        self._state = state

    def run(
        self,
        options: FakeOverlayOptions,
        scheduler: FakeReminderScheduler,
        get_reminder_text: Callable[[], str],
        get_todos: Callable[[], list[Todo]],
        actions: FakePanelActions,
    ) -> int:
        self._state.options = options
        self._state.scheduler = scheduler
        self._state.reminder_text = get_reminder_text()
        self._state.todos = get_todos()
        self._state.actions = actions
        return self._state.exit_code


def install_fake_animation_module(monkeypatch: pytest.MonkeyPatch) -> None:
    animations = types.ModuleType("todoy.display.overlay.animations")
    movements = ("auto", "walk", "hop", "float", "dash", "gallop", "still")
    bubble_effects = ("pop", "fade", "slide", "shake", "none")
    message_styles = ("auto", "bubble", "flag")

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


def install_fake_personas_module(
    monkeypatch: pytest.MonkeyPatch,
    movements: dict[str, str] | None = None,
    banners: dict[str, bool] | None = None,
    events: list[str] | None = None,
) -> list[str]:
    personas = types.ModuleType("todoy.display.overlay.personas")
    resolved_movements = {
        "cat": "walk",
        "robot": "walk",
        "horse": "walk",
        "butterfly": "float",
    }
    resolved_banners = {
        "cat": False,
        "robot": False,
        "horse": False,
        "butterfly": True,
    }
    if movements is not None:
        resolved_movements.update(movements)
    if banners is not None:
        resolved_banners.update(banners)
    calls: list[str] = []

    def persona(character_name: str) -> FakePersona:
        calls.append(character_name)
        if events is not None:
            events.append(f"persona:{character_name}")
        return FakePersona(
            movement=resolved_movements.get(character_name, "walk"),
            banner=resolved_banners.get(character_name, False),
        )

    personas.persona = persona
    monkeypatch.setitem(sys.modules, "todoy.display.overlay.personas", personas)
    return calls


def install_fake_display_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    messages = types.ModuleType("todoy.display.messages")

    def resolve_language(lang: str | None = None) -> str:
        return lang if lang is not None else "en"

    def taunt(
        count: int,
        language: str,
        rng: random.Random | None = None,
        *,
        voice: str = "default",
    ) -> str:
        del rng, voice
        return f"{language}: {count} open"

    messages.resolve_language = resolve_language
    messages.taunt = taunt
    monkeypatch.setitem(sys.modules, "todoy.display.messages", messages)

    characters = types.ModuleType("todoy.display.characters")
    available = {
        "cat": FakeCharacter(name="cat", emoji="🐱", ascii_art="(=^.^=)", voice="feline"),
        "robot": FakeCharacter(name="robot", emoji="🤖", ascii_art="[robot]", voice="robotic"),
        "butterfly": FakeCharacter(
            name="butterfly",
            emoji="🦋",
            ascii_art="><(^.^)><",
            voice="breezy",
        ),
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
    install_fake_personas_module(monkeypatch)

    core = types.ModuleType("todoy.display.overlay.core")

    def build_reminder_text(
        todos: list[Todo],
        language: str,
        rng: random.Random | None = None,
        *,
        voice: str = "default",
    ) -> str:
        del rng
        texts = ", ".join(sanitize_text(todo.text) for todo in todos)
        state.reminder_inputs.append(([todo.text for todo in todos], language, voice))
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
    base.PanelActions = FakePanelActions
    base.create_backend = create_backend
    monkeypatch.setitem(sys.modules, "todoy.display.overlay.base", base)

    return state


@dataclass
class FakeRunModulesState:
    terminal_inits: list[tuple[int, str]]
    render_calls: list[dict[str, object]]
    stride_calls: list[str]


@dataclass
class FakeRunCoreState:
    flag_inputs: list[tuple[list[str], str, str]]
    reminder_inputs: list[tuple[list[str], str, str]]
    alarm_inputs: list[tuple[list[str], str, str]]
    alarm_updates: list[list[str]]
    alarm_clock_inits: list[tuple[int, Callable[[], datetime] | None]]


class FakeRunClock:
    def __init__(
        self,
        current: datetime | None = None,
        *,
        advance_per_sleep: timedelta | None = None,
    ) -> None:
        self.current = current if current is not None else datetime(2026, 8, 21, 9, 0, 0)
        self.advance_per_sleep = advance_per_sleep
        self.sleep_seconds: list[float] = []

    def now(self) -> datetime:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.sleep_seconds.append(seconds)
        if self.advance_per_sleep is None:
            self.current += timedelta(seconds=seconds)
        else:
            self.current += self.advance_per_sleep


def install_fake_run_modules(monkeypatch: pytest.MonkeyPatch) -> FakeRunModulesState:
    state = FakeRunModulesState(terminal_inits=[], render_calls=[], stride_calls=[])
    frames_by_name = {
        "cat": ("cat-a", "cat-b"),
        "robot": ("robot-a", "robot-b", "robot-c"),
    }

    sprites = types.ModuleType("todoy.display.sprites")

    def gait_frames(name: str) -> tuple[str, ...]:
        return frames_by_name.get(name, (f"{name}-a", f"{name}-b"))

    def stride_columns(name: str) -> int:
        state.stride_calls.append(name)
        return 2

    sprites.gait_frames = gait_frames
    sprites.stride_columns = stride_columns
    monkeypatch.setitem(sys.modules, "todoy.display.sprites", sprites)

    terminal_run = types.ModuleType("todoy.display.terminal_run")

    class FakeTerminalRun:
        def __init__(self, width_cols: int, character_name: str) -> None:
            self.width_cols = width_cols
            self.character_name = character_name
            self.tick_count = 0
            state.terminal_inits.append((width_cols, character_name))

        def tick(self) -> tuple[int, int]:
            frames = gait_frames(self.character_name)
            frame_index = self.tick_count % len(frames)
            x_col = (self.tick_count * 3) % self.width_cols
            self.tick_count += 1
            return frame_index, x_col

    def render_run_line(
        x_col: int,
        frame: str,
        flag_text: str,
        width_cols: int,
        use_emoji: bool,
        emoji: str,
    ) -> str:
        state.render_calls.append(
            {
                "x_col": x_col,
                "frame": frame,
                "flag_text": flag_text,
                "width_cols": width_cols,
                "use_emoji": use_emoji,
                "emoji": emoji,
            }
        )
        line = f"{frame}@{x_col}|{flag_text}|w={width_cols}|emoji={use_emoji}|{emoji}"
        return line[:width_cols].ljust(width_cols)

    terminal_run.TerminalRun = FakeTerminalRun
    terminal_run.render_run_line = render_run_line
    monkeypatch.setitem(sys.modules, "todoy.display.terminal_run", terminal_run)
    return state


def install_fake_run_core(
    monkeypatch: pytest.MonkeyPatch,
    *,
    due_batches: list[list[Todo]] | None = None,
) -> FakeRunCoreState:
    state = FakeRunCoreState(
        flag_inputs=[],
        reminder_inputs=[],
        alarm_inputs=[],
        alarm_updates=[],
        alarm_clock_inits=[],
    )
    due_queue = list(due_batches or [])
    core = types.ModuleType("todoy.display.overlay.core")

    class FakeAlarmClock:
        def __init__(self, snooze_minutes: int, now: Callable[[], datetime] | None = None) -> None:
            state.alarm_clock_inits.append((snooze_minutes, now))
            self._due: list[Todo] = []

        def update(self, todos: list[Todo]) -> None:
            state.alarm_updates.append([todo.text for todo in todos])
            self._due = due_queue.pop(0) if due_queue else []

        def due(self) -> list[Todo]:
            return list(self._due)

    def build_flag_line(todos: list[Todo], language: str, *, voice: str = "default") -> str:
        texts = [todo.text for todo in todos]
        state.flag_inputs.append((texts, language, voice))
        return f"flag:{language}:{','.join(texts) or 'empty'}"

    def build_reminder_text(todos: list[Todo], language: str, *, voice: str = "default") -> str:
        texts = [todo.text for todo in todos]
        state.reminder_inputs.append((texts, language, voice))
        return f"reminder:{language}:{','.join(texts) or 'empty'}"

    def build_alarm_text(todos: list[Todo], language: str, *, voice: str = "default") -> str:
        texts = [todo.text for todo in todos]
        state.alarm_inputs.append((texts, language, voice))
        return "\n".join(f"alarm:{language}:{todo.at}:{todo.text}" for todo in todos)

    core.AlarmClock = FakeAlarmClock
    core.build_flag_line = build_flag_line
    core.build_reminder_text = build_reminder_text
    core.build_alarm_text = build_alarm_text
    monkeypatch.setitem(sys.modules, "todoy.display.overlay.core", core)
    return state


def run_namespace(
    *,
    character: str | None = None,
    lang: str | None = "en",
    interval: int | None = 30,
    force_ascii: bool = True,
    fps: int = 1,
) -> Namespace:
    return Namespace(
        character=character,
        lang=lang,
        interval=interval,
        force_ascii=force_ascii,
        fps=fps,
    )


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
    fake_input = FakeInput(["n", "", "not-a-real-character", "koala", ""])
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


def test_add_at_parses_and_persists_without_echoing_time(
    data_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["add", "회의", "--at", "9:05"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "Added #1: 회의\n"
    assert captured.err == ""
    todo = BuiltinSource().list_todos(include_done=True)[0]
    assert todo.text == "회의"
    assert todo.at == "09:05"
    assert data_file.exists()


def test_add_at_invalid_input_prints_sanitized_stderr_and_exits_1(
    data_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["add", "회의", "--at", "25:00\x1b]0;pwned\x07"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "invalid time" in captured.err
    assert "expected 'HH:MM'" in captured.err
    assert "\x1b" not in captured.err
    assert "\x07" not in captured.err
    assert "Traceback" not in captured.err
    assert not data_file.exists()


def test_add_pin_passes_pinned_true_and_prints_contract_message(
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del config_file

    class FakePinnedAddSource:
        def __init__(self) -> None:
            self.add_calls: list[tuple[str, str | None, bool]] = []

        def add(self, text: str, at: str | None = None, pinned: bool = False) -> Todo:
            self.add_calls.append((text, at, pinned))
            todo = Todo(text=text, id=41, at=at)
            todo.pinned = pinned
            return todo

    source = FakePinnedAddSource()
    monkeypatch.setattr("todoy.cli.BuiltinSource", lambda: source)

    exit_code = main(["add", "important", "--at", "9:05", "--pin"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "Added #41: important\n"
    assert captured.err == ""
    assert source.add_calls == [("important", "09:05", True)]


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


@pytest.mark.parametrize(
    ("argv", "expected_output", "expected_call"),
    [
        (["pin", "7"], "Pinned #7: urgent\n", ("set_pinned", 7, True)),
        (["unpin", "7"], "Unpinned #7: urgent\n", ("set_pinned", 7, False)),
        (["rm", "7"], "Removed #7: urgent\n", ("delete", 7, None)),
    ],
)
def test_manage_commands_print_contract_messages(
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    expected_output: str,
    expected_call: tuple[str, int, bool | None],
) -> None:
    del config_file

    class FakeManageSource:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int, bool | None]] = []

        def set_pinned(self, todo_id: int, pinned: bool) -> Todo:
            self.calls.append(("set_pinned", todo_id, pinned))
            return Todo(text="urgent", id=todo_id)

        def delete(self, todo_id: int) -> Todo:
            self.calls.append(("delete", todo_id, None))
            return Todo(text="urgent", id=todo_id)

    source = FakeManageSource()
    monkeypatch.setattr("todoy.cli.BuiltinSource", lambda: source)

    exit_code = main(argv)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == expected_output
    assert captured.err == ""
    assert source.calls == [expected_call]


@pytest.mark.parametrize("argv", [["pin", "999"], ["unpin", "999"], ["rm", "999"]])
def test_manage_unknown_id_uses_existing_stderr_path(
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
) -> None:
    del config_file

    class FakeManageSource:
        def set_pinned(self, todo_id: int, pinned: bool) -> Todo:
            del pinned
            raise KeyError(f"No todo with id {todo_id}")

        def delete(self, todo_id: int) -> Todo:
            raise KeyError(f"No todo with id {todo_id}")

    monkeypatch.setattr("todoy.cli.BuiltinSource", FakeManageSource)

    exit_code = main(argv)

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == "No todo with id 999\n"


@pytest.mark.parametrize(
    ("argv", "expected_after_sweep"),
    [
        (["add", "task"], "add"),
        (["done", "1"], "done"),
        (["pin", "1"], "set_pinned"),
        (["unpin", "1"], "set_pinned"),
        (["rm", "1"], "delete"),
    ],
)
def test_daily_clear_sweeps_before_mutating_builtin_commands(
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    expected_after_sweep: str,
) -> None:
    save_config(Config(daily_clear=True), config_file)

    class FakeSweepSource:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def sweep(self, today: object) -> int:
            del today
            self.calls.append("sweep")
            return 0

        def add(self, text: str, at: str | None = None, pinned: bool = False) -> Todo:
            del at, pinned
            self.calls.append("add")
            return Todo(text=text, id=1)

        def done(self, todo_id: int) -> Todo:
            self.calls.append("done")
            return Todo(text="task", id=todo_id, done=True)

        def set_pinned(self, todo_id: int, pinned: bool) -> Todo:
            del pinned
            self.calls.append("set_pinned")
            return Todo(text="task", id=todo_id)

        def delete(self, todo_id: int) -> Todo:
            self.calls.append("delete")
            return Todo(text="task", id=todo_id)

    source = FakeSweepSource()
    monkeypatch.setattr("todoy.cli.BuiltinSource", lambda: source)

    exit_code = main(argv)

    capsys.readouterr()
    assert exit_code == 0
    assert source.calls[:2] == ["sweep", expected_after_sweep]


@pytest.mark.parametrize(
    "argv",
    [
        ["list"],
        ["tui", "--brief", "--ascii"],
        ["overlay", "--once"],
    ],
)
def test_daily_clear_sweeps_before_builtin_collection_commands(
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
) -> None:
    import todoy.cli as cli

    save_config(Config(daily_clear=True), config_file)
    install_fake_display_modules(monkeypatch)
    install_fake_animation_module(monkeypatch)
    install_fake_overlay_modules(monkeypatch)

    class FakeSweepBuiltinSource:
        name = "builtin"

        def __init__(self) -> None:
            self.calls: list[str] = []

        def sweep(self, today: object) -> int:
            del today
            self.calls.append("sweep")
            return 0

        def list_todos(self, include_done: bool = False) -> list[Todo]:
            del include_done
            self.calls.append("list_todos")
            return []

    source = FakeSweepBuiltinSource()
    monkeypatch.setattr(cli, "BuiltinSource", FakeSweepBuiltinSource)
    monkeypatch.setattr(cli, "build_sources", lambda config: [source])

    exit_code = main(argv)

    capsys.readouterr()
    assert exit_code == 0
    assert source.calls[:2] == ["sweep", "list_todos"]


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


def test_list_prefixes_timed_open_todos(
    data_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["add", "회의", "--at", "14:00"])
    main(["add", "second"])
    capsys.readouterr()

    exit_code = main(["list"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "  1. 14:00 회의\n  2. second\n"
    assert captured.err == ""
    assert data_file.exists()


def test_list_appends_pin_suffix_after_text(
    data_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import todoy.cli as cli

    def collect_todos(
        *,
        include_done: bool,
        config: Config | None = None,
    ) -> tuple[list[Todo], list[Todo]]:
        del include_done, config
        return [pinned_todo("urgent", todo_id=3, at="14:00")], []

    monkeypatch.setattr(cli, "_collect_todos", collect_todos)

    exit_code = main(["list"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "  3. 14:00 urgent 📌\n"
    assert captured.err == ""
    assert not data_file.exists()


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


def test_list_all_prefixes_timed_done_items(
    data_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["add", "completed task", "--at", "14:00"])
    main(["done", "1"])
    capsys.readouterr()

    exit_code = main(["list", "--all"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "  1. [x] 14:00 completed task\n"
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


def test_list_prefixes_timed_markdown_source_todos(
    data_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import todoy.cli as cli

    def collect_todos(
        *,
        include_done: bool,
        config: Config | None = None,
    ) -> tuple[list[Todo], list[Todo]]:
        del include_done, config
        return [], [Todo(text="회의", source="markdown", at="14:00")]

    monkeypatch.setattr(cli, "_collect_todos", collect_todos)

    exit_code = main(["list"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "  - 14:00 회의\n"
    assert captured.err == ""
    assert not data_file.exists()


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


def test_tui_appends_pin_suffix_to_rendered_todos(
    data_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import todoy.cli as cli

    install_fake_display_modules(monkeypatch)

    def collect_todos(
        *,
        include_done: bool,
        config: Config | None = None,
    ) -> tuple[list[Todo], list[Todo]]:
        del include_done, config
        return [pinned_todo("urgent")], []

    monkeypatch.setattr(cli, "_collect_todos", collect_todos)

    exit_code = main(["tui", "--brief", "--ascii"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "(=^.^=) 1 todo: urgent 📌\n"
    assert captured.err == ""
    assert not data_file.exists()


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
    assert captured.err == "Unknown character: dragon[31m. Available: cat, robot, butterfly\n"
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


def test_run_loop_writes_cr_frames_and_refreshes_flag_on_interval(
    data_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import todoy.cli as cli

    install_fake_display_modules(monkeypatch)
    run_modules = install_fake_run_modules(monkeypatch)
    run_core = install_fake_run_core(monkeypatch)
    clock = FakeRunClock(advance_per_sleep=timedelta(minutes=1))
    writes: list[str] = []

    def collect_todos(
        *,
        include_done: bool,
        config: Config | None = None,
    ) -> tuple[list[Todo], list[Todo]]:
        del include_done, config
        if clock.current < datetime(2026, 8, 21, 9, 1, 0):
            return [Todo(text="first", id=1)], []
        return [Todo(text="second", id=2)], []

    monkeypatch.setattr(cli, "_collect_todos", collect_todos)

    exit_code = cli._run(
        run_namespace(lang="ko", interval=1, fps=1),
        BuiltinSource(),
        sleep=clock.sleep,
        now=clock.now,
        write=writes.append,
        max_frames=2,
        width_reader=lambda: 40,
    )

    assert exit_code == 0
    assert [call["flag_text"] for call in run_modules.render_calls] == [
        "flag:ko:first",
        "flag:ko:second",
    ]
    assert run_core.flag_inputs == [(["first"], "ko", "feline"), (["second"], "ko", "feline")]
    assert run_core.reminder_inputs == [(["second"], "ko", "feline")]
    assert writes[1] == "\nreminder:ko:second\n"
    assert writes[0].startswith("\rcat-a@0|flag:ko:first|w=40|emoji=False|")
    assert writes[2].startswith("\rcat-b@3|flag:ko:second|w=40|emoji=False|")
    assert all(write.startswith("\r") for write in writes if "cat-" in write)
    assert all("\x1b" not in write for write in writes)
    assert clock.sleep_seconds == [1.0]
    assert not data_file.exists()


def test_run_loop_prints_alarm_block_above_marquee_on_fresh_line(
    data_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import todoy.cli as cli

    install_fake_display_modules(monkeypatch)
    install_fake_run_modules(monkeypatch)
    due = Todo(text="standup", id=5, at="09:00")
    run_core = install_fake_run_core(monkeypatch, due_batches=[[due]])
    clock = FakeRunClock()
    writes: list[str] = []
    monkeypatch.setattr(
        cli,
        "_collect_todos",
        lambda *, include_done, config=None: ([due], []),
    )

    exit_code = cli._run(
        run_namespace(lang="en", interval=30, fps=1),
        BuiltinSource(),
        sleep=clock.sleep,
        now=clock.now,
        write=writes.append,
        max_frames=1,
        width_reader=lambda: 50,
    )

    assert exit_code == 0
    assert writes[0] == "\nalarm:en:09:00:standup\n"
    assert writes[1].startswith("\rcat-a@0|flag:en:standup|w=50|emoji=False|🐱")
    assert run_core.alarm_updates == [["standup"]]
    assert run_core.alarm_inputs == [(["standup"], "en", "feline")]
    assert not data_file.exists()


@pytest.mark.parametrize("interrupt_from", ["sleep", "write"])
def test_run_keyboard_interrupt_writes_newline_and_returns_zero(
    data_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    interrupt_from: str,
) -> None:
    import todoy.cli as cli

    install_fake_display_modules(monkeypatch)
    install_fake_run_modules(monkeypatch)
    install_fake_run_core(monkeypatch)
    clock = FakeRunClock()
    writes: list[str] = []
    monkeypatch.setattr(
        cli,
        "_collect_todos",
        lambda *, include_done, config=None: ([Todo(text="task", id=1)], []),
    )

    def write(text: str) -> None:
        writes.append(text)
        if interrupt_from == "write" and text.startswith("\r"):
            raise KeyboardInterrupt

    def sleep(seconds: float) -> None:
        del seconds
        if interrupt_from == "sleep":
            raise KeyboardInterrupt

    exit_code = cli._run(
        run_namespace(fps=3),
        BuiltinSource(),
        sleep=sleep,
        now=clock.now,
        write=write,
        width_reader=lambda: 40,
    )

    assert exit_code == 0
    assert writes[-1] == "\n"
    assert any(write.startswith("\r") for write in writes)
    assert not data_file.exists()


def test_run_rechecks_terminal_width_occasionally_and_clamps_minimum(
    data_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import todoy.cli as cli

    install_fake_display_modules(monkeypatch)
    run_modules = install_fake_run_modules(monkeypatch)
    install_fake_run_core(monkeypatch)
    clock = FakeRunClock()
    widths = iter([30, 10])
    monkeypatch.setattr(
        cli,
        "_collect_todos",
        lambda *, include_done, config=None: ([Todo(text="task", id=1)], []),
    )

    exit_code = cli._run(
        run_namespace(fps=2),
        BuiltinSource(),
        sleep=clock.sleep,
        now=clock.now,
        write=lambda text: None,
        max_frames=3,
        width_reader=lambda: next(widths),
    )

    assert exit_code == 0
    assert run_modules.terminal_inits == [(30, "cat"), (20, "cat")]
    assert [call["width_cols"] for call in run_modules.render_calls] == [30, 30, 20]
    assert not data_file.exists()


def test_run_cli_flags_resolve_character_language_ascii_and_fps(
    data_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import todoy.cli as cli

    install_fake_display_modules(monkeypatch)
    run_modules = install_fake_run_modules(monkeypatch)
    run_core = install_fake_run_core(monkeypatch)
    monkeypatch.setattr(
        cli,
        "_collect_todos",
        lambda *, include_done, config=None: ([Todo(text="task", id=1)], []),
    )
    sleep_seconds: list[float] = []

    def sleep(seconds: float) -> None:
        sleep_seconds.append(seconds)
        raise KeyboardInterrupt

    exit_code = cli._run(
        run_namespace(character="robot", lang="ko", interval=3, force_ascii=True, fps=5),
        BuiltinSource(),
        sleep=sleep,
        now=FakeRunClock().now,
        write=lambda text: None,
        width_reader=lambda: 40,
    )

    assert exit_code == 0
    assert run_modules.terminal_inits == [(40, "robot")]
    assert run_modules.render_calls[0]["use_emoji"] is False
    assert run_modules.render_calls[0]["emoji"] == "🤖"
    assert run_core.flag_inputs == [(["task"], "ko", "robotic")]
    assert sleep_seconds == [0.2]
    assert not data_file.exists()


def test_run_default_interval_comes_from_config(
    data_file: Path,
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import todoy.cli as cli

    save_config(Config(reminder_interval_minutes=7), config_file)
    install_fake_display_modules(monkeypatch)
    install_fake_run_modules(monkeypatch)
    run_core = install_fake_run_core(monkeypatch)
    clock = FakeRunClock(advance_per_sleep=timedelta(minutes=3, seconds=30))
    monkeypatch.setattr(
        cli,
        "_collect_todos",
        lambda *, include_done, config=None: ([Todo(text="task", id=1)], []),
    )

    cli._run(
        run_namespace(interval=None, fps=1),
        BuiltinSource(),
        sleep=clock.sleep,
        now=clock.now,
        write=lambda text: None,
        max_frames=3,
        width_reader=lambda: 40,
    )
    assert run_core.reminder_inputs == [(["task"], "en", "feline")]
    assert not data_file.exists()


@pytest.mark.parametrize("fps", ["0", "31"])
def test_run_rejects_invalid_fps(
    data_file: Path,
    capsys: pytest.CaptureFixture[str],
    fps: str,
) -> None:
    exit_code = main(["run", "--fps", fps])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "--fps" in captured.err
    assert "1..30" in captured.err
    assert not data_file.exists()


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="SIGINT semantics differ on Windows; injectable-loop tests cover the logic there",
)
def test_run_console_script_ascii_smoke(tmp_path: Path) -> None:
    script = Path(sys.executable).parent / "todoy"
    if not script.is_file():
        pytest.skip(f"todoy console script not found at {script}")

    env = os.environ.copy()
    env["TODOY_CONFIG_FILE"] = str(tmp_path / "config.toml")
    env["TODOY_DATA_FILE"] = str(tmp_path / "todos.json")
    process = subprocess.Popen(
        [str(script), "run", "--ascii", "--fps", "10"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        time.sleep(1.5)
        process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=5)

        stderr_text = stderr.decode("utf-8", errors="replace")
        assert process.returncode == 0, stderr_text
        assert stdout.count(b"\r") >= 2
        assert b"\x1b" not in stdout
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=2)


def _real_run_modules_available() -> bool:
    try:
        __import__("todoy.display.terminal_run")
        __import__("todoy.display.sprites")
    except ImportError:
        return False
    return True


@pytest.mark.skipif(
    not _real_run_modules_available(),
    reason="todoy.display.terminal_run/todoy.display.sprites unavailable",
)
def test_real_run_modules_stride_wrap_and_render_contract() -> None:
    from todoy.display.sprites import gait_frames, stride_columns
    from todoy.display.terminal_run import TerminalRun, render_run_line

    name = "horse"
    width_cols = 20
    frames = gait_frames(name)
    stride = stride_columns(name)
    runner = TerminalRun(width_cols, name)
    samples = [runner.tick() for _ in range(len(frames) * 3)]
    positions = [x_col for _, x_col in samples]

    assert len(frames) >= 2
    for index in range(len(frames) * 2):
        assert (positions[index + len(frames)] - positions[index]) % width_cols == (
            stride % width_cols
        )

    line = render_run_line(
        width_cols - 1,
        frames[0],
        "FLAG",
        width_cols,
        False,
        "🐎",
    )
    assert len(line) == width_cols
    assert "\r" not in line
    assert "\n" not in line
    assert "\x1b" not in line


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


def test_overlay_once_uses_selected_character_voice(
    data_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fake_display_modules(monkeypatch)
    install_fake_animation_module(monkeypatch)
    state = install_fake_overlay_modules(monkeypatch)
    main(["add", "oil gears"])
    capsys.readouterr()

    exit_code = main(["overlay", "--once", "--character", "robot", "--lang", "en"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "en: oil gears\n"
    assert captured.err == ""
    assert state.reminder_inputs == [(["oil gears"], "en", "robotic")]
    assert state.backend_calls == 0
    assert data_file.exists()


def test_overlay_once_unknown_character_prints_stderr_and_exits_1(
    data_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fake_display_modules(monkeypatch)
    install_fake_animation_module(monkeypatch)
    state = install_fake_overlay_modules(monkeypatch)

    exit_code = main(["overlay", "--once", "--character", "nope"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == "Unknown character: nope. Available: cat, robot, butterfly\n"
    assert state.backend_calls == 0
    assert not data_file.exists()


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
    sprite_folder = tmp_path / "sprites"
    save_config(
        Config(
            reminder_interval_minutes=99,
            character="robot",
            character_image=image_path,
            character_sprites=sprite_folder,
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
    assert state.options.sprite_name is None
    assert state.options.sprite_folder == sprite_folder
    assert state.options.language == "ko"
    assert state.options.test_seconds == 1.5
    assert state.options.movement == "walk"
    assert state.options.bubble_effect == "pop"
    assert state.options.message_style == "bubble"
    assert state.options.voice == "robotic"
    assert state.scheduler is not None
    assert state.scheduler.interval_minutes == 7
    assert state.scheduler.snooze_minutes == 8
    assert state.reminder_text == "ko: builtin task"
    assert state.reminder_inputs == [(["builtin task"], "ko", "robotic")]
    assert state.todos is not None
    assert [todo.text for todo in state.todos] == ["builtin task"]
    assert data_file.exists()


def test_overlay_gui_wires_panel_actions_with_sanitized_error_returns(
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import todoy.cli as cli

    install_fake_display_modules(monkeypatch)
    install_fake_animation_module(monkeypatch)
    state = install_fake_overlay_modules(monkeypatch)
    save_config(Config(daily_clear=True), config_file)
    monkeypatch.setattr(cli, "_collect_todos", lambda *, include_done, config=None: ([], []))

    class FakeActionSource:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object, object | None]] = []
            sources.append(self)

        def sweep(self, today: object) -> int:
            self.calls.append(("sweep", today, None))
            return 0

        def add(self, text: str, at: str | None = None, pinned: bool = False) -> Todo:
            self.calls.append(("add", text, at))
            if text == "explode":
                raise RuntimeError("bad add\x1b]0;x\x07")
            todo = Todo(text=text, id=1, at=at)
            todo.pinned = pinned
            return todo

        def done(self, todo_id: int) -> Todo:
            self.calls.append(("done", todo_id, None))
            if todo_id == 500:
                raise RuntimeError("bad done\x1b]0;x\x07")
            return Todo(text="done", id=todo_id, done=True)

        def delete(self, todo_id: int) -> Todo:
            self.calls.append(("delete", todo_id, None))
            if todo_id == 500:
                raise RuntimeError("bad delete\x1b]0;x\x07")
            return Todo(text="deleted", id=todo_id)

        def set_pinned(self, todo_id: int, pinned: bool) -> Todo:
            self.calls.append(("set_pinned", todo_id, pinned))
            if todo_id == 500:
                raise RuntimeError("bad pin\x1b]0;x\x07")
            return Todo(text="pinned", id=todo_id)

    sources: list[FakeActionSource] = []
    monkeypatch.setattr(cli, "BuiltinSource", FakeActionSource)

    exit_code = main(["overlay"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""
    assert captured.err == ""
    assert isinstance(state.actions, FakePanelActions)
    actions = state.actions

    initial_source_count = len(sources)
    invalid_time_error = actions.add("panel task", "25:00\x1b]0;x\x07")
    assert invalid_time_error is not None
    assert "invalid time" in invalid_time_error
    assert "\x1b" not in invalid_time_error
    assert "\x07" not in invalid_time_error
    assert len(sources) == initial_source_count

    assert actions.add("panel task", "9:05") is None
    assert sources[-1].calls[0][0] == "sweep"
    assert sources[-1].calls[1] == ("add", "panel task", "09:05")

    assert actions.set_done(5) is None
    assert sources[-1].calls[0][0] == "sweep"
    assert sources[-1].calls[1] == ("done", 5, None)

    assert actions.delete(6) is None
    assert sources[-1].calls[0][0] == "sweep"
    assert sources[-1].calls[1] == ("delete", 6, None)

    assert actions.set_pinned(7, True) is None
    assert sources[-1].calls[0][0] == "sweep"
    assert sources[-1].calls[1] == ("set_pinned", 7, True)

    for error in (
        actions.add("explode", None),
        actions.set_done(500),
        actions.delete(500),
        actions.set_pinned(500, False),
    ):
        assert error is not None
        assert "bad " in error
        assert "\x1b" not in error
        assert "\x07" not in error


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


def test_overlay_default_message_style_resolves_butterfly_banner_to_flag(
    data_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fake_display_modules(monkeypatch)
    install_fake_animation_module(monkeypatch)
    state = install_fake_overlay_modules(monkeypatch)

    exit_code = main(["overlay", "--character", "butterfly", "--movement", "walk"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""
    assert captured.err == ""
    assert state.options is not None
    assert state.options.message_style == "flag"
    assert not data_file.exists()


def test_overlay_default_message_style_resolves_cat_without_banner_to_bubble(
    data_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fake_display_modules(monkeypatch)
    install_fake_animation_module(monkeypatch)
    state = install_fake_overlay_modules(monkeypatch)

    exit_code = main(["overlay", "--character", "cat", "--movement", "walk"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""
    assert captured.err == ""
    assert state.options is not None
    assert state.options.message_style == "bubble"
    assert not data_file.exists()


def test_overlay_explicit_bubble_message_style_wins_for_butterfly(
    data_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fake_display_modules(monkeypatch)
    install_fake_animation_module(monkeypatch)
    state = install_fake_overlay_modules(monkeypatch)
    persona_calls = install_fake_personas_module(monkeypatch)

    exit_code = main(
        ["overlay", "--character", "butterfly", "--movement", "walk", "--message-style", "bubble"]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""
    assert captured.err == ""
    assert persona_calls == []
    assert state.options is not None
    assert state.options.message_style == "bubble"
    assert not data_file.exists()


def test_overlay_auto_movement_resolves_persona_before_overlay_options(
    data_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fake_display_modules(monkeypatch)
    install_fake_animation_module(monkeypatch)
    state = install_fake_overlay_modules(monkeypatch)
    events: list[str] = []
    persona_calls = install_fake_personas_module(
        monkeypatch,
        movements={"robot": "float"},
        events=events,
    )
    base_module = sys.modules["todoy.display.overlay.base"]

    def overlay_options(
        *,
        character: FakeCharacter,
        character_image: Path | None,
        language: str,
        test_seconds: float | None,
        sprite_name: str | None,
        sprite_folder: Path | None,
        movement: str,
        bubble_effect: str,
        message_style: str,
        voice: str,
    ) -> FakeOverlayOptions:
        events.append(f"options:{movement}")
        assert events == ["persona:robot", "options:float"]
        assert movement != "auto"
        return FakeOverlayOptions(
            character=character,
            character_image=character_image,
            language=language,
            test_seconds=test_seconds,
            movement=movement,
            bubble_effect=bubble_effect,
            message_style=message_style,
            sprite_name=sprite_name,
            sprite_folder=sprite_folder,
            voice=voice,
        )

    base_module.OverlayOptions = overlay_options

    exit_code = main(
        ["overlay", "--character", "robot", "--movement", "auto", "--message-style", "bubble"]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""
    assert captured.err == ""
    assert persona_calls == ["robot"]
    assert state.options is not None
    assert state.options.movement == "float"
    assert not data_file.exists()


def test_overlay_auto_message_style_resolves_persona_before_overlay_options(
    data_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fake_display_modules(monkeypatch)
    install_fake_animation_module(monkeypatch)
    state = install_fake_overlay_modules(monkeypatch)
    events: list[str] = []
    persona_calls = install_fake_personas_module(
        monkeypatch,
        banners={"robot": True},
        events=events,
    )
    base_module = sys.modules["todoy.display.overlay.base"]

    def overlay_options(
        *,
        character: FakeCharacter,
        character_image: Path | None,
        language: str,
        test_seconds: float | None,
        sprite_name: str | None,
        sprite_folder: Path | None,
        movement: str,
        bubble_effect: str,
        message_style: str,
        voice: str,
    ) -> FakeOverlayOptions:
        events.append(f"options:{message_style}")
        assert events == ["persona:robot", "options:flag"]
        assert message_style != "auto"
        return FakeOverlayOptions(
            character=character,
            character_image=character_image,
            language=language,
            test_seconds=test_seconds,
            movement=movement,
            bubble_effect=bubble_effect,
            message_style=message_style,
            sprite_name=sprite_name,
            sprite_folder=sprite_folder,
            voice=voice,
        )

    base_module.OverlayOptions = overlay_options

    exit_code = main(
        ["overlay", "--character", "robot", "--movement", "walk", "--message-style", "auto"]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""
    assert captured.err == ""
    assert persona_calls == ["robot"]
    assert state.options is not None
    assert state.options.message_style == "flag"
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


def test_overlay_character_blocky_wires_sprite_name_from_real_catalog(
    data_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fake_animation_module(monkeypatch)
    state = install_fake_overlay_modules(monkeypatch)

    exit_code = main(["overlay", "--character", "blocky", "--movement", "walk"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""
    assert captured.err == ""
    assert state.options is not None
    assert state.options.character.name == "blocky"
    assert state.options.sprite_name == "blocky"
    assert state.options.voice == "gamer"
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
            "Unknown movement: crawl]0;x. Available: auto, walk, hop, float, dash, gallop, still\n",
        ),
        (
            '[display]\nbubble_effect = "burst\\u001b]0;x\\u0007"\n',
            "Unknown bubble effect: burst]0;x. Available: pop, fade, slide, shake, none\n",
        ),
        (
            '[display]\nmessage_style = "scroll\\u001b]0;x\\u0007"\n',
            "Unknown message style: scroll]0;x. Available: auto, bubble, flag\n",
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
personas_spec = find_spec("todoy.display.overlay.personas")


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


@pytest.mark.skipif(
    animations_spec is None or personas_spec is None,
    reason="todoy.display.overlay real modules unavailable",
)
def test_overlay_auto_message_style_uses_real_personas_end_to_end(
    data_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state = FakeOverlayState()
    base = types.ModuleType("todoy.display.overlay.base")

    def create_backend() -> FakeOverlayBackend:
        state.backend_calls += 1
        return FakeOverlayBackend(state)

    base.OverlayOptions = FakeOverlayOptions
    base.PanelActions = FakePanelActions
    base.create_backend = create_backend
    monkeypatch.setitem(sys.modules, "todoy.display.overlay.base", base)

    exit_code = main(["overlay", "--character", "butterfly", "--movement", "walk"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""
    assert captured.err == ""
    assert state.backend_calls == 1
    assert state.options is not None
    assert state.options.character.name == "butterfly"
    assert state.options.message_style == "flag"
    assert not data_file.exists()


@pytest.mark.skipif(personas_spec is None, reason="todoy.display.overlay.personas unavailable")
def test_real_overlay_personas_return_concrete_movement() -> None:
    from todoy.display.overlay import personas
    from todoy.display.overlay.animations import MOVEMENTS

    movement = personas.persona("cat").movement

    assert movement in MOVEMENTS
    assert movement != "auto"
