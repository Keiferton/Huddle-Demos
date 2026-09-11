"""Small, explicit serial configuration."""

from dataclasses import dataclass, fields
import math
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class PrinterConfig:
    port: str | None = None
    baud: int = 115200
    timeout: float = 5.0
    startup_wait: float = 2.0
    motion_timeout: float = 120.0
    x_min: float | None = None
    x_max: float | None = None
    y_min: float | None = None
    y_max: float | None = None
    z_min: float | None = None
    z_max: float | None = None
    xy_feed: float = 300.0
    z_feed: float = 60.0
    max_jog: float = 5.0

    def __post_init__(self):
        if self.port is not None and (not isinstance(self.port, str) or not self.port.strip()):
            raise ValueError("port must be a nonempty device path")
        if type(self.baud) is not int or self.baud <= 0:
            raise ValueError("baud must be a positive integer")
        for name, minimum in (("timeout", 0), ("startup_wait", 0)):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or value < minimum:
                raise ValueError(f"{name} must be a finite nonnegative number")
        for name in ("motion_timeout", "xy_feed", "z_feed", "max_jog"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a finite positive number")
        for axis in "xyz":
            low, high = getattr(self, axis + "_min"), getattr(self, axis + "_max")
            if low is None and high is None:
                continue
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in (low, high)):
                raise ValueError(f"{axis} limits must both be finite numbers")
            if low >= high:
                raise ValueError(f"{axis}_min must be less than {axis}_max")
        if self.timeout == 0:
            raise ValueError("timeout must be greater than zero")


def load_config(path: str | None, **overrides) -> PrinterConfig:
    values = {}
    if path:
        with Path(path).open("rb") as file:
            document = tomllib.load(file)
        if set(document) - {"printer"}:
            raise ValueError("Only the [printer] configuration section is supported")
        values = document.get("printer", {})
        if not isinstance(values, dict):
            raise ValueError("[printer] must be a TOML table")
        unknown = set(values) - {field.name for field in fields(PrinterConfig)}
        if unknown:
            raise ValueError(f"Unknown printer settings: {', '.join(sorted(unknown))}")
    values.update({key: value for key, value in overrides.items() if value is not None})
    return PrinterConfig(**values)
