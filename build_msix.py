"""Build the Microsoft Store (MSIX) package for the OverAnalyzer companion app.

This wraps the same one-file executable :mod:`build` produces. It does not build
a second, different app: the EXE inside the package is the EXE from
``python build.py``, and it decides at runtime that it is a Store build (see
:mod:`overanalyzer_agent.packaging`) and stands its self-updater down.

    .venv\\Scripts\\python.exe -m pip install -r requirements.txt -r requirements-build.txt
    .venv\\Scripts\\python.exe build_msix.py

What it produces, in ``dist/msix``:

* ``Assets/`` - every tile and icon the Store requires, rendered from
  ``ui.brand`` so they cannot drift from the icon on the EXE or the mark the
  running app draws in its own title bar.
* ``AppxManifest.xml`` - generated, because three of its values (the package
  identity) come from Partner Center and one (the version) comes from
  ``overanalyzer_agent.__version__``. Hand-editing it is how those drift apart.
* ``OverAnalyzer.msix`` - the uploadable package.

**Package identity must match Partner Center exactly** or the upload is
rejected. Copy the three values from *Product → Product identity* into
``msix/identity.json`` (see ``msix/identity.example.json``), or set
``OA_MSIX_IDENTITY_NAME``, ``OA_MSIX_PUBLISHER`` and
``OA_MSIX_PUBLISHER_DISPLAY_NAME`` in the environment.

Signing: a package uploaded to the Store does **not** need your signature.
Microsoft re-signs it with the Store certificate during certification. Signing
here (``--sign``) is only for testing the package by installing it locally, and
requires a self-signed certificate whose subject equals the ``Publisher`` value.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

AGENT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(AGENT_DIR))

from overanalyzer_agent import __version__  # noqa: E402

BUILD_DIR = AGENT_DIR / "dist" / "msix"
ASSETS_DIR = BUILD_DIR / "Assets"
MANIFEST = BUILD_DIR / "AppxManifest.xml"
PACKAGE = AGENT_DIR / "dist" / "OverAnalyzer.msix"
EXE_SOURCE = AGENT_DIR / "dist" / "OverAnalyzer.exe"
IDENTITY_FILE = AGENT_DIR / "msix" / "identity.json"

# The Store shows the app on displays from 100% to 400% scaling, and Windows
# picks the tile it needs by these exact filenames. Shipping one size and
# letting Windows downscale is what makes an app look second-rate next to
# properly built ones - the same reason build.py ships a multi-size .ico.
SQUARE_LOGOS = {
    "Square44x44Logo": 44,    # app list, taskbar, title bar
    "Square71x71Logo": 71,    # small tile
    "Square150x150Logo": 150,  # medium tile - the default
    "Square310x310Logo": 310,  # large tile
    "StoreLogo": 50,          # Partner Center and the Store listing
}
SCALES = (100, 125, 150, 200, 400)
# Taskbar and Alt-Tab ask for these by pixel size rather than by scale.
TARGET_SIZES = (16, 24, 32, 48, 256)
WIDE_LOGO = ("Wide310x150Logo", 310, 150)
SPLASH = ("SplashScreen", 620, 300)

# Windows 10 1809 - the floor for reliable MSIX full-trust desktop packages.
MIN_WINDOWS_VERSION = "10.0.17763.0"
MAX_WINDOWS_VERSION_TESTED = "10.0.22621.0"

DISPLAY_NAME = "OverAnalyzer"
# Store listings truncate hard; this is the tile/app-list description, not the
# listing copy in store/listing.md.
APP_DESCRIPTION = (
    "Capture the Overwatch Game Report with a hotkey and log the match "
    "automatically."
)


def _load_build_module():
    """Load ``build.py`` by path.

    By path rather than ``import build`` because a top-level module named
    ``build`` is a common package name and this must resolve to the file next to
    this one, not to whatever else is on the path.
    """
    spec = importlib.util.spec_from_file_location("overanalyzer_build", AGENT_DIR / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def package_version(version: str) -> str:
    """The four-part version string an MSIX Identity needs.

    The Store reserves the fourth part and requires it to be 0, so the package
    version is the package's own ``major.minor.patch`` with a zero revision -
    derived, never typed, so it cannot disagree with the EXE metadata.
    """
    build_mod = _load_build_module()
    major, minor, patch, revision = build_mod.windows_version_parts(version)
    return f"{major}.{minor}.{patch}.{revision}"


def load_identity() -> dict[str, str]:
    """The three Partner Center identity values, from env or ``identity.json``.

    Env wins, so CI can supply them without a file in the tree.
    """
    data: dict[str, str] = {}
    if IDENTITY_FILE.is_file():
        data = json.loads(IDENTITY_FILE.read_text(encoding="utf-8"))
    resolved = {
        "identity_name": os.environ.get("OA_MSIX_IDENTITY_NAME") or data.get("identity_name", ""),
        "publisher": os.environ.get("OA_MSIX_PUBLISHER") or data.get("publisher", ""),
        "publisher_display_name": (
            os.environ.get("OA_MSIX_PUBLISHER_DISPLAY_NAME")
            or data.get("publisher_display_name", "")
        ),
    }
    missing = [key for key, value in resolved.items() if not value.strip()]
    if missing:
        raise SystemExit(
            "Missing package identity: "
            + ", ".join(missing)
            + ".\nThese must match Partner Center exactly (Product → Product identity).\n"
            f"Copy msix/identity.example.json to {IDENTITY_FILE} and fill it in, "
            "or set OA_MSIX_IDENTITY_NAME / OA_MSIX_PUBLISHER / "
            "OA_MSIX_PUBLISHER_DISPLAY_NAME."
        )
    if not resolved["publisher"].upper().startswith("CN="):
        raise SystemExit(
            "OA_MSIX_PUBLISHER must be the full distinguished name Partner Center "
            f"shows, which begins with 'CN=' - got {resolved['publisher']!r}."
        )
    return resolved


def _render_square(size: int):
    from overanalyzer_agent.ui import brand

    return brand.icon(size)


def _render_letterboxed(width: int, height: int):
    """The icon centred in a transparent frame, for the wide tile and splash.

    Transparent rather than filled: the manifest's ``BackgroundColor`` paints
    behind these, so a baked-in background would show as a hard rectangle
    against the user's chosen tile colour.
    """
    from PIL import Image

    from overanalyzer_agent.ui import brand

    # 60% of the short edge keeps the mark inside the safe area Windows crops to.
    side = round(min(width, height) * 0.6)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    canvas.alpha_composite(brand.icon(side), ((width - side) // 2, (height - side) // 2))
    return canvas


def write_assets(target: Path) -> list[Path]:
    """Render every Store asset. Returns what was written."""
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for name, base in SQUARE_LOGOS.items():
        # The unqualified file is the fallback Windows uses when no resource
        # index is present; the scale-* files are what it prefers when one is.
        # Shipping both means the package is correct with or without makepri.
        for path, size in [(target / f"{name}.png", base)] + [
            (target / f"{name}.scale-{scale}.png", round(base * scale / 100))
            for scale in SCALES
        ]:
            _render_square(size).save(path, format="PNG")
            written.append(path)

    for size in TARGET_SIZES:
        icon = _render_square(size)
        for suffix in ("", "_altform-unplated"):
            path = target / f"Square44x44Logo.targetsize-{size}{suffix}.png"
            icon.save(path, format="PNG")
            written.append(path)

    for name, width, height in (WIDE_LOGO, SPLASH):
        for path, scale in [(target / f"{name}.png", 100)] + [
            (target / f"{name}.scale-{s}.png", s) for s in SCALES
        ]:
            image = _render_letterboxed(round(width * scale / 100), round(height * scale / 100))
            image.save(path, format="PNG")
            written.append(path)

    return written


def manifest_xml(identity: dict[str, str], version: str) -> str:
    """Generate the package manifest.

    Generated rather than committed for the same reason ``build.py`` generates
    the VERSIONINFO resource: the version in it must come from
    ``overanalyzer_agent.__version__``, and a hand-maintained copy is a version
    that will eventually be wrong.
    """
    from overanalyzer_agent.ui import theme

    return f"""<?xml version="1.0" encoding="utf-8"?>
