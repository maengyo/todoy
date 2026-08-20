"""ASCII terminal renderer for open todos."""

from __future__ import annotations

import random
import sys
import unicodedata
from typing import TYPE_CHECKING

from todoy.display import sanitize_text
from todoy.models import Todo

if TYPE_CHECKING:
    from todoy.display.characters import Character
    from todoy.display.messages import Language


MAX_BUBBLE_WIDTH = 60


def render_tui(
    todos: list[Todo],
    *,
    character: Character,
    language: Language,
    brief: bool = False,
    use_emoji: bool | None = None,
    rng: random.Random | None = None,
) -> str:
    """Render todos as a character speech bubble or a one-line brief summary."""
    resolved_use_emoji = _resolve_use_emoji(character, use_emoji)
    character_display = character.emoji if resolved_use_emoji else character.ascii_art

    if brief:
        return _render_brief(todos, character_display, use_emoji=resolved_use_emoji)

    return _render_full(
        todos,
        character_display=character_display,
        language=language,
        rng=rng,
    )


def _resolve_use_emoji(character: Character, use_emoji: bool | None) -> bool:
    if use_emoji is not None:
        return use_emoji

    encoding = sys.stdout.encoding
    if encoding is None:
        return False

    try:
        character.emoji.encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return False
    return True


def todo_display_text(todo: Todo) -> str:
    """Return sanitized todo text with its optional alarm time prefix."""
    text = sanitize_text(todo.text)
    if todo.at is None:
        return text
    return f"{todo.at} {text}"


def _render_brief(todos: list[Todo], character_display: str, *, use_emoji: bool) -> str:
    count = len(todos)
    if count == 0:
        suffix = " 🎉" if use_emoji else ""
        return f"{character_display} No todos today{suffix}"

    first_todo = todo_display_text(todos[0])
    label = "todo" if count == 1 else "todos"
    more = "" if count == 1 else f" (+{count - 1} more)"
    return f"{character_display} {count} {label}: {first_todo}{more}"


def _render_full(
    todos: list[Todo],
    *,
    character_display: str,
    language: Language,
    rng: random.Random | None,
) -> str:
    raw_lines = [_taunt(len(todos), language, rng), *[_format_todo_line(todo) for todo in todos]]
    lines = [_truncate(line, MAX_BUBBLE_WIDTH) for line in raw_lines]
    width = max((_display_width(line) for line in lines), default=0)

    border = "-" * (width + 2)
    rendered = [f".{border}."]
    rendered.extend(f"| {_pad_right(line, width)} |" for line in lines)
    rendered.extend([f"`{border}'", "  /", character_display])
    return "\n".join(rendered)


def _format_todo_line(todo: Todo) -> str:
    text = todo_display_text(todo)
    if todo.source == "builtin":
        todo_id = str(todo.id) if todo.id is not None else "?"
        return f"[#{todo_id}] {text}"
    return f"* {text}"


def _truncate(text: str, max_width: int) -> str:
    if _display_width(text) <= max_width:
        return text

    ellipsis = "…"
    ellipsis_width = _display_width(ellipsis)
    if max_width <= ellipsis_width:
        return ellipsis if max_width == ellipsis_width else ""

    target_width = max_width - ellipsis_width
    current_width = 0
    chars: list[str] = []
    for char in text:
        char_width = _char_display_width(char)
        if current_width + char_width > target_width:
            break
        chars.append(char)
        current_width += char_width
    return f"{''.join(chars)}{ellipsis}"


def _pad_right(text: str, width: int) -> str:
    return text + (" " * (width - _display_width(text)))


def _display_width(text: str) -> int:
    return sum(_char_display_width(char) for char in text)


def _char_display_width(char: str) -> int:
    return 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1


def _taunt(count: int, language: Language, rng: random.Random | None) -> str:
    from todoy.display.messages import taunt

    return taunt(count, language, rng)
