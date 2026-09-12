"""Synchronous G-code transport with explicit homing and bounded jogs."""

import logging
import math
import re
import time

import serial
from serial.tools import list_ports

from .config import PrinterConfig

LOG = logging.getLogger(__name__)
STATUS_COMMANDS = frozenset({"M115", "M105"})


class PrinterError(RuntimeError):
    """Connection, protocol, firmware, or timeout failure."""


def discover_ports():
    """Enumerate serial devices without opening them or identifying a printer."""
    return sorted(list_ports.comports(), key=lambda device: device.device)


class Printer:
    def __init__(self, config: PrinterConfig):
        self.config = config
        self._serial = None
        self._pending = bytearray()
        self._homed = False

    def connect(self):
        if self._serial is not None:
            raise PrinterError("Already connected")
        if not self.config.port:
            raise PrinterError("Specify --port explicitly; use list-ports to find device paths")
        connection = serial.Serial(
            port=None, baudrate=self.config.baud, timeout=0.1,
            write_timeout=self.config.timeout, exclusive=True,
        )
        # Avoid deliberately asserting reset/flow-control lines. Some OS drivers
        # still pulse these on open; never connect during an active print.
        connection.dtr = False
        connection.rts = False
        connection.port = self.config.port
        self._serial = connection
        try:
            connection.open()
            LOG.info("Connected to %s at %s baud", self.config.port, self.config.baud)
            deadline = time.monotonic() + self.config.startup_wait
            while time.monotonic() < deadline:
                self._read_line(deadline)
            if self._pending:
                raise PrinterError("Incomplete startup response; increase startup_wait or check baud")
        except BaseException:
            self.close()
            raise
        return self

    def close(self):
        self._homed = False
        if self._serial is not None:
            self._serial.close()
            self._serial = None
            self._pending.clear()
            LOG.info("Disconnected")

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        self.close()

    def _read_line(self, deadline):
        while time.monotonic() < deadline:
            self._serial.timeout = min(0.1, max(0.001, deadline - time.monotonic()))
            byte = self._serial.read(1)
            if not byte:
                continue
            if byte == b"\n":
                line = self._pending.decode("ascii", errors="replace").strip()
                self._pending.clear()
                if not line:
                    continue
                LOG.info("RX %s", line)
                lower = line.lower()
                if (re.search(r"\b(error|resend|unknown command|halted|killed)\b", lower)
                        or lower.startswith(("!!", "rs ", "rs:"))):
                    raise PrinterError(f"Printer reported: {line}")
                return line
            self._pending.extend(byte)
            if len(self._pending) > 4096:
                raise PrinterError("Response line exceeded 4096 bytes; check baud/protocol")
        return None

    def send_gcode(self, command: str) -> list[str]:
        """Send an allowlisted query and wait for its `ok` acknowledgment.

        Acknowledgment only confirms protocol receipt, not physical completion.
        Failures disconnect so late responses cannot acknowledge another query.
        """
        if command not in STATUS_COMMANDS:
            raise ValueError("Only exact M115 and M105 status queries are supported")
        return self._send(command)

    def _send(self, command, timeout=None):
        if self._serial is None:
            raise PrinterError("Not connected")
        try:
            LOG.info("TX %s", command)
            data = (command + "\n").encode("ascii")
            if self._serial.write(data) != len(data):
                raise PrinterError("Incomplete serial write")
            deadline = time.monotonic() + (self.config.timeout if timeout is None else timeout)
            responses = []
            while time.monotonic() < deadline:
                line = self._read_line(deadline)
                if line is None:
                    break
                if line.lower() == "start" or line.startswith("FIRMWARE_NAME:") and command != "M115":
                    raise PrinterError("Printer restarted during session; reconnect and home again")
                responses.append(line)
                if re.match(r"^ok(?:\s|$)", line, re.IGNORECASE):
                    return responses
            raise PrinterError(f"Timed out waiting for ok after {command}; check baud, port, and firmware")
        except BaseException:
            self.close()
            raise

    def require_limits(self):
        if any(getattr(self.config, axis + "_min") is None for axis in "xyz"):
            raise ValueError("Configure x/y/z_min and x/y/z_max before homing or jogging")

    def position(self):
        """Firmware coordinates, not independent measurement of physical position."""
        self._send("M400", self.config.motion_timeout)
        lines = self._send("M114")
        number = r"([-+]?(?:\d+(?:\.\d*)?|\.\d+))"
        for line in lines:
            match = re.search(r"(?:^|\s)X:" + number + r"\s+Y:" + number + r"\s+Z:" + number + r"(?:\s|$)", line)
            if match:
                result = dict(zip("xyz", map(float, match.groups())))
                if all(math.isfinite(v) for v in result.values()):
                    return result
        self.close()
        raise PrinterError("No valid XYZ position in M114 response; session closed")

    def _check_position(self, position):
        for axis, value in position.items():
            low = getattr(self.config, axis + "_min")
            high = getattr(self.config, axis + "_max")
            if not low <= value <= high:
                raise ValueError(f"{axis.upper()}={value:g} is outside configured {low:g}..{high:g} mm")

    def home(self):
        """Explicit full homing; firmware controls the homing path and speed."""
        self.require_limits()
        self._homed = False
        self._send("G21")
        self._send("G90")
        self._send("G28", self.config.motion_timeout)
        position = self.position()
        self._check_position(position)
        self._homed = True
        return position

    def jog(self, axis, distance):
        self.require_limits()
        if not self._homed:
            raise ValueError("Run home in this session before jogging")
        if axis not in "xyz" or len(axis) != 1:
            raise ValueError("Axis must be x, y, or z")
        if not math.isfinite(distance) or not 0 < abs(distance) <= self.config.max_jog:
            raise ValueError(f"Jog must be nonzero and at most {self.config.max_jog:g} mm")
        current = self.position()
        self._check_position(current)
        target = dict(current)
        target[axis] = round(current[axis] + distance, 4)
        self._check_position(target)
        return self._move_axis(axis, current, target)

    def move_to(self, axis, value):
        """Move one axis to an absolute coordinate within configured travel limits."""
        self.require_limits()
        if not self._homed:
            raise ValueError("Run home in this session before positioning")
        if axis not in ("x", "y", "z") or not math.isfinite(value):
            raise ValueError("Specify x, y, or z and a finite coordinate")
        self._check_position({axis: value})
        current = self.position()
        self._check_position(current)
        target = dict(current)
        target[axis] = round(value, 4)
        self._check_position(target)
        return self._move_axis(axis, current, target)

    def _move_axis(self, axis, current, target):
        feed = self.config.z_feed if axis == "z" else self.config.xy_feed
        self._send("G21")
        self._send("G90")
        self._send(f"G1 {axis.upper()}{target[axis]:.4f} F{feed:.4f}")
        actual = self.position()
        if any(abs(actual[a] - target[a]) > 0.05 for a in "xyz"):
            self.close()
            raise PrinterError("Reported position differs from target; inspect printer before rehoming")
        return actual
