"""todoy command-line interface (stub — replaced in a later task)."""

from __future__ import annotations

from todoy import __version__


def main(argv: list[str] | None = None) -> int:
    print(f"todoy {__version__}")
    return 0
