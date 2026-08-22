"""todoy command-line interface."""

from __future__ import annotations

import argparse
import importlib
import os
import shutil
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from todoy.config import (
    DEFAULT_CHARACTER,
    DEFAULT_INTERVAL_MINUTES,
    Config,
    build_sources,
    config_path,
    load_config,
    save_config,
)
from todoy.display import sanitize_text
from todoy.display.characters import get_character
from todoy.display.messages import resolve_language
from todoy.display.overlay.animations import BUBBLE_EFFECTS, MESSAGE_STYLES, MOVEMENTS
from todoy.display.tui import render_tui, todo_display_text
from todoy.models import Todo, parse_at
from todoy.sources.builtin import BuiltinSource

CommandHandler = Callable[[argparse.Namespace, BuiltinSource], int]
PIN_SUFFIX = " 📌"
MIN_RUN_WIDTH_COLS = 20
RUN_WIDTH_REFRESH_SECONDS = 1.0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="todoy")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add")
    add_parser.add_argument("text")
    add_parser.add_argument("--at")
    add_parser.add_argument("--pin", action="store_true")
    add_parser.set_defaults(handler=_add)

    done_parser = subparsers.add_parser("done")
    done_parser.add_argument("todo_id", type=int, metavar="id")
    done_parser.set_defaults(handler=_done)

    pin_parser = subparsers.add_parser("pin")
    pin_parser.add_argument("todo_id", type=int, metavar="id")
    pin_parser.set_defaults(handler=_pin)

    unpin_parser = subparsers.add_parser("unpin")
    unpin_parser.add_argument("todo_id", type=int, metavar="id")
    unpin_parser.set_defaults(handler=_unpin)

    rm_parser = subparsers.add_parser("rm")
    rm_parser.add_argument("todo_id", type=int, metavar="id")
    rm_parser.set_defaults(handler=_rm)

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--all", action="store_true", dest="include_done")
    list_parser.set_defaults(handler=_list)

    tui_parser = subparsers.add_parser("tui")
    tui_parser.add_argument("--brief", action="store_true")
    tui_parser.add_argument("--character")
    tui_parser.add_argument("--lang", choices=("en", "ko"))
    tui_parser.add_argument("--ascii", action="store_true", dest="force_ascii")
    tui_parser.set_defaults(handler=_tui)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--character")
    run_parser.add_argument("--lang", choices=("en", "ko"))
    run_parser.add_argument("--interval", type=int, metavar="MINUTES")
    run_parser.add_argument("--ascii", action="store_true", dest="force_ascii")
    run_parser.add_argument("--fps", type=_fps_arg, default=8, metavar="N")
    run_parser.set_defaults(handler=_run)

    init_parser = subparsers.add_parser("init")
    init_parser.set_defaults(handler=_init)

    overlay_parser = subparsers.add_parser("overlay")
    overlay_parser.add_argument("--interval", type=int, metavar="MINUTES")
    overlay_parser.add_argument("--lang", choices=("en", "ko"))
    overlay_parser.add_argument("--once", action="store_true")
    overlay_parser.add_argument("--character", metavar="NAME")
    overlay_parser.add_argument("--movement", choices=MOVEMENTS)
    overlay_parser.add_argument("--bubble-effect", choices=BUBBLE_EFFECTS)
    overlay_parser.add_argument("--message-style", choices=MESSAGE_STYLES)
    overlay_parser.set_defaults(handler=_overlay)

    return parser


def _fps_arg(value: str) -> int:
    try:
        fps = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--fps must be an integer in the range 1..30") from exc
    if not 1 <= fps <= 30:
        raise argparse.ArgumentTypeError("--fps must be in the range 1..30")
    return fps


