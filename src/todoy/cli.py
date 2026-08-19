"""todoy command-line interface."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

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

    return parser


def _todo_id(todo: Todo) -> int:
    if todo.id is None:
        msg = "Builtin todo is missing an id"
        raise ValueError(msg)
    return todo.id


def _add(args: argparse.Namespace, source: BuiltinSource) -> int:
    todo = source.add(args.text)
    print(f"Added #{_todo_id(todo)}: {todo.text}")
    return 0


def _done(args: argparse.Namespace, source: BuiltinSource) -> int:
    try:
        todo = source.done(args.todo_id)
    except KeyError:
        print(f"No todo with id {args.todo_id}", file=sys.stderr)
        return 1

    print(f"Done #{_todo_id(todo)}: {todo.text}")
    return 0


def _list(args: argparse.Namespace, source: BuiltinSource) -> int:
    todos = source.list_todos(include_done=args.include_done)
    if not todos:
        print("No todos for today 🎉")
        return 0

    for todo in todos:
        marker = "[x] " if todo.done else ""
        print(f"  {_todo_id(todo)}. {marker}{todo.text}")
    return 0


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
