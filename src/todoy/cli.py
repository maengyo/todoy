"""todoy command-line interface."""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from collections.abc import Callable
from pathlib import Path

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
from todoy.display.tui import render_tui
from todoy.models import Todo
from todoy.sources.builtin import BuiltinSource

CommandHandler = Callable[[argparse.Namespace, BuiltinSource], int]
MOVEMENT_CHOICES = ("walk", "hop", "float", "dash", "still")
BUBBLE_EFFECT_CHOICES = ("pop", "fade", "slide", "shake", "none")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="todoy")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add")
    add_parser.add_argument("text")
    add_parser.set_defaults(handler=_add)

    done_parser = subparsers.add_parser("done")
    done_parser.add_argument("todo_id", type=int, metavar="id")
    done_parser.set_defaults(handler=_done)

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
    overlay_parser.add_argument("--movement", choices=MOVEMENT_CHOICES)
    overlay_parser.add_argument("--bubble-effect", choices=BUBBLE_EFFECT_CHOICES)
    overlay_parser.set_defaults(handler=_overlay)

    return parser


def _todo_id(todo: Todo) -> int:
    if todo.id is None:
        msg = "Builtin todo is missing an id"
        raise ValueError(msg)
    return todo.id


def _add(args: argparse.Namespace, source: BuiltinSource) -> int:
    todo = source.add(args.text)
    print(f"Added #{_todo_id(todo)}: {sanitize_text(todo.text)}")
    return 0


def _done(args: argparse.Namespace, source: BuiltinSource) -> int:
    try:
        todo = source.done(args.todo_id)
    except KeyError:
        print(f"No todo with id {args.todo_id}", file=sys.stderr)
        return 1

    print(f"Done #{_todo_id(todo)}: {sanitize_text(todo.text)}")
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
        if isinstance(configured_source, BuiltinSource):
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
        print(f"  {_todo_id(todo)}. {marker}{sanitize_text(todo.text)}")
    for todo in non_builtin_todos:
        print(f"  - {sanitize_text(todo.text)}")
    return 0


def _tui(args: argparse.Namespace, source: BuiltinSource) -> int:
    del source

    character = get_character(args.character)
    language = resolve_language(args.lang)
    builtin_todos, non_builtin_todos = _collect_todos(include_done=False)
    use_emoji = False if args.force_ascii else None
    print(
        render_tui(
            [*builtin_todos, *non_builtin_todos],
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

    core_module = importlib.import_module("todoy.display.overlay.core")
    build_reminder_text = core_module.build_reminder_text

    if args.once:
        builtin_todos, non_builtin_todos = _collect_todos(include_done=False, config=config)
        print(build_reminder_text([*builtin_todos, *non_builtin_todos], language))
        return 0

    base_module = importlib.import_module("todoy.display.overlay.base")
    character = get_character(config.character)
    scheduler = core_module.ReminderScheduler(interval_minutes, config.snooze_minutes)
    options = base_module.OverlayOptions(
        character=character,
        character_image=config.character_image,
        language=language,
        test_seconds=_overlay_test_seconds(),
        movement=movement,
        bubble_effect=bubble_effect,
    )

    try:
        backend = base_module.create_backend()
    except RuntimeError as exc:
        print(sanitize_text(str(exc)), file=sys.stderr)
        return 1

    def get_reminder_text() -> str:
        builtin_todos, non_builtin_todos = _collect_todos(include_done=False, config=config)
        return build_reminder_text([*builtin_todos, *non_builtin_todos], language)

    return backend.run(options, scheduler, get_reminder_text)


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