@dataclass
class _RunLoopState:
    character_name: str
    emoji: str
    language: str
    interval_minutes: int
    use_emoji: bool
    terminal_run_module: Any
    sprites_module: Any
    core_module: Any
    alarm_clock: Any
    get_todos: Callable[[], list[Todo]]
    now: Callable[[], datetime]
    write: Callable[[str], None]
    width_reader: Callable[[], int]
    width_cols: int
    runner: Any
    frames: tuple[str, ...]
    flag_text: str
    next_interval_at: datetime
    next_width_check_at: datetime
    last_alarm_second: tuple[int, int, int, int, int, int] | None = None


def _todo_id(todo: Todo) -> int:
    if todo.id is None:
        msg = "Builtin todo is missing an id"
        raise ValueError(msg)
    return todo.id


def _is_builtin_source(source: object) -> bool:
    builtin_type = BuiltinSource
    return (
        isinstance(builtin_type, type)
        and isinstance(source, builtin_type)
        or getattr(source, "name", None) == "builtin"
    )


def _sweep_if_daily_clear(source: object, config: Config) -> None:
    if not config.daily_clear:
        return
    source.sweep(date.today())


def _source_add(source: object, text: str, *, at: str | None, pinned: bool) -> Todo:
    return _expect_todo(source.add(text, at=at, pinned=pinned))


def _source_done(source: object, todo_id: int) -> Todo:
    return _expect_todo(source.done(todo_id))


def _source_set_pinned(source: object, todo_id: int, pinned: bool) -> Todo:
    return _expect_todo(source.set_pinned(todo_id, pinned))


def _source_delete(source: object, todo_id: int) -> Todo:
    return _expect_todo(source.delete(todo_id))


def _expect_todo(value: object) -> Todo:
    if not isinstance(value, Todo):
        raise ValueError("Builtin source returned an invalid todo")
    return value


def _unknown_id(todo_id: int) -> None:
    print(f"No todo with id {todo_id}", file=sys.stderr)


def _action_error(exc: Exception) -> str:
    if isinstance(exc, KeyError) and exc.args:
        message = str(exc.args[0])
    else:
        message = str(exc)
    if not message:
        message = exc.__class__.__name__
    return sanitize_text(message)


def _todo_is_pinned(todo: Todo) -> bool:
    return bool(todo.pinned)


def _display_todo_text(todo: Todo) -> str:
    text = todo_display_text(todo)
    if _todo_is_pinned(todo) and not text.endswith(PIN_SUFFIX):
        return f"{text}{PIN_SUFFIX}"
    return text


def _todo_for_tui(todo: Todo) -> Todo:
    if not _todo_is_pinned(todo) or todo_display_text(todo).endswith(PIN_SUFFIX):
        return todo
    return replace(todo, text=f"{todo.text}{PIN_SUFFIX}")


def _todos_for_tui(todos: list[Todo]) -> list[Todo]:
    return [_todo_for_tui(todo) for todo in todos]


def _add(args: argparse.Namespace, source: BuiltinSource) -> int:
    config = load_config()
    _sweep_if_daily_clear(source, config)
    at = parse_at(args.at) if args.at is not None else None
    todo = _source_add(source, args.text, at=at, pinned=args.pin)
    print(f"Added #{_todo_id(todo)}: {sanitize_text(todo.text)}")
    return 0


def _done(args: argparse.Namespace, source: BuiltinSource) -> int:
    config = load_config()
    _sweep_if_daily_clear(source, config)
    try:
        todo = _source_done(source, args.todo_id)
    except KeyError:
        _unknown_id(args.todo_id)
        return 1

    print(f"Done #{_todo_id(todo)}: {sanitize_text(todo.text)}")
    return 0


def _pin(args: argparse.Namespace, source: BuiltinSource) -> int:
    return _set_pinned(args.todo_id, True, "Pinned", source)


def _unpin(args: argparse.Namespace, source: BuiltinSource) -> int:
    return _set_pinned(args.todo_id, False, "Unpinned", source)


