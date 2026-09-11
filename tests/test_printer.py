"""Exercise real pySerial against a pseudo-terminal, never printer hardware."""

import os
import pty
import select
import threading
import unittest
from unittest.mock import patch

from shared.config import PrinterConfig, load_config
from shared.printer import Printer, PrinterError


class PrinterTests(unittest.TestCase):
    def setUp(self):
        self.master, self.slave = pty.openpty()
        self.printer = Printer(PrinterConfig(
            port=os.ttyname(self.slave), timeout=0.15, startup_wait=0,
        ))
        self.printer.connect()

    def tearDown(self):
        self.printer.close()
        os.close(self.master)
        os.close(self.slave)

    def reply(self, response):
        self.sent = b""

        def device():
            if select.select([self.master], [], [], 1)[0]:
                self.sent = os.read(self.master, 4096)
                os.write(self.master, response)

        worker = threading.Thread(target=device)
        worker.start()
        self.addCleanup(worker.join)
        return worker

    def test_firmware_response_and_exact_wire_command(self):
        worker = self.reply(b"FIRMWARE_NAME:Test\r\nCap:AUTOREPORT_TEMP:1\nok\n")
        result = self.printer.send_gcode("M115")
        worker.join()
        self.assertEqual(self.sent, b"M115\n")
        self.assertEqual(result, ["FIRMWARE_NAME:Test", "Cap:AUTOREPORT_TEMP:1", "ok"])

    def test_inline_temperature_ack(self):
        self.reply(b"ok T:21.0 /0 B:20.0 /0\n")
        self.assertEqual(self.printer.send_gcode("M105"), ["ok T:21.0 /0 B:20.0 /0"])

    def test_motion_and_command_injection_rejected_without_write(self):
        for command in ("G28", "G1 X1", "M500", "M115\nG28", "M115 S1"):
            with self.assertRaises(ValueError):
                self.printer.send_gcode(command)
        self.assertFalse(select.select([self.master], [], [], 0)[0])

    def test_timeout_disconnects(self):
        with self.assertRaisesRegex(PrinterError, "Timed out"):
            self.printer.send_gcode("M115")
        with self.assertRaisesRegex(PrinterError, "Not connected"):
            self.printer.send_gcode("M115")

    def test_firmware_errors_and_resend_fail(self):
        for response in (b"Error:Printer halted\nok\n", b"Resend:1\n", b'echo:Unknown command: "M115"\nok\n'):
            with self.subTest(response=response):
                if self.printer._serial is None:
                    self.printer.connect()
                self.reply(response)
                with self.assertRaises(PrinterError):
                    self.printer.send_gcode("M115")
                self.assertIsNone(self.printer._serial)

    def test_partial_ack_is_not_success(self):
        self.reply(b"ok")
        with self.assertRaisesRegex(PrinterError, "Timed out"):
            self.printer.send_gcode("M115")

    def test_context_manager_closes_on_exception(self):
        self.printer.close()
        with self.assertRaises(RuntimeError):
            with self.printer:
                raise RuntimeError("test")
        self.assertIsNone(self.printer._serial)


class ConfigurationTests(unittest.TestCase):
    def test_invalid_settings(self):
        for setting in ({"baud": 0}, {"baud": True}, {"timeout": 0},
                        {"timeout": float("nan")}, {"startup_wait": -1}, {"port": ""}):
            with self.subTest(setting=setting), self.assertRaises(ValueError):
                PrinterConfig(**setting)

    def test_example_and_override(self):
        config = load_config("printer.example.toml", port="/dev/test", baud=250000)
        self.assertEqual(config.port, "/dev/test")
        self.assertEqual(config.baud, 250000)

    def test_missing_port_does_not_open_serial(self):
        with patch("shared.printer.serial.Serial") as serial_class:
            with self.assertRaises(PrinterError):
                Printer(PrinterConfig()).connect()
            serial_class.assert_not_called()


if __name__ == "__main__":
    unittest.main()
