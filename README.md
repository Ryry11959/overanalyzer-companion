# OverAnalyzer desktop capture app

A small desktop **app** that captures the three regions of the Overwatch **Game Report**
on a global hotkey (the match summary and both team leaderboards) and uploads them to a
running OverAnalyzer API for OCR - so you can log a match with a keypress instead of
screenshotting and uploading by hand.

The main UI is a **360px overlay panel** (`window.py`): a frameless, always-on-top
card that sits in the corner of your screen over a topographic contour backdrop,
with a live capture/paused status row, the two capture buttons with their key
chips, running counts, the last match you captured, and a collapsible activity
log. Settings is a **second screen inside the same frame**, not a second window.
The capture code fits a summary crop to the display, finds the blue/red
leaderboard **anchors**, and POSTs the three Game Report regions to
`POST /api/uploads/screenshots`.

The capture/upload core (`controller.py`) is UI-agnostic, so a **system-tray**
variant (`--tray`) and a **headless CLI** (`--cli`) share it. Out of scope (P2+):
in-match overlay, automatic Game Report detection, multi-monitor auto-detect, and
the eventual Tauri rewrite.

## Design

The panel uses violet-navy chrome, an indigo primary, 6px radii, Space Grotesk
for UI text, and JetBrains Mono for every numeral. It is drawn on a single Tk
canvas rather than assembled from widgets, because Tk widgets are opaque and
would paint the backdrop out of the gaps between panels. There is **no UI toolkit
dependency** - the design tokens,
the lucide glyphs and the contour texture are all in `overanalyzer_agent/ui/`:

| Module | What it does |
| --- | --- |
| `ui/theme.py` | the design system's tokens as Tk colours, plus alpha flattening |
| `ui/layout.py` | each screen as a pure list of draw ops + hit regions (fully unit-tested) |
| `ui/surface.py` | paints a layout onto a canvas; hover, cursor, tooltips, clicks |
| `ui/icons.py` | lucide glyphs, from lucide's own SVG source via `ui/svgpath.py` |
| `ui/topography.py` | the contour backdrop (**static** - it never repaints over a game) |
| `ui/fonts.py` | registers the bundled TTFs privately, falls back to system fonts |
| `ui/toast.py` | the corner toasts (uploaded / needs review / error) |

Fonts are vendored under `assets/fonts` (Space Grotesk, JetBrains Mono, Rajdhani
- SIL Open Font License, texts in `assets/fonts/licenses`) and registered with
`AddFontResourceEx(FR_PRIVATE)` at startup, so nothing is installed on your
machine and the registration dies with the process.

## Install

Python 3.11+ (release builds use Python 3.13.4). From the repository root:

```
pip install -r requirements.txt
```

## Configure

```
cp agent.example.toml agent.toml   # then edit agent.toml
```