def _set_pinned(todo_id: int, pinned: bool, label: str, source: BuiltinSource) -> int:
    config = load_config()
    _sweep_if_daily_clear(source, config)
    try:
        todo = _source_set_pinned(source, todo_id, pinned)
    except KeyError:
        _unknown_id(todo_id)
        return 1

    print(f"{label} #{_todo_id(todo)}: {sanitize_text(todo.text)}")
    return 0


def _rm(args: argparse.Namespace, source: BuiltinSource) -> int:
    config = load_config()
    _sweep_if_daily_clear(source, config)
    try:
        todo = _source_delete(source, args.todo_id)
    except KeyError:
        _unknown_id(args.todo_id)
        return 1

    print(f"Removed #{_todo_id(todo)}: {sanitize_text(todo.text)}")
    return 0


def _collect_todos(
    *,
    include_done: bool,
    config: Config | None = None,
) -> tuple[list[Todo], list[Todo]]:
    builtin_todos: list[Todo] = []
    non_builtin_todos: list[Todo] = []
    source_config = config if config is not None else load_config()
    for configured_source in build_sources(source_config):
        if _is_builtin_source(configured_source):
            _sweep_if_daily_clear(configured_source, source_config)
            builtin_todos.extend(configured_source.list_todos(include_done=include_done))
        else:
            non_builtin_todos.extend(configured_source.get_todos())
    return builtin_todos, non_builtin_todos


def _list(args: argparse.Namespace, source: BuiltinSource) -> int:
    del source

    builtin_todos, non_builtin_todos = _collect_todos(include_done=args.include_done)

    if not builtin_todos and not non_builtin_todos:
        print("No todos for today 🎉")
        return 0

    for todo in builtin_todos:
        marker = "[x] " if todo.done else ""
        print(f"  {_todo_id(todo)}. {marker}{_display_todo_text(todo)}")
    for todo in non_builtin_todos:
        print(f"  - {_display_todo_text(todo)}")
    return 0


def _tui(args: argparse.Namespace, source: BuiltinSource) -> int:
    del source

    character = get_character(args.character)
    language = resolve_language(args.lang)
    builtin_todos, non_builtin_todos = _collect_todos(include_done=False)
    use_emoji = False if args.force_ascii else None
    print(
        render_tui(
            _todos_for_tui([*builtin_todos, *non_builtin_todos]),
            character=character,
            language=language,
            brief=args.brief,
            use_emoji=use_emoji,
        )
    )
    return 0


def _run(
    args: argparse.Namespace,
    source: BuiltinSource,
    *,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = datetime.now,
    write: Callable[[str], None] | None = None,
    max_frames: int | None = None,
    width_reader: Callable[[], int] | None = None,
) -> int:
    del source

    config = load_config()
    character = get_character(args.character)
    language = resolve_language(args.lang)
    interval_minutes = (
        args.interval if args.interval is not None else config.reminder_interval_minutes
    )
    if interval_minutes <= 0:
        raise ValueError("reminder interval must be a positive number of minutes")

    terminal_run_module = importlib.import_module("todoy.display.terminal_run")
    sprites_module = importlib.import_module("todoy.display.sprites")
    core_module = importlib.import_module("todoy.display.overlay.core")
    resolved_write = write if write is not None else _stdout_write
    resolved_width_reader = width_reader if width_reader is not None else _terminal_width_columns
    use_emoji = _resolve_run_use_emoji(character, force_ascii=args.force_ascii)

    def get_todos() -> list[Todo]:
        builtin_todos, non_builtin_todos = _collect_todos(include_done=False, config=config)
        return [*builtin_todos, *non_builtin_todos]

    current = now()
    width_cols = _clamped_terminal_width(resolved_width_reader())
    state = _RunLoopState(
        character_name=character.name,
        emoji=character.emoji,
        language=language,
        interval_minutes=interval_minutes,
        use_emoji=use_emoji,
        terminal_run_module=terminal_run_module,
        sprites_module=sprites_module,
        core_module=core_module,
        alarm_clock=core_module.AlarmClock(config.snooze_minutes, now=now),
        get_todos=get_todos,
        now=now,
        write=resolved_write,
        width_reader=resolved_width_reader,
        width_cols=width_cols,
        runner=terminal_run_module.TerminalRun(width_cols, character.name),
        frames=_run_frames(sprites_module, character.name, character.ascii_art),
        flag_text=core_module.build_flag_line(get_todos(), language),
        next_interval_at=current + timedelta(minutes=interval_minutes),
        next_width_check_at=current + timedelta(seconds=RUN_WIDTH_REFRESH_SECONDS),
    )

    try:
        return _run_terminal_loop(state, args.fps, sleep=sleep, max_frames=max_frames)
    except KeyboardInterrupt:
        _write_interrupt_newline(resolved_write)
        return 0


