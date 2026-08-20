"""Backend-agnostic overlay contract: options, protocol, and OS factory.

Only `create_backend()` ever imports a concrete backend (`macos`), and only
after confirming the platform/toolkit is available -- so importing this
module never requires pyobjc, on any OS.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from todoy.display.characters import Character
    from todoy.display.messages import Language
    from todoy.display.overlay.core import ReminderScheduler
    from todoy.models import Todo

_INSTALL_HINT = (
    "todoy overlay currently supports macOS only. On macOS, install the overlay "
    "extra: pip install 'todoy[overlay]' (or: uv sync --extra overlay)"
)


@dataclass(frozen=True)
class OverlayOptions:
    """Immutable, backend-agnostic overlay launch options."""

    character: Character
    character_image: Path | None  # user image wins over emoji when set and readable
    language: Language
    test_seconds: float | None  # auto-quit after N seconds; None = run forever
    movement: str = "walk"  # one of animations.MOVEMENTS
    bubble_effect: str = "pop"  # one of animations.BUBBLE_EFFECTS
    message_style: str = "bubble"  # one of animations.MESSAGE_STYLES


class OverlayBackend(Protocol):
    """A concrete desktop-overlay implementation for one OS/toolkit."""

    def run(
        self,
        options: OverlayOptions,
        scheduler: ReminderScheduler,
        get_reminder_text: Callable[[], str],
        get_todos: Callable[[], list[Todo]],
    ) -> int:
        """Run the overlay event loop until quit; return the process exit code.

        `get_todos` is polled on the same 1s cadence as the reminder check so
        the backend can drive a `core.AlarmClock` with a fresh todo list --
        kept separate from `get_reminder_text` because the alarm check needs
        the todo objects themselves (for `todo.at`), not pre-rendered text.
        """
        ...


def create_backend() -> OverlayBackend:
    """Pick the overlay backend for the current platform.

    Raises RuntimeError with an install hint when no backend is available:
    any non-macOS platform, or macOS without the `overlay` extra installed.
    """
    if sys.platform != "darwin":
        raise RuntimeError(_INSTALL_HINT)

    try:
        import AppKit  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(_INSTALL_HINT) from exc

    from todoy.display.overlay.macos import MacOSOverlayBackend

    return MacOSOverlayBackend()
