"""Contracts for the Store package that hold without a Windows SDK.

The package itself can only be built on Windows, but the two things that most
often get a submission rejected - a package identity that does not match Partner
Center, and a version that disagrees with the executable - are pure data, and
are checked here so a bad package is caught before an upload rather than by
certification a day later.
"""
import importlib.util
from pathlib import Path
from xml.etree import ElementTree

import pytest
from PIL import Image

from overanalyzer_agent import __version__

NS = {
    "m": "http://schemas.microsoft.com/appx/manifest/foundation/windows10",
    "uap": "http://schemas.microsoft.com/appx/manifest/uap/windows10",
    "rescap": "http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities",
}

IDENTITY = {
    "identity_name": "12345Example.OverAnalyzer",
    "publisher": "CN=A1B2C3D4-1111-2222-3333-444455556666",
    "publisher_display_name": "OverAnalyzer",
}


@pytest.fixture(scope="module")
def msix():
    path = Path(__file__).resolve().parents[1] / "build_msix.py"
    spec = importlib.util.spec_from_file_location("overanalyzer_build_msix", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def manifest(msix):
    return ElementTree.fromstring(msix.manifest_xml(IDENTITY, msix.package_version(__version__)))


def test_the_package_version_is_derived_from_the_package_not_typed(msix):
    """A hand-maintained package version is one that eventually disagrees with
    the EXE metadata, and the Store rejects a resubmission at the same version."""
    assert msix.package_version("0.1.0") == "0.1.0.0"
    assert msix.package_version("2.10.3") == "2.10.3.0"


def test_the_store_reserves_the_fourth_version_part(msix):
    """The Store requires the revision field to be 0 and rejects anything else."""
    assert msix.package_version(__version__).split(".")[3] == "0"


def test_an_unparseable_version_fails_the_build_rather_than_shipping(msix):
    with pytest.raises(ValueError):
        msix.package_version("not-a-version")


def test_the_manifest_carries_the_partner_center_identity(manifest):
    identity = manifest.find("m:Identity", NS)
    assert identity.get("Name") == IDENTITY["identity_name"]
    assert identity.get("Publisher") == IDENTITY["publisher"]
    assert identity.get("ProcessorArchitecture") == "x64"


def test_the_manifest_version_matches_the_package_version(manifest, msix):
    assert manifest.find("m:Identity", NS).get("Version") == msix.package_version(__version__)


def test_the_app_is_declared_as_a_full_trust_desktop_app(manifest):
    """A packaged PyInstaller EXE needs a global keyboard hook and a desktop
    screen grab; neither is expressible as a sandboxed UWP capability."""
    application = manifest.find("m:Applications/m:Application", NS)
    assert application.get("EntryPoint") == "Windows.FullTrustApplication"
    assert application.get("Executable") == "OverAnalyzer.exe"

    capabilities = [c.get("Name") for c in manifest.findall("m:Capabilities/rescap:Capability", NS)]
    assert capabilities == ["runFullTrust"]


def test_the_manifest_references_only_assets_the_build_writes(manifest, msix, tmp_path):
    """Every logo path in the manifest must exist in the package, or the app
    ships with blank tiles and certification flags it."""
    written = {p.name for p in msix.write_assets(tmp_path)}

    referenced = {manifest.find("m:Properties/m:Logo", NS).text}
    visual = manifest.find("m:Applications/m:Application/uap:VisualElements", NS)
    referenced.update({visual.get("Square150x150Logo"), visual.get("Square44x44Logo")})
    tile = visual.find("uap:DefaultTile", NS)
    referenced.update(tile.attrib.values())
    referenced.add(visual.find("uap:SplashScreen", NS).get("Image"))

    for path in referenced:
        assert path.startswith("Assets\\"), path
        assert path.split("\\")[-1] in written, f"{path} is referenced but never rendered"


def test_the_scaled_tiles_are_actually_rendered_at_their_scale(msix, tmp_path):
    """Shipping one size and letting Windows downscale is what makes an app look
    second-rate next to properly built ones."""
    msix.write_assets(tmp_path)
    for scale in (100, 200, 400):
        with Image.open(tmp_path / f"Square150x150Logo.scale-{scale}.png") as image:
            assert image.size == (round(150 * scale / 100),) * 2

    with Image.open(tmp_path / "Wide310x150Logo.scale-100.png") as image:
        assert image.size == (310, 150)


def test_the_taskbar_icons_include_the_unplated_variants(msix, tmp_path):
    """Windows uses altform-unplated on the taskbar; without it the icon gets a
    coloured plate behind it that no other app has."""
    written = {p.name for p in msix.write_assets(tmp_path)}
    for size in (16, 24, 32, 48, 256):
        assert f"Square44x44Logo.targetsize-{size}.png" in written
        assert f"Square44x44Logo.targetsize-{size}_altform-unplated.png" in written


def test_the_rendered_tile_is_not_blank(msix, tmp_path):
    msix.write_assets(tmp_path)
    with Image.open(tmp_path / "Square150x150Logo.png") as image:
        opaque = [p for p in image.convert("RGBA").get_flattened_data() if p[3] > 200]
    assert len(opaque) > 500, "the tile rendered blank"


def test_a_placeholder_identity_is_refused(msix, monkeypatch):
    """The example file ships with obvious placeholders; building with them
    would produce a package Partner Center rejects on upload."""
    monkeypatch.setenv("OA_MSIX_IDENTITY_NAME", "Example.App")
    monkeypatch.setenv("OA_MSIX_PUBLISHER", "OverAnalyzer")  # missing CN=
    monkeypatch.setenv("OA_MSIX_PUBLISHER_DISPLAY_NAME", "OverAnalyzer")
    with pytest.raises(SystemExit, match="CN="):
        msix.load_identity()


def test_missing_identity_names_what_to_set(msix, monkeypatch, tmp_path):
    monkeypatch.delenv("OA_MSIX_IDENTITY_NAME", raising=False)
    monkeypatch.delenv("OA_MSIX_PUBLISHER", raising=False)
    monkeypatch.delenv("OA_MSIX_PUBLISHER_DISPLAY_NAME", raising=False)
    monkeypatch.setattr(msix, "IDENTITY_FILE", tmp_path / "absent.json")
    with pytest.raises(SystemExit, match="Partner Center"):
        msix.load_identity()
