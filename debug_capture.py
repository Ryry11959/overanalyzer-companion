"""Interactive capture-debug tool for the OverAnalyzer agent.

It reuses the REAL capture logic (``overanalyzer_agent.capture`` / ``.config``),
so what you see here is exactly what the agent would crop and upload. Use it to
dial in the resolution-specific geometry in ``agent.toml`` until every screenshot
crops cleanly.

Two ways to run (from the repo root):

  LIVE - mirrors the agent's hotkeys. Be on the right Overwatch screen, then press:
      ..\\.venv\\Scripts\\python.exe agent\\debug_capture.py --config agent\\agent.toml
        f11  -> grab + analyze the SUMMARY crop
        f12  -> grab + analyze the SCOREBOARD (both leaderboards)
        f9   -> grab the whole frame only (raw, no crop)
        esc  -> quit

  OFFLINE - iterate on regions WITHOUT Overwatch. Point it at a saved full frame and it
  re-runs the analysis against your *current* agent.toml instantly, so you can
  edit numbers and re-run in a tight loop:
      ..\\.venv\\Scripts\\python.exe agent\\debug_capture.py -c agent\\agent.toml --image agent\\debug_out\\full_frame.png

Every run writes annotated PNGs to --out (default ``debug_out``) and prints a
report: the summary box (and whether it fits the frame), each leaderboard anchor's
hit/miss with pixel counts, and - when the exact team-bar colors don't match -
concrete suggested colors to paste into ``agent.toml``.

Note (same as the agent): global hotkeys may need a terminal run **as
administrator**, and Overwatch should be in borderless/windowed mode.
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

# Make ``overanalyzer_agent`` importable no matter the working directory.
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from overanalyzer_agent import capture  # noqa: E402
from overanalyzer_agent.config import AgentConfig, Box, Color, load_config  # noqa: E402

GREEN = (0, 255, 0)
CYAN = (0, 200, 255)
RED = (255, 60, 60)


# --------------------------------------------------------------------------- #
# Small image / array helpers
# --------------------------------------------------------------------------- #
def _save(img: Image.Image, out_dir: str, name: str) -> str:
    path = os.path.join(out_dir, name)
    img.save(path)
    return path


def _rgb_array(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("RGB"))


def _exact_mask(arr: np.ndarray, colors: list[Color]) -> np.ndarray:
    """Pixels exactly equal to any listed color - same test capture.py uses."""
    mask = np.zeros(arr.shape[:2], dtype=bool)
    for color in colors:
        mask |= np.all(arr == np.array(color, dtype=arr.dtype), axis=-1)
    return mask


def _tolerant_mask(arr: np.ndarray, colors: list[Color], tol: int) -> np.ndarray:
    """Pixels within +/-tol on every channel of any listed color."""
    mask = np.zeros(arr.shape[:2], dtype=bool)
    target = arr.astype(np.int16)
    for color in colors:
        diff = np.abs(target - np.array(color, dtype=np.int16))
        mask |= np.all(diff <= tol, axis=-1)
    return mask


def _top_colors(arr: np.ndarray, mask: np.ndarray, k: int = 5) -> list[tuple[Color, int]]:
    """The k most common exact RGB values among masked pixels (color, count)."""
    px = arr[mask]
    if px.size == 0:
        return []
    colors, counts = np.unique(px.reshape(-1, 3), axis=0, return_counts=True)
    order = np.argsort(counts)[::-1][:k]
    return [(tuple(int(c) for c in colors[i]), int(counts[i])) for i in order]


def _bbox(mask: np.ndarray) -> Box | None:
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def _mask_view(frame: Image.Image, mask: np.ndarray, paint: Color) -> Image.Image:
    """Dim the frame and paint matched pixels bright so they pop."""
    base = _rgb_array(frame).astype(np.float32)
    dim = (base * 0.25).astype(np.uint8)
    dim[mask] = paint
    return Image.fromarray(dim)


def _draw_box(draw: ImageDraw.ImageDraw, box: Box | None, color: Color, label: str) -> None:
    if box is None:
        return
    draw.rectangle(box, outline=color, width=4)
    draw.text((box[0] + 6, max(box[1] - 16, 2)), label, fill=color)


# --------------------------------------------------------------------------- #
# Heuristic bar-color discovery (works even when the configured colors miss)
# --------------------------------------------------------------------------- #
def _heuristic_blue(arr: np.ndarray) -> np.ndarray:
    r, g, b = (arr[..., i].astype(np.int16) for i in range(3))
    return (b > 170) & (g > 130) & (r < 90) & (b >= g)


def _heuristic_red(arr: np.ndarray) -> np.ndarray:
    r, g, b = (arr[..., i].astype(np.int16) for i in range(3))
    return (r > 170) & (g < 120) & (b < 130)


# --------------------------------------------------------------------------- #
# Analyses
# --------------------------------------------------------------------------- #
def analyze_summary(frame: Image.Image, cfg: AgentConfig, out_dir: str) -> None:
    w, h = frame.size
    box = capture.resolve_summary_region(cfg, frame.size)
    source = "configured" if cfg.summary_region else "auto-fitted to this frame"
    print(f"\n=== SUMMARY ===\nframe: {w}x{h}   summary_region: {list(box)} ({source})")
    if box[2] > w or box[3] > h or box[0] < 0 or box[1] < 0:
        print(f"  !! region extends outside the {w}x{h} frame - coordinates are for "
              f"another resolution. Clear summary_region in agent.toml to auto-fit it.")
    crop = capture.crop_region(frame, box)
    overlay = frame.copy()
    _draw_box(ImageDraw.Draw(overlay), box, GREEN, "summary_region")
    print(f"  saved: {_save(crop, out_dir, 'summary_crop.png')}")
    print(f"  saved: {_save(overlay, out_dir, 'summary_overlay.png')}")
    print("  -> open summary_crop.png: it should contain ONLY the map/result/score "
          "panel. Shift summary_region [left,top,right,bottom] if it's off.")


def _report_side(
    frame: Image.Image,
    arr: np.ndarray,
    name: str,
    colors: list[Color],
    cfg: AgentConfig,
    tol: int,
    out_dir: str,
    paint: Color,
) -> Box | None:
    """Report one leaderboard side; return the box the REAL anchor logic produces."""
    exact = _exact_mask(arr, colors)
    width = capture.resolve_leaderboard_width(cfg, frame.size)
    box = capture.find_leaderboard_anchor(frame, colors, width, cfg.color_tolerance)
    print(f"\n  [{name}] configured colors: {[list(c) for c in colors]}")
    print(f"    exact-match pixels: {int(exact.sum())}")
    if box is not None:
        bw, bh = box[2] - box[0], box[3] - box[1]
        print(f"    anchor box: {list(box)}  ({bw}x{bh}, width fixed at "
              f"leaderboard_width={width})")
    else:
        print("    anchor box: NONE - color not found, this side won't be captured.")

    # Tolerant + heuristic suggestions help when the exact color is slightly off.
    tol_mask = _tolerant_mask(arr, colors, tol)
    tol_box = _bbox(tol_mask)
    if int(tol_mask.sum()) > int(exact.sum()):
        print(f"    with tolerance +/-{tol}: {int(tol_mask.sum())} px, bbox {list(tol_box) if tol_box else None}")
    heur = _heuristic_blue(arr) if paint == CYAN else _heuristic_red(arr)
    suggestions = _top_colors(arr, heur, k=4)
    if exact.sum() < 50 and suggestions:
        pretty = ", ".join(f"{list(c)} (x{n})" for c, n in suggestions)
        key = "blue_colors" if paint == CYAN else "red_colors"
        print(f"    !! exact match is weak. Most common {name}-ish bar colors on screen: {pretty}")
        print(f"       try setting  {key} = [{list(suggestions[0][0])}]  in agent.toml")

    _save(_mask_view(frame, exact, paint), out_dir,
          f"{'blue' if paint == CYAN else 'red'}_mask.png")
    if box is not None:
        _save(capture.crop_region(frame, box), out_dir,
              f"{'team1' if paint == CYAN else 'team2'}_crop.png")
    return box


def analyze_leaderboards(frame: Image.Image, cfg: AgentConfig, out_dir: str, tol: int) -> None:
    w, h = frame.size
    arr = _rgb_array(frame)
    print(f"\n=== SCOREBOARD ===\nframe: {w}x{h}   leaderboard_mode: {cfg.leaderboard_mode}")
    overlay = frame.copy()
    draw = ImageDraw.Draw(overlay)

    if cfg.leaderboard_mode == "region":
        print(f"  team1_region: {list(cfg.team1_region)}   team2_region: {list(cfg.team2_region)}")
        _draw_box(draw, cfg.team1_region, CYAN, "team1_region")
        _draw_box(draw, cfg.team2_region, RED, "team2_region")
        _save(capture.crop_region(frame, cfg.team1_region), out_dir, "team1_crop.png")
        _save(capture.crop_region(frame, cfg.team2_region), out_dir, "team2_crop.png")
        print("  (region mode) tweak team1_region/team2_region in agent.toml to fit each board.")
    else:
        blue_box = _report_side(frame, arr, "blue/own-team", cfg.blue_colors, cfg, tol, out_dir, CYAN)
        red_box = _report_side(frame, arr, "red/enemy", cfg.red_colors, cfg, tol, out_dir, RED)
        _draw_box(draw, blue_box, CYAN, "team1 (blue)")
        _draw_box(draw, red_box, RED, "team2 (red)")

        # What the runtime fallback would find on its own - the answer that matters
        # for a player whose palette isn't the author's (colourblind options).
        auto1, auto2 = capture.detect_team_colors(frame)
        if auto1 and auto2:
            print(f"\n  [auto-detect] sampled bar colours: own-team {list(auto1[0])}, "
                  f"enemy {list(auto2[0])} (used automatically when the configured "
                  f"colours find nothing)")
        else:
            print("\n  [auto-detect] found no pair of team bars in this frame - if this "
                  "is a scoreboard, capture would fail here.")

    print(f"\n  saved: {_save(overlay, out_dir, 'scoreboard_overlay.png')}")
    print("  saved: blue_mask.png / red_mask.png (bright = matched bar pixels), "
          "team1_crop.png / team2_crop.png")
    print("  -> open scoreboard_overlay.png: the two boxes should hug each team's "
          "leaderboard. Fix colors (anchor mode) or rectangles (region mode) above.")


def analyze_full(frame: Image.Image, out_dir: str) -> None:
    w, h = frame.size
    print(f"\n=== FULL FRAME ===\ncaptured {w}x{h}")
    if (w, h) != (1920, 1080):
        print(f"  note: the agent.toml defaults are the original 1920x1080 capture "
              f"geometry; you're at {w}x{h}, so the regions will need tuning.")
    print(f"  saved: {_save(frame, out_dir, 'full_frame.png')}")
    print("  -> re-run offline against this file to iterate on regions:")
    print(f"     python agent\\debug_capture.py -c agent\\agent.toml --image "
          f"{os.path.join(out_dir, 'full_frame.png')}")


# --------------------------------------------------------------------------- #
# Runners
# --------------------------------------------------------------------------- #
def _open(path: str) -> None:
    try:
        os.startfile(path)  # type: ignore[attr-defined]  # Windows only
    except Exception:
        pass


def run_offline(image_path: str, cfg: AgentConfig, out_dir: str, tol: int) -> int:
    if not os.path.isfile(image_path):
        print(f"--image not found: {image_path}")
        return 2
    frame = Image.open(image_path).convert("RGB")
    print(f"Loaded {image_path} ({frame.size[0]}x{frame.size[1]})")
    analyze_summary(frame, cfg, out_dir)
    analyze_leaderboards(frame, cfg, out_dir, tol)
    print(f"\nAll outputs in: {os.path.abspath(out_dir)}")
    _open(os.path.join(out_dir, "scoreboard_overlay.png"))
    _open(os.path.join(out_dir, "summary_overlay.png"))
    return 0


def run_live(cfg: AgentConfig, out_dir: str, tol: int) -> int:
    import keyboard  # lazy: global-hotkey lib, only needed live

    abs_out = os.path.abspath(out_dir)
    print("OverAnalyzer capture DEBUG running.")
    print(f"  outputs -> {abs_out}   (alt-tab here after each capture to read the report)")
    print(f"  {cfg.hotkey_summary}: summary   {cfg.hotkey_scoreboard}: scoreboard   "
          f"{cfg.hotkey_reset}: full frame only   esc: quit")

    def _guard(fn):
        # Keep the hotkey thread alive on a bad grab and print a clean message
        # instead of dumping a traceback into the listener thread.
        def wrapped() -> None:
            try:
                fn()
            except ImportError as exc:
                print(f"\n!! capture dependency missing ({exc}). Run with the repo venv:")
                print("   .venv\\Scripts\\python.exe agent\\debug_capture.py")
            except Exception as exc:  # noqa: BLE001
                print(f"\n!! capture failed: {exc}")
        return wrapped

    def on_summary() -> None:
        analyze_summary(capture.grab_screen(cfg.monitor_index), cfg, out_dir)

    def on_scoreboard() -> None:
        frame = capture.grab_screen(cfg.monitor_index)
        analyze_full(frame, out_dir)          # always stash a raw frame for offline iteration
        analyze_leaderboards(frame, cfg, out_dir, tol)

    def on_full() -> None:
        analyze_full(capture.grab_screen(cfg.monitor_index), out_dir)

    keyboard.add_hotkey(cfg.hotkey_summary, _guard(on_summary))
    keyboard.add_hotkey(cfg.hotkey_scoreboard, _guard(on_scoreboard))
    keyboard.add_hotkey(cfg.hotkey_reset, _guard(on_full))
    keyboard.wait("esc")
    print("Shutting down.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="debug_capture", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-c", "--config", help="Path to agent TOML (defaults applied if omitted).")
    parser.add_argument("--image", help="Offline mode: analyze this saved full frame instead of grabbing the screen.")
    parser.add_argument("--out", default=os.path.join(HERE, "debug_out"), help="Output directory.")
    parser.add_argument("--tolerance", type=int, default=12, help="Color +/- tolerance for anchor diagnostics (default 12).")
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config)
    except (OSError, ValueError) as exc:
        print(f"Config error: {exc}")
        return 2
    os.makedirs(args.out, exist_ok=True)

    if args.image:
        return run_offline(args.image, cfg, args.out, args.tolerance)
    return run_live(cfg, args.out, args.tolerance)


if __name__ == "__main__":
    sys.exit(main())