<!-- Generated by build_msix.py. Do not edit; edit build_msix.py. -->
<Package
  xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
  xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
  xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
  IgnorableNamespaces="uap rescap">

  <Identity
    Name={quoteattr(identity["identity_name"])}
    Publisher={quoteattr(identity["publisher"])}
    Version={quoteattr(version)}
    ProcessorArchitecture="x64" />

  <Properties>
    <DisplayName>{escape(DISPLAY_NAME)}</DisplayName>
    <PublisherDisplayName>{escape(identity["publisher_display_name"])}</PublisherDisplayName>
    <Logo>Assets\\StoreLogo.png</Logo>
  </Properties>

  <Dependencies>
    <TargetDeviceFamily
      Name="Windows.Desktop"
      MinVersion="{MIN_WINDOWS_VERSION}"
      MaxVersionTested="{MAX_WINDOWS_VERSION_TESTED}" />
  </Dependencies>

  <Resources>
    <Resource Language="en-us" />
  </Resources>

  <Applications>
    <Application
      Id="OverAnalyzer"
      Executable="OverAnalyzer.exe"
      EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements
        DisplayName={quoteattr(DISPLAY_NAME)}
        Description={quoteattr(APP_DESCRIPTION)}
        BackgroundColor={quoteattr(theme.PAGE)}
        Square150x150Logo="Assets\\Square150x150Logo.png"
        Square44x44Logo="Assets\\Square44x44Logo.png">
        <uap:DefaultTile
          Wide310x150Logo="Assets\\Wide310x150Logo.png"
          Square71x71Logo="Assets\\Square71x71Logo.png"
          Square310x310Logo="Assets\\Square310x310Logo.png" />
        <uap:SplashScreen
          Image="Assets\\SplashScreen.png"
          BackgroundColor={quoteattr(theme.PAGE)} />
      </uap:VisualElements>
    </Application>
  </Applications>

  <Capabilities>
    <!-- The app is a packaged Win32 desktop app: it registers a global keyboard
         hook so a capture can be triggered while the game has focus, and takes
         an ordinary desktop screen grab. Neither is expressible as a sandboxed
         UWP capability. See store/certification-notes.md. -->
    <rescap:Capability Name="runFullTrust" />
  </Capabilities>
