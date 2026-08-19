import json

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
