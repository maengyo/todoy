# todoy

> 한국어 버전: [README.ko.md](README.ko.md)

A character that reminds you of today's todos — in your terminal and on your desktop.

**Status: WIP.** M1 (core CLI), M2 (markdown/Obsidian source + `todoy init`),
M3 (`todoy tui`), M4 (`todoy overlay`, macOS), and M5 (release prep: CI, PyPI
packaging, docs) are done — see the [roadmap](docs/requirements.md#milestones).
No version has been published to PyPI yet; install from source for now (below).

## Demo

The desktop overlay, actually running — a horse galloping along the screen
bottom, carrying today's todos on a flag (frames self-rendered from the live
app's real windows):

![todoy overlay: galloping horse with a message flag](demo/overlay-demo.gif)

The TUI, real output (default cat, and the snail in `--ascii` mode):

![todoy tui](demo/tui.png)

See [docs/demo.md](docs/demo.md) for how recordings are made.

## Install (from source, for now)

Requires Python 3.11+.

```console
$ git clone https://github.com/maengyo/todoy.git
$ cd todoy
$ uv sync            # or: pip install -e .
$ uv run todoy list  # or: todoy list (inside the venv)
```

PyPI packaging is wired up (`pipx install todoy` / `uv tool install todoy` —
see [`.github/workflows/release.yml`](.github/workflows/release.yml)), but no
version has been published yet, so install from source until the first
tagged release lands.

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

More management: `todoy rm <id>` deletes, `todoy pin <id>` / `unpin <id>` pins
(pinned todos show a 📌 and survive the daily sweep), `todoy add --pin` pins on
creation. Set `daily_clear = true` under `[general]` in the config and every
non-pinned todo from previous days is swept away on first use each morning —
the list starts fresh daily, pinned tasks stay.

### Time alarms

Give a todo a time and the overlay pops that message — and only that message —
right on time:

```console
$ todoy add "standup meeting" --at 9:55
Added #3: standup meeting

$ todoy list
  3. 09:55 standup meeting
```

Markdown notes work too: `- [ ] 14:00 회의` fires at 14:00. Alarms fire once
per day per todo (snooze re-arms them), independent of the periodic reminder.

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

### Meet the character (`todoy tui`)

A character delivers today's todos in a speech bubble — with a gentle dose of taunting:

```console
$ todoy tui
.--------------------------------------------------.
| 3 todos and counting. No pressure. (Some pressure.) |
| [#1] buy milk                                    |
| * prepare the meeting                            |
| * call the bank                                  |
`--------------------------------------------------'
  /
🐱
```

- `todoy tui --brief` prints a single line — drop it in your `.zshrc` / `.bashrc`
  to get nagged by every new terminal: `🐱 3 todos: buy milk (+2 more)`
- 15 characters to choose from: cat (default), dog, ghost, robot, horse,
  turtle, snail, penguin, frog, bee, owl, unicorn, dino, alien, crab —
  `--character NAME`, `--lang en|ko`, `--ascii` for emoji-free terminals.
- Messages tease your todos, never you. The character reminds — finishing them is still your job.

### A character on your desktop (`todoy overlay`, macOS)

```console
$ uv sync --extra overlay   # or: pip install -e '.[overlay]'
$ todoy overlay
```

A transparent character wanders along the bottom of your screen and pops a
speech bubble with today's todos on your configured interval (default 30 min,
`[general] reminder_interval_minutes`). The bubble offers **Snooze** (temporary)
and **Quit** — that's all, on purpose: the character never completes todos for
you, and there is no permanent mute button. To silence it for good you have to
edit your config yourself. Deliberate friction is the feature.

- Replace the character with your own image: set `character_image` in
  `~/.config/todoy/config.toml` (or answer the `todoy init` prompt).
- Pick how it moves and how the message appears:
  `todoy overlay --movement gallop --message-style flag --character horse`
  makes a horse gallop across your screen carrying your todos on a flag.
  Movements: `walk` (default) / `hop` / `float` / `dash` / `gallop` / `still`.
  Message styles: `bubble` (default, stays put) / `flag` (rides along with the
  character). Entrance effects: `--bubble-effect pop` (default) / `fade` /
  `slide` / `shake` / `none`. Set them permanently via `movement` /
  `message_style` / `bubble_effect` under `[display]` in the config.
- `todoy overlay --once` prints the reminder text to stdout without any GUI
  (works on every OS — handy for scripts and previews).
- Other platforms: the display layer is pluggable; overlay backends for
  Linux/Windows are welcome contributions.

While the overlay runs, a **menu-bar item** (the character's emoji) opens a
quick panel: type a todo (+ optional `HH:MM` for an alarm), hit return — done.
The same panel lists today's todos with check (✓), delete (✕), and pin (📌)
controls for todoy's own todos; note-sourced todos are shown read-only (todoy
never edits your notes). The reminder bubble itself still only offers Snooze
and Quit — managing your list is your job, on purpose.

## Roadmap

M1–M5 are all implemented. What's left is operational, not code: tag and
push the first release so CI actually publishes it to PyPI.

Details: [docs/requirements.md](docs/requirements.md) ·
decisions & changes: [docs/decisions.md](docs/decisions.md)

## Development

```console
$ uv sync
$ uv run pytest
$ uv run ruff check .
$ uv run ruff format --check .
```

CI (`.github/workflows/ci.yml`) runs the same checks on Linux/macOS/Windows
for Python 3.11 and 3.13 on every push and pull request.

Contributions welcome — the source-plugin interface (`src/todoy/sources/`,
see `Source` in `base.py`) stabilized in M2.

## License

MIT — see [LICENSE](LICENSE).
