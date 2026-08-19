import os
import time
from datetime import date, timedelta
from pathlib import Path

import pytest

from todoy.sources.base import Source
from todoy.sources.markdown import MarkdownSource

TODAY = date(2026, 1, 15)
YESTERDAY = TODAY - timedelta(days=1)


def _touch(path: Path, content: str, when: date) -> None:
    path.write_text(content, encoding="utf-8")
    ts = time.mktime(when.timetuple())
    os.utime(path, (ts, ts))


def test_is_source_subclass():
    assert issubclass(MarkdownSource, Source)
    assert MarkdownSource.name == "markdown"


def test_open_checkbox_is_todo(tmp_path):
    note = tmp_path / "note.md"
    _touch(note, "- [ ] buy milk\n", TODAY)
    src = MarkdownSource(folder=tmp_path, today=TODAY)
    todos = src.get_todos()
    assert [t.text for t in todos] == ["buy milk"]
    assert todos[0].done is False
    assert todos[0].id is None
    assert todos[0].source == "markdown"


def test_plain_dash_is_todo(tmp_path):
    note = tmp_path / "note.md"
    _touch(note, "- water plants\n", TODAY)
    src = MarkdownSource(folder=tmp_path, today=TODAY)
    assert [t.text for t in src.get_todos()] == ["water plants"]


def test_done_checkbox_excluded(tmp_path):
    note = tmp_path / "note.md"
    _touch(note, "- [x] finished\n- [ ] pending\n", TODAY)
    src = MarkdownSource(folder=tmp_path, today=TODAY)
    assert [t.text for t in src.get_todos()] == ["pending"]


def test_done_checkbox_uppercase_x_excluded(tmp_path):
    note = tmp_path / "note.md"
    _touch(note, "- [X] finished\n- [ ] pending\n", TODAY)
    src = MarkdownSource(folder=tmp_path, today=TODAY)
    assert [t.text for t in src.get_todos()] == ["pending"]


def test_non_bullet_lines_ignored(tmp_path):
    note = tmp_path / "note.md"
    content = (
        "# Heading\n* asterisk bullet\n1. numbered item\nplain paragraph text\n- [ ] real todo\n"
    )
    _touch(note, content, TODAY)
    src = MarkdownSource(folder=tmp_path, today=TODAY)
    assert [t.text for t in src.get_todos()] == ["real todo"]


def test_empty_checkbox_text_skipped(tmp_path):
    note = tmp_path / "note.md"
    _touch(note, "- [ ]\n- [ ] \n- [ ] real one\n", TODAY)
    src = MarkdownSource(folder=tmp_path, today=TODAY)
    assert [t.text for t in src.get_todos()] == ["real one"]


def test_empty_dash_bullet_skipped(tmp_path):
    note = tmp_path / "note.md"
    _touch(note, "-\n- \n- [ ] real one\n", TODAY)
    src = MarkdownSource(folder=tmp_path, today=TODAY)
    assert [t.text for t in src.get_todos()] == ["real one"]


def test_blank_lines_ignored(tmp_path):
    note = tmp_path / "note.md"
    _touch(note, "\n\n- [ ] only one\n\n", TODAY)
    src = MarkdownSource(folder=tmp_path, today=TODAY)
    assert [t.text for t in src.get_todos()] == ["only one"]


def test_file_modified_today_included(tmp_path):
    note = tmp_path / "today.md"
    _touch(note, "- [ ] today task\n", TODAY)
    src = MarkdownSource(folder=tmp_path, today=TODAY)
    assert [t.text for t in src.get_todos()] == ["today task"]


def test_file_modified_yesterday_excluded_unless_pinned(tmp_path):
    note = tmp_path / "old.md"
    _touch(note, "- [ ] old task\n", YESTERDAY)
    src = MarkdownSource(folder=tmp_path, today=TODAY)
    assert src.get_todos() == []


def test_pinned_old_file_included(tmp_path):
    note = tmp_path / "old.md"
    _touch(note, "- [ ] old pinned task\n", YESTERDAY)
    src = MarkdownSource(folder=tmp_path, pinned_notes=["old.md"], today=TODAY)
    assert [t.text for t in src.get_todos()] == ["old pinned task"]


