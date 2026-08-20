import json
from datetime import date

import pytest

from todoy.models import Todo
from todoy.sources.base import Source
from todoy.sources.builtin import BuiltinSource


def test_is_source_subclass():
    assert issubclass(BuiltinSource, Source)
    assert BuiltinSource.name == "builtin"


def test_add_returns_todo_with_assigned_id(tmp_path):
    src = BuiltinSource(path=tmp_path / "todos.json")
    todo = src.add("buy milk")
    assert isinstance(todo, Todo)
    assert todo.id == 1
    assert todo.text == "buy milk"
    assert todo.done is False
    assert todo.source == "builtin"


def test_add_assigns_incrementing_ids(tmp_path):
    src = BuiltinSource(path=tmp_path / "todos.json")
    t1 = src.add("first")
    t2 = src.add("second")
    assert t1.id == 1
    assert t2.id == 2


def test_list_todos_default_excludes_done(tmp_path):
    src = BuiltinSource(path=tmp_path / "todos.json")
    t1 = src.add("open task")
    t2 = src.add("will be done")
    src.done(t2.id)

    open_todos = src.list_todos()
    assert [t.id for t in open_todos] == [t1.id]


def test_list_todos_include_done(tmp_path):
    src = BuiltinSource(path=tmp_path / "todos.json")
    t1 = src.add("open task")
    t2 = src.add("will be done")
    src.done(t2.id)

    all_todos = src.list_todos(include_done=True)
    assert {t.id for t in all_todos} == {t1.id, t2.id}
    done_map = {t.id: t.done for t in all_todos}
    assert done_map[t1.id] is False
    assert done_map[t2.id] is True


def test_get_todos_returns_only_open(tmp_path):
    src = BuiltinSource(path=tmp_path / "todos.json")
    t1 = src.add("open task")
    t2 = src.add("done task")
    src.done(t2.id)

    todos = src.get_todos()
    assert [t.id for t in todos] == [t1.id]


def test_done_marks_and_persists(tmp_path):
    path = tmp_path / "todos.json"
    src = BuiltinSource(path=path)
    todo = src.add("finish report")
    updated = src.done(todo.id)
    assert updated.done is True
    assert updated.id == todo.id

    # reload from disk in a fresh instance
    src2 = BuiltinSource(path=path)
    reloaded = src2.list_todos(include_done=True)
    assert reloaded[0].done is True


def test_done_unknown_id_raises_keyerror(tmp_path):
    src = BuiltinSource(path=tmp_path / "todos.json")
    with pytest.raises(KeyError):
        src.done(999)


def test_persistence_across_instances(tmp_path):
    path = tmp_path / "todos.json"
    src1 = BuiltinSource(path=path)
    src1.add("persisted task")

    src2 = BuiltinSource(path=path)
    todos = src2.list_todos()
    assert len(todos) == 1
    assert todos[0].text == "persisted task"


def test_id_never_reused_after_done(tmp_path):
    path = tmp_path / "todos.json"
    src = BuiltinSource(path=path)
    t1 = src.add("a")
    src.done(t1.id)
    t2 = src.add("b")
    assert t2.id == 2
    assert t2.id != t1.id


def test_missing_file_returns_empty_list(tmp_path):
    path = tmp_path / "does_not_exist" / "todos.json"
    src = BuiltinSource(path=path)
    assert src.list_todos() == []
    assert src.get_todos() == []


def test_empty_file_returns_empty_list(tmp_path):
    path = tmp_path / "todos.json"
    path.write_text("")
    src = BuiltinSource(path=path)
    assert src.list_todos() == []


def test_corrupt_json_raises_valueerror_with_path(tmp_path):
    path = tmp_path / "todos.json"
    path.write_text("{not valid json")
    src = BuiltinSource(path=path)
    with pytest.raises(ValueError) as excinfo:
        src.list_todos()
    assert str(path) in str(excinfo.value)


