import pytest

from todoy.models import Todo


def test_todo_defaults():
    t = Todo(text="buy milk")
    assert t.text == "buy milk"
    assert t.done is False
    assert t.id is None
    assert t.source == "builtin"


def test_todo_to_dict():
    t = Todo(text="buy milk", done=True, id=3, source="builtin")
    assert t.to_dict() == {
        "id": 3,
        "text": "buy milk",
        "done": True,
        "source": "builtin",
    }


def test_todo_from_dict():
    d = {"id": 5, "text": "walk dog", "done": False, "source": "builtin"}
    t = Todo.from_dict(d)
    assert t == Todo(text="walk dog", done=False, id=5, source="builtin")


def test_todo_roundtrip():
    t = Todo(text="한글 할 일 🎉", done=True, id=1, source="markdown")
    assert Todo.from_dict(t.to_dict()) == t


def test_todo_from_dict_defaults_missing_keys():
    # from_dict should tolerate a minimal dict (e.g. only text present)
    d = {"text": "only text"}
    t = Todo.from_dict(d)
    assert t.text == "only text"
    assert t.done is False
    assert t.id is None
    assert t.source == "builtin"


def test_todo_from_dict_missing_text_raises_valueerror():
    with pytest.raises(ValueError):
        Todo.from_dict({"id": 1, "done": False, "source": "builtin"})


def test_todo_from_dict_rejects_non_string_text():
    with pytest.raises(ValueError):
        Todo.from_dict({"text": 123})


def test_todo_from_dict_rejects_string_id():
    with pytest.raises(ValueError):
        Todo.from_dict({"text": "x", "id": "abc"})


def test_todo_from_dict_rejects_bool_id():
    # bool is a subclass of int in Python, but must NOT be accepted as a valid id.
    with pytest.raises(ValueError):
        Todo.from_dict({"text": "x", "id": True})


def test_todo_from_dict_rejects_non_bool_done():
    with pytest.raises(ValueError):
        Todo.from_dict({"text": "x", "done": "yes"})


def test_todo_from_dict_rejects_non_string_source():
    with pytest.raises(ValueError):
        Todo.from_dict({"text": "x", "source": 42})


def test_todo_from_dict_accepts_none_id():
    t = Todo.from_dict({"text": "x", "id": None})
    assert t.id is None
