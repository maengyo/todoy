from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from todoy.cli import _sanitize_todo_text, main
from todoy.config import DEFAULT_INTERVAL_MINUTES, Config, load_config, save_config
from todoy.sources.builtin import BuiltinSource


@pytest.fixture
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "config.toml"
    monkeypatch.setenv("TODOY_CONFIG_FILE", str(path))
    return path


@pytest.fixture
def data_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config_file: Path) -> Iterator[Path]:
    path = tmp_path / "todos.json"
    monkeypatch.setenv("TODOY_DATA_FILE", str(path))
    yield path


class FakeInput:
    def __init__(self, answers: list[str]) -> None:
        self._answers = answers
        self._index = 0
        self.prompts: list[str] = []

    def __call__(self, prompt: str = "") -> str:
        self.prompts.append(prompt)
        if self._index >= len(self._answers):
            raise AssertionError(f"Unexpected prompt: {prompt}")
        answer = self._answers[self._index]
        self._index += 1
        return answer


def test_init_wizard_builtin_only_writes_default_config(
    config_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_input = FakeInput(["n", ""])
    monkeypatch.setattr("builtins.input", fake_input)

    exit_code = main(["init"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert fake_input.prompts == [
        "Enable markdown source? [y/N]",
        "Reminder interval in minutes [30]:",
    ]
    assert captured.out == f"Config written to {config_file}\n"
    assert captured.err == ""
    assert load_config(config_file) == Config()


def test_init_wizard_with_markdown_writes_folder_and_pinned_notes(
    tmp_path: Path,
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    notes_folder = tmp_path / "notes"
    notes_folder.mkdir()
    fake_input = FakeInput(
        [
            "y",
            str(notes_folder),
            "Pinned.md, nested/Now.md",
            "45",
        ]
    )
    monkeypatch.setattr("builtins.input", fake_input)

    exit_code = main(["init"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert fake_input.prompts == [
        "Enable markdown source? [y/N]",
        "Notes folder path:",
        "Pinned notes (comma-separated, optional):",
        "Reminder interval in minutes [30]:",
    ]
    assert captured.out == f"Config written to {config_file}\n"
    assert captured.err == ""
    assert load_config(config_file) == Config(
        enabled_sources=["builtin", "markdown"],
        markdown_folder=notes_folder,
        markdown_pinned=["Pinned.md", "nested/Now.md"],
        reminder_interval_minutes=45,
    )


def test_init_wizard_overwrite_no_aborts(
    config_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_file.write_text("existing config\n", encoding="utf-8")
    fake_input = FakeInput(["n"])
    monkeypatch.setattr("builtins.input", fake_input)

    exit_code = main(["init"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert fake_input.prompts == [f"Config already exists at {config_file}. Overwrite? [y/N]"]
    assert captured.out == "Aborted.\n"
    assert captured.err == ""
    assert config_file.read_text(encoding="utf-8") == "existing config\n"


def test_init_wizard_invalid_interval_reprompts_once_then_defaults(
    config_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_input = FakeInput(["n", "soon", "later"])
    monkeypatch.setattr("builtins.input", fake_input)

    exit_code = main(["init"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert fake_input.prompts == [
        "Enable markdown source? [y/N]",
        "Reminder interval in minutes [30]:",
        "Reminder interval in minutes [30]:",
    ]
    assert captured.out == f"Config written to {config_file}\n"
    assert captured.err == ""
    assert load_config(config_file).reminder_interval_minutes == DEFAULT_INTERVAL_MINUTES


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


def test_list_uses_missing_config_as_builtin_default(
    data_file: Path, config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["add", "default config task"])
    capsys.readouterr()

    exit_code = main(["list"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "  1. default config task\n"
    assert captured.err == ""
    assert data_file.exists()
    assert not config_file.exists()


def test_list_renders_markdown_source_after_builtin_block(
    tmp_path: Path,
    data_file: Path,
    config_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    notes_folder = tmp_path / "notes"
    notes_folder.mkdir()
    (notes_folder / "Pinned.md").write_text(
        "- markdown task\x1b]0;pwned\x07\n- [x] done markdown\n",
        encoding="utf-8",
    )
    save_config(
        Config(
            enabled_sources=["builtin", "markdown"],
            markdown_folder=notes_folder,
            markdown_pinned=["Pinned.md"],
        ),
        config_file,
    )
    main(["add", "builtin task"])
    capsys.readouterr()

    exit_code = main(["list"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "  1. builtin task\n  - markdown task]0;pwned\n"
    assert captured.err == ""
    assert data_file.exists()


def test_list_config_error_prints_stderr_and_exits_1(
    data_file: Path, config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_file.write_text('[sources]\nenabled = ["not-a-source"]\n', encoding="utf-8")

    exit_code = main(["list"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == "Unknown source name: not-a-source\n"
    assert "Traceback" not in captured.err
    assert not data_file.exists()


def test_sanitize_todo_text_strips_control_characters() -> None:
    assert _sanitize_todo_text("evil\x1b]0;pwned\x07") == "evil]0;pwned"


def test_todo_text_is_sanitized_in_add_list_and_done_output(
    data_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    hostile_text = "evil\x1b]0;pwned\x07"
    safe_text = "evil]0;pwned"

    add_exit_code = main(["add", hostile_text])
    add_output = capsys.readouterr()
    list_exit_code = main(["list"])
    list_output = capsys.readouterr()
    done_exit_code = main(["done", "1"])
    done_output = capsys.readouterr()

    assert add_exit_code == 0
    assert add_output.out == f"Added #1: {safe_text}\n"
    assert add_output.err == ""
    assert list_exit_code == 0
    assert list_output.out == f"  1. {safe_text}\n"
    assert list_output.err == ""
    assert done_exit_code == 0
    assert done_output.out == f"Done #1: {safe_text}\n"
    assert done_output.err == ""
    assert data_file.exists()
