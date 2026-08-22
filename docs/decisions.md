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

## M14 (follow-up) — 2026-08-23

### Decisions

- **Animated sprite characters (issue #18).** User feedback: a translating emoji is not animation. Shipped an original pixel-art pack (blocky/slime/knight — Minecraft/game-style, but original art; copyrighted game characters cannot be bundled) defined entirely as code (pixel grids + palettes in `display/pixelart.py`, no binary assets). Each has idle/walk/jump/wave states; walk cycles genuinely articulate (legs alternate, arms counter-swing, 1px bob).
- **Renderer.** Pixel grids → cached nearest-neighbor NSImages (~6x, crisp). A pure state machine (`display/overlay/spritestate.py`, CI-tested on every OS) picks the state from what the character is doing: entrance-jump > flourish-wave > airborne-jump > walk (frame index locked to distance — no foot sliding) > idle (~2fps, forced during eased turns). Facing mirror/squash/entrance alpha unchanged; emoji characters unaffected.
- **Bring-your-own sprites.** `[display] character_sprites` points at a folder of `<state>_<n>.png` frames (fallbacks: jump→walk[0], wave→idle; ≤96px) — users can animate any sprites they own.

### Modifications from cross-review

- Pure sprite logic extracted from macos.py so its tests run on Linux/Windows CI; turning uses `movement.is_turning` instead of per-tick net dx; knight's ASCII fallback frame repaired; leftover parallel-dev scaffolding removed.

## M13 (follow-up) — 2026-08-22

### Decisions

- **Character personas (issue #17).** Every character has a Persona (zone/entrance/flourish/banner/default movement) in `display/overlay/personas.py`: water dwellers splash up from below the screen edge and dive-resurface when reminders fire; flyers cruise near the screen top (clearance derived from the real menu-bar height) with the message hanging below as a two-string banner; hoppers bounce in; spectral characters materialize with blinks; the rest walk in. Entrance/flourish curves are pure dt-driven state machines.
- **movement="auto"** is the new default: resolves to the persona's natural preset in the CLI before OverlayOptions (never leaks downstream); explicit values win; old explicit configs unchanged.
- **User-reported fixes:** the flag genuinely lagged/desynced on water characters — pop/slide entrance effects animated the window frame via Core Animation, fighting the 30fps ride-along ticks (flag style now uses alpha-only entrance); the bubble panel was compacted ~11% with smaller buttons.

### Modifications from cross-review

- A reminder firing during an entrance defers the flourish instead of dropping it; sky clearance uses NSScreen frame-vs-visibleFrame instead of a hardcoded 24px; banner strings spread from two feet; extra flag-tracking regressions (repeated fires, edge-clamped launches).

## M12 (follow-up) — 2026-08-22

### Decisions

- **Smooth motion (issue #16).** The overlay wander tick runs at 30fps (movement was made dt-independent in M11, so average speeds are unchanged). Edge turns are eased: ~0.3s decelerate → flip facing at the zero-velocity midpoint → accelerate, C1-continuous (no velocity jumps); gallop squash interpolates smoothly. Measured live: monotonic velocity trace through a turn, ~3-4% CPU.
- **Catalog: 25 characters.** + fox, panda, chick, rabbit, hamster, duck, whale, octopus, butterfly, dragon. New rule: EVERY catalog character has ≥2 ASCII gait frames (rabbit: 3-frame hop) with per-character stride columns — the terminal runner animates all of them; the static-art fallback is now unreachable for catalog names.

## M11 (follow-up) — 2026-08-21

### Decisions

- **`todoy run` — cross-platform in-terminal live mode (issue #15).** A single-line marquee redrawn with plain `\r` (no ANSI, no dependencies — works on Linux/Windows/macOS terminals alike): the character runs left-to-right and wraps ticker-style (never runs backwards), carrying the one-line flag message 2 columns behind; interval reminders and time alarms print as blocks above, then the run resumes.
- **Real gait.** `display/sprites.py` holds per-character ASCII gait cycles — the horse gets a 4-frame gallop (`,,=(oo)=,,` legs gather→reach→extend→land) — and `STRIDE_COLUMNS`: movement is stride-locked (exactly N columns per full leg cycle, Bresenham-distributed), so feet never slide.
- **Overlay facing + stride-sync.** The character view mirrors to face its travel direction (Apple's 🐎 faces left — moving right used to look like running backwards); gallop concentrates ~80% of horizontal advance into the airborne phase with per-cycle distance preserved, plus a subtle gallop-only squash-stretch.

### Modifications from cross-review

- `render_run_line` sanitizes flag text (an ESC sequence could leak into terminal output).
- Gallop integrates piecewise across phase boundaries — a dt spanning a boundary no longer distorts the per-cycle distance (regression tests with non-aligned dts).
- CLI formatting blocker fixed; the real-subprocess SIGINT smoke test is now committed (POSIX-gated).

## M10 (follow-up) — 2026-08-20

### Decisions

- **Compact fluttering flag.** User feedback: the flag panel was too bulky. `message_style="flag"` is now a single-line pennant (~34px, no buttons) carrying ONE essential line — `build_flag_line` ("N to go: first (+k)" / "할 일 N개: …", 38 display columns max) or `build_alarm_flag_line` ("⏰ HH:MM …") — that flutters (6Hz notch wave) while riding the character, auto-hides after 10s, and snoozes on click (alarm-aware). `bubble` remains the full detailed style (30s, Snooze/Quit buttons).
- Quit stays reachable in every style: the menu-bar status item gained a right-click "Quit todoy" menu.
- Catalog grew to 15 characters (+turtle, snail, penguin, frog, bee, owl, unicorn, dino, alien, crab); English taunt lines reworded count-agnostic ("1 things" bug).
- README demo media are self-rendered from the live app (see docs/demo.md).

### Modifications from cross-review

- FLAG_MAX_WIDTH raised 280→500px — the widest legal 38-column line measured ~464px and would have been clipped; regression test scans every widest legal builder output against the cap.
- Quit-menu test coverage extended to bubble style.

## M9 (follow-up) — 2026-08-20

### Decisions

- **Menu-bar quick-add panel (issue #14).** While the overlay runs, an NSStatusItem opens a panel: quick-add (text + optional HH:MM, Return submits, inline sanitized errors) and today's list with ✓ done / ✕ delete / 📌 pin controls for builtin todos; note-sourced todos are read-only (todoy never writes user notes). The reminder bubble keeps only Snooze/Quit — management stays deliberate.
- **Model.** `Todo.pinned` + `Todo.created` (YYYY-MM-DD, back-compat); `BuiltinSource.set_pinned/delete/sweep`.
- **Daily clear.** `[general] daily_clear = false` by default (opt-in — silent data deletion must be chosen). When on, every builtin-touching command sweeps non-pinned todos created before today (done or not); rows without a created date are stamped with today (migration), never deleted.
- **PanelActions.** The backend gets a frozen dataclass of never-raising callables (error-string-or-None) — GUI code stays decoupled from storage.
- CLI: `todoy pin/unpin/rm <id>`, `add --pin`; pinned render with a trailing 📌.

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

## M15 — 2026-08-23 (issue #19: character-voiced messages + compact following bubble)

- **Per-character message voices**: `Character.voice` selects one of 8 voice
  packs (`knightly`, `robotic`, `spooky`, `bouncy`, `salty`, `breezy`,
  `feline`, `gamer`) plus `default`; `messages.taunt` gained keyword-only
  `voice` with per-voice en/ko taunt+congrats pools and safe fallback to the
  default pool for unknown voices. All 28 catalog characters map explicitly.
  English lines are count-agnostic (valid for 1 and N); tone rule unchanged
  (tease the todos, never the person). The voice threads from the CLI through
  `OverlayOptions.voice` into every reminder/flag/alarm builder.
- **Bubble rides along**: the reminder bubble no longer stays where it first
  appeared — its window frame is updated every wander tick from the character
  position (ground zone above, sky zone hanging below with the tail flipped
  upward), clamped on-screen with the drawn tail always pointing at the
  character (pure math in `display/overlay/bubblelayout.py`, CI-tested on all
  OSes). Live-measured divergence: 0.000 px over 210 ticks.
- **Compact height**: the bubble text area is measured per fire
  (boundingRect at the real wrap width + 4 px slack, clamped 22–132 px)
  instead of a fixed 132 px — a 1-todo bubble dropped from 200 px to 125 px
  total.
- **Entrance effects vs ride-along**: the window frame is owned exclusively
  by the 30 fps tick (the flag-desync lesson); `pop`/`slide` degrade to an
  alpha fade for the bubble, `shake` moves the content view's bounds instead
  of the window. The flag style keeps its previous behavior.
- Cross-review: voices (Codex) reviewed by todoy-reviewer — approved with 7
  findings, all fixed (notably 4 English lines that read wrong at count=1);
  bubble work (Claude agent) reviewed by Codex — approved. 1295 tests.
