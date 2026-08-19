from __future__ import annotations

import subprocess
import sys

import pytest

from todoy.display.overlay.base import create_backend


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
