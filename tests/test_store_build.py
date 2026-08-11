"""The one behaviour that must differ between the Store and direct builds.

Both channels ship the same executable, so nothing here is about a build flag:
these tests pin the runtime detection and the two places that consume it. If the
Store build ever offered its own update, the package would try to overwrite a
read-only, signed payload - so this is the contract worth guarding.
"""
import pytest

from overanalyzer_agent import packaging, updater


@pytest.fixture(autouse=True)
def _clear_channel_cache():
    """``is_store_build`` is cached for the process; tests need it re-evaluated."""
    packaging.is_store_build.cache_clear()
    yield
    packaging.is_store_build.cache_clear()


def test_no_package_identity_means_a_direct_build():
    assert not packaging.has_package_identity(
        query=lambda: packaging.APPMODEL_ERROR_NO_PACKAGE
    )


@pytest.mark.parametrize("status", [packaging.ERROR_SUCCESS, packaging.ERROR_INSUFFICIENT_BUFFER])
def test_package_identity_means_a_store_build(status):
    """Windows answers with either of these when the process is packaged: the
    buffer error is what it returns for the length probe this code makes."""
    assert packaging.has_package_identity(query=lambda: status)


def test_an_unanswerable_identity_probe_does_not_stop_the_app():
    """A failed probe must not be fatal at startup. Falling back to 'direct'
    only re-enables the app's own updater, which is the safe direction."""
    def explode() -> int:
        raise OSError("kernel32 unavailable")

    assert not packaging.has_package_identity(query=explode)


def test_a_store_build_is_never_offered_an_update(monkeypatch):
    """The banner must not appear at all - offering an update the packaged app
    is not permitted to install would be worse than staying silent."""
    monkeypatch.setattr(packaging, "is_store_build", lambda: True)

    def fail(*args, **kwargs):
        raise AssertionError("a Store build must not even ask the service")

    assert updater.check_for_update(
        cfg=type("Cfg", (), {"api_url": "https://api.example"})(),
        current_version="0.1.0",
        request_get=fail,
    ) is None


def test_a_store_build_refuses_to_install_one(monkeypatch):
    """Defence in depth for a caller that goes around check_for_update."""
    monkeypatch.setattr(packaging, "is_store_build", lambda: True)
    release = updater.Release(version="9.9.9", url="https://github.com/x", sha256="0" * 64)

    with pytest.raises(updater.UpdateError) as excinfo:
        updater.install_release(release)
    assert "Microsoft Store" in str(excinfo.value)


def test_a_direct_build_still_updates_itself(monkeypatch):
    """The Store work must not disable the channel it does not apply to."""
    monkeypatch.setattr(packaging, "is_store_build", lambda: False)
    calls: list[str] = []

    class Response:
        status_code = 200

        @staticmethod
        def json() -> dict[str, object]:
            return {
                "version": "9.9.9",
                "url": "https://github.com/o/r/releases/download/v9.9.9/OverAnalyzer.exe",
                "sha256": "0" * 64,
            }

    def request_get(url, timeout=None):
        calls.append(url)
        return Response()

    release = updater.check_for_update(
        cfg=type("Cfg", (), {"api_url": "https://api.example"})(),
        current_version="0.1.0",
        request_get=request_get,
    )
    assert calls, "the direct build must still ask the service"
    assert release is not None and release.version == "9.9.9"
