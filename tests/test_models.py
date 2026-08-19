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
