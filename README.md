# Huddle Demos

Fresh Raspberry Pi demonstrations that repurpose a USB G-code 3D printer.
The plotter currently provides **serial discovery and status-only communication**.
Drawing and movement come later. The existing `microscope/` directory is reserved
for future work; no microscope functionality is implemented.

## Requirements and installation

Tested development environment: Raspberry Pi 4, ARM64 Debian 13 (Raspberry Pi
environment), Python 3.13.5. Python 3.11 or later is required. The only runtime
dependency is pySerial 3.5.

From the repository directory, use Raspberry Pi OS/Debian packages and a virtual
environment that can access them. This avoids modifying the system Python with pip:

```bash
sudo apt update
sudo apt install python3-venv python3-serial python3-setuptools python3-wheel
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install --no-build-isolation --no-deps -e .
```

The Pi inspected during implementation already had pySerial 3.5 and setuptools.
Alternatively, for a fully isolated environment on a machine with internet access:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

Use one installation approach. All commands below run from the repository root
and do not require activating the environment or running Python as root.

## First physical connection and communication test

1. Ensure the printer is idle, with no print running or queued. Leave its motion
   area clear. No pen, paper, camera, or GPIO wiring is needed for this iteration.
2. Power the Pi with its normal supply and the printer with its normal power
   supply. Connect a Pi USB port to the printer's USB communication port using a
   **data-capable USB cable** of the appropriate connector type.
3. Close other serial hosts such as slicers, OctoPrint, or serial terminals.
4. List devices; this only enumerates ports and does not open them:

   ```bash
   .venv/bin/python -m plotter list-ports
   ```

5. Identify the printer by comparing the list before/after plugging in its USB
   cable. Discovery lists serial devices, not verified printers. Confirm the
   printer's configured baud rate from its documentation. Run, replacing the
   example port and baud as necessary:

   ```bash
   .venv/bin/python -m plotter status --port /dev/ttyACM0 --baud 115200
   ```

The test opens the selected device, logs startup output for two seconds, sends
exactly `M115` (firmware information), displays every response, waits for an `ok`
line, and disconnects. Success ends with `Communication test passed`; failures
exit with status 1. An acknowledgment proves communication, not hardware readiness.
`connect` is an alias for `status`; it also disconnects after the query.

The supported protocol is newline-delimited, Marlin/RepRap-style G-code with `ok`
acknowledgments. Firmware compatibility still needs verification on your printer.
This implementation accepts only exact `M115` and `M105` queries; it exposes no
raw-command, homing, motion, heater-setting, or persistent-setting interface.

Opening USB serial can reset some controller boards even though the program
does not deliberately assert DTR/RTS. Never connect during a print. If your
printer performs automatic motion on connection or reset, establish its behavior
before this test. See [pySerial's serial-open notes](https://pyserial.readthedocs.io/en/latest/pyserial_api.html).

After confirming firmware communication, optionally request temperatures:

```bash
.venv/bin/python -m plotter status --port /dev/ttyACM0 --baud 115200 --query temperature
```

`M105` reports temperatures; it does not set them. Command references:
[Marlin M115](https://marlinfw.org/docs/gcode/M115.html) and
[Marlin M105](https://marlinfw.org/docs/gcode/M105.html).

## Configuration and logging

```bash
cp printer.example.toml printer.toml
# Edit printer.toml to match your device and baud rate.
.venv/bin/python -m plotter status --config printer.toml --log-file printer.log
```

Configuration is loaded only when `--config` is supplied. CLI options override
file settings. Defaults: no port (explicit selection required), baud 115200,
response timeout 5 seconds, startup wait 2 seconds. Adjust with `--timeout 10`
or `--startup-wait 5` if needed. `/dev/serial/by-id/...` paths can be used for
stable device selection when available. There is no automatic baud probing.
Unknown configuration keys fail visibly. TX/RX and connection events appear on
stderr; `--log-file` additionally appends them to a file. Local configuration
and logs are ignored by Git.

## Troubleshooting and shutdown

- **No device:** check printer power, USB data cable, and another USB port. Run
  `list-ports` again. No USB serial devices were present during implementation.
- **Permission denied:** inspect `ls -l /dev/ttyACM0` (substitute your device).
  If its group is `dialout`, run `sudo usermod -aG dialout "$USER"`, then log out
  and back in before retrying. The inspected user was not in `dialout`. Do not
  solve this by running the CLI as root or making the port world-writable.
- **Busy device:** close other serial clients. Linux exclusive access is requested,
  but other programs may not honor the lock.
- **Garbled text / timeout:** check the documented baud rate (some printers use
  250000), device, and firmware protocol. Increase startup wait for slow boards.
  Responses without a terminating newline and `ok` do not pass. The tool closes
  on failure and does not retry or resend commands automatically.
- **Firmware error / unknown command / resend:** stop and inspect the logged
  response. These are failures, even if followed by `ok`.
- **Shutdown:** let the query finish or press Ctrl+C to close the serial port.
  Then disconnect USB and shut down printer/Pi normally. This tool sends no
  shutdown, heater, or motor commands.

## Layout and software verification

- `shared/`: serial discovery, configuration, connection and response handling.
- `plotter/`: small CLI using the shared layer.
- `microscope/`: existing empty directory, reserved for later.
- `tests/`: standard-library tests using simulated serial pseudo-terminals.

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Tests send bytes only to operating-system pseudo-terminals, never physical
serial devices. Physical printer communication has not yet been validated.
