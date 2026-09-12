"""Validate and send files from the Huddle SVG exporter."""

import math
from pathlib import Path
import re
import tomllib


def load_job(path, config, workspace):
    with Path(workspace).open('rb') as file:
        settings = tomllib.load(file)
    try:
        area, pen = settings['workspace'], settings['pen']
        ox, oy, w, h = (area[k] for k in ('origin_x', 'origin_y', 'width', 'height'))
        down, up = pen['down_z'], pen['up_z']
        if not all(type(v) in (int, float) and math.isfinite(v) for v in (ox, oy, w, h, down, up)):
            raise ValueError('Workspace values must be finite numbers')
        if w <= 0 or h <= 0 or up <= down:
            raise ValueError('Invalid workspace or pen heights')
        bounds = {'X': (ox, ox + w), 'Y': (oy, oy + h), 'Z': (down, up)}
        for axis, (low, high) in bounds.items():
            if not getattr(config, axis.lower() + '_min') <= low <= high <= getattr(config, axis.lower() + '_max'):
                raise ValueError(f'{axis} workspace exceeds printer limits')
    except (KeyError, TypeError) as exc:
        raise ValueError('Configure workspace, pen heights, and printer limits first') from exc
    lines = [raw.split(';', 1)[0].strip().upper() for raw in Path(path).read_text().splitlines()]
    lines = [line for line in lines if line]
    if lines[:4] != ['G21', 'G90', 'G28', 'M400']:
        raise ValueError('Expected Huddle export header: G21, G90, G28, M400')
    commands = []
    position = {}
    drew = False
    for line in lines[4:]:
        if line == 'M400':
            commands.append(line)
            continue
        tokens = line.split()
        if tokens[0] not in ('G0', 'G00', 'G1', 'G01'):
            raise ValueError(f'Unsupported file command: {line}')
        values = {}
        for token in tokens[1:]:
            match = re.fullmatch(r'([XYZF])([-+]?(?:\d+(?:\.\d*)?|\.\d+))', token)
            if not match or match[1] in values:
                raise ValueError(f'Invalid or duplicate move parameter: {line}')
            values[match[1]] = float(match[2])
        axes = set(values) - {'F'}
        if not axes or 'F' not in values or not all(math.isfinite(v) for v in values.values()):
            raise ValueError(f'Move needs coordinates and a finite feed rate: {line}')
        if 'Z' in axes and len(axes) != 1:
            raise ValueError('Z must move separately from XY')
        maximum = config.z_feed if 'Z' in axes else config.xy_feed
        if not 0 < values['F'] <= maximum:
            raise ValueError(f'Feed rate exceeds configured speed: {line}')
        for axis in axes:
            low, high = bounds[axis]
            if not low <= values[axis] <= high:
                raise ValueError(f'{axis} move outside drawing workspace: {line}')
        if 'Z' in axes:
            if values['Z'] not in (down, up):
                raise ValueError('Z must equal the calibrated pen-up or pen-down height')
            if values['Z'] == down and not {'X', 'Y'} <= position.keys():
                raise ValueError('Position both X and Y over the workspace before lowering the pen')
        else:
            if position.get('Z') not in (down, up):
                raise ValueError('Lift the pen before XY travel')
            if tokens[0] in ('G0', 'G00') and position['Z'] != up:
                raise ValueError('Rapid XY travel requires pen-up')
            if position['Z'] == down:
                drew = True
        position.update({axis: values[axis] for axis in axes})
        commands.append(line)
    if not drew or position.get('Z') != up:
        raise ValueError('File must contain drawing moves and finish with the pen raised')
    return commands


def run_job(printer, commands):
    """commands must be the complete list returned by load_job before connection."""
    printer.home()
    target = {}
    for command in commands:
        target.update({axis.lower(): float(value) for axis, value in
                       re.findall(r"([XYZ])([-+0-9.]+)", command)})
        printer._send(command, printer.config.motion_timeout)
    # Read after all queued moves finish; failures close the connection.
    return printer._verify_target(target)
