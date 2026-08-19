# Recording the demo assets

> 한국어 버전: [demo.ko.md](demo.ko.md)

The README embeds two GIFs that aren't recorded yet:

- `demo/todoy.gif` — the CLI/TUI walkthrough (`todoy add`, `todoy list`,
  `todoy tui`, `todoy done`).
- `demo/overlay.gif` — the macOS desktop overlay (`todoy overlay`).

Neither recording tool (`vhs`, `asciinema`/`agg`) nor a macOS screen recorder
is available on every dev machine, so these are recorded manually and
committed as binary GIFs. This doc is the walkthrough for whoever records
them next.

## `demo/todoy.gif` — CLI/TUI, via VHS

1. Install [VHS](https://github.com/charmbracelet/vhs):

   ```console
   $ brew install vhs
   ```

2. From the repo root, run the tape:

   ```console
   $ vhs demo/demo.tape
   ```

   This plays `todoy add` (×2), `todoy list`, `todoy tui`, `todoy tui --brief`,
   `todoy done 1`, and `todoy tui` again, using `uv run todoy` against a
   throwaway `demo/demo-tmp/` data/config file (never your real todos) with
   `TODOY_LANG=en` pinned so the output doesn't depend on the recording
   machine's locale. It writes `demo/todoy.gif`.

3. Sanity-check the GIF (size, readability at GitHub's README width — around
   800–900px looks right), then commit it.

To tweak timing or add commands, edit `demo/demo.tape` directly — see the
[VHS command reference](https://github.com/charmbracelet/vhs#vhs-command-reference)
for `Type`/`Sleep`/`Env`/`Hide`/`Show`.

## `demo/overlay.gif` — macOS overlay, via screen recording

The overlay is a real `NSWindow` (see `src/todoy/display/overlay/macos.py`),
so it isn't capturable by a terminal-recording tool like VHS — it needs an
actual screen recording.

1. Set up a throwaway config so the recording doesn't show your real todos:

   ```console
   $ export TODOY_DATA_FILE=/tmp/todoy-overlay-demo/todos.json
   $ export TODOY_CONFIG_FILE=/tmp/todoy-overlay-demo/config.toml
   $ mkdir -p /tmp/todoy-overlay-demo
   $ uv run todoy add "buy milk"
   $ uv run todoy add "prepare the meeting"
   ```

2. Start a screen recording with **Cmd-Shift-5**, select a small region
   around where the character will appear (bottom of the screen), and start
   recording.

3. Launch the overlay with a short interval so the reminder bubble appears
   quickly, and let it play out (character walk, bubble pop, Snooze/Quit):

   ```console
   $ uv sync --extra overlay
   $ uv run todoy overlay --interval 1
   ```

4. Stop the recording (Cmd-Shift-5's stop button, or the menu bar icon). This
   saves an `.mov`; convert it to a GIF (e.g. `ffmpeg -i in.mov -vf
   "fps=12,scale=600:-1" demo/overlay.gif`) and commit it as
   `demo/overlay.gif`.

## Where the files go

```
demo/
├── demo.tape     # VHS script (committed, text)
├── todoy.gif     # CLI/TUI recording (committed, binary — not yet added)
└── overlay.gif   # macOS overlay recording (committed, binary — not yet added)
```

Until both GIFs are recorded and committed, the README's Demo section links
will 404 — see the note there.
