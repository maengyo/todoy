# demo.tape — records demo/todoy.gif for the README.
#
# Requires vhs (https://github.com/charmbracelet/vhs): `brew install vhs`.
# Run from the repo root:
#
#   vhs demo/demo.tape
#
# Uses TODOY_DATA_FILE / TODOY_CONFIG_FILE pointed at demo/demo-tmp so the
# recording never touches your real todos or config. Runs `uv run todoy`
# so it works straight from a clone, with no `pip install -e .` needed.
# See docs/demo.md for the full recording walkthrough.

Output demo/todoy.gif

Require uv

Set Shell "bash"
Set FontSize 18
Set Width 1000
Set Height 620
Set Padding 20

# Pin the data/config file and force English messages so the recording is
# identical no matter the host machine's locale (todoy defaults to Korean
# when $LANG starts with "ko" — see src/todoy/display/messages.py).
Env TODOY_DATA_FILE "demo/demo-tmp/todos.json"
Env TODOY_CONFIG_FILE "demo/demo-tmp/config.toml"
Env TODOY_LANG "en"

Hide
Type "mkdir -p demo/demo-tmp && rm -f demo/demo-tmp/todos.json demo/demo-tmp/config.toml && clear"
Enter
Show

Type "uv run todoy add 'buy milk'"
Enter
Sleep 1s

Type "uv run todoy add 'prepare the meeting'"
Enter
Sleep 1s

Type "uv run todoy list"
Enter
Sleep 1.5s

Type "uv run todoy tui"
Enter
Sleep 2.5s

Type "uv run todoy tui --brief"
Enter
Sleep 1.5s

Type "uv run todoy done 1"
Enter
Sleep 1s

Type "uv run todoy tui"
Enter
Sleep 2.5s

Hide
Type "rm -rf demo/demo-tmp"
Enter
Show
