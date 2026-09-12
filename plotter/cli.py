"""Workshop CLI for status queries and manual, bounded movement."""

import argparse
import logging
import math
from pathlib import Path
import tomllib

import serial

from shared.config import load_config
from shared.printer import Printer, PrinterError, discover_ports


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("list-ports", help="List devices without opening any serial port")
    status = commands.add_parser("status", aliases=["connect"], help="Connect, query status, then disconnect")
    motion = commands.add_parser("manual", help="Interactive homing and single-axis jogs")
    for option in (status, motion):
        add_connection_arguments(option)
    status.add_argument("--query", choices=["firmware", "temperature"], default="firmware")
    motion.add_argument("--workspace", default="plotter/workspace.toml", help="Drawing workspace and pen heights")
    args = parser.parse_args(argv)
    return run(args)


def add_connection_arguments(status):
    status.add_argument("--config", help="TOML configuration file")
    status.add_argument("--port", help="Explicit serial device, e.g. /dev/ttyACM0")
    status.add_argument("--baud", type=int, help="Printer baud rate (default: 115200)")
    status.add_argument("--timeout", type=float, help="Seconds to wait for a query acknowledgment (default: 5)")
    status.add_argument("--startup-wait", type=float, help="Seconds to read startup output (default: 2)")
    status.add_argument("--log-file", help="Also append timestamped TX/RX logs to this file")


def run(args):
    try:
        handlers = [logging.StreamHandler()]
        if getattr(args, "log_file", None):
            handlers.append(logging.FileHandler(args.log_file))
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                            handlers=handlers, force=True)
        if args.action == "list-ports":
            devices = discover_ports()
            if not devices:
                print("No serial devices detected. Connect the printer with a USB data cable and retry.")
            for device in devices:
                print(f"{device.device}\t{device.description}\t{device.hwid}")
            return 0
        config = load_config(args.config, port=args.port, baud=args.baud,
                             timeout=args.timeout, startup_wait=args.startup_wait)
        if args.action == "manual":
            printer = Printer(config)
            printer.require_limits()
            with printer:
                manual_session(printer, args.workspace)
            return 0
        with Printer(config) as printer:
            printer.send_gcode("M115" if args.query == "firmware" else "M105")
        print("Communication test passed: printer acknowledged the status query.")
        return 0
    except (PrinterError, serial.SerialException, OSError, ValueError) as exc:
        logging.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        logging.info("Interrupted; serial connection closed")
        return 130


def manual_session(printer, workspace="plotter/workspace.toml"):
    print("Connected. No motion until you enter home, center, or an axis jog.")
    print("Commands: home, center, position, x MM, y MM, z MM, quit")
    print("Home first. Enter ONE command at a time and inspect each move.")
    print("Keep the area clear and the power switch accessible. Ctrl+C is NOT an emergency stop.")
    print("Do not move axes by hand or use LCD movement during this session.")
    print("If motors release or position becomes uncertain, home again before jogging.")
    config = printer.config
    print("Limits: " + ", ".join(
        f"{a.upper()} {getattr(config, a + '_min'):g}..{getattr(config, a + '_max'):g} mm"
        for a in "xyz"))
    while True:
        try:
            parts = input("printer> ").lower().split()
        except EOFError:
            return
        if not parts:
            continue
        if parts == ["quit"]:
            return
        try:
            if parts == ["home"]:
                position = printer.home()
            elif parts == ["center"]:
                position = center_pen(printer, workspace)
            elif parts == ["position"]:
                position = printer.position()
            elif len(parts) == 2 and parts[0] in ("x", "y", "z"):
                position = printer.jog(parts[0], float(parts[1]))
            else:
                print("Use: home, center, position, x MM, y MM, z MM, quit")
                continue
            print("Firmware position: " + " ".join(f"{a.upper()}={v:g}" for a, v in position.items()))
        except ValueError as exc:
            print(f"Rejected: {exc}")


def center_pen(printer, path):
    with Path(path).open("rb") as file:
        settings = tomllib.load(file)
    try:
        area, pen = settings["workspace"], settings["pen"]
        values = [area[k] for k in ("origin_x", "origin_y", "width", "height")]
        values += [pen["up_z"], pen["down_z"]]
    except (KeyError, TypeError) as exc:
        raise ValueError("Workspace needs origin_x/y, width/height, and pen up_z/down_z") from exc
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise ValueError("Workspace and pen values must be finite numbers")
    ox, oy, width, height, up, down = values
    if width <= 0 or height <= 0 or up <= down:
        raise ValueError("Workspace dimensions must be positive and pen-up must exceed pen-down")
    printer.require_limits()
    printer._check_position(dict(x=ox, y=oy, z=down))
    printer._check_position(dict(x=ox + width, y=oy + height, z=up))
    # Never lower a pen that is already higher than its calibrated clearance.
    current = printer.position()
    printer.move_to("z", max(up, current["z"]))
    printer.move_to("x", ox + width / 2)
    return printer.move_to("y", oy + height / 2)
