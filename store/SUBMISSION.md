# Microsoft Store submission

Everything needed to get OverAnalyzer onto the Microsoft Store, in the order it
has to happen. The other files in this folder are the content each step asks
for; this one is the sequence.

**The Store does not replace the direct download.** Both channels ship the same
executable, and it works out at runtime which one it is
(`overanalyzer_agent/packaging.py`). The Store build disables its own updater
and lets the Store update it; the GitHub Releases build keeps updating itself,
exactly as before. Keeping the direct download also keeps the
**run-as-administrator** fallback for players whose global hotkeys are swallowed
by exclusive fullscreen - a Store-installed app cannot elevate that way.

---

## Step 0 - do this first, today

**Open the Store developer account and start identity verification.**

> ### Use the right entry point
>
> Start at **<https://storedeveloper.microsoft.com>** → **Get started for free**
> → **Individual developer**.
>
> Do **not** start at `partner.microsoft.com`. That is the general Partner
> Center - the cloud/solutions partner program - and it enrols you as a
> **company**, asking for business details this app does not have. It looks like
> the right place and is not.
>
> ### Sign in with a *personal* Microsoft account
>
> The Individual tier requires a **personal Microsoft account (MSA)**. A
> **work or school account (Microsoft Entra ID) cannot be an Individual
> account** - sign in with one and Partner Center will only offer you Company,
> with no visible explanation.
>
> If the browser silently reuses a work account, open the link in a private /
> incognito window and sign in deliberately with the personal account you want
> to own this app.
>
> ### This choice is permanent
>
> **Individual cannot be converted to Company later.** Switching means opening a
> new account and re-publishing. Pick deliberately now: Individual unless you
> have a registered legal business entity you want to publish under.

Registration is **free** for both types. Individual verification is a
government-issued photo ID plus a selfie, which is normally fast; Company
verification checks business documents and is the slower path.

This step is first because it is the only thing on the critical path you do not
control. Everything below can be done while you wait, and leaving it until the
package is ready is the most common reason a submission slips a week.

### Your name, and what the public sees

The listing shows your **publisher display name**, which you choose. Set it to:

```
OverAnalyzer
```

You are not required to publish under your legal name. Microsoft collects your
real name and address for verification, tax and payouts, but that is private
account data and is not shown on the listing. Two exceptions worth knowing:

- **Trader status.** In the EU and some other regions, a publisher classified as
  a commercial *trader* must show contact details - name, address, email - to
  customers. For a free app you would normally declare **non-trader** and none
  of it is displayed. If you later charge for the app, revisit this.
- **The other submission path.** Publishing a signed `.exe` instead of an MSIX
  means buying a code-signing certificate, and an individual certificate's
  subject is your legal name, visible in the file's Digital Signatures tab. The
  MSIX path avoids this entirely - Microsoft signs the package.

Changing the publisher display name later forces an account review and a
re-submission of every app, so pick it once.

---

## Step 1 - reserve the app name

Partner Center → **Apps and games** → **New product** → **MSIX or PWA app**.
Reserve:

```
OverAnalyzer
```

Do not put "Overwatch" in the product name. See the trademark note at the end of
`listing.md` - nominative use in the description is fine, in the name it is not.

---

## Step 2 - capture your package identity

Once the name is reserved, open **Product → Product identity**. Copy the three
values into `msix/identity.json` (start from `msix/identity.example.json`):

| Partner Center field | Goes to |
| --- | --- |
| Package/Identity/Name | `identity_name` |
| Package/Identity/Publisher | `publisher` (begins `CN=`) |
| Package/Properties/PublisherDisplayName | `publisher_display_name` |

They must match **character for character** or the upload is rejected. The build
refuses to run with placeholders rather than producing a package that fails at
upload.

For CI, set the same three as repository *variables* named
`OA_MSIX_IDENTITY_NAME`, `OA_MSIX_PUBLISHER`, `OA_MSIX_PUBLISHER_DISPLAY_NAME`.
They are not secrets - they ship inside every copy of the package.

---

## Step 3 - build the package

On Windows, with the Windows 10/11 SDK installed (for `makeappx.exe`):

```
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-build.txt
.venv\Scripts\python.exe build_msix.py
```

Produces `dist/OverAnalyzer.msix`. The workflow
`.github/workflows/release-msix.yml` does the same build on a clean runner, on
demand or from a `store-v<version>` tag.

**Do not sign it.** Microsoft re-signs the package during certification. The
`--sign` flag exists only for installing it locally to test, and needs a
self-signed certificate whose subject equals your `Publisher` value.

---

## Step 4 - test the package before you upload it

The tests in `tests/test_msix.py` check the manifest and assets, but they cannot
prove the packaged app runs. Do this on a Windows machine:

1. Install the locally signed package (or use **App Installer**) and launch it
   from the Start menu.
2. The panel opens, fonts and role art render, and no console window appears.
3. `OverAnalyzer.exe --version` reports **`(store)`**, not `(direct)`. This is
   the check that the self-updater is inert - if it says `direct`, package
   identity was not detected and the app will try to update itself.
4. **No update banner appears** at the top of the panel.
5. Settings → **Run self test** passes its stages.
6. With Overwatch in borderless/windowed mode, F11/F12/F9 fire while the game
   has focus, and the on-screen capture buttons work.
7. Capture a real 1920×1080 Game Report and confirm the match is logged.

Steps 6 and 7 need real hardware and the game; they cannot be done in CI, which
is the same constraint the direct release already documents in the README.

---

## Step 5 - fill in the submission

In Partner Center, on the submission:

| Page | What to enter | Source |
| --- | --- | --- |
| **Pricing and availability** | Free. Markets: all. | |
| **Properties** | Category **Utilities & tools**. Tick **"This app collects personal information"** and give the privacy policy URL. | `age-rating.md` |
| **Age ratings** | Complete the IARC questionnaire. | `age-rating.md` |
| **Packages** | Upload `dist/OverAnalyzer.msix`. | Step 3 |
| **Store listing** | Description, features, search terms, screenshots. | `listing.md`, `screenshots.md` |
| **Submission options** | Paste the reviewer notes. | `certification-notes.md` |

**The privacy policy URL is required** and must load without a login - the app
collects data (captured images contain other players' in-game names). Host
`privacy-policy.md` somewhere public and fill in the contact address first.

---

## Step 6 - submit, then wait

Certification usually takes a few hours to three days. Expect a possible
question about `runFullTrust`, the screen capture, or the global keyboard hook -
that is exactly what `certification-notes.md` pre-empts. If certification comes
back with a request, answer it in the same terms: the app takes an ordinary
desktop screenshot after an explicit keypress, and does not hook, read, or
inject into the game.

---

## After it is published

- **Updates go through the Store.** Bump `overanalyzer_agent.__version__`,
  rebuild, upload a new package. The version must be higher than the published
  one; the Store rejects a resubmission at the same version.
- **The two channels can drift in version, and that is fine.** They are the same
  binary; only the update mechanism differs.
- **Keep the four data declarations consistent** whenever behaviour changes:
  `privacy-policy.md`, `certification-notes.md`, `age-rating.md`, and the
  Product declarations page.

## Known limitation of the Store build

A Store-installed app cannot be launched elevated the ordinary way, so the
"run as administrator" workaround for hotkeys in **exclusive fullscreen** is not
available there. Players who need it should use the GitHub Releases download.
Worth a line on the download page so nobody files it as a bug.
