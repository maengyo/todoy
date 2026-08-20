from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from todoy.display.characters import Character
from todoy.display.overlay.base import OverlayOptions, create_backend


def test_create_backend_raises_helpful_error_on_non_darwin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")

    with pytest.raises(RuntimeError) as exc_info:
        create_backend()

    assert "macOS" in str(exc_info.value)


def test_create_backend_error_mentions_install_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")

    with pytest.raises(RuntimeError) as exc_info:
        create_backend()

    assert "todoy[overlay]" in str(exc_info.value)


@pytest.mark.parametrize(
    "module_name",
    ["todoy.display.overlay", "todoy.display.overlay.base"],
)
def test_importing_overlay_package_does_not_import_appkit(module_name: str) -> None:
    # Run in a fresh subprocess (not this test process) so we get a clean
    # sys.modules unpolluted by any other test that may have imported the
    # real macos backend (or monkeypatched a fake AppKit) earlier in the run.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import {module_name}; import sys; print('AppKit' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "False"


def test_create_backend_raises_when_appkit_missing_on_darwin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setitem(sys.modules, "AppKit", None)

    with pytest.raises(RuntimeError) as exc_info:
        create_backend()

    assert "todoy[overlay]" in str(exc_info.value)


def test_overlay_options_movement_and_bubble_effect_default() -> None:
    options = OverlayOptions(
        character=Character(name="cat", emoji="🐱", ascii_art="(=^.^=)"),
        character_image=None,
        language="en",
        test_seconds=None,
    )

    assert options.movement == "walk"
    assert options.bubble_effect == "pop"


def test_overlay_options_movement_and_bubble_effect_overridable() -> None:
    options = OverlayOptions(
        character=Character(name="cat", emoji="🐱", ascii_art="(=^.^=)"),
        character_image=Path("/tmp/does-not-exist.png"),
        language="ko",
        test_seconds=5.0,
        movement="hop",
        bubble_effect="shake",
    )

    assert options.movement == "hop"
    assert options.bubble_effect == "shake"