def test_json_valid_but_wrong_field_types_raises_valueerror_with_path(tmp_path):
    # JSON-valid file, but "id" is a string instead of an int — must be treated as
    # corrupt data, not crash downstream (e.g. in add()'s max(...) + 1) with a raw TypeError.
    path = tmp_path / "todos.json"
    path.write_text(
        json.dumps({"todos": [{"id": "abc", "text": "x", "done": False, "source": "builtin"}]}),
        encoding="utf-8",
    )
    src = BuiltinSource(path=path)
    with pytest.raises(ValueError) as excinfo:
        src.list_todos()
    assert str(path) in str(excinfo.value)


def test_add_on_file_with_wrong_field_types_raises_valueerror_not_typeerror(tmp_path):
    path = tmp_path / "todos.json"
    path.write_text(
        json.dumps({"todos": [{"id": "abc", "text": "x", "done": False, "source": "builtin"}]}),
        encoding="utf-8",
    )
    src = BuiltinSource(path=path)
    with pytest.raises(ValueError) as excinfo:
        src.add("y")
    assert str(path) in str(excinfo.value)


def test_storage_file_format(tmp_path):
    path = tmp_path / "todos.json"
    src = BuiltinSource(path=path)
    src.add("check format")

    data = json.loads(path.read_text(encoding="utf-8"))
    assert "todos" in data
    assert isinstance(data["todos"], list)
    assert data["todos"][0]["text"] == "check format"
    assert data["todos"][0]["id"] == 1
    assert data["todos"][0]["done"] is False
    assert data["todos"][0]["source"] == "builtin"


def test_parent_dirs_created_lazily_on_write(tmp_path):
    path = tmp_path / "nested" / "dir" / "todos.json"
    assert not path.parent.exists()
    src = BuiltinSource(path=path)
    src.add("creates dirs")
    assert path.exists()


def test_default_path_uses_env_var_override(tmp_path, monkeypatch):
    override = tmp_path / "custom_todos.json"
    monkeypatch.setenv("TODOY_DATA_FILE", str(override))
    src = BuiltinSource()
    src.add("via env var")
    assert override.exists()


