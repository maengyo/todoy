"""todoy command-line interface."""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from collections.abc import Callable
from dataclasses import replace
from datetime import date
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
    movement = animations_module.validate_movement(
        args.movement if args.movement is not None else config.movement
    )
    bubble_effect = animations_module.validate_bubble_effect(
        args.bubble_effect if args.bubble_effect is not None else config.bubble_effect
    )
    message_style = animations_module.validate_message_style(
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
    scheduler = core_module.ReminderScheduler(interval_minutes, config.snooze_minutes)
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
