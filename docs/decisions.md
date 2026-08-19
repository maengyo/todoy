# todoy — Decision & Change Log

> 한국어 버전: [decisions.ko.md](decisions.ko.md)

Engineering decisions and notable modifications, newest first. Each milestone appends its entries here.

## M1 — 2026-08-20

### Decisions

- **Stdlib-only runtime for M1.** The CLI uses `argparse`; no third-party runtime dependencies. A `pyobjc` optional extra was initially added for the future overlay but removed after review — it belongs to M4.
- **Data model.** `Todo` is a plain dataclass (`text`, `done`, `id`, `source`) with `to_dict`/`from_dict`. `id` is `None` for read-only sources; only the builtin store assigns ids.
- **Source plugin interface.** `Source` is an ABC with a single required method `get_todos() -> list[Todo]` returning today's *open* todos, plus a `name` class attribute. Management operations (`add`/`done`) are specific to `BuiltinSource`, not part of the interface.
- **Builtin storage.** JSON file resolved as `TODOY_DATA_FILE` env var → `$XDG_DATA_HOME/todoy/todos.json` → `~/.local/share/todoy/todos.json`. Writes are atomic (temp file + `os.replace`). Ids are never reused (max existing id + 1). A corrupt file raises `ValueError` naming the file path.
- **CLI error policy.** Expected errors never show a traceback: unknown id and corrupt data file both print a message to stderr and exit 1.

### Modifications from cross-review

- CLI: catch the corrupt-data-file `ValueError` in `main()` and report via stderr + exit 1, with a regression test (was: raw traceback).
- Packaging: removed the premature `overlay = ["pyobjc"]` optional extra and its lockfile entries.
- Repo hygiene: local agent/session scaffolding (internal planning docs and assistant configuration) is git-ignored and was removed from history before publishing; no personal paths appear in the repository.

### Process

- Milestones are developed test-first (TDD) and cross-reviewed by two independent reviewers before merge (M1: 31 tests, ruff-clean).

## M2 — 2026-08-20

### Decisions

- **Config.** `~/.config/todoy/config.toml` (override order: `TODOY_CONFIG_FILE` env → `$XDG_CONFIG_HOME/todoy/config.toml` → `~/.config/todoy/config.toml`). Read with stdlib `tomllib`; written by a small hand-rolled emitter (stdlib has no TOML writer, and minimal dependencies win over adding `tomli-w`).
- **Markdown source.** A file contributes todos if its mtime date is today or it is pinned in config. Line rules: `- [ ] text` and `- text` are open todos, `- [x]` is excluded; dedup by text, pinned files first. Fenced code blocks / YAML frontmatter are not special-cased yet (#10).
- **`add`/`done` always target the builtin store** regardless of which sources are enabled — predictable UX; read-only sources are aggregated only in `list` (and later TUI/overlay).
- **Output sanitization pulled forward from #7.** Markdown notes are untrusted input that now reaches the terminal, so all rendered todo text is stripped of control/escape characters as of M2.
- Validated against a real Obsidian vault during development (Korean todos, nested folders, pinned note) — the vault path stays out of code, tests, and fixtures.

### Modifications from cross-review

- Config emitter: escape U+007F (DEL) in TOML strings — save/load round-trip could otherwise produce a file todoy itself could not parse.
- Deferred minors filed as issues: markdown parser robustness (#10), CLI hardening additions (#6).

## M3 — 2026-08-20

### Decisions

- **Display layer package.** TUI lives in `src/todoy/display/` (`tui.py`, `messages.py`, `characters.py`) so M4 can add the overlay backend beside it; `sanitize_text` moved there as the shared output-sanitizing helper.
- **Taunting message pack.** en/ko pools (≥5 taunts, ≥3 cheeky congrats per language); tone rule enforced in review: tease the todos/situation, never the person. Language resolution: explicit flag → `TODOY_LANG` → `LANG` starting with `ko` → `en`. No config schema change in M3.
- **Characters.** Built-in catalog (cat/dog/ghost/robot) with emoji + pure-ASCII fallback art; `--character` flag selects, emoji auto-disabled when stdout encoding can't encode it (`--ascii` forces).
- **Bubble metrics use display columns**, not code points — East Asian Wide/Fullwidth characters count as 2 (stdlib `unicodedata.east_asian_width`), so Korean text renders an aligned bubble.

### Modifications from cross-review & security audit

- Replaced a ko taunt line that implied habitual personal failure (tone rule); tests now assert every taunt line carries `{count}`.
- Markdown source no longer reads symlinked files during folder scans (a symlink pointing outside the folder could leak file contents as todos); pinned notes are exempt (explicit user config).
- The CLI's generic error output is sanitized too — `--character` error messages no longer reflect raw control characters to stderr.

## Post-M1 — 2026-08-20

- **LICENSE added ahead of schedule.** At the user's request, the MIT `LICENSE` file (standard text, copyright maengyo) was added now instead of waiting for M5; `pyproject.toml` already carried `license = "MIT"` (PEP 639 SPDX expression), and adding the file makes hatchling emit `License-Expression: MIT` + `License-File: LICENSE` in built metadata. Verified via `uv build`, `uv sync`, and the full test suite (31 passed, ruff clean).
- **Dependency license check (license-compliance-expert).** No runtime dependencies. Dev-only deps: pytest (MIT) and ruff (MIT), with transitives colorama (BSD-3-Clause), iniconfig (MIT), packaging (Apache-2.0 OR BSD-2-Clause), pluggy (MIT), pygments (BSD-2-Clause). All permissive, MIT-compatible, no copyleft — no blockers.
