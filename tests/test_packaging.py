"""Packaging contracts that remain unit-testable without building an EXE."""
from overanalyzer_agent import __version__
from overanalyzer_agent.app import missing_bundled_assets, version_message


def test_package_version_is_the_cli_version_source():
    assert version_message().startswith(f"overanalyzer-agent {__version__}")


def test_the_version_line_names_the_install_channel():
    """Store and direct builds differ in whether the app updates itself, so
    support needs to see which one a user is running without asking."""
    assert version_message().endswith(" (direct)")  # a test run is never packaged


def test_source_tree_contains_every_asset_required_by_the_frozen_app():
    assert missing_bundled_assets() == []


def test_the_executable_carries_the_brand_icon(tmp_path):
    """A downloaded EXE showed PyInstaller's default icon, which is the first
    thing a stranger sees. The icon is generated from ui.brand rather than
    committed, so it cannot drift from the mark the running app draws."""
    import importlib.util
    from pathlib import Path

    from PIL import Image

    spec_path = Path(__file__).resolve().parents[1] / "build.py"
    spec = importlib.util.spec_from_file_location("agent_build", spec_path)
    build_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_mod)

    icon = build_mod.write_icon(tmp_path / "OverAnalyzer.ico")
    assert icon.is_file()
    with Image.open(icon) as image:
        sizes = {size[0] for size in image.info["sizes"]}
    # Shipping one size makes Windows downscale it, which looks muddy in the
    # taskbar and Explorer's small-icon views.
    assert {16, 32, 48, 256} <= sizes

    with Image.open(icon) as image:
        image.size = (32, 32)
        image.load()
        opaque = [p for p in image.convert("RGBA").get_flattened_data() if p[3] > 200]
    assert len(opaque) > 100, "the icon rendered blank"


def test_the_spec_refuses_to_build_without_a_generated_icon():
    """The spec reads the icon from the environment, the same way it reads the
    version resource, so the public export builds identically."""
    from pathlib import Path

    spec_text = (Path(__file__).resolve().parents[1] / "OverAnalyzer.spec").read_text(
        encoding="utf-8"
    )
    assert "OA_AGENT_ICON" in spec_text
    assert "icon=ICON," in spec_text
