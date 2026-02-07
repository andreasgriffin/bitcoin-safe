# Agent Guidelines

- Never use `getattr` or `setattr`;
- use type hints
- write clean code.  if you're writing many if statements you're probably doing it wrong.
- Before you commit, run pre-commit ruff format. commit and push the changes (use a dedicated branch for each session). If the pre-commit returns errors, fix them. For the pre-commit to work you have to cd into the current project and activate the environment.

## App run + GUI interaction notes
- Launch the app with `DISPLAY=desktop:0 poetry run python -m bitcoin_safe`.
- For GUI pytests where you want to *see* the windows on the running X server, force the display and Qt platform:
  - `DISPLAY=desktop:0 QT_QPA_PLATFORM=xcb poetry run pytest <test> -vv -s`
- Screenshot the X server via a tiny PyQt6 script using `QGuiApplication` + `primaryScreen().grabWindow(0)`.
- Best practice for clicks:
  - Ensure window focus (`xdotool windowactivate --sync <id>`).
  - Use `--clearmodifiers` and/or explicit `mousedown`/`mouseup`.
  - If a button ignores clicks, try small coordinate offsets or absolute screen coords.
  - Keyboard fallback: tab to focus, then `Return` or `space`.

## Using the local bitcoind regtest node
- Start: `/usr/local/bin/start-regtest.sh`
- RPC creds/port: user `regtest`, pass `regtestpass`, port `18043`
- Data dir: `$HOME/.bitcoin` (override with `BITCOIN_DATADIR=/path`)
- Example: `bitcoin-cli -regtest -datadir=$HOME/.bitcoin -rpcuser=regtest -rpcpassword=regtestpass getblockcount`
