"""Local companion-app removal with device-key revocation.

This module owns the boundary in D14: remove the app and its PC-local traces,
but never account data.  The device key is revoked first through the existing
``GET /api/me/devices`` + ``DELETE /api/me/devices/{token_id}`` contract.  A
one-file frozen executable is removed by a detached PowerShell helper after
the current process exits; the helper writes a failure report only when it can
verify that a target remains.
"""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from overanalyzer_agent import config as config_module
from overanalyzer_agent.session import default_state_path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "OverAnalyzer"
STARTUP_RELATIVE = Path("Microsoft") / "Windows" / "Start Menu" / "Programs" / "Startup"
LOCAL_CACHE_NAMES = ("cache", "Cache", "http_cache", "local_cache")


@dataclass(frozen=True)
class RemovalPlan:
    """The exact local targets owned by this companion installation."""

    data_dir: Path
    local_paths: tuple[Path, ...]
    startup_paths: tuple[Path, ...]
    executable_path: Path | None


@dataclass(frozen=True)
class RevokeResult:
    ok: bool
    message: str
    token_id: str | None = None


@dataclass(frozen=True)
class CleanupResult:
    ok: bool
    message: str
    remaining: tuple[Path, ...] = ()


@dataclass(frozen=True)
class RemovalResult:
    ok: bool
    scheduled: bool
    verified: bool
    message: str
    revocation: RevokeResult
    remaining: tuple[Path, ...] = ()
    failure_report: Path | None = None


def confirmation_text() -> str:
    """Copy for the destructive confirmation dialog.

    Keep the two data boundaries in the same dialog so an uninstall cannot be
    mistaken for account deletion.  The Settings → Devices fallback remains
    useful if a future service or a temporary outage prevents self-revocation.
    """
    return (
        "This removes OverAnalyzer from this PC: the executable, agent.toml and "
        "its device key, agent.state.json (session count and window position), "
        "debug_out captures, local cache, and this app's tray/startup registration.\n\n"
        "Your OverAnalyzer account stays. Matches, screenshots, and rank history "
        "remain in the account and are not deleted. Delete account data separately "
        "in the website Settings.\n\n"
        "The app will revoke this PC's device key before removing local files. If "
        "self-revocation cannot be confirmed, nothing is removed; open the web "
        "app's Settings → Devices to revoke it manually."
    )


def _startup_paths() -> tuple[Path, ...]:
    if os.name != "nt":
        return ()
    app_data = os.environ.get("APPDATA")
    if not app_data:
        return ()
    startup = Path(app_data) / STARTUP_RELATIVE
    return (startup / "OverAnalyzer.lnk", startup / "OverAnalyzer.cmd")


def build_removal_plan(
    *,
    config_path: str | os.PathLike[str] | None = None,
    data_dir: str | os.PathLike[str] | None = None,
    executable_path: str | os.PathLike[str] | None = None,
    frozen: bool | None = None,
) -> RemovalPlan:
    """Build a narrow, explicit plan without touching account or match data."""
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))

    config = Path(config_path).expanduser().resolve() if config_path else config_module.DEFAULT_CONFIG_PATH.resolve()
    if data_dir is not None:
        root = Path(data_dir).expanduser().resolve()
    elif config_path is None and frozen:
        root = config_module.user_data_dir().resolve()
    else:
        # Source-mode  is code and assets, not a disposable app-data root.
        root = config.parent

    paths: list[Path] = [config, default_state_path(str(config))]
    paths.extend(root / name for name in ("debug_out", *LOCAL_CACHE_NAMES))

    deduped: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved not in deduped:
            deduped.append(resolved)

    exe = Path(executable_path).expanduser().resolve() if executable_path else None
    return RemovalPlan(
        data_dir=root,
        local_paths=tuple(deduped),
        startup_paths=_startup_paths(),
        executable_path=exe,
    )


def _remove_path(path: Path) -> str | None:
    """Remove one file/directory, returning an error string instead of hiding it."""
    if not path.exists() and not path.is_symlink():
        return None
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    except OSError as exc:
        return f"{path}: {exc}"
    return None


def _remaining(paths: tuple[Path, ...] | list[Path]) -> tuple[Path, ...]:
    return tuple(path for path in paths if path.exists() or path.is_symlink())


