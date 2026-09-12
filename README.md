# Huddle Demos

Fresh Raspberry Pi demonstrations that repurpose a USB G-code 3D printer.
The plotter currently provides **serial discovery, status queries, and manual
homing, XYZ jogs, arcs, and SVG-to-G-code export**. The existing `microscope/` directory is reserved
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
within the configured bounds. Combine X/Y with `x 5 y 5` (or `y 5 x 5`)
for one diagonal move; these are relative distances and Z stays unchanged.
The jog cap applies per axis. The Ender 3 profile uses `xy_feed=3000` and `z_feed=240` mm/min
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

## Arcs and circles

At the manual prompt, use `g2 X Y I J` clockwise or `g3 X Y I J`
counterclockwise. Supply four numbers in millimeters: X/Y are endpoint offsets
from the current position, and I/J are center offsets from the current position.
For example, `g2 0 0 5 0` makes a full circle of radius 5 mm, with its center
5 mm to the right of the starting pen position. `g3 10 0 5 0` makes a half-circle.
These CLI endpoint values are relative, even though generated G-code uses
absolute endpoints. Z stays unchanged; lift/lower the pen separately.

Restart the CLI, `home`, then `center`. With Z=2, first try `g2 0 0 5 0`
above the paper. After checking the path, use `z -2`, repeat the circle command,
and `z 2` to lift. Enter commands individually. Arc speed uses `xy_feed`.
Arcs require homing and check all swept extrema against printer travel limits;
the linear `max_jog` cap does not apply to arcs. The configured drawing square
is not enforced for manual arcs. Protocol errors stop the session.

The implementation uses [Marlin G2/G3](https://marlinfw.org/docs/gcode/G002-G003.html)
in the firmware's default XY plane, with I/J centers and no Z/extrusion motion.
It waits for completion and checks reported endpoint coordinates. Arc support
was reported by this printer; physical arc behavior still needs validation.

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

## Inkscape SVG export

Inkscape 1.4 and the [GcodePlot converter](https://github.com/arpruss/gcodeplot)
were verified on this Pi with Python 3.13. The local exporter is file-only:
exporting never connects to the printer. The sample `plotter/examples/first-art.svg`
is a 20 mm square with diagonals, centered on a 100 mm page.

Already installed on this Pi: restart Inkscape, open the sample, then choose
**File → Save a Copy → Huddle pen plotter (*.gcode)**. The export dialog lets you
set drawing speed (default 20 mm/s for this first artwork test). Travel remains
50 mm/s and Z remains 4 mm/s, read from `ender3.toml`; manual jog speeds are unchanged.
The exporter reads `plotter/workspace.toml` for the workspace offset and pen heights.

For your own art, use a **100 × 100 mm page**, keep paths inside the page, use a
black stroke with no fill for outlines, and convert text/shapes via **Path → Object
to Path**. Bitmap images need tracing first. The exporter preserves size and page
placement; it does not automatically resize artwork or fill shaded regions.

Equivalent terminal export, from the repository root:

```bash
.venv/bin/python -m plotter.convert plotter/examples/first-art.svg output/first-art.gcode
```

The output includes full homing, a pen lift before XY travel, and a final pen
lift. Verify clearance during homing with the mounted pen. Run a checked export from the repository root after closing any manual serial
session with `quit`:

```bash
.venv/bin/python -m plotter run-file --config ender3.toml --dry-run output/first-art.gcode
.venv/bin/python -m plotter run-file --config ender3.toml output/first-art.gcode
```

The first command checks the entire file without opening serial. The second
**physically homes and draws**, then lifts the pen and disconnects. Keep paper
secured and the homing/travel route clear of clips. There is no extra home or
center command needed. Ctrl+C or a serial failure does not stop moves already
queued; use the physical power switch if motion is unsafe.

The runner accepts this exporter's absolute linear moves and startup header,
checks workspace bounds, feeds and pen heights before connecting, waits for
acknowledgments, and verifies the final position after motion completes.
It rejects arbitrary G-code, heater commands, relative mode, and arcs in files
(the interactive arc commands remain available). First physical SVG file
execution is still pending.

To reproduce installation on another Pi (Git and Inkscape required):

```bash
git clone https://github.com/arpruss/gcodeplot.git .tools/gcodeplot
git -C .tools/gcodeplot checkout dc9ca1eef3b7af4a253de3adfbd0f1cac3da8364
python3 plotter/inkscape/install.py
```

The installer adds only `huddle_plotter.inx` and `huddle_plotter.py` to the user's
Inkscape extensions folder. It links back to this checkout, so keep the repository
and `.tools/gcodeplot` in place. Run the installer again if the checkout moves.
GcodePlot stays separate and Git-ignored in `.tools/` under its upstream license.
Generated files belong in the Git-ignored `output/` folder. Restart Inkscape if
the export format is missing. Conversion errors appear instead of a valid export;
text must be paths and paths must fit the workspace.

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
2.0.8.2) at 115200 baud and Auto Home through its LCD. The user has since verified Python-driven homing, XYZ and diagonal movement,
pen contact at Z=0 and clearance at Z=2, a small square, and circles.
