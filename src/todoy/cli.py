"""todoy command-line interface."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from todoy.config import (
    DEFAULT_INTERVAL_MINUTES,
    Config,
    build_sources,
    config_path,
    load_config,
    save_config,
)
from todoy.models import Todo
from todoy.sources.builtin import BuiltinSource

CommandHandler = Callable[[argparse.Namespace, BuiltinSource], int]


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

    init_parser = subparsers.add_parser("init")
    init_parser.set_defaults(handler=_init)

    return parser


def _sanitize_todo_text(text: str) -> str:
    return "".join(ch for ch in text if ch.isprintable() or ch == " ")


def _todo_id(todo: Todo) -> int:
    if todo.id is None:
        msg = "Builtin todo is missing an id"
        raise ValueError(msg)
    return todo.id


def _add(args: argparse.Namespace, source: BuiltinSource) -> int:
    todo = source.add(args.text)
    print(f"Added #{_todo_id(todo)}: {_sanitize_todo_text(todo.text)}")
    return 0


def _done(args: argparse.Namespace, source: BuiltinSource) -> int:
    try:
        todo = source.done(args.todo_id)
    except KeyError:
        print(f"No todo with id {args.todo_id}", file=sys.stderr)
        return 1

    print(f"Done #{_todo_id(todo)}: {_sanitize_todo_text(todo.text)}")
    return 0


def _list(args: argparse.Namespace, source: BuiltinSource) -> int:
    del source

    builtin_todos: list[Todo] = []
    non_builtin_todos: list[Todo] = []
    for configured_source in build_sources(load_config()):
        if isinstance(configured_source, BuiltinSource):
            builtin_todos.extend(configured_source.list_todos(include_done=args.include_done))
        else:
            non_builtin_todos.extend(configured_source.get_todos())

    if not builtin_todos and not non_builtin_todos:
        print("No todos for today 🎉")
        return 0

    for todo in builtin_todos:
        marker = "[x] " if todo.done else ""
        print(f"  {_todo_id(todo)}. {marker}{_sanitize_todo_text(todo.text)}")
    for todo in non_builtin_todos:
        print(f"  - {_sanitize_todo_text(todo.text)}")
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
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