def _run_terminal_loop(
    state: _RunLoopState,
    fps: int,
    *,
    sleep: Callable[[float], None],
    max_frames: int | None,
) -> int:
    frame_delay = 1.0 / fps
    frames_written = 0
    while max_frames is None or frames_written < max_frames:
        _run_frame_step(state)
        frames_written += 1
        if max_frames is not None and frames_written >= max_frames:
            break
        sleep(frame_delay)
    return 0


def _run_frame_step(state: _RunLoopState) -> str:
    current = state.now()
    _refresh_run_width_if_due(state, current)

    blocks: list[str] = []
    alarm_block = _alarm_block_if_due(state, current)
    if alarm_block:
        blocks.append(alarm_block)
    reminder_block = _reminder_block_if_due(state, current)
    if reminder_block:
        blocks.append(reminder_block)
    if blocks:
        state.write("\n" + "\n".join(block.rstrip("\n") for block in blocks) + "\n")

    frame_index, x_col = state.runner.tick()
    frame = state.frames[frame_index % len(state.frames)]
    line = state.terminal_run_module.render_run_line(
        x_col,
        frame,
        state.flag_text,
        state.width_cols,
        state.use_emoji,
        state.emoji,
    )
    state.write("\r" + line)
    return line


def _refresh_run_width_if_due(state: _RunLoopState, current: datetime) -> None:
    if current < state.next_width_check_at:
        return
    state.next_width_check_at = current + timedelta(seconds=RUN_WIDTH_REFRESH_SECONDS)
    width_cols = _clamped_terminal_width(state.width_reader())
    if width_cols == state.width_cols:
        return
    state.width_cols = width_cols
    state.runner = state.terminal_run_module.TerminalRun(width_cols, state.character_name)


def _alarm_block_if_due(state: _RunLoopState, current: datetime) -> str | None:
    second = (
        current.year,
        current.month,
        current.day,
        current.hour,
        current.minute,
        current.second,
    )
    if second == state.last_alarm_second:
        return None
    state.last_alarm_second = second
    todos = state.get_todos()
    state.alarm_clock.update(todos)
    due = state.alarm_clock.due()
    if not due:
        return None
    return state.core_module.build_alarm_text(due, state.language)


def _reminder_block_if_due(state: _RunLoopState, current: datetime) -> str | None:
    if current < state.next_interval_at:
        return None
    state.next_interval_at = current + timedelta(minutes=state.interval_minutes)
    todos = state.get_todos()
    state.flag_text = state.core_module.build_flag_line(todos, state.language)
    return state.core_module.build_reminder_text(todos, state.language)


def _run_frames(sprites_module: Any, character_name: str, fallback: str) -> tuple[str, ...]:
    frames = tuple(sprites_module.gait_frames(character_name))
    if frames:
        return frames
    return (fallback,)


def _resolve_run_use_emoji(character: Any, *, force_ascii: bool) -> bool:
    use_emoji = False if force_ascii else None
    tui_module = importlib.import_module("todoy.display.tui")
    return bool(tui_module._resolve_use_emoji(character, use_emoji))


