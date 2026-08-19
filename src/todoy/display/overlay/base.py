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


class OverlayBackend(Protocol):
    """A concrete desktop-overlay implementation for one OS/toolkit."""

    def run(
        self,
        options: OverlayOptions,
        scheduler: ReminderScheduler,
        get_reminder_text: Callable[[], str],
    ) -> int:
        """Run the overlay event loop until quit; return the process exit code."""
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
