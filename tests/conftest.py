from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def fake_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOMEDRIVE", tmp_path.drive)
    monkeypatch.setenv("HOMEPATH", str(tmp_path)[len(tmp_path.drive) :])

    return tmp_path
