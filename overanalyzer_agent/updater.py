"""Offer, verify, and install a new build of the capture app.

Without this an installed app is frozen at whatever version its user downloaded.
There is no store, no MSI, and no public Releases feed to poll (the repository is
private), so the service announces the release: ``GET /api/client/release``
returns the version, the download URL, its SHA-256 and the notes, or 204 when
there is nothing to announce.

**This code downloads a file and arranges to execute it, so its trust rules are
the point of the module.** They are, in order:

1. **The service does not get to choose the host.** ``ALLOWED_HOSTS`` is
   compiled into the app; a URL anywhere else is refused before a request is
   made. A compromised API can therefore withhold or misdescribe a release, but
   cannot point installations at an arbitrary binary.
2. **HTTPS only**, so the bytes cannot be rewritten in transit.
3. **The SHA-256 is checked before anything is replaced.** A mismatch deletes
   the download and reports failure. This is also what makes the published
   checksum meaningful for someone verifying by hand.
4. **A download is bounded** (:data:`MAX_DOWNLOAD_BYTES`), so a hostile or
   broken response cannot fill the disk.
5. **Nothing installs itself.** Every path here begins with the user clicking
   Update, including a release the service marks mandatory - "mandatory" changes
   how insistently the app asks, and nothing else.

The swap itself reuses the pattern ``removal.py`` established: a running EXE on
Windows cannot replace itself, so a detached PowerShell helper waits for this
process to exit, swaps the file, and starts the new one. The old build is kept
next to the new one until the replacement is in place, so a failed swap can be
rolled back rather than leaving the user with no app at all.
"""
from __future__ import annotations

import base64
import hashlib
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

RELEASE_PATH = "/api/client/release"

# Hosts a release may be downloaded from. GitHub serves release assets from
# objects.githubusercontent.com after a redirect, so both are required.
ALLOWED_HOSTS = frozenset({
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
})

MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024  # a one-file build is ~32 MiB
CHUNK_BYTES = 64 * 1024


class UpdateError(RuntimeError):
    """Anything that stops an update, phrased for the user."""


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    sha256: str
    notes: str = ""
    mandatory: bool = False


def parse_version(value: str) -> tuple[int, ...]:
    """``"0.2.10"`` -> ``(0, 2, 10)``. Unparseable parts sort as 0.

    Deliberately lenient: a version string the app cannot read must not crash
    the check, it must simply fail to look newer.
    """
    parts: list[int] = []
    for chunk in str(value).strip().lstrip("vV").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)


def check_url_allowed(url: str) -> None:
    """Refuse a download location the app was not built to trust."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise UpdateError("The update location is not HTTPS, so it was refused.")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise UpdateError(
            f"The update location ({host or 'unknown host'}) is not one this app "
            "downloads from, so it was refused. Update from the website instead."
        )


def check_for_update(
    cfg: Any,
    *,
    current_version: str,
    request_get: Callable[..., Any] | None = None,
    timeout: float = 10.0,
) -> Release | None:
    """Ask the service what the newest build is. ``None`` means nothing to do.

    Never raises: a failed check is not something to interrupt a capture
    session over, and the app simply stays on the version it has.
    """
    if request_get is None:
        import requests

        request_get = requests.get

    url = str(getattr(cfg, "api_url", "")).rstrip("/") + RELEASE_PATH
    try:
        response = request_get(url, timeout=timeout)
    except Exception:  # noqa: BLE001 - an offline check is not an error
        return None

    status = int(getattr(response, "status_code", 0))
    if status == 204 or status >= 400:
        return None
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None

    version = str(payload.get("version", "")).strip()
    download = str(payload.get("url", "")).strip()
    digest = str(payload.get("sha256", "")).strip().lower()
    if not version or not download or len(digest) != 64:
        return None
    if not is_newer(version, current_version):
        return None
    try:
        check_url_allowed(download)
    except UpdateError:
        # An announcement pointing somewhere unexpected is not offered at all.
        return None

    return Release(
        version=version,
        url=download,
        sha256=digest,
        notes=str(payload.get("notes", "") or "").strip(),
        mandatory=bool(payload.get("mandatory")),
    )


def download_release(
    release: Release,
    destination: Path,
    *,
    request_get: Callable[..., Any] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    timeout: float = 60.0,
) -> Path:
    """Download the release to ``destination`` and verify its SHA-256.

    The file is written to a ``.part`` and only renamed once the digest matches,
    so a partial or wrong download can never be mistaken for an installable one.
    """
    check_url_allowed(release.url)
    if request_get is None:
        import requests

        request_get = requests.get

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    digest = hashlib.sha256()
    written = 0

    try:
        response = request_get(release.url, timeout=timeout, stream=True)
    except Exception as exc:  # noqa: BLE001
        raise UpdateError(f"The update could not be downloaded: {exc}") from exc

    status = int(getattr(response, "status_code", 0))
    if status >= 400:
        raise UpdateError(f"The update download returned HTTP {status}.")

    expected = _content_length(response)
    try:
        with open(partial, "wb") as handle:
            for chunk in response.iter_content(chunk_size=CHUNK_BYTES):
                if not chunk:
                    continue
                written += len(chunk)
                if written > MAX_DOWNLOAD_BYTES:
                    raise UpdateError("The update download was larger than expected, so it was stopped.")
                handle.write(chunk)
                digest.update(chunk)
                if on_progress is not None:
                    on_progress(written, expected)
    except UpdateError:
        partial.unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001
        partial.unlink(missing_ok=True)
        raise UpdateError(f"The update could not be saved: {exc}") from exc

    if digest.hexdigest() != release.sha256:
        partial.unlink(missing_ok=True)
        raise UpdateError(
            "The downloaded update did not match its published checksum, so it "
            "was discarded. Nothing on this PC was changed."
        )

    destination.unlink(missing_ok=True)
    partial.replace(destination)
    return destination


def _content_length(response: Any) -> int:
    headers = getattr(response, "headers", {}) or {}
    try:
        return int(headers.get("Content-Length") or 0)
    except (TypeError, ValueError):
        return 0


def staging_path(version: str) -> Path:
    """Where a downloaded build waits, outside the running app's directory."""
    return Path(tempfile.gettempdir()) / f"OverAnalyzer-{version}.exe"


