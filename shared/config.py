"""Small, explicit serial configuration."""

from dataclasses import dataclass
import math
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class PrinterConfig:
    port: str | None = None
    baud: int = 115200
    timeout: float = 5.0
    startup_wait: float = 2.0

    def __post_init__(self):
        if self.port is not None and (not isinstance(self.port, str) or not self.port.strip()):
            raise ValueError("port must be a nonempty device path")
        if type(self.baud) is not int or self.baud <= 0:
            raise ValueError("baud must be a positive integer")
        for name, minimum in (("timeout", 0), ("startup_wait", 0)):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or value < minimum:
                raise ValueError(f"{name} must be a finite nonnegative number")
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
        unknown = set(values) - {"port", "baud", "timeout", "startup_wait"}
        if unknown:
            raise ValueError(f"Unknown printer settings: {', '.join(sorted(unknown))}")
    values.update({key: value for key, value in overrides.items() if value is not None})
    return PrinterConfig(**values)
