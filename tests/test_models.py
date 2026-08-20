import pytest

from todoy.models import Todo, parse_at, parse_date


def test_todo_defaults():
    t = Todo(text="buy milk")
    assert t.text == "buy milk"
    assert t.done is False
    assert t.id is None
    assert t.source == "builtin"
    assert t.at is None
    assert t.pinned is False
    assert t.created is None


def test_todo_to_dict():
    t = Todo(text="buy milk", done=True, id=3, source="builtin")
    assert t.to_dict() == {
        "id": 3,
        "text": "buy milk",
        "done": True,
        "source": "builtin",
        "at": None,
        "pinned": False,
        "created": None,
    }


def test_todo_to_dict_includes_at():
    t = Todo(text="meeting", id=1, source="builtin", at="14:00")
    assert t.to_dict() == {
        "id": 1,
        "text": "meeting",
        "done": False,
        "source": "builtin",
        "at": "14:00",
        "pinned": False,
        "created": None,
    }


def test_todo_to_dict_includes_pinned_and_created():
    t = Todo(text="meeting", id=1, source="builtin", pinned=True, created="2026-08-20")
    assert t.to_dict() == {
        "id": 1,
        "text": "meeting",
        "done": False,
        "source": "builtin",
        "at": None,
        "pinned": True,
        "created": "2026-08-20",
    }


def test_todo_from_dict():
    d = {"id": 5, "text": "walk dog", "done": False, "source": "builtin"}
    t = Todo.from_dict(d)
    assert t == Todo(text="walk dog", done=False, id=5, source="builtin")


def test_todo_roundtrip():
    t = Todo(text="한글 할 일 🎉", done=True, id=1, source="markdown")
    assert Todo.from_dict(t.to_dict()) == t


def test_todo_roundtrip_with_at():
    t = Todo(text="meeting", done=False, id=1, source="builtin", at="09:30")
    assert Todo.from_dict(t.to_dict()) == t


def test_todo_from_dict_defaults_missing_keys():
    # from_dict should tolerate a minimal dict (e.g. only text present)
    d = {"text": "only text"}
    t = Todo.from_dict(d)
    assert t.text == "only text"
    assert t.done is False
    assert t.id is None
    assert t.source == "builtin"
    assert t.at is None
    assert t.pinned is False
    assert t.created is None


def test_todo_from_dict_back_compat_old_json_without_pinned_or_created():
    # Simulates a todos.json row written before pinned/created existed.
    d = {"id": 5, "text": "legacy row", "done": False, "source": "builtin", "at": None}
    t = Todo.from_dict(d)
    assert t.pinned is False
    assert t.created is None


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


def test_todo_from_dict_missing_at_key_defaults_to_none():
    # Back-compat: old JSON rows written before `at` existed have no key at all.
    t = Todo.from_dict({"text": "x", "id": 1, "done": False, "source": "builtin"})
    assert t.at is None


def test_todo_from_dict_accepts_none_at():
    t = Todo.from_dict({"text": "x", "at": None})
    assert t.at is None


def test_todo_from_dict_accepts_valid_at():
    t = Todo.from_dict({"text": "x", "at": "14:00"})
    assert t.at == "14:00"


def test_todo_from_dict_pads_unpadded_hour_at():
    t = Todo.from_dict({"text": "x", "at": "9:30"})
    assert t.at == "09:30"


def test_todo_from_dict_rejects_non_string_at():
    with pytest.raises(ValueError, match="Todo 'at' must be 'HH:MM' or null"):
        Todo.from_dict({"text": "x", "at": 1400})


@pytest.mark.parametrize("bad_at", ["24:00", "9:60", "9:5", "ㅁ:ㅁ", "not a time", "", "９:３０"])
def test_todo_from_dict_rejects_invalid_at_format(bad_at):
    with pytest.raises(ValueError, match="Todo 'at' must be 'HH:MM' or null"):
        Todo.from_dict({"text": "x", "at": bad_at})


def test_todo_from_dict_missing_pinned_key_defaults_to_false():
    t = Todo.from_dict({"text": "x", "id": 1, "done": False, "source": "builtin"})
    assert t.pinned is False