def current_executable(frozen: bool | None = None) -> Path | None:
    """The running EXE, or ``None`` when running from source.

    Source checkouts are updated with git, not by swapping a binary, so the app
    offers the update only where it can actually perform one.
    """
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    return Path(sys.executable).resolve() if frozen else None


def _ps_quote(value: str | os.PathLike[str]) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def failure_report_path(process_id: int) -> Path:
    return Path(tempfile.gettempdir()) / f"OverAnalyzer-update-failed-{process_id}.txt"


def swap_helper_script(target: Path, downloaded: Path, process_id: int) -> str:
    """PowerShell that waits for this process to exit, then swaps the binary.

    Rolls the previous build back if the replacement cannot be put in place, so
    a failed update leaves a working app rather than none. It reports a failure
    to a file instead of exiting quietly, because nobody is watching it.
    """
    backup = target.with_suffix(target.suffix + ".old")
    report = failure_report_path(process_id)
    return f"""$ErrorActionPreference = 'Stop'
$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline -and (Get-Process -Id {process_id} -ErrorAction SilentlyContinue)) {{
    Start-Sleep -Milliseconds 200
}}
$target = {_ps_quote(target)}
$source = {_ps_quote(downloaded)}
$backup = {_ps_quote(backup)}
try {{
    if (Test-Path -LiteralPath $backup) {{ Remove-Item -LiteralPath $backup -Force }}
    if (Test-Path -LiteralPath $target) {{ Move-Item -LiteralPath $target -Destination $backup -Force }}
    Move-Item -LiteralPath $source -Destination $target -Force
    if (Test-Path -LiteralPath $backup) {{ Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue }}
    Start-Process -FilePath $target
}} catch {{
    $message = $_.Exception.Message
    if ((Test-Path -LiteralPath $backup) -and -not (Test-Path -LiteralPath $target)) {{
        try {{ Move-Item -LiteralPath $backup -Destination $target -Force }} catch {{ }}
    }}
    [IO.File]::WriteAllLines({_ps_quote(report)}, @('OverAnalyzer update failed.', $message))
    if (Test-Path -LiteralPath $target) {{ Start-Process -FilePath $target }}
}}
"""


def spawn_swap_helper(
    target: Path,
    downloaded: Path,
    *,
    process_id: int | None = None,
    runner: Callable[..., Any] | None = None,
) -> Path:
    """Start the detached helper. Returns the path it would report a failure to."""
    process_id = process_id or os.getpid()
    script = swap_helper_script(target, downloaded, process_id)
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-WindowStyle",
        "Hidden",
        "-EncodedCommand",
        encoded,
    ]
    if runner is None:
        if os.name != "nt":
            raise UpdateError("The detached update helper is Windows-only.")
        flags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=flags,
        )
    else:
        runner(command)
    return failure_report_path(process_id)


def install_release(
    release: Release,
    *,
    executable: Path | None = None,
    request_get: Callable[..., Any] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    helper_runner: Callable[..., Any] | None = None,
    process_id: int | None = None,
) -> Path:
    """Download, verify, and schedule the swap. Returns the failure-report path.

    The caller quits the app immediately afterwards: the helper is waiting for
    this process to exit before it can replace the file.
    """
    target = executable if executable is not None else current_executable()
    if target is None:
        raise UpdateError(
            "This copy is running from source, so it updates with git rather "
            "than by replacing a binary."
        )
    downloaded = download_release(
        release, staging_path(release.version),
        request_get=request_get, on_progress=on_progress,
    )
    return spawn_swap_helper(
        target, downloaded, process_id=process_id, runner=helper_runner
    )