def test_pinned_missing_file_skipped(tmp_path):
    src = MarkdownSource(folder=tmp_path, pinned_notes=["missing.md"], today=TODAY)
    assert src.get_todos() == []


def test_pinned_absolute_path(tmp_path):
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    note = outside_dir / "note.md"
    _touch(note, "- [ ] outside task\n", YESTERDAY)

    folder = tmp_path / "vault"
    folder.mkdir()
    src = MarkdownSource(folder=folder, pinned_notes=[str(note)], today=TODAY)
    assert [t.text for t in src.get_todos()] == ["outside task"]


def test_dot_directory_skipped(tmp_path):
    hidden = tmp_path / ".obsidian"
    hidden.mkdir()
    note = hidden / "config.md"
    _touch(note, "- [ ] hidden task\n", TODAY)
    src = MarkdownSource(folder=tmp_path, today=TODAY)
    assert src.get_todos() == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_unreadable_file_skipped(tmp_path):
    readable = tmp_path / "readable.md"
    _touch(readable, "- [ ] visible task\n", TODAY)
    locked = tmp_path / "locked.md"
    _touch(locked, "- [ ] secret task\n", TODAY)
    locked.chmod(0o000)
    try:
        src = MarkdownSource(folder=tmp_path, today=TODAY)
        assert [t.text for t in src.get_todos()] == ["visible task"]
    finally:
        locked.chmod(0o644)


def test_dedup_across_files_first_wins(tmp_path):
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    _touch(a, "- [ ] shared task\n", TODAY)
    _touch(b, "- [ ] shared task\n- [ ] unique in b\n", TODAY)
    src = MarkdownSource(folder=tmp_path, today=TODAY)
    todos = src.get_todos()
    assert [t.text for t in todos] == ["shared task", "unique in b"]


def test_ordering_pinned_first_then_sorted_scanned(tmp_path):
    pinned = tmp_path / "pinned.md"
    z_file = tmp_path / "z.md"
    a_file = tmp_path / "a.md"
    _touch(pinned, "- [ ] pinned task\n", YESTERDAY)
    _touch(z_file, "- [ ] z task\n", TODAY)
    _touch(a_file, "- [ ] a task\n", TODAY)
    src = MarkdownSource(folder=tmp_path, pinned_notes=["pinned.md"], today=TODAY)
    todos = src.get_todos()
    assert [t.text for t in todos] == ["pinned task", "a task", "z task"]


def test_unicode_and_emoji_text_preserved(tmp_path):
    note = tmp_path / "note.md"
    _touch(note, "- [ ] 우유 사기 🥛\n", TODAY)
    src = MarkdownSource(folder=tmp_path, today=TODAY)
    assert [t.text for t in src.get_todos()] == ["우유 사기 🥛"]


def test_nested_indented_checkbox_is_todo(tmp_path):
    note = tmp_path / "note.md"
    _touch(note, "- [ ] parent\n  - [ ] nested child\n    - [x] nested done\n", TODAY)
    src = MarkdownSource(folder=tmp_path, today=TODAY)
    assert [t.text for t in src.get_todos()] == ["parent", "nested child"]


def test_recurses_into_subdirectories(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    note = sub / "note.md"
    _touch(note, "- [ ] nested folder task\n", TODAY)
    src = MarkdownSource(folder=tmp_path, today=TODAY)
    assert [t.text for t in src.get_todos()] == ["nested folder task"]


def test_non_markdown_files_ignored(tmp_path):
    note = tmp_path / "note.txt"
    _touch(note, "- [ ] not markdown\n", TODAY)
    src = MarkdownSource(folder=tmp_path, today=TODAY)
    assert src.get_todos() == []


def test_default_today_is_date_today(tmp_path):
    src = MarkdownSource(folder=tmp_path)
    assert src.today == date.today()


def test_missing_folder_returns_empty(tmp_path):
    src = MarkdownSource(folder=tmp_path / "does_not_exist", today=TODAY)
    assert src.get_todos() == []


def test_no_pinned_notes_defaults_to_empty_list(tmp_path):
    src = MarkdownSource(folder=tmp_path, today=TODAY)
    assert src.pinned_notes == []
