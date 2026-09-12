"""Convert SVG to a G-code file with GcodePlot. Never opens a serial connection."""

import argparse
import math
from pathlib import Path
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("svg", type=Path)
    parser.add_argument("output", nargs="?", type=Path, help="Default: write G-code to stdout")
    parser.add_argument("--draw-speed", type=float, default=20, help="Drawing speed in mm/s")
    parser.add_argument("--workspace", type=Path, default=ROOT / "plotter/workspace.toml")
    parser.add_argument("--printer", type=Path, default=ROOT / "ender3.toml")
    args = parser.parse_args(argv)
    try:
        converter = ROOT / ".tools/gcodeplot/gcodeplot.py"
        if not converter.is_file():
            raise ValueError("Install GcodePlot in .tools/gcodeplot; see README")
        if args.output and args.output.resolve() == args.svg.resolve():
            raise ValueError("Output must not overwrite the source SVG")
        svg = ET.parse(args.svg)
        if any(node.tag.rsplit("}", 1)[-1] in ("text", "image") for node in svg.iter()):
            raise ValueError("Convert text to paths and remove bitmap images in Inkscape first")
        with args.workspace.open("rb") as file:
            settings = tomllib.load(file)
        with args.printer.open("rb") as file:
            printer = tomllib.load(file)["printer"]
        area, pen = settings["workspace"], settings["pen"]
        ox, oy = area["origin_x"], area["origin_y"]
        width, height = area["width"], area["height"]
        down, up = pen["down_z"], pen["up_z"]
        travel, zspeed = printer["xy_feed"] / 60, printer["z_feed"] / 60
        values = (ox, oy, width, height, down, up, travel, zspeed, args.draw_speed)
        if not all(type(v) in (int, float) and math.isfinite(v) for v in values):
            raise ValueError("Configuration values must be finite numbers")
        if min(width, height, travel, zspeed, args.draw_speed) <= 0 or down >= up:
            raise ValueError("Invalid workspace dimensions, speeds, or pen heights")
        for axis, low, high in (("x", ox, ox + width), ("y", oy, oy + height), ("z", down, up)):
            if not printer[axis + "_min"] <= low <= high <= printer[axis + "_max"]:
                raise ValueError(f"Drawing {axis.upper()} range exceeds printer travel limits")
        command = [sys.executable, str(converter),
            f"--area={ox},{oy},{ox+width},{oy+height}",
            f"--work-z={down}", f"--lift-delta-z={up-down}", f"--safe-delta-z={up-down}",
            f"--pen-up-speed={travel}", f"--pen-down-speed={args.draw_speed}", f"--z-speed={zspeed}",
            "--scale=none", "--align-x=none", "--align-y=none", "--shading-threshold=0",
            "--optimization-time=0", "--init-code=G21|G90|G28|M400",
            f"--end-code=G0 Z{up:g} F{zspeed*60:g}|M400", str(args.svg.resolve())]
        result = subprocess.run(command, text=True, capture_output=True, timeout=60)
        if result.returncode or not result.stdout.strip():
            raise ValueError(result.stderr.strip() or "GcodePlot produced no drawing")
        if args.output:
            args.output.write_text(result.stdout)
            print(f"Saved {args.output}; no commands sent to printer.")
        else:
            sys.stdout.write(result.stdout)
        return 0
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError, subprocess.TimeoutExpired) as exc:
        print(f"Conversion failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
