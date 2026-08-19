from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from todoy.cli import main
from todoy.sources.builtin import BuiltinSource


@pytest.fixture
def data_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    path = tmp_path / "todos.json"
    monkeypatch.setenv("TODOY_DATA_FILE", str(path))
    yield path


def test_add_prints_contract_message_and_persists(
    data_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["add", "buy milk"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "Added #1: buy milk\n"
    assert captured.err == ""
    assert BuiltinSource().list_todos(include_done=True)[0].text == "buy milk"
    assert data_file.exists()


def test_done_prints_contract_message(data_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["add", "finish report"])
    capsys.readouterr()

    exit_code = main(["done", "1"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "Done #1: finish report\n"
    assert captured.err == ""
    assert BuiltinSource().list_todos() == []
    assert data_file.exists()


def test_done_unknown_id_prints_stderr_and_exits_1(
    data_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["done", "999"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == "No todo with id 999\n"
    assert not data_file.exists()


def test_list_empty_prints_contract_message(
    data_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["list"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "No todos for today 🎉\n"
    assert captured.err == ""
    assert not data_file.exists()


def test_list_corrupt_data_file_prints_stderr_and_exits_1(
    data_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_file.write_text("not json", encoding="utf-8")

    exit_code = main(["list"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert f"Corrupt todos file at {data_file}:" in captured.err
    assert "Traceback" not in captured.err


def test_list_prints_open_todos_in_order(
    data_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["add", "first"])
    main(["add", "second"])
    capsys.readouterr()

    exit_code = main(["list"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "  1. first\n  2. second\n"
    assert captured.err == ""
    assert data_file.exists()


def test_list_all_marks_done_items(data_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["add", "open task"])
    main(["add", "completed task"])
    main(["done", "2"])
    capsys.readouterr()

    exit_code = main(["list", "--all"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "  1. open task\n  2. [x] completed task\n"
    assert captured.err == ""
    assert data_file.exists()
