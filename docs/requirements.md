# todoy — Requirements

> 한국어 버전: [requirements.ko.md](requirements.ko.md)

## Vision

An open-source CLI tool that keeps you from forgetting the day's todos you jotted down in a note app (such as Obsidian) or in your terminal: a character pops up on screen and reminds you with a speech bubble.

- Published on GitHub so anyone can install it with a single command: `pipx install todoy` / `uv tool install todoy`.
- No hardcoded personal paths — all configuration goes through the `todoy init` wizard and `~/.config/todoy/config.toml`.
- Obsidian is only **one example source**. Sources are plugins; todoy works fully without Obsidian.

## Functional requirements

### Todo sources (plugin architecture)

- `sources/base.py` — the `Source` interface: `get_todos() -> list[Todo]`. Adding a new source (Notion, Todoist, …) should take one new file.
- `sources/markdown.py` — extracts todos from markdown files in a configured folder (an Obsidian vault is just a folder).
  - `- item` and `- [ ] item` lines are todos; `- [x]` is done and excluded.
  - "Today's todos" = notes modified today (mtime) + user-pinned notes (e.g. a fixed `Todo.md`).
- `sources/builtin.py` — self-contained storage managed from the terminal: `todoy add "buy milk"`, `todoy done 1`, `todoy list`. Stored as a simple local JSON file (`~/.local/share/todoy/todos.json`, honoring `TODOY_DATA_FILE` and `XDG_DATA_HOME`).
- Multiple sources can be active at once, selected in the config.

### Display (two modes)

- `todoy tui` — an emoji/ASCII character prints today's todos in a speech bubble in the terminal. Cross-platform (macOS/Linux/Windows). A compact mode (`todoy tui --brief`) suitable for `.zshrc` so it greets every new terminal.
- `todoy overlay` — a transparent floating character window that lives on the desktop (macOS first, pyobjc). Shows a reminder bubble on a configurable interval (default 30 min); click to snooze/dismiss/quit. The display layer is separated so other OS backends can be added later.

### Character & interaction principles (added 2026-08-20)

- **Customizable character.** The user can replace the character: use their own image (e.g. a photo) or pick one of the bundled copyright-free characters. Selected via config / `todoy init`.
- **The character only passes by.** It reminds and teases, but never completes todos for the user, and there is no in-app button to permanently silence it — turning it off requires the user to edit the config themselves (deliberate friction; snooze stays temporary).
- **Taunting tone.** Reminder messages playfully needle the user about unfinished todos (message pack, en/ko), and the character's entrances carry the same teasing feel.
- **Pinned files.** Specific files inside a folder can be designated as todo sources — covered by the markdown source's `pinned_notes` config.
- **Live demo in README.** A recording of the real app (TUI + overlay) is embedded in the GitHub README (M5).

### CLI

`todoy init` (interactive setup) / `add` / `done` / `list` / `tui` / `overlay`. Python 3.11+, `pyproject.toml`-based, minimal dependencies.

## Quality bar

- A new user reading only the README reaches install → `todoy init` → first reminder within 5 minutes.
- The TUI works on all three OSes (verified in CI); the overlay is verified live on macOS.
- Public-repo quality: type hints, ruff-clean lint, test coverage on core logic.

## Milestones

| # | Scope | Status |
|---|-------|--------|
| M1 | Project skeleton (pyproject, git, tests) + `Todo` model + builtin source + `add`/`done`/`list` CLI | ✅ Done (2026-08-20) |
| M2 | Markdown source (Obsidian-vault compatible) + `todoy init` wizard | ✅ Done (2026-08-20) |
| M3 | TUI character (cross-platform, `--brief` mode) | ✅ Done (2026-08-20) |
| M4 | macOS overlay character (periodic reminders, snooze) | ✅ Done (2026-08-20) |
| M5 | Release prep: README, MIT license, GitHub Actions CI, PyPI packaging, demo GIF | ✅ Done (2026-08-20, pending first tagged PyPI publish) |

Each milestone is developed test-first (TDD) and merges only after cross-review.