def _terminal_width_columns() -> int:
    return shutil.get_terminal_size().columns


def _clamped_terminal_width(width_cols: int) -> int:
    return max(MIN_RUN_WIDTH_COLS, width_cols)


def _stdout_write(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def _write_interrupt_newline(write: Callable[[str], None]) -> None:
    try:
        write("\n")
    except KeyboardInterrupt:
        pass


def _init(args: argparse.Namespace, source: BuiltinSource) -> int:
    del args, source

    path = config_path()
    if path.exists():
        overwrite = input(f"Config already exists at {path}. Overwrite? [y/N]")
        if not _is_yes(overwrite):
            print("Aborted.")
            return 1

    enabled_sources = ["builtin"]
    markdown_folder: Path | None = None
    markdown_pinned: list[str] = []

    if _is_yes(input("Enable markdown source? [y/N]")):
        markdown_folder = _prompt_notes_folder()
        if not markdown_folder.exists():
            print(f"Warning: notes folder does not exist: {markdown_folder}", file=sys.stderr)
        markdown_pinned = _parse_pinned_notes(input("Pinned notes (comma-separated, optional):"))
        enabled_sources.append("markdown")

    config = Config(
        enabled_sources=enabled_sources,
        markdown_folder=markdown_folder,
        markdown_pinned=markdown_pinned,
        reminder_interval_minutes=_prompt_reminder_interval(),
        character=_prompt_character(),
        character_image=_prompt_character_image_path(),
    )
    written_path = save_config(config, path)
    print(f"Config written to {written_path}")
    return 0


def _is_yes(value: str) -> bool:
    return value.strip().lower() in {"y", "yes"}


def _prompt_notes_folder() -> Path:
    while True:
        raw_path = input("Notes folder path:")
        if raw_path.strip():
            return Path(raw_path).expanduser()


def _parse_pinned_notes(raw_notes: str) -> list[str]:
    return [note.strip() for note in raw_notes.split(",") if note.strip()]


def _prompt_reminder_interval() -> int:
    for _ in range(2):
        raw_interval = input("Reminder interval in minutes [30]:")
        if not raw_interval.strip():
            return DEFAULT_INTERVAL_MINUTES
        try:
            return int(raw_interval)
        except ValueError:
            pass
    return DEFAULT_INTERVAL_MINUTES


def _prompt_character() -> str:
    for _ in range(2):
        raw_character = input("Character [cat/dog/ghost/robot] (default cat):").strip()
        if not raw_character:
            return DEFAULT_CHARACTER
        try:
            return get_character(raw_character).name
        except ValueError:
            pass
    return DEFAULT_CHARACTER


def _prompt_character_image_path() -> Path | None:
    raw_path = input("Custom character image path (optional):").strip()
    if not raw_path:
        return None
    return Path(raw_path).expanduser()


def _fresh_swept_builtin_source(config: Config) -> object:
    source = BuiltinSource()
    _sweep_if_daily_clear(source, config)
    return source


def _build_panel_actions(base_module: Any, config: Config) -> object:
    def add(text: str, at: str | None) -> str | None:
        try:
            parsed_at = parse_at(at) if at is not None else None
            source = _fresh_swept_builtin_source(config)
            _source_add(source, text, at=parsed_at, pinned=False)
        except Exception as exc:
            return _action_error(exc)
        return None

    def set_done(todo_id: int) -> str | None:
        try:
            source = _fresh_swept_builtin_source(config)
            _source_done(source, todo_id)
        except Exception as exc:
            return _action_error(exc)
        return None

    def delete(todo_id: int) -> str | None:
        try:
            source = _fresh_swept_builtin_source(config)
            _source_delete(source, todo_id)
        except Exception as exc:
            return _action_error(exc)
        return None

    def set_pinned(todo_id: int, pinned: bool) -> str | None:
        try:
            source = _fresh_swept_builtin_source(config)
            _source_set_pinned(source, todo_id, pinned)
        except Exception as exc:
            return _action_error(exc)
        return None

    return base_module.PanelActions(
        add=add,
        set_done=set_done,
        delete=delete,
        set_pinned=set_pinned,
    )


def _overlay(args: argparse.Namespace, source: BuiltinSource) -> int:
    del source

    config = load_config()
    language = resolve_language(args.lang)
    interval_minutes = (
        args.interval if args.interval is not None else config.reminder_interval_minutes
    )
    animations_module = importlib.import_module("todoy.display.overlay.animations")
    configured_movement = animations_module.validate_movement(
        args.movement if args.movement is not None else config.movement
    )
    bubble_effect = animations_module.validate_bubble_effect(
        args.bubble_effect if args.bubble_effect is not None else config.bubble_effect
    )
    configured_message_style = animations_module.validate_message_style(
        args.message_style if args.message_style is not None else config.message_style
    )

    core_module = importlib.import_module("todoy.display.overlay.core")
    build_reminder_text = core_module.build_reminder_text

    if args.once:
        builtin_todos, non_builtin_todos = _collect_todos(include_done=False, config=config)
        print(build_reminder_text([*builtin_todos, *non_builtin_todos], language))
        return 0

    base_module = importlib.import_module("todoy.display.overlay.base")
    character = get_character(args.character if args.character is not None else config.character)
    movement = _resolve_overlay_movement(configured_movement, character.name, animations_module)
    message_style = _resolve_overlay_message_style(
        configured_message_style,
        character.name,
        animations_module,
    )
    scheduler = core_module.ReminderScheduler(interval_minutes, config.snooze_minutes)
    assert movement != "auto"
    assert message_style != "auto"
    options = base_module.OverlayOptions(
        character=character,
        character_image=config.character_image,
        language=language,
        test_seconds=_overlay_test_seconds(),
        movement=movement,
        bubble_effect=bubble_effect,
        message_style=message_style,
    )

    try:
        backend = base_module.create_backend()
    except RuntimeError as exc:
        print(sanitize_text(str(exc)), file=sys.stderr)
        return 1

    def get_todos() -> list[Todo]:
        builtin_todos, non_builtin_todos = _collect_todos(include_done=False, config=config)
        return [*builtin_todos, *non_builtin_todos]

    def get_reminder_text() -> str:
        return build_reminder_text(get_todos(), language)

    actions = _build_panel_actions(base_module, config)
    return backend.run(options, scheduler, get_reminder_text, get_todos, actions)


def _resolve_overlay_movement(
    configured_movement: str,
    character_name: str,
    animations_module: Any,
) -> str:
    if configured_movement != "auto":
        return configured_movement

    personas_module = importlib.import_module("todoy.display.overlay.personas")
    movement = animations_module.validate_movement(personas_module.persona(character_name).movement)
    if movement == "auto":
        raise ValueError("Persona movement must be concrete, not auto")
    return movement


def _resolve_overlay_message_style(
    configured_message_style: str,
    character_name: str,
    animations_module: Any,
) -> str:
    if configured_message_style != "auto":
        return configured_message_style

    personas_module = importlib.import_module("todoy.display.overlay.personas")
    message_style = "flag" if personas_module.persona(character_name).banner else "bubble"
    return animations_module.validate_message_style(message_style)


def _overlay_test_seconds() -> float | None:
    raw_value = os.environ.get("TODOY_OVERLAY_TEST_SECONDS")
    if raw_value is None or not raw_value.strip():
        return None
    return float(raw_value)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if isinstance(exc.code, int):
            return exc.code
        return 2

    handler: CommandHandler = args.handler
    try:
        return handler(args, BuiltinSource())
    except ValueError as exc:
        print(sanitize_text(str(exc)), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