def _remove_registry_registration() -> str | None:
    if os.name != "nt":
        return None
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            try:
                winreg.DeleteValue(key, RUN_VALUE)
            except FileNotFoundError:
                pass
    except FileNotFoundError:
        pass
    except OSError as exc:
        return f"HKCU\\{RUN_KEY}\\{RUN_VALUE}: {exc}"
    return None


def cleanup_local_traces(plan: RemovalPlan) -> CleanupResult:
    """Synchronously remove local data and registrations that are not locked."""
    errors: list[str] = []
    for path in (*plan.local_paths, *plan.startup_paths):
        if error := _remove_path(path):
            errors.append(error)
    if error := _remove_registry_registration():
        errors.append(error)
    # Remove only an empty dedicated app-data directory. Never recursively
    # delete an unknown sibling that a user may have placed beside our files.
    try:
        plan.data_dir.rmdir()
    except OSError:
        pass

    remaining = _remaining((*plan.local_paths, *plan.startup_paths))
    if errors or remaining:
        detail = "; ".join(errors) if errors else "one or more paths still exist"
        return CleanupResult(False, f"Local removal was not verified: {detail}.", remaining)
    return CleanupResult(True, "Local app data and registrations removed.")


def _request_functions(
    request_get: Callable[..., Any] | None,
    request_delete: Callable[..., Any] | None,
) -> tuple[Callable[..., Any], Callable[..., Any]]:
    if request_get is not None and request_delete is not None:
        return request_get, request_delete
    import requests

    return request_get or requests.get, request_delete or requests.delete