def test_todo_from_dict_accepts_pinned_true():
    t = Todo.from_dict({"text": "x", "pinned": True})
    assert t.pinned is True


def test_todo_from_dict_rejects_non_bool_pinned():
    with pytest.raises(ValueError, match="Todo 'pinned' must be a bool"):
        Todo.from_dict({"text": "x", "pinned": "yes"})


def test_todo_from_dict_missing_created_key_defaults_to_none():
    t = Todo.from_dict({"text": "x", "id": 1, "done": False, "source": "builtin"})
    assert t.created is None


def test_todo_from_dict_accepts_none_created():
    t = Todo.from_dict({"text": "x", "created": None})
    assert t.created is None


def test_todo_from_dict_accepts_valid_created():
    t = Todo.from_dict({"text": "x", "created": "2026-08-20"})
    assert t.created == "2026-08-20"


def test_todo_from_dict_rejects_non_string_created():
    with pytest.raises(ValueError, match="Todo 'created' must be 'YYYY-MM-DD' or null"):
        Todo.from_dict({"text": "x", "created": 20260820})


@pytest.mark.parametrize(
    "bad_created",
    [
        "2026-8-20",
        "2026/08/20",
        "2026-13-01",
        "2026-02-30",
        "not a date",
        "",
        "2026-08-20T00:00",
        "２０２６-０８-２０",
    ],
)
def test_todo_from_dict_rejects_invalid_created_format(bad_created):
    with pytest.raises(ValueError, match="Todo 'created' must be 'YYYY-MM-DD' or null"):
        Todo.from_dict({"text": "x", "created": bad_created})


def test_todo_roundtrip_with_pinned_and_created():
    t = Todo(text="meeting", done=False, id=1, source="builtin", pinned=True, created="2026-08-20")
    assert Todo.from_dict(t.to_dict()) == t


class TestParseAt:
    def test_accepts_padded_time(self):
        assert parse_at("14:00") == "14:00"

    def test_pads_unpadded_hour(self):
        assert parse_at("9:30") == "09:30"

    def test_accepts_midnight_and_end_of_day(self):
        assert parse_at("0:00") == "00:00"
        assert parse_at("23:59") == "23:59"

    @pytest.mark.parametrize(
        "value",
        [
            "24:00",  # hour out of range
            "9:60",  # minute out of range
            "9:5",  # minute must be exactly 2 digits
            "ㅁ:ㅁ",  # non-digit garbage
            "9",  # no colon/minute at all
            "9:",  # missing minute
            ":30",  # missing hour
            "9:030",  # minute too long
            "099:30",  # hour too long
            "9:30 ",  # trailing whitespace not stripped by caller
            " 9:30",  # leading whitespace not stripped by caller
            "",  # empty string
            "９:３０",  # full-width Unicode digits — must not be accepted as ASCII digits
        ],
    )
    def test_rejects_invalid_values(self, value):
        with pytest.raises(ValueError):
            parse_at(value)


class TestParseDate:
    def test_accepts_canonical_date(self):
        assert parse_date("2026-08-20") == "2026-08-20"

    def test_accepts_leap_day(self):
        assert parse_date("2024-02-29") == "2024-02-29"

    @pytest.mark.parametrize(
        "value",
        [
            "2026-8-20",  # month must be exactly 2 digits
            "2026-08-2",  # day must be exactly 2 digits
            "26-08-20",  # year must be exactly 4 digits
            "2026/08/20",  # wrong separator
            "2026-13-01",  # month out of range
            "2026-00-01",  # month out of range (zero)
            "2026-02-30",  # not a real day (Feb has 28/29 days)
            "2025-02-29",  # not a leap year
            "2026-08-20T00:00",  # trailing content
            "not a date",
            "",
            " 2026-08-20",  # leading whitespace not stripped by caller
            "2026-08-20 ",  # trailing whitespace not stripped by caller
            "２０２６-０８-２０",  # full-width Unicode digits, not ASCII — must be rejected
        ],
    )
    def test_rejects_invalid_values(self, value):
        with pytest.raises(ValueError):
            parse_date(value)
