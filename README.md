# OverAnalyzer desktop companion

The OverAnalyzer companion captures two full Overwatch **Game Report** frames on
explicit global hotkeys, one Summary frame and one Teams frame, then uploads them for
OCR. The service locates and retains only the useful Game Report regions. The full
frames are discarded after processing.

The companion has no crop geometry. It runs one coarse check on the Teams frame, then
posts both frames to `POST /api/uploads/screenshots` with
`capture_format=full_frames_v1`. Precise locate, five-row refusal, cropping, and
retention are server-owned.

## Privacy and capture behavior

Capture happens only when you press **F11**, **F12**, a capture button,
**Test capture**, or **Run self test**. There is no timed, background, or continuous
screen-capture loop.

The whole selected game frame is uploaded for processing, then discarded. Full frame
pixels are never written to the local debug folder. The service retains only the
located board context and Summary artifact. Nothing hooks the game process, reads its
memory, or injects into it. Capture is an ordinary desktop screen grab through `mss`.

## How capture works

1. Open the Game Report **Summary** screen and press **F11**. The full frame is held in
   memory.
2. Open the Game Report **Teams** screen and press **F12**. The companion runs its
   coarse accidental-capture guard and uploads both full frames.
3. The server locates the boards, keeps only board-plus-margin artifacts, discards the
   full frames, and starts OCR.
4. The companion polls the result and reports complete, partial, needs review, or
   error.

Both source frames are required. The server may produce a partial match only when one
team side is genuinely absent after locate. A Teams frame that does not prove a valid
five-row board is refused before anything is retained.

While a Summary frame is held, the panel offers **Discard**. F9 pauses or resumes
capture in the app and tray. The headless CLI keeps the legacy F9 reset behavior.

## Install from source

Python 3.11 or newer is required. Release builds use Python 3.13.4.

```text
pip install -r requirements.txt
python -m overanalyzer_agent
```

The default command opens the 360px overlay panel. Other modes use the same capture
controller:

```text
python -m overanalyzer_agent --tray
python -m overanalyzer_agent --settings
python -m overanalyzer_agent --cli
```

The panel opens with capture active. It includes pause and resume, both capture
buttons, daily and session counts, the last captured match, activity history, device
pairing, hotkey rebinding, monitor selection, self test, test capture, and the debug
report folder.

## Configuration

Most players need only a device key, pasted in the app's Settings screen. Create one
from Settings > Devices in the web app. Your gamertag lives on the account, not in the
companion.

For self-hosting or source development:

```text
copy agent.example.toml agent.toml
```

Active options are:

- `api_url`: API origin, default `https://api.overanalyzer.app`
- `web_url`: web origin, default `https://overanalyzer.app`
- `bearer_token`: device key
- `monitor_index`: 1-based display selection, unset means primary
- `timeout_sec`: request timeout
- `hotkey_summary`, `hotkey_scoreboard`, `hotkey_reset`: global hotkeys

Environment overrides are `OA_AGENT_API_URL`, `OA_AGENT_WEB_URL`,
`OA_AGENT_GAMERTAG`, and `OA_AGENT_TOKEN`.

There are no capture regions, colour tolerances, leaderboard widths, team colours, or
crop overrides to tune. Older geometry keys in `agent.toml` are ignored safely during
upgrade.

## Coarse Game Report guard

The Teams frame must contain two large vivid areas roughly where the team boards
appear. This check is intentionally colour-agnostic and broad. It prevents a common
accidental desktop upload but never chooses crop or retained bounds. The server remains
the authority and must independently prove a valid board.

Use **Settings > Advanced > Test capture** while the Teams screen is visible to verify
the selected display and coarse guard without uploading.

## Self test

The self test uses the real upload and OCR path:

1. Capture Summary with **F11**.
2. Open Teams.
3. Choose **Run self test** in Settings.

It verifies the service and device key, captures the visible Teams screen, uploads both
frames, waits for OCR, then deletes the test match. It consumes one daily upload. If
cleanup fails, the report names the match so it can be removed in the web app.

The self test refuses to continue if no Summary frame is held or the visible display
does not resemble the Teams Game Report. This keeps the test on the same protocol as a
real capture.

## Debug reports

Each settled attempt writes a metadata-only folder under `debug_out` beside
`agent.toml`. A packaged build uses
`%LOCALAPPDATA%\OverAnalyzer\debug_out`.

```text
2026-08-23_15-42-03_needs_review/
    attempt.txt
    attempt.json
```

Reports contain the result, match id, service host, display, frame dimensions, encoded
byte counts, and self-test stages. They contain no screenshots, full-frame pixels, or
device key. Only the newest 10 reports are kept.

## Authentication

The hosted service requires a device key, not login credentials. The companion sends
it as `Authorization: Bearer <key>`. One account has one live device key, so creating a
replacement revokes the previous key.

Self-hosters can override the hosted origins in `agent.toml` or through environment
variables. Hosted users do not see server-address fields in the UI.

## Display and hotkey caveats

- Global hotkeys are most reliable when Overwatch runs borderless or windowed.
  Exclusive fullscreen can swallow the hook.
- Windows may require running the app as administrator for hotkeys to fire while the
  game has focus. The on-screen buttons remain available if binding fails.
- Capture defaults to the primary display. Select another monitor in Settings >
  Advanced or set `monitor_index`.
- Monitor selection is manual. Automatic game-monitor detection is not implemented.
- The panel is frameless and always on top, so it has no taskbar button. Quit from the
  panel or tray.

## Tests

The versioned full-frame upload, coarse guard, memory-only buffer, metadata-only
recorder, self test, configuration, and presentation layer are tested without a
desktop:

```text
python -m pytest tests -q
```

A release still requires real Windows hardware and matching Summary and Teams Game
Report frames. Unit tests are not a substitute for that proof.

## Updating

The app checks `GET /api/client/release` at startup. When a newer build is available,
the user can choose **Update now**. No update installs itself. Downloads are restricted
to approved GitHub release hosts, use HTTPS, are size-bounded, and must match the
published SHA-256 before replacement. A failed swap rolls back to the prior executable.

## Windows release build

The Windows x64 artifact is `dist/OverAnalyzer.exe`.

```text
python -m pip install -r requirements.txt -r requirements-build.txt
python build.py
```

The build reads the version only from `overanalyzer_agent.__version__`, writes EXE
metadata, renders and embeds the app icon, bundles assets, then runs `--version` and
`--verify-assets` smoke checks. GitHub Actions uses the same build. A tag must match the
package version, for example `agent-v0.2.0` for package version `0.2.0`, and creates a
draft GitHub Release.

The binary is intentionally unsigned. Windows SmartScreen can show "Windows protected
your PC" on first run. Choose **More info > Run anyway**. Every release includes a
SHA-256 sidecar:

```powershell
(Get-FileHash OverAnalyzer.exe -Algorithm SHA256).Hash.ToLower()
```

### Owner validation before publication

1. Download the exact draft artifact and verify its SHA-256.
2. Run it normally on clean Windows and verify the SmartScreen path, panel, fonts,
   role art, and lack of a console window.
3. Pair an approved test account. Capture Summary with F11, show Teams, then run the
   self test.
4. Verify the visible buttons and configured F9, F11, and F12 hotkeys with Overwatch
   borderless or windowed.
5. Capture a real matching Game Report pair and confirm the expected retained result.
6. Publish the existing draft without rebuilding or replacing its bytes.
