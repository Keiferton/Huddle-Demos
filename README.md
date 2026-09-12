# Huddle Demos

Fresh Raspberry Pi demonstrations that repurpose a USB G-code 3D printer.
The plotter currently provides **serial discovery, status queries, and manual
homing/small XYZ jogs**. Drawing comes later. The existing `microscope/` directory is reserved
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
The status interface accepts only exact `M115` and `M105` queries. The separate
manual interface below enables explicit homing and bounded movement. Neither
interface exposes raw commands, heater settings, or persistent settings.

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

## Manual homing and first axis tests

The supplied `ender3.toml` describes this workshop printer: user-reported nominal
X/Y maxima of 220 mm, reported home coordinates X=-3 and Y=-10 mm (configured
as x_min and y_min), and a measured safe Z maximum of 200 mm from the modified
home position. The physical Z-stop attachment must remain in the same position.
Verify X/Y bounds before approaching their ends. These limits apply to this
program's jogs; they do not update firmware or constrain LCD moves or G28's
firmware-controlled homing path. Homing must already be mechanically safe.

With the printer idle, the bed clear, and the power switch accessible:

```bash
.venv/bin/python -m plotter manual --config ender3.toml
```

Connecting alone does not send motion commands, though opening USB may reset the
controller. At `printer>` enter **one command at a time**, observe completion,
and proceed only if the result is correct:

1. `home` — full XYZ homing, then report firmware coordinates.
2. `z 1` — raise Z by 1 mm on this verified printer orientation.
3. `x 5` — move X in its positive direction by 5 mm.
4. `y 5` — move Y in its positive direction by 5 mm.
5. `position` — report firmware coordinates.
6. `quit` (or `exit` / `q`) — close the connection without additional motion.

Do not paste the whole sequence. Stop after any unexpected movement. Ctrl+C,
quit, disconnects, and timeouts **do not stop a move already accepted by the
printer**; use the physical power switch if motion is unsafe.

The session stays connected and requires its own successful `home` before any
jog. The Ender 3 profile allows jogs up to 100 mm with `max_jog`; negative increments are supported
within the configured bounds. The Ender 3 profile uses `xy_feed=3000` and `z_feed=240` mm/min
(50 and 4 mm/s); firmware feed overrides may affect actual speed. Keep the LCD
speed override at 100%. Homing uses firmware speeds. Motion acknowledgment and
completion have a separate `motion_timeout` of 120 seconds.

The implementation uses [G28](https://marlinfw.org/docs/gcode/G028.html) to home,
[M400](https://marlinfw.org/docs/gcode/M400.html) to wait for moves, and
[M114](https://marlinfw.org/docs/gcode/M114.html) to read firmware coordinates.
Jogs use explicit millimeter units and absolute targets derived from current
coordinates. A target mismatch or transport failure closes the session.
Coordinates are firmware estimates, not physical feedback: slipping, hand
movement, or released motors can invalidate them. Do not use LCD movement or
move axes by hand during a session. Rehome if motors release or position becomes
uncertain; do not leave a motion session unattended. No homed state is saved
across connections. A physical limit switch is not a substitute for these bounds.

## Plotter drawing area

`plotter/workspace.toml` records a 100 × 100 mm square centered on the nominal
220 × 220 mm bed: the pen covers bed X/Y 60–160 mm. Drawing coordinates run
from (0, 0) to (100, 100), with (50, 50) at the center.

Using the estimated pen offset X=-26.25 mm and Y=0 mm, the corresponding machine
bounds are X=86.25–186.25 and Y=60–160 mm. The center is X=136.25, Y=110.
The estimate assumes the original nozzle was centered on the measured 63.5 mm
E plate and the pen center is 5.5 mm inward from its left edge. Verify alignment
with the mounted pen; its front/back offset has not been measured.

The manual `center` command loads this file (override with `--workspace PATH`).
After `home`, enter `center`: it lifts to Z=2 (or retains a higher current Z),
then moves X and Y together diagonally to the workspace center. The Z lift
finishes before XY travel begins, and the command waits for XY to finish.
Keep the route clear of clips and check the estimated center visually.
Individual jogs still use printer travel limits from `ender3.toml`, not drawing
bounds, so homing and positioning outside the drawing square remain possible. The mounted pen was calibrated at Z=0 for
contact and Z=2 mm for clearance, recorded in the workspace file’s [pen] section.
Recheck these heights if the pen, paper thickness, or Z home reference changes.

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
  `list-ports` again. The workshop Ender 3 was subsequently verified at `/dev/ttyUSB0`, 115200 baud.
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
serial devices. The user validated physical M115 communication with the Ender 3 (firmware
2.0.8.2) at 115200 baud and Auto Home through its LCD. Python-driven homing
and jogging still need physical validation.
