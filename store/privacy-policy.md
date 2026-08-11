# OverAnalyzer privacy policy

**Last updated: 11 August 2026**

> **Before you publish:** this is a factual description of what the app actually
> does, written from its source. Two things still need you:
>
> 1. Replace `<CONTACT EMAIL>` below with a real address you monitor.
> 2. Read it against the *service* as well. It describes the desktop app
>    accurately; you own what `api.overanalyzer.app` does with an upload after it
>    arrives, including how long it keeps images, and only you can confirm the
>    retention sentence is true.
>
> The Store requires a **publicly reachable URL**, not a file. Publishing the
> repository's `docs/` folder to GitHub Pages, or linking the rendered file on
> GitHub, both satisfy it - the URL just has to load without a login.

## What this covers

OverAnalyzer is a desktop companion app for the game Overwatch. This policy
covers the desktop app and the OverAnalyzer service it uploads to.

## What the app collects

**Screenshots of the game's post-match Game Report.** When you press a capture
hotkey (default F11 and F12) or click a capture button, the app takes a picture
of up to three regions of your screen: the match summary and the two team
leaderboards. It uploads them over HTTPS to the OverAnalyzer service, which
reads them with OCR to record the match in your history.

**These images show the in-game names of the other players in your match.**
That is unavoidable - those names are printed on the leaderboard the app is
built to read. The app does not attempt to identify those players beyond the
name shown on screen, and does not build profiles of them.

**Your account's device key**, if your OverAnalyzer server requires one. It is
sent as an HTTP `Authorization` header to prove the upload is yours. It is
stored on your PC in `agent.toml` in your user profile.

**Your in-game name**, only where an older installation still has the legacy
`self_gamertag` setting filled in; current versions take it from your account
instead and never ask for it.

## What the app does not collect

- **No analytics, telemetry, tracking, or advertising.** There is no third-party
  SDK in the app and nothing reports how you use it.
- **No keystroke logging.** The app registers a global hotkey so a capture can
  be triggered while the game has focus. It reacts to the specific keys you have
  bound and does not record, store, or transmit anything you type.
- **No continuous or background screen capture.** A capture happens only after
  an explicit action: a hotkey press, a capture button, **Test capture**, or
  **Run self test**. The app does not watch your screen between those.
- **No access to your game account, no reading of game memory, and no
  modification of the game.** Capture is an ordinary desktop screenshot.
- **No location data, contacts, camera, or microphone.**
- **No sale of personal information to anyone, ever.**

## When the app talks to the network

1. **Uploading a capture** - `POST /api/uploads/screenshots`, carrying the
   captured images and your device key. This only happens when you capture.
2. **Checking the result** - the app polls the match it just created until OCR
   finishes, so it can tell you complete / needs review / error.
3. **Checking for an update, on startup** - a request to the service asking what
   the newest build is. It sends no personal data, though as with any web request
   the server sees your IP address. **Copies installed from the Microsoft Store
   do not make this request at all**, because the Store handles their updates.
4. **Loading map artwork** for the "last captured" card in the panel.

All of it goes over HTTPS to the single service address the app is configured
with (`https://api.overanalyzer.app` by default). If you self-host OverAnalyzer
and point the app at your own server, your data goes there instead, and this
policy's description of the service does not apply to your server.

## What is stored on your own PC

- `agent.toml` - your settings, including your device key.
- `agent.state.json` - the day's capture count, and nothing else.
- `debug_out` - the **last 10 capture attempts**, kept so a bad OCR result can
  be diagnosed. Each folder holds the captured images and a report of what
  happened. The report records the service address and **never your device
  key**. The images are pictures of the Game Report, so they do show the
  gamertags from that match - worth a look before you send one to anyone.

These files stay on your machine. Nothing deletes them but you and the app's own
10-attempt limit. They live in `%LOCALAPPDATA%\OverAnalyzer` (for a Microsoft
Store install, Windows redirects that to the app's own per-user package folder).

## Data kept by the service

Uploaded images and the match data read from them are stored against your
account so you can see your match history. You can delete a match from the web
app; deleting it removes the match and its images.

## Children

OverAnalyzer is not directed at children under 13 and does not knowingly collect
personal information from them.

## Changes

Material changes to this policy will be published here with a new date at the
top, and the current version always applies to the current release.

## Contact

Questions, or a request to delete your data: **`<CONTACT EMAIL>`**

Source code: https://github.com/ryry11959/overanalyzer-companion