</Package>
"""


def find_sdk_tool(name: str) -> Path | None:
    """Locate a Windows SDK tool (``makeappx``/``signtool``/``makepri``)."""
    found = shutil.which(name)
    if found:
        return Path(found)
    roots = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Windows Kits" / "10" / "bin",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Windows Kits" / "10" / "bin",
    ]
    candidates: list[Path] = []
    for root in roots:
        if root.is_dir():
            candidates.extend(root.glob(f"*/x64/{name}.exe"))
    # Highest SDK version wins.
    return max(candidates, default=None, key=lambda p: p.parts)


def run(command: list[str]) -> None:
    print("+", subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, check=True)


def build(*, skip_exe: bool = False, sign_thumbprint: str | None = None) -> Path:
    if platform.system() != "Windows":
        raise SystemExit(
            "The MSIX package must be built on Windows: it wraps a PyInstaller "
            "executable and uses the Windows SDK's makeappx."
        )

    identity = load_identity()
    version = package_version(__version__)

    if not skip_exe:
        _load_build_module().build()
    if not EXE_SOURCE.is_file():
        raise SystemExit(
            f"{EXE_SOURCE} is missing. Run python build.py first, or drop --skip-exe."
        )

    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    BUILD_DIR.mkdir(parents=True)

    shutil.copy2(EXE_SOURCE, BUILD_DIR / "OverAnalyzer.exe")
    write_assets(ASSETS_DIR)
    MANIFEST.write_text(manifest_xml(identity, version), encoding="utf-8")

    # Optional but preferred: a resource index lets Windows pick the scale-*
    # assets. Without one it falls back to the unqualified files, which are
    # also in the package, so a missing makepri degrades quality rather than
    # breaking the build.
    makepri = find_sdk_tool("makepri")
    if makepri:
        config = BUILD_DIR / "priconfig.xml"
        run([str(makepri), "createconfig", "/cf", str(config), "/dq", "en-US", "/o"])
        run([
            str(makepri), "new",
            "/pr", str(BUILD_DIR),
            "/cf", str(config),
            "/of", str(BUILD_DIR / "resources.pri"),
            "/o",
        ])
        config.unlink(missing_ok=True)
    else:
        print("makepri.exe not found - packaging with unqualified assets only.", flush=True)

    makeappx = find_sdk_tool("makeappx")
    if not makeappx:
        raise SystemExit(
            "makeappx.exe not found. Install the Windows 10/11 SDK "
            "(App Certification Kit / MSIX packaging tools)."
        )
    PACKAGE.unlink(missing_ok=True)
    run([str(makeappx), "pack", "/d", str(BUILD_DIR), "/p", str(PACKAGE), "/o"])

    if sign_thumbprint:
        signtool = find_sdk_tool("signtool")
        if not signtool:
            raise SystemExit("signtool.exe not found, but --sign was requested.")
        run([
            str(signtool), "sign",
            "/fd", "SHA256",
            "/sha1", sign_thumbprint,
            "/t", "http://timestamp.digicert.com",
            str(PACKAGE),
        ])

    print(f"Built OverAnalyzer {version}: {PACKAGE}", flush=True)
    print("Upload this file in Partner Center. Do not sign it for Store submission - "
          "Microsoft re-signs it during certification.", flush=True)
    return PACKAGE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Microsoft Store MSIX package.")
    parser.add_argument(
        "--skip-exe",
        action="store_true",
        help="Reuse the existing dist/OverAnalyzer.exe instead of rebuilding it.",
    )
    parser.add_argument(
        "--sign",
        metavar="THUMBPRINT",
        help=(
            "Sign the package with the local certificate of this thumbprint, for "
            "installing it locally to test. Not needed - and not wanted - for a "
            "Store upload."
        ),
    )
    args = parser.parse_args(argv)
    build(skip_exe=args.skip_exe, sign_thumbprint=args.sign)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
