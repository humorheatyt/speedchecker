"""Display conversions. Measurement storage remains normalized to decimal Mbps."""

SPEED_UNITS = {
    "Mbps": {"label": "Mbps · مگابیت بر ثانیه", "factor": 1.0},
    "MB/s": {"label": "MB/s · مگابایت بر ثانیه", "factor": 0.125},
    "Kbps": {"label": "Kbps · کیلوبیت بر ثانیه", "factor": 1_000.0},
    "KB/s": {"label": "KB/s · کیلوبایت بر ثانیه", "factor": 125.0},
    "Gbps": {"label": "Gbps · گیگابیت بر ثانیه", "factor": 0.001},
    "GB/s": {"label": "GB/s · گیگابایت بر ثانیه", "factor": 0.000125},
    "bps": {"label": "bps · بیت بر ثانیه", "factor": 1_000_000.0},
    "B/s": {"label": "B/s · بایت بر ثانیه", "factor": 125_000.0},
    "KiB/s": {"label": "KiB/s · کیبی‌بایت بر ثانیه", "factor": 125_000 / 1024},
    "MiB/s": {"label": "MiB/s · مِبی‌بایت بر ثانیه", "factor": 125_000 / 1024**2},
    "GiB/s": {"label": "GiB/s · گیبی‌بایت بر ثانیه", "factor": 125_000 / 1024**3},
}

LATENCY_UNITS = {
    "ms": {"label": "میلی‌ثانیه", "factor": 1.0},
    "s": {"label": "ثانیه", "factor": 0.001},
    "µs": {"label": "میکروثانیه", "factor": 1000.0},
}


def convert_speed(mbps: float, unit: str) -> float:
    try:
        return float(mbps) * SPEED_UNITS[unit]["factor"]
    except KeyError as exc:
        raise ValueError(f"Unsupported speed unit: {unit}") from exc


def format_speed(mbps: float, unit: str, decimals: int = 2) -> str:
    return f"{convert_speed(mbps, unit):,.{decimals}f} {unit}"


def convert_latency(milliseconds: float, unit: str) -> float:
    try:
        return float(milliseconds) * LATENCY_UNITS[unit]["factor"]
    except KeyError as exc:
        raise ValueError(f"Unsupported latency unit: {unit}") from exc
