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

## Post-M1 — 2026-08-20

- **LICENSE added ahead of schedule.** At the user's request, the MIT `LICENSE` file (standard text, copyright maengyo) was added now instead of waiting for M5; `pyproject.toml` already carried `license = "MIT"` (PEP 639 SPDX expression), and adding the file makes hatchling emit `License-Expression: MIT` + `License-File: LICENSE` in built metadata. Verified via `uv build`, `uv sync`, and the full test suite (31 passed, ruff clean).
- **Dependency license check (license-compliance-expert).** No runtime dependencies. Dev-only deps: pytest (MIT) and ruff (MIT), with transitives colorama (BSD-3-Clause), iniconfig (MIT), packaging (Apache-2.0 OR BSD-2-Clause), pluggy (MIT), pygments (BSD-2-Clause). All permissive, MIT-compatible, no copyleft — no blockers.
