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

## M8 (follow-up) — 2026-08-20

### Decisions

- **Time alarms (issue #13).** `Todo.at` (`"HH:MM"`, canonical zero-padded via `parse_at`) from `todoy add --at` or a leading time token in markdown lines (`- [ ] 14:00 회의`). The overlay's `AlarmClock` (pure, injectable clock) fires each timed todo once per day at its minute — showing ONLY that message (⏰ line, no taunt) — with a 10-minute bounded catch-up for missed minutes and snooze re-arming. Independent of the periodic interval reminder. Timed todos render with an `HH:MM ` prefix in list/TUI/overlay.
- `OverlayBackend.run` gained a `get_todos` callable so the backend reads fresh todos every tick.

### UI polish (same day)

- Overlay bubble/flag restyled by the new ui-polish-expert agent: typographic hierarchy, accent Snooze pill + quiet Quit, drawn bubble tail and flag pennant+pole, system colors (dark/light), softer radius/shadow/padding.
- Live verification surfaced and fixed two CLI gaps: argparse choices now come from the animations constants (gallop had been missing), and `todoy overlay --character` was added.

## M7 (follow-up) — 2026-08-20

### Decisions

- **Galloping horse with a message flag (issue #12).** Character `horse` (🐎) joined the catalog; movement `gallop` = ~3× walk speed with a rhythmic double-beat hop (≤14px). Message presentation became its own axis: `message_style = "bubble"` (default, appears at show time and stays put) vs `"flag"` (a pennant that rides along with the character, repositioned every tick while visible, clamped fully on screen). Entrance `bubble_effect`s apply to both styles.
- Selection: `[display] message_style` + `todoy overlay --message-style {bubble,flag}`.

### Modifications from cross-review

- Shake effect re-clamps every oscillation (a flag near the screen edge could drift off-screen) and composes with the live ride-along origin (it could briefly snap away from a galloping character).
- Bubble mode no longer repositions on wander ticks — show-time position only, per contract.

## M6 (follow-up) — 2026-08-20

### Decisions

- **Selectable animations (issue #11).** Character movement presets (`walk` default, `hop`, `float`, `dash`, `still`) live in `display/overlay/animations.py` as a pure, dt-driven, rng-injectable state machine (`CharacterMovement.step(dt) -> (x, y_offset)`); the macOS backend just applies positions. Bubble entrance effects (`pop` default, `fade`, `slide`, `shake`, `none`) are applied via `NSAnimationContext` in the backend.
- Selection surface: `[display] movement / bubble_effect` in config plus `todoy overlay --movement/--bubble-effect` (flag > config > default). `todoy init` intentionally not extended — the wizard stays short.
- Name validation lives in `animations.validate_*` (overlay path), config load only type-checks — same split as character names. Unknown names report the available list via sanitized stderr + exit 1.
- Character position note: the character patrols the bottom edge — `CHARACTER_BOTTOM_MARGIN = 24px` above the screen bottom plus the movement's vertical offset (≤40px). A configurable edge/position is a possible follow-up, not yet requested as config.

## M4 — 2026-08-20

### Decisions

- **Overlay architecture.** `display/overlay/` splits a pure-Python core (`ReminderScheduler` on a monotonic clock, `build_reminder_text`) from a thin pyobjc backend (`macos.py`) behind an `OverlayBackend` protocol + `create_backend()` factory — other OS backends can be added beside it; AppKit is imported lazily and only on the GUI path.
- **Dependency.** `todoy[overlay]` extra = `pyobjc-framework-Cocoa` only (not the full pyobjc umbrella).
- **Product rules enforced in code.** The bubble offers exactly two controls — temporary snooze and quit; no permanent mute and no "complete todo" button (deliberate friction). The character wanders along the bottom of the screen and fires a first reminder ~5s after launch.
- **Config.** New `[display]` table: `character`, `character_image` (user image wins over the emoji when set/readable), `snooze_minutes`. `todoy init` asks for both character and optional image.
- **`todoy overlay --once`** prints the reminder text without any GUI — works on every OS, used for demos/tests/CI.
- **Verification.** Automated checks cover AppKit window state and clean exits (`TODOY_OVERLAY_TEST_SECONDS`); pixel-level screenshots are blocked in the sandboxed dev environment (macOS TCC), so final visual sign-off is a manual step.

### Modifications from cross-review

- macOS backend stores and invalidates all NSTimers on quit/test-timeout (was: leaked scheduled timers on repeated runs).
- Added Korean wide-char truncation coverage and subprocess tests asserting `todoy.display.overlay` imports never pull in AppKit.
- CLI `--once` test now exercises the real overlay core instead of fakes (integration seam).

## Post-M1 — 2026-08-20

- **LICENSE added ahead of schedule.** At the user's request, the MIT `LICENSE` file (standard text, copyright maengyo) was added now instead of waiting for M5; `pyproject.toml` already carried `license = "MIT"` (PEP 639 SPDX expression), and adding the file makes hatchling emit `License-Expression: MIT` + `License-File: LICENSE` in built metadata. Verified via `uv build`, `uv sync`, and the full test suite (31 passed, ruff clean).
- **Dependency license check (license-compliance-expert).** No runtime dependencies. Dev-only deps: pytest (MIT) and ruff (MIT), with transitives colorama (BSD-3-Clause), iniconfig (MIT), packaging (Apache-2.0 OR BSD-2-Clause), pluggy (MIT), pygments (BSD-2-Clause). All permissive, MIT-compatible, no copyleft — no blockers.

## M5 — 2026-08-20

### Decisions

- **CI: 3-OS matrix.** `.github/workflows/ci.yml` runs `uv sync --dev`, `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .` on ubuntu-latest/macos-latest/windows-latest × Python 3.11/3.13 (fail-fast: false). `pyobjc` only builds on macOS, so the `overlay` extra is synced and import-checked (`import todoy.display.overlay.base`) only on `runner.os == 'macOS'`; the other backends stay pure-Python-importable everywhere. `PYTHONIOENCODING: utf-8` is set at job level on every OS (not just Windows) since todoy prints emoji and Korean text and Windows' console codepage isn't UTF-8 by default.
- **Release: tag-triggered Trusted Publishing.** `.github/workflows/release.yml` triggers on `v*` tags with three jobs — `build` (uv build → sdist+wheel → upload-artifact), `publish` (download-artifact → `pypa/gh-action-pypi-publish` using PyPI **Trusted Publishing**, i.e. OIDC — no API token/secret stored in the repo), `release` (download-artifact → `softprops/action-gh-release` attaching the built dists to a GitHub Release). `permissions:` are minimal per job: `id-token: write` only on `publish`, `contents: write` only on `release`; the top-level default is `contents: read`. Trusted Publishing requires a "pypi" trusted publisher configured on the PyPI project page ahead of the first tag push — an external/account action left to the maintainer, not automatable from this repo.
- **Supply-chain hardening.** Every third-party GitHub Action (`actions/checkout`, `astral-sh/setup-uv`, `actions/upload-artifact`, `actions/download-artifact`, `pypa/gh-action-pypi-publish`, `softprops/action-gh-release`) is pinned to a full commit SHA with a `# vX.Y.Z` comment, resolved live from each repo's GitHub API tag ref at authoring time — not a mutable tag. Every `actions/checkout` step also sets `persist-credentials: false` so the default `GITHUB_TOKEN` isn't left in the git config for anything running after checkout.
- **Packaging metadata.** `pyproject.toml` gained `authors` (name only, no email), `keywords`, PyPI `classifiers` (Beta/Console/Developers+End Users/OS Independent/Python 3.11–3.13/Office-Business-Scheduling — deliberately *not* including the deprecated `License :: OSI Approved :: MIT License` classifier, since PEP 639's SPDX `license = "MIT"` field is now the single source of truth and hatchling already emits `License-Expression: MIT` from it), and `[project.urls]` (Homepage/Repository/Issues → `https://github.com/maengyo/todoy`).
- **Demo assets.** `demo/demo.tape` (a VHS script) and `docs/demo.md`/`docs/demo.ko.md` (recording walkthroughs) were authored, but the GIFs themselves (`demo/todoy.gif`, `demo/overlay.gif`) are not recorded — no vhs/asciinema/screen-recording tooling is available in this environment. The README's Demo section embeds them as commented-out `<!-- ![...] -->` placeholders (not live `![...]()` tags) so nothing 404s until they're recorded and committed.
- **Overlay extra dependency license check.** `todoy[overlay]`'s only dependency, `pyobjc-framework-Cocoa` (which pulls in `pyobjc-core`), is MIT-licensed — verified directly against both packages' installed wheel `METADATA` (`License: MIT` on both, `pyobjc-framework-Cocoa` also ships `License-File: LICENSE.txt`) after `uv sync --dev --extra overlay`. Fully compatible with todoy's MIT license; no blockers.

### Verification

`uv run pytest -q` (186 passed), `uv run ruff check .` + `uv run ruff format --check .` (clean), `uv build` (sdist+wheel built; wheel `METADATA` inspected directly to confirm `License-Expression: MIT` and the classifier list), `uv run python -c "import todoy"`, and both workflow YAML files parsed with `pyyaml` (pulled ephemerally via `uv run --with pyyaml`, not added as a project dependency). Every command each CI job step runs was also executed by hand on this machine first (`uv sync --dev`, `uv sync --dev --extra overlay`, the overlay import check) to confirm they work before committing them to `ci.yml`; the workflows themselves were not run through an actual GitHub Actions runner.
