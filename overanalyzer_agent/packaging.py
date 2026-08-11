"""How this copy of the app was installed, and what that permits.

The same executable ships through two channels, and they differ in exactly one
behaviour that matters at runtime: **who installs updates.**

* The **direct download** from GitHub Releases updates itself - see
  :mod:`overanalyzer_agent.updater`, which downloads a verified build and swaps
  the binary.
* The **Microsoft Store** build must not. Its install directory
  (``%ProgramFiles%\\WindowsApps``) is read-only to the app, so the swap could
  not succeed anyway; more importantly the Store owns the update channel, and a
  packaged app that replaced its own signed payload would break the package's
  signature and fail Store certification.

Rather than build two executables and rely on the right flag being passed, the
distinction is discovered at runtime from **package identity**: a process
running inside an MSIX package has one, an ordinary EXE does not. That means a
single build behaves correctly in both channels, and a Store package can never
be produced with the self-updater accidentally left live.

The check is :c:func:`GetCurrentPackageFullName` from ``kernel32``, which is the
documented way to ask. It returns ``APPMODEL_ERROR_NO_PACKAGE`` when the process
has no package identity, and either success or ``ERROR_INSUFFICIENT_BUFFER``
when it does.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Callable

# winerror.h / appmodel.h
APPMODEL_ERROR_NO_PACKAGE = 15700
ERROR_INSUFFICIENT_BUFFER = 122
ERROR_SUCCESS = 0


def _kernel32_package_query() -> Callable[[], int] | None:
    """Return a callable giving ``GetCurrentPackageFullName``'s status code.

    ``None`` when the API cannot be reached at all, which is not the same as
    "no package": a machine too old to have the API is by definition not running
    an MSIX package, but the caller distinguishes the two for logging.
    """
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:  # pragma: no cover - ctypes is stdlib on Windows
        return None
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_name = kernel32.GetCurrentPackageFullName
    except (AttributeError, OSError):
        # Windows 7 and earlier have no app model at all.
        return None
    get_name.argtypes = [ctypes.POINTER(wintypes.UINT32), wintypes.LPWSTR]
    get_name.restype = wintypes.LONG

    def query() -> int:
        length = wintypes.UINT32(0)
        return int(get_name(ctypes.byref(length), None))

    return query


def has_package_identity(query: Callable[[], int] | None = None) -> bool:
    """True when this process is running from inside an MSIX package.

    ``query`` is injectable so the two branches are testable off Windows; in
    production it is the ``kernel32`` call above.
    """
    if query is None:
        query = _kernel32_package_query()
    if query is None:
        return False
    try:
        status = query()
    except Exception:
        # Never let an identity probe stop the app from starting. An
        # unanswerable question is treated as "not packaged", which only means
        # the app keeps its own update path - the conservative direction.
        return False
    if status == APPMODEL_ERROR_NO_PACKAGE:
        return False
    return status in (ERROR_SUCCESS, ERROR_INSUFFICIENT_BUFFER)


@lru_cache(maxsize=1)
def is_store_build() -> bool:
    """Cached :func:`has_package_identity` - it cannot change while running."""
    return has_package_identity()


def channel() -> str:
    """A short name for the install channel, for logs and ``--version``."""
    return "store" if is_store_build() else "direct"


# Shown wherever the app would otherwise offer to update itself. Phrased for a
# user, not a developer: it says who updates the app now, not what an API returned.
STORE_UPDATE_MESSAGE = (
    "This copy was installed from the Microsoft Store, so the Store keeps it "
    "up to date. Check for updates there."
)
