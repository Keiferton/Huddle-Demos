"""Exercise real pySerial against a pseudo-terminal, never printer hardware."""

import os
import pty
import select
import threading
import unittest
from unittest.mock import patch
from dataclasses import replace

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


    def motion_config(self):
        self.printer.config = replace(self.printer.config, motion_timeout=0.2,
            x_min=0, x_max=220, y_min=0, y_max=220, z_min=0, z_max=200)

    def sequence(self, responses):
        self.commands = []
        def device():
            for response in responses:
                data = b""
                while not data.endswith(b"\n"):
                    if not select.select([self.master], [], [], 1)[0]:
                        return
                    data += os.read(self.master, 1)
                self.commands.append(data.decode().strip())
                os.write(self.master, response)
        worker = threading.Thread(target=device)
        worker.start()
        self.addCleanup(worker.join)
        return worker

    def test_home_then_jog_wire_sequence(self):
        self.printer.config = replace(load_config("ender3.toml"),
            port=self.printer.config.port, timeout=0.15, startup_wait=0, motion_timeout=0.2)
        origin = b"X:-3.00 Y:-10.00 Z:0.00 E:0 Count X:-240 Y:-800 Z:0\nok\n"
        raised = b"X:-3.00 Y:-10.00 Z:1.00 E:0\nok\n"
        worker = self.sequence([b"ok\n"] * 4 + [origin] +
                               [b"ok\n", origin] + [b"ok\n"] * 4 + [raised])
        self.assertEqual(self.printer.home(), dict(x=-3, y=-10, z=0))
        self.assertEqual(self.printer.jog("z", 1), dict(x=-3, y=-10, z=1))
        worker.join()
        self.assertEqual(self.commands, ["G21", "G90", "G28", "M400", "M114",
            "M400", "M114", "G21", "G90", "G1 Z1.0000 F60.0000", "M400", "M114"])
        self.printer.close()
        self.assertFalse(self.printer._homed)

    def test_motion_requires_limits_and_session_home(self):
        with self.assertRaises(ValueError):
            self.printer.home()
        self.motion_config()
        with self.assertRaisesRegex(ValueError, "Run home"):
            self.printer.jog("x", 1)
        self.assertFalse(select.select([self.master], [], [], 0)[0])

    def test_invalid_jogs_write_nothing(self):
        self.motion_config()
        self.printer._homed = True
        for axis, distance in [("z", 6), ("z", float("nan")), ("z", float("inf")),
                               ("z", 0), ("xy", 1), ("", 1)]:
            with self.assertRaises(ValueError):
                self.printer.jog(axis, distance)
        self.assertFalse(select.select([self.master], [], [], 0)[0])

    def test_limits_reject_without_motion(self):
        self.motion_config()
        self.printer._homed = True
        for axis, distance, xyz in [("z", 1, "X:0 Y:0 Z:200"),
                                    ("x", -1, "X:0 Y:0 Z:0"),
                                    ("y", 1, "X:0 Y:220 Z:0")]:
            worker = self.sequence([b"ok\n", (xyz + "\nok\n").encode()])
            with self.assertRaisesRegex(ValueError, "outside configured"):
                self.printer.jog(axis, distance)
            worker.join()
            self.assertEqual(self.commands, ["M400", "M114"])

    def test_missing_position_closes_connection(self):
        self.sequence([b"ok\n", b"ok\n"])
        with self.assertRaisesRegex(PrinterError, "No valid XYZ"):
            self.printer.position()
        self.assertIsNone(self.printer._serial)

    def test_home_completion_timeout_clears_homing(self):
        self.motion_config()
        self.sequence([b"ok\n"] * 3 + [b"echo:busy: processing\n"])
        with self.assertRaises(PrinterError):
            self.printer.home()
        self.assertFalse(self.printer._homed)
        self.assertIsNone(self.printer._serial)

    def test_reported_target_mismatch_closes(self):
        self.motion_config()
        self.printer._homed = True
        pos = b"X:0 Y:0 Z:0\nok\n"
        self.sequence([b"ok\n", pos] + [b"ok\n"] * 4 + [pos])
        with self.assertRaisesRegex(PrinterError, "differs from target"):
            self.printer.jog("z", 1)
        self.assertFalse(self.printer._homed)
        self.assertIsNone(self.printer._serial)


class ConfigurationTests(unittest.TestCase):
    def test_invalid_settings(self):
        for setting in ({"x_min": 0}, {"z_min": 200, "z_max": 0}, {"xy_feed": 0}, {"motion_timeout": -1}, {"baud": 0}, {"baud": True}, {"timeout": 0},
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
