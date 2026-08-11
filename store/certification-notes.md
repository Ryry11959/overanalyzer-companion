# Notes for certification

Paste the section below into **Partner Center → Submission → Submission options →
Notes for certification**. It exists because this app trips three things a
reviewer is trained to look at twice - a full-trust capability, screen capture,
and global keyboard hooks - and every one of them has an ordinary explanation
that is faster to read than to infer from the binary.

Keep it accurate. If the app's behaviour changes, change this first.

---

## Paste this

**What the app does**

OverAnalyzer is a companion app for the game Overwatch. When the player finishes
a match and opens the in-game Game Report, they press a hotkey and the app
captures the three regions of that screen (the match summary and both team
leaderboards) and uploads them to the OverAnalyzer service, which reads them
with OCR and records the match. It replaces taking screenshots by hand and
uploading them to a website.

**Testing the app without the game**

You do not need Overwatch to verify the app runs and that its capture and
network paths work:

1. Launch the app. A 360px frameless panel appears in the corner of the screen.
   It has no title bar by design - drag it by its own header, quit with the
   power button at its top right.
2. Open **Settings** (gear, top right) → **Run self test**. This exercises the
   entire pipeline once and reports each stage separately: service reachability,
   screen capture, upload, OCR, and cleanup.
3. With no Game Report on screen there are no leaderboards to find, so the
   capture stage reports that and the remaining stages still run. That is the
   expected result on a desktop and is sufficient to confirm the app functions.
4. **Settings → Advanced → Test capture** performs a single capture and writes
   the images to a local folder, openable with **Open debug folder**.

The app works with no sign-in. A device key is only required if the account
holder has enabled authentication on their own self-hosted server; the default
hosted service does not require one for the self test to run.

**Why the app declares `runFullTrust`**

The app is a Python/Tkinter desktop application packaged with PyInstaller, and
it needs two things outside the UWP sandbox:

- **A global hotkey.** The capture must trigger while Overwatch has keyboard
  focus, so the app registers a low-level keyboard hook (default F11, F12, F9).
  The keys are rebindable in Settings.
- **A desktop screen capture.** Capture is an ordinary desktop screen grab of a
  single selected monitor via the `mss` library.

**What the app deliberately does not do**

- It does **not** hook, read the memory of, or inject into the game process, or
  any other process. It is a separate desktop window that takes screenshots.
- It does **not** capture on a timer or in the background. A capture happens
  only after an explicit user action: a hotkey press, a button in the panel,
  **Test capture**, or **Run self test**. There is no background capture loop.
- It does **not** modify the game or provide any in-match advantage. Capture is
  of the post-match summary screen only.
- It does **not** install or modify anything outside its own package and its
  per-user data folder. Bundled fonts are registered privately with
  `AddFontResourceEx(FR_PRIVATE)` and the registration ends with the process -
  nothing is installed into the system font store.
- The Store build does **not** self-update. The app detects MSIX package
  identity at runtime and disables its own updater, leaving updates to the
  Store.

**Data collected, and the privacy policy**

Captured images are of the game's own post-match report. They contain the
in-game names of the nine other players in that match, which is why the app has
a privacy policy and declares data collection. Images are sent over HTTPS to the
account holder's OverAnalyzer service for OCR. The app stores the last 10
capture attempts locally for troubleshooting; those local reports record the API
host and never the user's device key.

**Source code**

The app is open source and the release build is reproducible from it:
https://github.com/ryry11959/overanalyzer-companion