def revoke_device_key(
    cfg: Any,
    *,
    request_get: Callable[..., Any] | None = None,
    request_delete: Callable[..., Any] | None = None,
    timeout: float = 10.0,
) -> RevokeResult:
    """Revoke this installation's key without exposing plaintext credentials."""
    bearer_token = str(getattr(cfg, "bearer_token", "") or "").strip()
    if not bearer_token:
        return RevokeResult(True, "No device key is saved.")

    get, delete = _request_functions(request_get, request_delete)
    base = str(getattr(cfg, "api_url", "")).rstrip("/")
    headers = {"Authorization": f"Bearer {bearer_token}"}
    try:
        listed = get(f"{base}/api/me/devices", headers=headers, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - the UI needs an actionable failure
        return RevokeResult(False, f"Could not reach the device-key service: {exc}.")

    status = int(getattr(listed, "status_code", 0))
    if status == 401:
        return RevokeResult(True, "The saved device key is already invalid or revoked.")
    if status != 200:
        return RevokeResult(False, f"The device-key service returned HTTP {status}.")
    try:
        devices = listed.json()
    except Exception as exc:  # noqa: BLE001 - malformed service output is a failure
        return RevokeResult(False, f"The device-key service returned invalid data: {exc}.")
    if not isinstance(devices, list):
        return RevokeResult(False, "The device-key service returned an invalid device list.")
    if not devices:
        return RevokeResult(True, "The saved device key is already revoked.")
    if len(devices) != 1:
        return RevokeResult(
            False,
            "More than one device key is active, so this app cannot identify its own "
            "key safely. Open the web app's Settings → Devices.",
        )

    token_id = devices[0].get("token_id") if isinstance(devices[0], dict) else None
    if not token_id:
        return RevokeResult(False, "The device-key service omitted the opaque token id.")
    try:
        revoked = delete(
            f"{base}/api/me/devices/{quote(str(token_id), safe='')}",
            headers=headers,
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 - the UI needs an actionable failure
        return RevokeResult(False, f"Could not revoke the device key: {exc}.", str(token_id))
    revoke_status = int(getattr(revoked, "status_code", 0))
    if revoke_status in (200, 204, 404):
        return RevokeResult(True, "This PC's device key is revoked.", str(token_id))
    return RevokeResult(False, f"Device-key revocation returned HTTP {revoke_status}.", str(token_id))


def _ps_quote(value: str | os.PathLike[str]) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def failure_report_path(process_id: int) -> Path:
    return Path(tempfile.gettempdir()) / f"OverAnalyzer-removal-failed-{process_id}.txt"


def cleanup_helper_script(plan: RemovalPlan, process_id: int) -> str:
    """Build the detached helper's self-checking PowerShell source."""
    targets = [*plan.local_paths, *plan.startup_paths]
    if plan.executable_path is not None:
        targets.append(plan.executable_path)
    target_literals = ",\n    ".join(_ps_quote(path) for path in targets)
    report = failure_report_path(process_id)
    return f"""$ErrorActionPreference = 'Stop'
$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline -and (Get-Process -Id {process_id} -ErrorAction SilentlyContinue)) {{
    Start-Sleep -Milliseconds 200
}}
$failed = @()
$targets = @(
    {target_literals}
)
foreach ($target in $targets) {{
    if (Test-Path -LiteralPath $target) {{
        try {{ Remove-Item -LiteralPath $target -Force -Recurse -ErrorAction Stop }}
        catch {{ $failed += ($target + ' :: ' + $_.Exception.Message) }}
    }}
}}
try {{
    Remove-ItemProperty -Path 'HKCU:\\{RUN_KEY}' -Name '{RUN_VALUE}' -ErrorAction SilentlyContinue
}} catch {{ $failed += ('HKCU\\{RUN_KEY}\\{RUN_VALUE} :: ' + $_.Exception.Message) }}
$remaining = @($targets | Where-Object {{ Test-Path -LiteralPath $_ }})
if ($failed.Count -or $remaining.Count) {{
    $lines = @('OverAnalyzer removal was not verified.') + $failed + ($remaining | ForEach-Object {{ 'Still present: ' + $_ }})
    [IO.File]::WriteAllLines({_ps_quote(report)}, $lines)
}}
"""


def spawn_cleanup_helper(
    plan: RemovalPlan,
    *,
    process_id: int | None = None,
    runner: Callable[..., Any] | None = None,
) -> Path:
    """Start a hidden helper and return its failure-report path.

    The returned path is deliberately a possible failure report, not a claim
    that the EXE was deleted. The helper verifies target absence after the
    parent exits and leaves that report only on failure.
    """
    process_id = process_id or os.getpid()
    script = cleanup_helper_script(plan, process_id)
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
            raise OSError("the detached uninstall helper is Windows-only")
        flags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
        runner = subprocess.Popen
        runner(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=flags,
        )
    else:
        runner(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return failure_report_path(process_id)


def remove_app(
    cfg: Any,
    *,
    config_path: str | os.PathLike[str] | None = None,
    data_dir: str | os.PathLike[str] | None = None,
    executable_path: str | os.PathLike[str] | None = None,
    frozen: bool | None = None,
    request_get: Callable[..., Any] | None = None,
    request_delete: Callable[..., Any] | None = None,
    helper_runner: Callable[..., Any] | None = None,
    process_id: int | None = None,
) -> RemovalResult:
    """Revoke, remove local traces, then schedule frozen-EXE deletion."""
    plan = build_removal_plan(
        config_path=config_path,
        data_dir=data_dir,
        executable_path=executable_path,
        frozen=frozen,
    )
    revocation = revoke_device_key(
        cfg,
        request_get=request_get,
        request_delete=request_delete,
    )
    if not revocation.ok:
        return RemovalResult(False, False, False, revocation.message, revocation)

    cleanup = cleanup_local_traces(plan)
    if not cleanup.ok:
        return RemovalResult(False, False, False, cleanup.message, revocation, cleanup.remaining)

    if plan.executable_path is None:
        return RemovalResult(
            True,
            False,
            True,
            "OverAnalyzer and its local traces were removed from this PC.",
            revocation,
        )

    try:
        report = spawn_cleanup_helper(
            plan,
            process_id=process_id,
            runner=helper_runner,
        )
    except OSError as exc:
        return RemovalResult(
            False,
            False,
            False,
            "Local traces were removed and the device key was revoked, but the "
            f"executable could not be scheduled for deletion: {exc}.",
            revocation,
            failure_report= None,
        )
    return RemovalResult(
        True,
        True,
        False,
        "Removal is scheduled. This window will close; the detached cleanup will "
        f"verify the executable and local paths. If anything remains, see {report}.",
        revocation,
        failure_report=report,
    )
