"""Synchronous, status-only G-code transport. No automatic retries or motion."""

import logging
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
        if self._serial is None:
            raise PrinterError("Not connected")
        try:
            LOG.info("TX %s", command)
            data = (command + "\n").encode("ascii")
            if self._serial.write(data) != len(data):
                raise PrinterError("Incomplete serial write")
            deadline = time.monotonic() + self.config.timeout
            responses = []
            while time.monotonic() < deadline:
                line = self._read_line(deadline)
                if line is None:
                    break
                responses.append(line)
                if re.match(r"^ok(?:\s|$)", line, re.IGNORECASE):
                    return responses
            raise PrinterError(f"Timed out waiting for ok after {command}; check baud, port, and firmware")
        except BaseException:
            self.close()
            raise
