# Store listing copy

Every field Partner Center asks for under **Store listings → English (United
States)**, written to paste straight in. Character limits are the Store's, and
each block below is inside its limit.

---

## Product name

> Reserve this under **Product → Product identity → Manage app names**.

```
OverAnalyzer
```

---

## Short description

*Limit 1,000 characters. This is what shows in search results, so the first line
carries it.*

```
Log your Overwatch matches with a keypress. OverAnalyzer captures the Game Report at the end of a match and reads it for you - map, result, role, duration, eliminations, deaths and the full scoreboard - so your match history builds itself instead of costing you a screenshot, a browser tab and a manual upload every game.

Press F11 on the summary, Tab to the scoreboard, press F12. That is the whole workflow. A small always-on-top panel shows what it captured and whether it read cleanly, then gets out of your way.
```

---

## Description

*Limit 10,000 characters.*

```
OverAnalyzer turns the end-of-match Game Report into a logged match, automatically.

Overwatch shows you a detailed report after every game and then throws it away. Keeping any of it means screenshotting, alt-tabbing, finding the file and uploading it - every match, which is exactly why nobody does it past the first week. OverAnalyzer replaces all of that with two keypresses.

HOW IT WORKS

On the match summary screen, press F11. Open the scoreboard with Tab and press F12. The app captures the summary and both team leaderboards, uploads them, reads them, and records the match. A corner toast tells you it landed. That is it - you are already queueing for the next game.

WHAT YOU GET

- Your match history builds itself, game after game, with no tab-out and no manual upload.
- Map, result, your role, match duration and your eliminations and deaths, read from the report itself.
- The full scoreboard for both teams, not just your own row.
- A "last captured" card in the panel showing the match you just logged and whether OCR read it cleanly, with a link straight to it in the web app.

THE PANEL

A 360px always-on-top card that sits in the corner of your screen. It shows whether capture is active, the two capture buttons and their keys, your running count for the day, the last match you logged, and an activity log you can collapse. It is deliberately small and completely static - it never animates or repaints over your game.

Pause it with F9 whenever you want. Rebind any of the three keys in Settings by clicking the row and pressing the key you want. If you run more than one monitor, pick which one to capture from.

DOES IT ACTUALLY WORK? RUN THE SELF TEST

Settings has a Run self test button that puts a real capture through the entire pipeline and reports each stage separately - the service, the screen capture, the upload, OCR, and cleanup. If something is broken it names the part that broke and what to do about it, instead of giving you one unhelpful verdict. It is a real capture rather than a synthetic ping, because only a real one proves the thing you actually care about.

WHAT IT DOESN'T DO

OverAnalyzer does not hook the game, read its memory, or inject anything into it. It is a normal desktop window that takes a screenshot of your own screen when you press a key, and it only ever captures after you press one - there is no background capture loop. It gives no in-match advantage of any kind: it reads the summary screen after the game is already over.

BEFORE YOU INSTALL

- Built and tested for 1920x1080. Other resolutions are derived automatically and should work, but are not yet hardware-verified.
- Global hotkeys are most reliable with Overwatch in borderless or windowed mode. In exclusive fullscreen Windows can swallow the hook - if that happens, the on-screen capture buttons still work.
- Captured images are of the Game Report, so they include the in-game names of the other players in your match. See the privacy policy.

OverAnalyzer is open source. You can read exactly what it captures and where it sends it:
https://github.com/ryry11959/overanalyzer-companion
```

---

## What's new in this version

*Limit 1,500 characters. For 0.1.0:*

```
First release on the Microsoft Store.

- Two-key capture of the Overwatch Game Report: F11 on the summary, F12 on the scoreboard.
- Always-on-top companion panel with live status, the last match you captured, and an activity log.
- Run self test: puts a real capture through the whole pipeline and reports each stage separately.
- Rebindable hotkeys, multi-monitor selection, and a capture-region override for unusual setups.
```

---

## Product features

*Up to 20, 200 characters each. These render as the bulleted list near the top of
the listing.*

```
Log a match with two keypresses - no screenshots, no alt-tab, no manual upload
Reads map, result, role, duration, eliminations and deaths from the Game Report
Captures the full scoreboard for both teams, not just your own row
A small always-on-top panel that never animates or repaints over your game
Rebindable hotkeys, pause with F9, and multi-monitor support
Built-in self test that checks every stage of the pipeline and names what broke
Open source - read exactly what it captures and where it sends it
```

---

## Search terms

*Up to 7, 30 characters each. Not shown to users; these only affect search.*

```
overwatch
overwatch tracker
match history
scoreboard capture
game report
ow2 stats
match tracker
```

---

## Additional listing fields

| Field | Value |
| --- | --- |
| **Category** | Utilities & tools *(secondary: Games → Utilities, if offered)* |
| **Privacy policy URL** | The hosted URL of `store/privacy-policy.md` - **required**, see that file |
| **Website** | `https://overanalyzer.app` |
| **Support contact info** | The email you monitor, or the repo's issues URL |
| **Copyright and trademark info** | `© 2026 OverAnalyzer` |
| **Applicable license terms** | `https://github.com/ryry11959/overanalyzer-companion/blob/main/LICENSE` |

### A note on the word "Overwatch"

The listing describes what the app is compatible with, which is ordinary
nominative use and is fine. Keep it that way:

- **Do** say OverAnalyzer is *for* Overwatch, or *works with* Overwatch.
- **Do not** put "Overwatch" in the product name, and do not use Blizzard's
  logos, fonts, or artwork anywhere in the listing or the screenshots.
- The app name stays `OverAnalyzer`.

This is the most likely reason a listing like this gets flagged, and it is
entirely avoidable.