def test_default_path_uses_xdg_data_home(tmp_path, monkeypatch):
    monkeypatch.delenv("TODOY_DATA_FILE", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    src = BuiltinSource()
    src.add("via xdg")
    expected = tmp_path / "todoy" / "todos.json"
    assert expected.exists()


def test_default_path_falls_back_to_home(fake_home, monkeypatch):
    monkeypatch.delenv("TODOY_DATA_FILE", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    src = BuiltinSource()
    expected = fake_home / ".local" / "share" / "todoy" / "todos.json"
    assert src.path == expected


def test_add_without_at_defaults_to_none(tmp_path):
    src = BuiltinSource(path=tmp_path / "todos.json")
    todo = src.add("buy milk")
    assert todo.at is None


def test_add_with_at_stores_canonical_padded_form(tmp_path):
    src = BuiltinSource(path=tmp_path / "todos.json")
    todo = src.add("meeting", at="9:30")
    assert todo.at == "09:30"


def test_add_with_invalid_at_raises_valueerror(tmp_path):
    src = BuiltinSource(path=tmp_path / "todos.json")
    with pytest.raises(ValueError):
        src.add("meeting", at="24:00")


def test_at_round_trips_through_json(tmp_path):
    path = tmp_path / "todos.json"
    src = BuiltinSource(path=path)
    added = src.add("meeting", at="14:00")

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["todos"][0]["at"] == "14:00"

    src2 = BuiltinSource(path=path)
    reloaded = src2.list_todos(include_done=True)
    assert reloaded[0].at == "14:00"
    assert reloaded[0] == added


def test_old_json_file_without_at_key_loads_with_at_none(tmp_path):
    # Simulates a todos.json written before the `at` field existed.
    path = tmp_path / "todos.json"
    legacy_row = {"id": 1, "text": "legacy task", "done": False, "source": "builtin"}
    path.write_text(json.dumps({"todos": [legacy_row]}), encoding="utf-8")
    src = BuiltinSource(path=path)
    todos = src.list_todos()
    assert todos[0].at is None
    assert todos[0].text == "legacy task"


def test_done_preserves_at(tmp_path):
    path = tmp_path / "todos.json"
    src = BuiltinSource(path=path)
    todo = src.add("meeting", at="14:00")
    updated = src.done(todo.id)
    assert updated.at == "14:00"


def test_add_stamps_created_with_injectable_today(tmp_path):
    src = BuiltinSource(path=tmp_path / "todos.json", today=lambda: date(2026, 8, 20))
    todo = src.add("buy milk")
    assert todo.created == "2026-08-20"


def test_add_uses_real_today_by_default(tmp_path):
    src = BuiltinSource(path=tmp_path / "todos.json")
    todo = src.add("buy milk")
    assert todo.created == date.today().isoformat()


def test_add_defaults_pinned_false(tmp_path):
    src = BuiltinSource(path=tmp_path / "todos.json")
    todo = src.add("buy milk")
    assert todo.pinned is False


def test_add_with_pinned_true(tmp_path):
    src = BuiltinSource(path=tmp_path / "todos.json")
    todo = src.add("buy milk", pinned=True)
    assert todo.pinned is True


def test_done_preserves_pinned_and_created(tmp_path):
    src = BuiltinSource(path=tmp_path / "todos.json", today=lambda: date(2026, 8, 20))
    todo = src.add("finish report", pinned=True)
    updated = src.done(todo.id)
    assert updated.pinned is True
    assert updated.created == "2026-08-20"


class TestSetPinned:
    def test_sets_pinned_true(self, tmp_path):
        src = BuiltinSource(path=tmp_path / "todos.json")
        todo = src.add("task")
        updated = src.set_pinned(todo.id, True)
        assert updated.pinned is True
        assert updated.id == todo.id

    def test_sets_pinned_false(self, tmp_path):
        src = BuiltinSource(path=tmp_path / "todos.json")
        todo = src.add("task", pinned=True)
        updated = src.set_pinned(todo.id, False)
        assert updated.pinned is False

    def test_persists(self, tmp_path):
        path = tmp_path / "todos.json"
        src = BuiltinSource(path=path)
        todo = src.add("task")
        src.set_pinned(todo.id, True)

        src2 = BuiltinSource(path=path)
        reloaded = src2.list_todos(include_done=True)
        assert reloaded[0].pinned is True

    def test_preserves_other_fields(self, tmp_path):
        src = BuiltinSource(path=tmp_path / "todos.json", today=lambda: date(2026, 8, 20))
        todo = src.add("meeting", at="14:00")
        updated = src.set_pinned(todo.id, True)
        assert updated.text == "meeting"
        assert updated.at == "14:00"
        assert updated.created == "2026-08-20"
        assert updated.done is False

    def test_unknown_id_raises_keyerror(self, tmp_path):
        src = BuiltinSource(path=tmp_path / "todos.json")
        with pytest.raises(KeyError):
            src.set_pinned(999, True)


class TestDelete:
    def test_removes_and_returns_todo(self, tmp_path):
        src = BuiltinSource(path=tmp_path / "todos.json")
        t1 = src.add("keep")
        t2 = src.add("remove me")
        removed = src.delete(t2.id)
        assert removed.id == t2.id
        assert removed.text == "remove me"
        remaining = src.list_todos(include_done=True)
        assert [t.id for t in remaining] == [t1.id]

    def test_persists(self, tmp_path):
        path = tmp_path / "todos.json"
        src = BuiltinSource(path=path)
        todo = src.add("gone")
        src.delete(todo.id)

        src2 = BuiltinSource(path=path)
        assert src2.list_todos(include_done=True) == []

    def test_removes_done_todo_too(self, tmp_path):
        src = BuiltinSource(path=tmp_path / "todos.json")
        todo = src.add("finish")
        src.done(todo.id)
        removed = src.delete(todo.id)
        assert removed.done is True

    def test_unknown_id_raises_keyerror(self, tmp_path):
        src = BuiltinSource(path=tmp_path / "todos.json")
        with pytest.raises(KeyError):
            src.delete(999)


class TestSweep:
    def _make_source(self, tmp_path, add_today):
        return BuiltinSource(path=tmp_path / "todos.json", today=lambda: add_today)

    def test_removes_old_non_pinned_done_todo(self, tmp_path):
        src = self._make_source(tmp_path, date(2026, 8, 18))
        todo = src.add("old done task")
        src.done(todo.id)

        removed = src.sweep(date(2026, 8, 20))
        assert removed == 1
        assert src.list_todos(include_done=True) == []

    def test_removes_old_non_pinned_open_todo(self, tmp_path):
        src = self._make_source(tmp_path, date(2026, 8, 18))
        src.add("old open task")

        removed = src.sweep(date(2026, 8, 20))
        assert removed == 1
        assert src.list_todos(include_done=True) == []

    def test_keeps_pinned_old_todo(self, tmp_path):
        src = self._make_source(tmp_path, date(2026, 8, 18))
        todo = src.add("old pinned task", pinned=True)

        removed = src.sweep(date(2026, 8, 20))
        assert removed == 0
        remaining = src.list_todos(include_done=True)
        assert [t.id for t in remaining] == [todo.id]

    def test_keeps_todo_created_today(self, tmp_path):
        src = self._make_source(tmp_path, date(2026, 8, 20))
        todo = src.add("today task")

        removed = src.sweep(date(2026, 8, 20))
        assert removed == 0
        assert [t.id for t in src.list_todos(include_done=True)] == [todo.id]

    def test_keeps_todo_created_in_future(self, tmp_path):
        src = self._make_source(tmp_path, date(2026, 8, 21))
        todo = src.add("future task")

        removed = src.sweep(date(2026, 8, 20))
        assert removed == 0
        assert [t.id for t in src.list_todos(include_done=True)] == [todo.id]

    def test_migrates_created_none_rows_instead_of_deleting(self, tmp_path):
        path = tmp_path / "todos.json"
        legacy_row = {
            "id": 1,
            "text": "legacy row",
            "done": False,
            "source": "builtin",
            "at": None,
        }  # no "created" key at all -> Todo.from_dict defaults created=None
        path.write_text(json.dumps({"todos": [legacy_row]}), encoding="utf-8")
        src = BuiltinSource(path=path)

        removed = src.sweep(date(2026, 8, 20))
        assert removed == 0
        remaining = src.list_todos(include_done=True)
        assert len(remaining) == 1
        assert remaining[0].created == "2026-08-20"

    def test_returns_total_removed_count(self, tmp_path):
        src = self._make_source(tmp_path, date(2026, 8, 18))
        src.add("old 1")
        src.add("old 2")
        pinned = src.add("old pinned", pinned=True)

        removed = src.sweep(date(2026, 8, 20))
        assert removed == 2
        remaining = src.list_todos(include_done=True)
        assert [t.id for t in remaining] == [pinned.id]

    def test_persists_removal(self, tmp_path):
        path = tmp_path / "todos.json"
        src = BuiltinSource(path=path, today=lambda: date(2026, 8, 18))
        src.add("old task")

        src.sweep(date(2026, 8, 20))

        src2 = BuiltinSource(path=path)
        assert src2.list_todos(include_done=True) == []

    def test_persists_migration(self, tmp_path):
        path = tmp_path / "todos.json"
        legacy_row = {"id": 1, "text": "legacy row", "done": False, "source": "builtin"}
        path.write_text(json.dumps({"todos": [legacy_row]}), encoding="utf-8")
        src = BuiltinSource(path=path)
        src.sweep(date(2026, 8, 20))

        src2 = BuiltinSource(path=path)
        assert src2.list_todos(include_done=True)[0].created == "2026-08-20"
