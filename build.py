"""Build and smoke-check the Windows one-file OverAnalyzer companion app.

All paths resolve relative to this file, so the same script works from the private
repository's ```` subtree and from the root-level public export.

Run from the repository root with the Windows Python environment:

    .venv\\Scripts\\python.exe -m pip install -r requirements-build.txt
    .venv\\Scripts\\python.exe build.py
"""
from __future__ import annotations

import argparse
import os
import platform
import re
import subprocess
import sys
from pathlib import Path


AGENT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(AGENT_DIR))

from overanalyzer_agent import __version__  # noqa: E402


DIST_DIR = AGENT_DIR / "dist"
WORK_DIR = AGENT_DIR / "build" / "pyinstaller"
SPEC_FILE = AGENT_DIR / "OverAnalyzer.spec"
VERSION_INFO = AGENT_DIR / "build" / "overanalyzer-version.txt"
ICON_FILE = AGENT_DIR / "build" / "OverAnalyzer.ico"
ARTIFACT = DIST_DIR / "OverAnalyzer.exe"

# Sizes Windows actually asks for: the small ones appear in Explorer's list and
# details views and in the taskbar, 256 is the large/extra-large tile. Shipping
# only one size makes Windows downscale it, which is what makes an app icon look
# muddy next to properly built ones.
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def write_icon(path: Path) -> Path:
    """Render the app icon to a multi-resolution .ico for the executable.

    Generated from ``ui.brand`` rather than committed as a binary, so the icon on
    the downloaded EXE cannot drift from the one the running app draws in its own
    title bar and tray. Both come from the same vendored brand paths.
    """
    from overanalyzer_agent.ui import brand

    path.parent.mkdir(parents=True, exist_ok=True)
    largest = brand.icon(max(ICON_SIZES))
    largest.save(path, format="ICO", sizes=[(s, s) for s in ICON_SIZES])
    return path


def windows_version_parts(version: str) -> tuple[int, int, int, int]:
    """Convert the package version to the four integers Windows file metadata needs."""
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:[.+-].*)?", version)
    if not match:
        raise ValueError(
            "overanalyzer_agent.__version__ must begin with major.minor.patch "
            "to build a Windows executable."
        )
    return (*map(int, match.groups()), 0)


def write_version_info(path: Path, version: str) -> None:
    """Generate a PyInstaller VERSIONINFO resource from the package version."""
    major, minor, patch, build = windows_version_parts(version)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'''# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({major}, {minor}, {patch}, {build}),
    prodvers=({major}, {minor}, {patch}, {build}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '040904B0',
          [
            StringStruct('CompanyName', 'OverAnalyzer'),
            StringStruct('FileDescription', 'OverAnalyzer desktop capture app'),
            StringStruct('FileVersion', '{version}'),
            StringStruct('InternalName', 'OverAnalyzer'),
            StringStruct('OriginalFilename', 'OverAnalyzer.exe'),
            StringStruct('ProductName', 'OverAnalyzer'),
            StringStruct('ProductVersion', '{version}')
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
''',
        encoding="utf-8",
    )


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+", subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, check=True, env=env)


def build() -> Path:
    if platform.system() != "Windows":
        raise SystemExit("The release artifact must be built on Windows (PyInstaller is platform-specific).")

    write_version_info(VERSION_INFO, __version__)
    write_icon(ICON_FILE)
    env = os.environ | {
        "OA_AGENT_BUILD_VERSION": __version__,
        "OA_AGENT_VERSION_INFO": str(VERSION_INFO),
        "OA_AGENT_ICON": str(ICON_FILE),
    }
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--log-level",
            "WARN",
            "--distpath",
            str(DIST_DIR),
            "--workpath",
            str(WORK_DIR),
            str(SPEC_FILE),
        ],
        env=env,
    )
    if not ARTIFACT.is_file():
        raise RuntimeError(f"PyInstaller completed without creating {ARTIFACT}")

    # Both checks run the actual one-file executable. They do not open the GUI,
    # bind global hotkeys, access a display, or contact a service.
    run([str(ARTIFACT), "--help"])
    run([str(ARTIFACT), "--version"])
    run([str(ARTIFACT), "--verify-assets"])
    print(f"Built OverAnalyzer {__version__}: {ARTIFACT}", flush=True)
    return ARTIFACT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="store_true", help="Print the package version and exit.")
    args = parser.parse_args(argv)
    if args.version:
        print(__version__)
        return 0
    build()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
