# Screenshots and Store images

**This is the one part of the submission that cannot be generated from the
repository.** Every other file in `store/` is finished text; these have to be
captured from the app running on your Windows machine, because they are pictures
of it. The spec below is exact enough to shoot in one sitting.

## What the Store requires

| Image | Required? | Size | Notes |
| --- | --- | --- | --- |
| **Screenshots** | **Yes - at least 1** | 1366×768 or 1920×1080 PNG | Up to 10. Shoot 4-5; the first is the one nearly everyone sees. |
| Store logo | Recommended | 300×300 PNG | Generated for you - use `dist/msix/Assets/Square310x310Logo.png`, resized to 300×300. |
| Poster art | Optional | 720×1080 PNG | Improves placement in Store collections. Skip for the first submission. |
| Hero image | Optional | 1920×1080 PNG | Only used if the Store features the app. Skip for the first submission. |

Screenshots must show **the app itself**. A picture that is mostly Overwatch
gameplay with the panel in a corner is the most likely rejection here, and it
also makes a bad listing image.

## The shots to take

Take these at **1920×1080** with the panel at 100% display scaling.

**1. The panel, capture active, with a match in "last captured".**
The money shot - it is the listing thumbnail. Run a capture first so the card
shows a real map, result, role, duration and K/D rather than an empty state.
Caption: `Log a match with two keypresses - the panel shows what it captured.`

**2. The panel with the activity log expanded.**
Click the activity row so several real events are visible. Shows that the app
tells you what it is doing.
Caption: `An activity log that tells you exactly what happened, capture by capture.`

**3. Settings → Connection, after Run self test.**
With the per-stage results visible. This is the app's most distinctive feature
and reads well as a screenshot.
Caption: `A built-in self test that checks every stage and names what broke.`

**4. Settings → hotkey rebinding.**
Showing the three bindable keys.
Caption: `Rebind the capture keys to anything you like.`

**5. Optional - the panel over a real Game Report.**
The most persuasive shot, and the riskiest. If you take it, the panel must be
the clear subject of the image. Do not use it as the *first* screenshot, and
crop so it is not simply a picture of Blizzard's UI.

## Two rules that get listings rejected

1. **No other company's trademarks or artwork.** No Blizzard logos, no Overwatch
   wordmark, no hero art, no key art anywhere in a screenshot, in a caption, or
   in the poster/hero images. Shot 5 is where this goes wrong.
2. **No personal information in the frame.** The "last captured" card and any
   Game Report in shot 5 will show **other players' gamertags**. Blur them, or
   use a custom game with friends who are fine with appearing. Also check the
   panel for your own account details, and make sure no device key is visible in
   the Settings screenshots - blank the field before shooting.

## Practical notes

- Capture with **Win+Shift+S** or Snipping Tool, and save as **PNG**. Do not use
  JPEG - the Store accepts it, but the panel's flat dark UI shows compression
  artefacts badly.
- The panel is frameless and always-on-top, so a window-capture tool may miss
  it. Grab the region instead.
- Do not upscale. If you shoot at 1366×768, upload at 1366×768.
- Captions are optional but worth writing - they appear beneath each screenshot
  and are the only place to explain what the reader is looking at.
