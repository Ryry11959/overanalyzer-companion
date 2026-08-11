# Age rating (IARC) answers

Partner Center makes you complete the IARC questionnaire before a submission can
be certified. It is short, but two of the questions are easy to answer wrongly
for this app in a way that either inflates the rating or - worse - understates
what it does. The answers below are the accurate ones, with the reasoning kept
next to them so a future version can be re-checked rather than re-guessed.

**Expected outcome:** the lowest rating in every board (ESRB Everyone, PEGI 3,
USK 0, and equivalents). Nothing here pushes it higher.

## The questionnaire

| Question | Answer | Why |
| --- | --- | --- |
| Is this app a game? | **No** | It is a utility that captures and uploads a screen region. Answering yes routes you into a long content questionnaire that does not apply. |
| Violence, blood, or gore | **No** | The app contains no content of its own. It captures a statistics screen, not gameplay. |
| Sexual content or nudity | **No** | |
| Profanity or crude humour | **No** | |
| Alcohol, tobacco, or drug references | **No** | |
| Gambling, real or simulated | **No** | No loot boxes, no wagering, no simulated gambling. |
| Fear, horror, or disturbing content | **No** | |
| Discrimination or hate content | **No** | |
| **Does the app allow users to interact or communicate with each other?** | **No** | There is no chat, no comment, no messaging, and no social feature *inside the app*. Users cannot reach each other through it. |
| **Does the app allow users to share user-generated content?** | **No** | Captures upload to the user's own private match history. They are not published, not shown to other users, and there is no sharing feature in the app. |
| **Does the app share the user's personal information with third parties?** | **No** | Data goes only to the OverAnalyzer service the app is configured for - the first party. No analytics SDK, no ad network, no data broker. |
| **Does the app share the user's current physical location with other users?** | **No** | The app has no access to location. |
| Does the app allow purchases of digital goods? | **No** | Nothing is sold in the app. |
| Does the app contain advertising? | **No** | No ads and no ad SDK. |
| Does the app collect or transmit personal information? | **Yes** | Answer honestly. Captured images contain in-game names, and the app sends a device key. This does not raise the age rating; it is the answer that makes the privacy policy declaration consistent, and an inconsistency here is a certification failure. |

## Keep this consistent with the rest of the submission

The rating questionnaire, the privacy policy, and the **Product declarations**
page all describe the same behaviour, and certification checks that they agree.
If any of these change, change all four together:

- `store/privacy-policy.md` - what is collected and where it goes.
- `store/certification-notes.md` - the explanation reviewers read.
- This file.
- Partner Center → **Properties → Product declarations** → *"This app collects
  personal information"*, which must be **checked**, with the privacy policy URL
  supplied.

## If the app gains a social feature

Adding sharing, a public profile, leaderboards other users can see, or any way
for users to reach each other flips the two bolded "interact / user-generated
content" answers to **Yes**, which raises the rating and requires a
content-moderation answer. Re-run the questionnaire before shipping that
version - the rating does not update itself.
