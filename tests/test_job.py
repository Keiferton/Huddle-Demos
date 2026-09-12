"""File validation happens before any serial connection or motion."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from plotter.cli import main
from plotter.job import load_job, run_job
from shared.config import load_config
from shared.printer import PrinterError

SAMPLE = """G21
G90
G28
M400
G0 Z2 F240
G0 X100 Y100 F3000
G0 Z0 F240
G1 X110 Y100 F1200
G1 X100 Y100 F1200
G0 Z2 F240
M400
"""


class JobTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.file = Path(folder.name) / "test.gcode"
        self.file.write_text(SAMPLE)
        self.config = load_config("ender3.toml")

    def load(self):
        return load_job(self.file, self.config, "plotter/workspace.toml")

    def test_valid_job_homes_once_and_checks_final_position(self):
        commands = self.load()
        printer = Mock(config=self.config)
        run_job(printer, commands)
        self.assertEqual(printer.mock_calls[0][0], "home")
        printer.home.assert_called_once_with()
        self.assertEqual([c.args[0] for c in printer._send.call_args_list], commands)
        printer._verify_target.assert_called_once_with(dict(x=100, y=100, z=2))

    def test_rejects_unsafe_or_unsupported_files(self):
        for before, after in [("G90", "G91"), ("X110", "X200"), ("Z0", "Z-1"),
                              ("F1200", "F9000"), ("G1 X110", "M104 S200\nG1 X110"),
                              ("G0 Z2 F240\nM400", "M400"),
                              ("G1 X110", "G0 X110"), ("X110", "X110 X111"),
                              ("G0 X100 Y100 F3000", "G0 Y100 F3000")]:
            with self.subTest(after=after):
                self.file.write_text(SAMPLE.replace(before, after))
                with self.assertRaises(ValueError):
                    self.load()

    def test_invalid_file_and_dry_run_never_open_serial(self):
        with patch("plotter.cli.Printer") as printer, patch("builtins.print"), patch("logging.basicConfig"), patch("logging.error"):
            self.assertEqual(main(["run-file", "--config", "ender3.toml", "--dry-run", str(self.file)]), 0)
            self.file.write_text(SAMPLE + "M500\n")
            self.assertEqual(main(["run-file", "--config", "ender3.toml", str(self.file)]), 1)
            printer.assert_not_called()

    def test_transport_error_stops_remaining_commands(self):
        printer = Mock(config=self.config)
        printer._send.side_effect = PrinterError("test failure")
        with self.assertRaises(PrinterError):
            run_job(printer, self.load())
        self.assertEqual(printer._send.call_count, 1)
        printer._verify_target.assert_not_called()