**You normally don't need a config file at all.** The only thing the app asks
for is a **device key**, and you paste that into its Settings screen - see
[Authentication](#authentication). Captures always go to the hosted
OverAnalyzer, so there is deliberately no server-address field in the UI.

The file is for **self-hosting** and tweaks:
- `api_url` - your own API (defaults to `https://api.overanalyzer.app`).
- `web_url` - the matching web app (defaults to `https://overanalyzer.app`). Powers device
  pairing, the "Open in app" link, and map art on the last-captured card.
- `bearer_token` - the device key, if you'd rather set it here than in the UI.
- `monitor_index` - which display to capture, on a multi-monitor setup.

**There is no gamertag setting.** Your in-game name lives on your *account* - you
set it during onboarding in the web app, and the server uses that. (`self_gamertag`
still exists in the config as a legacy fallback for old installs; the app never
asks for it and never writes it.)

Env vars override the file (handy for secrets): `OA_AGENT_API_URL`,
`OA_AGENT_WEB_URL`, `OA_AGENT_TOKEN`.

## Run - the app

**Double-click `OverAnalyzer.cmd`** (Windows) - it launches the panel with
the repo venv's windowed Python, no console. Or from a terminal:

```
cd agent
python -m overanalyzer_agent          # the panel (picks up agent.toml automatically)
```

The panel opens with **capture active** and starts listening for your hotkeys
immediately. It has no OS title bar: drag it by its own header, and quit with the
power button top-right. From here you can:

- **Pause / Resume** - the button in the status row, the F9 hint line beneath the
  capture buttons, or the **F9** key itself. All three do the same thing.
- **Capture summary** / **Scoreboard + upload** - trigger a capture by button
  (works even if the hotkeys couldn't bind).
- **Last captured** - the map, result, your role, duration and K/D of the match
  you just uploaded, with its OCR status. Click **Open in app →** to open it in
  the web app.
- **Activity** - the row at the bottom always shows the latest event; click it to
  expand the log.
- **Settings** (gear, top-right) - a **Device key** field (with a **Pair a
  device →** link into the web app) and **Run self test**, hotkey rebinding
  (click a row, press a key), an **Advanced** section with a **Monitor** picker
  (only shown when more than one display is detected), the capture-region
  override, **Test capture**, and the **debug folder**, and Quit. Changes save
  as you make them; there is no Save button. Server addresses aren't here on
  purpose - captures always go to the same place, and self-hosters set
  `api_url` in `agent.toml`.

## Does it actually work? The self test

**Run self test** (Settings → Connection) runs the whole capture path once and
reports each hop separately: the service and device key, the screen capture, the
upload, the OCR pipeline, and cleanup. A failure names the hop that broke and
what to do about it, rather than a single verdict you cannot act on.

It is a *real* capture, because nothing else proves the thing you care about:

- It **uploads**, so it uses one of your daily uploads. A synthetic ping would
  exercise a path no real capture takes, which is exactly how a valid device key
  used to pass while every upload was being refused.
- It therefore **creates a real match**, and the last stage deletes it again. If
  that delete fails, the report gives you the match id to remove by hand instead
  of claiming your history is clean.

You can run it from the desktop. With no Game Report on screen there are no
leaderboards to find, so the capture stage says so and the rest of the test still
runs - the pipeline is what is being tested.

## Updating

The app asks the service what the newest build is when it starts
(`GET /api/client/release`). If there is one, a banner appears at the top of the
panel: **Update 0.2.0 available**, with an **Update now** button. Clicking it
downloads the new build, checks it against the published SHA-256, then closes
the app and reopens it on the new version. A release marked important is worded
more insistently and nothing else: **no update ever installs itself.**

Because this is an unsigned binary that a user's machine downloads and runs, the
rules are worth stating plainly:

- **The service cannot choose the download host.** The app carries its own
  allow-list (GitHub's release hosts) and refuses any other location before it
  makes a request, so a compromised API can withhold or misdescribe a release
  but cannot point installations at an arbitrary binary.
- **HTTPS only**, and the download is size-bounded.
- **The SHA-256 is verified before anything is replaced.** A mismatch deletes
  the download and changes nothing on your PC.
- **A failed swap rolls back**, so an update that goes wrong leaves the previous
  working build rather than no app at all. If it cannot, it writes a report to
  `%TEMP%\OverAnalyzer-update-failed-<pid>.txt` instead of failing silently.

Running from a source checkout, the app says so and points you at git rather
than trying to swap a binary that isn't there.

## The debug folder

Every capture attempt, successful or not, is saved under `debug_out` next to
`agent.toml` (`%LOCALAPPDATA%\OverAnalyzer\debug_out` in a packaged build). Open
it from **Settings → Advanced → Open debug folder**. Each attempt is one folder:

```
2026-08-10_15-42-03_needs_review/
    summary.png  team1.png  team2.png
    attempt.txt     <- readable report: outcome, stages, display, geometry
    attempt.json    <- the same facts for tooling
```

That is what to send when a match comes back wrong: the images are the only
thing that explains a bad read. The report deliberately records the API host and
**never your device key**. The screenshots are pictures of the Game Report, so
they do show the gamertags from your match - the report says so, and it is worth
a look before you share one. Only the last 10 attempts are kept; the server keeps
the authoritative copies.

The two-step capture: on the **summary** screen press the summary hotkey (default
**F11**), then open the **scoreboard** (Tab) and press the scoreboard hotkey
(**F12**) - that uploads `summary + team1 + team2` in one request and polls the
match until OCR settles, reporting **complete / needs review / error** in a corner
toast and the activity log. While a summary is held, the panel says so and offers
**Discard**. (Summary is required; a leaderboard that can't be found is simply
omitted - the server records the match as partial.) Capture/upload runs on a
worker thread so the panel stays responsive while OCR is polled.

> **F9 pauses; it no longer resets the buffer.** The design gives F9 to pause,
> which is the thing you actually reach for mid-session. Discarding a half-made
> capture is now the **Discard** link that appears when a summary is held, and
> **Reset buffer** in the tray menu. The `hotkey_reset` config key kept its name
> so existing `agent.toml` files still work; in the headless `--cli` driver it
> still resets, as it always did.

## Other ways to run

The capture core is shared, so the same behaviour is available headless or in the tray:

```
python -m overanalyzer_agent --tray       # system-tray icon + menu + toasts
python -m overanalyzer_agent --settings   # open the panel on its settings screen
python -m overanalyzer_agent --cli        # headless global-hotkey loop (prints results)
```

## Tuning capture regions

**You normally don't.** Geometry is derived from your screen at capture time:
Overwatch scales its menus into a 16:9 box fitted to the display and centred, so
the crop is computed from that box rather than from fixed pixel coordinates.
The geometry scales to other display shapes, but the first public release is
hardware-validated at 1920x1080 only. Treat other resolutions as unverified.

- **Leaderboards** default to `leaderboard_mode = "anchor"`, which finds each
  team's bar by an **exact** colour match (`blue_colors` = own team, `red_colors`
  = enemy).
- **`color_tolerance`** (default `0`) and **`auto_team_colors`** (default `false`)
  loosen that match - the latter samples the bars off the frame by saturation and
  position, for Overwatch's colourblind palettes. **Both are opt-in on purpose.** The
  anchor box spans every matched pixel, so a looser match lets one stray pixel
  elsewhere on screen stretch the crop past the leaderboard; the rows then no
  longer align with the grid and every stat comes out wrong rather than the
  capture simply failing. If you turn either on, verify with `debug_capture.py`
  that the box still hugs the leaderboard (~850×330 on 1080p, not ~850×670).
- **Overrides** still work - set `summary_region` / `leaderboard_width` to pin
  explicit pixels. Take a screenshot, read off the left/top/right/bottom of the
  result panel, and put them in `agent.toml` (or in Settings → Advanced). Clear
  the value to go back to auto.
- If anchor detection misfires entirely, set `leaderboard_mode = "region"` and
  provide `team1_region` / `team2_region` rectangles explicitly.
- `python debug_capture.py` prints the resolved geometry, whether it was
  configured or derived, and which bar colours auto-detection finds on your frame.

## Authentication

With the default **auth-off** deployment (`the default unauthenticated mode`) no token is
needed. If the server runs with auth **on**, the agent authenticates with a
**device key**, not your login credentials: open the web app, go to
**Settings → Devices**, and mint one (one live key per account - minting a
second revokes the first). Paste it into the app's Settings screen (the
**Device key** field - there's a **Pair a device →** link that jumps straight to
that page once `web_url` is set) or into `bearer_token` / `OA_AGENT_TOKEN`
directly. The agent sends it as `Authorization: Bearer …`; the server tells a
device key apart from a user session token without a DB hit.

## Caveats

- **Windows + fullscreen games:** global hotkeys (the `keyboard` library) are
  most reliable when Overwatch runs in **borderless/windowed** mode; exclusive
  fullscreen can swallow the hook. You may need to run the app **as administrator**
  for the hotkeys to fire while the game is focused. If a hotkey can't bind, the
  app says so in the activity log and the on-screen capture buttons still work.
- The panel is frameless and always-on-top, so it has **no taskbar button** -
  quit it from its own power button or the tray.
- **Multi-monitor:** capture defaults to the primary display; if the game runs
  on a secondary one, pick it from Settings → Advanced → Monitor (only shown
  when more than one display is detected) or set `monitor_index` in
  `agent.toml`. *Auto*-detecting which monitor the game is on is still out of
  scope - this is a manual pick, not automatic.
- Live capture needs a real screen + the game, so it can't be tested in CI - see
  the hermetic tests below for what *is* covered automatically.
- `agent.state.json` (next to `agent.toml`) holds only the day's capture count.

## Tests

The upload path, capture geometry, and the whole presentation layer are unit-
tested without a display (the screen/hotkey libraries and Tk are imported lazily,
and the layout is pure data):

```
.venv/Scripts/python.exe -m pytest tests -q
```

The release gate also runs **Run self test** and a real 1920x1080 Game Report on
Windows hardware. The unit suite is not a substitute for that proof.

## Windows release build

The distributable is one Windows x64 file: `dist/OverAnalyzer.exe`.
Build it only on Windows; PyInstaller bundles are platform-specific.

```
.venv/Scripts/python.exe -m pip install -r requirements.txt -r requirements-build.txt
.venv/Scripts/python.exe build.py
```

The build script gets the release version solely from
`overanalyzer_agent.__version__`, writes it into the EXE metadata, renders the
app icon from `ui/brand.py` into a multi-resolution `.ico` and embeds it (so the
downloaded file carries the OverAnalyzer mark in Explorer and the taskbar rather
than PyInstaller's default), explicitly bundles `assets`, then starts the
real one-file EXE with `--version` and `--verify-assets`. Those smoke checks do not open the panel, bind a global hotkey,
or contact a service.

The dedicated `.github/workflows/release-agent.yml` workflow performs that same
build on Windows. A manual run uploads the EXE and SHA-256 sidecar as a short-lived
Actions artifact. Pushing a tag that exactly matches the packaged version, for
example `agent-v0.1.0` for package version `0.1.0`, also creates a **draft** GitHub
Release containing those files. The draft remains private to repository maintainers
until the exact candidate passes the Windows and Game Report checks below. Publishing
the tested draft is a separate owner action and must not rebuild or replace its bytes.

### The release is unsigned - on purpose

`OverAnalyzer.exe` carries **no Authenticode signature**, so Windows SmartScreen
shows *"Windows protected your PC"* on first run and the user has to choose
**More info → Run anyway**. That is expected, not a symptom of a broken download.

Code signing was dropped for the beta because it required legal-entity identity
validation and an ongoing subscription. Trust is provided differently here: the
companion source and release workflow are public and auditable.

- `capture.py` selects exactly **one monitor** and captures only after an explicit
  action: F11/F12, a capture button, Test capture, or Run self test. There is no
  timed or background screen-capture loop.
- `uploader.py` constructs every upload and status URL from the single configured
  `api_url` host.
- Nothing hooks the game process, reads its memory, or injects into it. Capture is
  an ordinary desktop screen grab through `mss`; the companion panel is a separate
  desktop window.

Every release publishes a SHA-256 sidecar. It verifies the exact bytes downloaded
from that Release. The direct dependencies, PyInstaller, and Python patch are pinned
so the build inputs are reviewable, but independent PyInstaller builds are **not**
promised to be byte-identical. Verify the published candidate against its sidecar:

```
# PowerShell - compare against the published .sha256
(Get-FileHash OverAnalyzer.exe -Algorithm SHA256).Hash.ToLower()
```

### Owner-only Windows validation before publication

1. Download the exact EXE from the release run and verify its SHA-256 against the
   published sidecar.
2. On a clean Windows machine, open it normally and click through the SmartScreen
   warning as a user would. Confirm the panel opens, fonts and role art render,
   and no console window appears.
3. Pair with a non-production or approved test account and use **Run self test**.
   Do not use a live account for release validation without the owner's approval.
4. With Overwatch in the intended borderless/windowed configuration, verify the
   visible buttons and the configured F9/F11/F12 hotkeys. Exclusive fullscreen or
   Windows permissions can prevent global hooks, so the owner-not CI-must perform
   this hardware validation.
5. Capture a real 1920x1080 Game Report, confirm the expected upload/result state,
   and only then publish the existing draft without rebuilding its EXE or checksum.
   The download
   page must document the SmartScreen warning - screenshot, exact click path, and
   the checksum command above - before the link goes live.
