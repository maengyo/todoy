"""Display helpers shared by terminal renderers."""

from __future__ import annotations


def sanitize_text(text: str) -> str:
    """Strip control characters from user-controlled display text."""
    return "".join(ch for ch in text if ch.isprintable() or ch == " ")
