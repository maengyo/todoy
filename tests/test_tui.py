from __future__ import annotations

import random
import sys
import types
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pytest

from todoy.models import Todo


@dataclass(frozen=True)
class FakeCharacter:
    name: str
    emoji: str
    ascii_art: str


class FakeStdout:
    encoding = "ascii"


def _display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in {"W", "F"} else 1 for ch in text)


def _install_fake_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    messages = types.ModuleType("todoy.display.messages")

    def taunt(count: int, language: str, rng: random.Random | None = None) -> str:
        if rng is not None:
            rng.randrange(10)
        if language == "ko":
            return f"아직 {count}개 남았는데?"
        return f"Still {count} todos."

    messages.taunt = taunt
    monkeypatch.setitem(sys.modules, "todoy.display.messages", messages)


def test_full_render_with_mixed_builtin_and_markdown_todos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_messages(monkeypatch)
    from todoy.display.tui import render_tui

    character = FakeCharacter(name="cat", emoji="🐱", ascii_art="(=^.^=)")
    todos = [
        Todo(text="buy milk", id=12, source="builtin"),
        Todo(text="read notes", source="markdown"),
    ]

    rendered = render_tui(
        todos,
        character=character,
        language="en",
        rng=random.Random(4),
        use_emoji=True,
    )

    assert rendered == "\n".join(
        [
            ".----------------.",
            "| Still 2 todos. |",
            "| [#12] buy milk |",
            "| * read notes   |",
            "`----------------'",
            "  /",
            "🐱",
        ]
    )


def test_full_render_passes_ko_language_to_taunt(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_messages(monkeypatch)
    from todoy.display.tui import render_tui

    rendered = render_tui(
        [Todo(text="보고서 쓰기", id=1, source="builtin")],
        character=FakeCharacter(name="cat", emoji="🐱", ascii_art="(=^.^=)"),
        language="ko",
        use_emoji=False,
    )

    assert "| 아직 1개 남았는데? |" in rendered
    assert rendered.endswith("(=^.^=)")


def test_brief_render_handles_zero_one_and_many_todos(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_messages(monkeypatch)
    from todoy.display.tui import render_tui

    character = FakeCharacter(name="cat", emoji="🐱", ascii_art="(=^.^=)")

    assert (
        render_tui([], character=character, language="en", brief=True, use_emoji=True)
        == "🐱 No todos today 🎉"
    )
    assert (
        render_tui([], character=character, language="en", brief=True, use_emoji=False)
        == "(=^.^=) No todos today"
    )
    assert (
        render_tui(
            [Todo(text="buy milk", id=1, source="builtin")],
            character=character,
            language="en",
            brief=True,
            use_emoji=True,
        )
        == "🐱 1 todo: buy milk"
    )
    assert (
        render_tui(
            [
                Todo(text="first", id=1, source="builtin"),
                Todo(text="second", source="markdown"),
                Todo(text="third", source="markdown"),
            ],
            character=character,
            language="en",
            brief=True,
            use_emoji=True,
        )
        == "🐱 3 todos: first (+2 more)"
    )


def test_full_render_truncates_todo_lines_to_sixty_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_messages(monkeypatch)
    from todoy.display.tui import render_tui

    rendered = render_tui(
        [Todo(text="x" * 80, id=4, source="builtin")],
        character=FakeCharacter(name="cat", emoji="🐱", ascii_art="(=^.^=)"),
        language="en",
        use_emoji=False,
    )

    todo_line = rendered.splitlines()[2]
    content = todo_line.removeprefix("| ").removesuffix(" |")
    assert len(content) == 60
    assert content == f"[#4] {'x' * 54}…"


def test_render_sanitizes_hostile_todo_text(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_messages(monkeypatch)
    from todoy.display.tui import render_tui

    rendered = render_tui(
        [Todo(text="evil\x1b]0;pwned\x07", id=1, source="builtin")],
        character=FakeCharacter(name="cat", emoji="🐱", ascii_art="(=^.^=)"),
        language="en",
        use_emoji=False,
    )

    assert "\x1b" not in rendered
    assert "\x07" not in rendered
    assert "evil]0;pwned" in rendered


def test_use_emoji_auto_falls_back_when_stdout_encoding_cannot_encode_character(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_messages(monkeypatch)
    from todoy.display.tui import render_tui

    monkeypatch.setattr(sys, "stdout", FakeStdout())

    rendered = render_tui(
        [Todo(text="buy milk", id=1, source="builtin")],
        character=FakeCharacter(name="cat", emoji="🐱", ascii_art="(=^.^=)"),
        language="en",
        brief=True,
        use_emoji=None,
    )

    assert rendered == "(=^.^=) 1 todo: buy milk"


def test_tui_command_with_real_display_modules_aligns_korean_bubble(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from todoy.cli import main

    monkeypatch.setenv("TODOY_CONFIG_FILE", str(tmp_path / "config.toml"))
    monkeypatch.setenv("TODOY_DATA_FILE", str(tmp_path / "todos.json"))
    assert main(["add", "회의 준비와 자료 정리"]) == 0
    assert main(["add", "긴급한 보고서 초안 작성하기"]) == 0
    capsys.readouterr()

    exit_code = main(["tui", "--lang", "ko", "--ascii"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    bubble_lines = [line for line in captured.out.splitlines() if line.startswith((".", "|", "`"))]
    assert len(bubble_lines) >= 3
    assert len({_display_width(line) for line in bubble_lines}) == 1
