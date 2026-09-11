"""Workshop CLI for serial discovery and nonmoving status queries."""

import argparse
import logging

import serial

from shared.config import load_config
from shared.printer import Printer, PrinterError, discover_ports


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("list-ports", help="List devices without opening any serial port")
    status = commands.add_parser("status", aliases=["connect"], help="Connect, query status, then disconnect")
    status.add_argument("--config", help="TOML configuration file")
    status.add_argument("--port", help="Explicit serial device, e.g. /dev/ttyACM0")
    status.add_argument("--baud", type=int, help="Printer baud rate (default: 115200)")
    status.add_argument("--timeout", type=float, help="Seconds to wait for a query acknowledgment (default: 5)")
    status.add_argument("--startup-wait", type=float, help="Seconds to read startup output (default: 2)")
    status.add_argument("--query", choices=["firmware", "temperature"], default="firmware")
    status.add_argument("--log-file", help="Also append timestamped TX/RX logs to this file")
    args = parser.parse_args(argv)
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
