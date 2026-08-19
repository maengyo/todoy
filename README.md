# todoy

> 한국어 버전: [README.ko.md](README.ko.md)

A character that reminds you of today's todos — in your terminal and on your desktop.

**Status: WIP.** M1 (core CLI) and M2 (markdown/Obsidian source + `todoy init`) are done.
The TUI character and the macOS overlay are on the [roadmap](docs/requirements.md#milestones).

## What works today

A stdlib-only todo CLI backed by a local JSON file, plus todos pulled from your notes:

```console
$ todoy add "buy milk"
Added #1: buy milk

$ todoy list
  1. buy milk

$ todoy done 1
Done #1: buy milk

$ todoy list --all
  1. [x] buy milk
```

Todos live in `~/.local/share/todoy/todos.json` (honors `XDG_DATA_HOME`;
override the file entirely with the `TODOY_DATA_FILE` environment variable).

### Pull todos from your notes (Obsidian-friendly)

Run `todoy init` and point todoy at any folder of markdown files — an Obsidian
vault works as-is. Notes edited today, plus the notes you pin, contribute their
`- [ ] task` / `- task` lines to `todoy list` (checked-off `- [x]` lines are
skipped):

```console
$ todoy init
Enable markdown source? [y/N] y
Notes folder path: ~/notes
Pinned notes (comma-separated, optional): Todo.md
Reminder interval in minutes [30]:
Config written to ~/.config/todoy/config.toml

$ todoy list
  1. buy milk
  - prepare the meeting
  - call the bank
```

## Install (from source, for now)

Requires Python 3.11+.

```console
$ git clone https://github.com/maengyo/todoy.git
$ cd todoy
$ uv sync            # or: pip install -e .
$ uv run todoy list  # or: todoy list (inside the venv)
```

PyPI packaging (`pipx install todoy` / `uv tool install todoy`) arrives in M5.

## Roadmap

- **M3** — `todoy tui`: a character greets you with today's todos in a speech bubble; `--brief` mode for your shell rc
- **M4** — `todoy overlay`: a floating desktop character (macOS first) with periodic reminders and snooze
- **M5** — Release: full docs, MIT license, CI, PyPI

Details: [docs/requirements.md](docs/requirements.md) ·
decisions & changes: [docs/decisions.md](docs/decisions.md)

## Development

```console
$ uv sync
$ uv run pytest
$ uv run ruff check .
```

Contributions welcome once the plugin interface stabilizes (post-M2).

## License

MIT — see [LICENSE](LICENSE).
