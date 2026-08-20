"""Built-in JSON-file todo storage."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from datetime import date
from pathlib import Path

from todoy.models import Todo, parse_at
from todoy.sources.base import Source


def _default_path() -> Path:
    env_override = os.environ.get("TODOY_DATA_FILE")
    if env_override:
        return Path(env_override)

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        base = Path(xdg_data_home)
    else:
        base = Path.home() / ".local" / "share"

    return base / "todoy" / "todos.json"


class BuiltinSource(Source):
    """Stores todos in a local JSON file (default: XDG data dir)."""

    name = "builtin"

    def __init__(self, path: Path | None = None, today: Callable[[], date] = date.today) -> None:
        self.path = path if path is not None else _default_path()
        self._today = today

    def get_todos(self) -> list[Todo]:
        """Return today's open (not done) todos."""
        return self.list_todos(include_done=False)

    def add(self, text: str, at: str | None = None, pinned: bool = False) -> Todo:
        if at is not None:
            at = parse_at(at)
        todos = self._load()
        next_id = max((t.id for t in todos if t.id is not None), default=0) + 1
        created = self._today().isoformat()
        todo = Todo(
            text=text,
            done=False,
            id=next_id,
            source=self.name,
            at=at,
            pinned=pinned,
            created=created,
        )
        todos.append(todo)
        self._save(todos)
        return todo

    def done(self, todo_id: int) -> Todo:
        todos = self._load()
        for i, todo in enumerate(todos):
            if todo.id == todo_id:
                updated = Todo(
                    text=todo.text,
                    done=True,
                    id=todo.id,
                    source=todo.source,
                    at=todo.at,
                    pinned=todo.pinned,
                    created=todo.created,
                )
                todos[i] = updated
                self._save(todos)
                return updated
        raise KeyError(f"No todo with id {todo_id}")

    def set_pinned(self, todo_id: int, pinned: bool) -> Todo:
        todos = self._load()
        for i, todo in enumerate(todos):
            if todo.id == todo_id:
                updated = Todo(
                    text=todo.text,
                    done=todo.done,
                    id=todo.id,
                    source=todo.source,
                    at=todo.at,
                    pinned=pinned,
                    created=todo.created,
                )
                todos[i] = updated
                self._save(todos)
                return updated
        raise KeyError(f"No todo with id {todo_id}")

    def delete(self, todo_id: int) -> Todo:
        todos = self._load()
        for i, todo in enumerate(todos):
            if todo.id == todo_id:
                removed = todos.pop(i)
                self._save(todos)
                return removed
        raise KeyError(f"No todo with id {todo_id}")

    def sweep(self, today: date) -> int:
        """Remove stale, non-pinned todos and migrate legacy created=None rows.

        A todo is removed (regardless of its done status) when its `created`
        date is strictly before `today` and it is not pinned. Rows with
        `created=None` (written before this field existed) are not removed;
        instead they are stamped with `today` in place, since we have no way
        to know their true age. Persists only if anything changed. Returns
        the number of todos removed.
        """
        todos = self._load()
        kept: list[Todo] = []
        removed_count = 0
        changed = False
        today_str = today.isoformat()

        for todo in todos:
            if todo.created is None:
                todo = Todo(
                    text=todo.text,
                    done=todo.done,
                    id=todo.id,
                    source=todo.source,
                    at=todo.at,
                    pinned=todo.pinned,
                    created=today_str,
                )
                changed = True
                kept.append(todo)
                continue

            created_date = date.fromisoformat(todo.created)
            if created_date < today and not todo.pinned:
                removed_count += 1
                changed = True
                continue

            kept.append(todo)

        if changed:
            self._save(kept)
        return removed_count

    def list_todos(self, include_done: bool = False) -> list[Todo]:
        todos = self._load()
        if include_done:
            return todos
        return [t for t in todos if not t.done]

    def _load(self) -> list[Todo]:
        if not self.path.exists():
            return []

        raw = self.path.read_text(encoding="utf-8")
        if not raw.strip():
            return []

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"Corrupt todos file at {self.path}: {e}") from e

        try:
            return [Todo.from_dict(d) for d in data["todos"]]
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"Corrupt todos file at {self.path}: {e}") from e

    def _save(self, todos: list[Todo]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"todos": [t.to_dict() for t in todos]}

        fd, tmp_name = tempfile.mkstemp(dir=self.path.parent, prefix=".todos-", suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            os.replace(tmp_name, self.path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
