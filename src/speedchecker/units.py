"""Speed / data-size unit conversion (single source of truth for GUI + CLI).

Canonical internal unit is **Mbps** (megabits per second) for speed and
bytes for sizes, exactly like the original measurement code.
"""

# unit -> multiplier applied to a value in Mbps
SPEED_UNITS: dict[str, float] = {
    "Mbps": 1.0,
    "Gbps": 1 / 1_000,
    "Kbps": 1_000.0,
    "bps": 1_000_000.0,
    "MB/s": 1 / 8,
    "GB/s": 1 / 8_000,
    "KB/s": 125.0,
    "MiB/s": 1 / 8.388608,
    "KiB/s": 122.0703125,
}

SPEED_DESCRIPTIONS = {
    "Mbps": ("megabits per second", "مگابیت بر ثانیه"),
    "Gbps": ("gigabits per second", "گیگابیت بر ثانیه"),
    "Kbps": ("kilobits per second", "کیلوبیت بر ثانیه"),
    "bps": ("bits per second", "بیت بر ثانیه"),
    "MB/s": ("megabytes per second", "مگابایت بر ثانیه"),
    "GB/s": ("gigabytes per second", "گیگابایت بر ثانیه"),
    "KB/s": ("kilobytes per second", "کیلوبایت بر ثانیه"),
    "MiB/s": ("mebibytes per second (1024² bytes)", "مبی‌بایت بر ثانیه (۱۰۲۴² بایت)"),
    "KiB/s": ("kibibytes per second (1024 bytes)", "کیبی‌بایت بر ثانیه (۱۰۲۴ بایت)"),
}

SIZE_UNITS: dict[str, float] = {  # unit -> bytes
    "B": 1,
    "KB": 1_000,
    "MB": 1_000_000,
    "GB": 1_000_000_000,
    "KiB": 1024,
    "MiB": 1024**2,
    "GiB": 1024**3,
}


def convert_speed(mbps: float, unit: str) -> float:
    if unit not in SPEED_UNITS:
        raise ValueError(f"Unknown speed unit: {unit!r} (choose from {', '.join(SPEED_UNITS)})")
    return mbps * SPEED_UNITS[unit]


def format_speed(mbps: float, unit: str = "Mbps", digits: int = 2) -> str:
    return f"{convert_speed(mbps, unit):.{digits}f} {unit}"


def format_size(num_bytes: float, unit: str | None = None) -> str:
    if unit is not None:
        if unit not in SIZE_UNITS:
            raise ValueError(f"Unknown size unit: {unit!r}")
        return f"{num_bytes / SIZE_UNITS[unit]:.2f} {unit}"
    value, label = float(num_bytes), "B"
    for label in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or label == "TiB":
            break
        value /= 1024
    return f"{value:.2f} {label}"
