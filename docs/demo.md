# Demo assets — how they're made

> 한국어 버전: [demo.ko.md](demo.ko.md)

The README embeds two committed assets, both captured from the app actually
running:

- `demo/overlay-demo.gif` — the macOS overlay (galloping horse carrying the
  todo flag). Recorded by **self-rendering the app's real windows**: a small
  script drives the real `_OverlayController`, snapshots the character and
  message windows every 0.15s via `cacheDisplayInRect` (no Screen Recording
  permission needed), and assembles the PNG frames with
  `ffmpeg -framerate 7 -i frame%03d.png -vf "split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" -loop 0 out.gif`.
- `demo/tui.png` — real `render_tui` output (default cat + `--ascii` snail)
  drawn to a PNG with an AppKit text renderer.

## Re-recording / replacing

**Overlay GIF (self-render, any dev Mac, no permissions):** adapt the frame
recorder — construct `OverlayOptions` (pick character/movement/message_style),
run the controller with a repeating `NSTimer` that snapshots
`char_window`/`bubble_window` content views to PNGs, then assemble with the
ffmpeg palette command above. Use a throwaway `TODOY_DATA_FILE` so real todos
never appear.

**Overlay, full-fidelity screen recording (optional, nicer):** set up throwaway
env vars, start **Cmd-Shift-5** over the bottom of the screen, run
`uv sync --extra overlay && uv run todoy overlay --interval 1`, then convert:
`ffmpeg -i in.mov -vf "fps=12,scale=760:-1" demo/overlay-demo.gif`.

**Terminal walkthrough GIF (optional):** `demo/demo.tape` is a ready
[VHS](https://github.com/charmbracelet/vhs) script (`brew install vhs`, then
`vhs demo/demo.tape`) playing add/list/tui/done against a throwaway
`demo/demo-tmp/` store. It writes `demo/todoy.gif`; if you record it, embed it
in the README alongside (or instead of) `demo/tui.png`.

## Where the files go

```
demo/
├── demo.tape          # VHS script (text, committed)
├── overlay-demo.gif   # live overlay recording (committed)
└── tui.png            # real TUI output (committed)
```

Keep GIFs modest (README renders ~880px wide; aim ≤2MB) and never record
against your real data files.
