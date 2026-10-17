"""Input validation and lossless speed measurements."""

import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import fmean


class CheckerError(Exception):
    """An actionable configuration, command, or measurement error."""


def slug(value: str) -> str:
    return re.sub(r"[\s_]+", "-", value.strip().casefold())


@dataclass(frozen=True)
class Location:
    country: str
    city: str = ""
    region: str = ""

    @property
    def name(self) -> str:
        return ", ".join(filter(None, (self.country, self.city)))

    def find_region(self, regions: list[str]) -> str | None:
        lookup = {slug(region): region for region in regions}
        if self.region:
            return lookup.get(slug(self.region))
        exact = slug(f"{self.country}-{self.city}") if self.city else slug(self.country)
        return lookup.get(exact) or lookup.get(slug(self.country))


def load_locations(path: Path) -> list[Location]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CheckerError(f"Cannot read locations file {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("locations"), list):
        raise CheckerError('Input must contain a "locations" array.')
    if not data["locations"]:
        raise CheckerError('The "locations" array must not be empty.')
    locations = []
    for index, item in enumerate(data["locations"], 1):
        if not isinstance(item, dict):
            raise CheckerError(f"Location #{index} must be an object.")
        values = {key: item.get(key, "") for key in ("country", "city", "region")}
        if any(not isinstance(value, str) for value in values.values()):
            raise CheckerError(f"Location #{index}: country, city and region must be strings.")
        values = {key: value.strip() for key, value in values.items()}
        if not values["country"]:
            raise CheckerError(f"Location #{index} needs a non-empty country.")
        locations.append(Location(**values))
    return locations


@dataclass(frozen=True)
class Measurement:
    download_mbps: float
    upload_mbps: float
    latency_ms: float
    server: str
    server_location: str

    @classmethod
    def from_json(cls, output: str) -> "Measurement":
        try:
            data = json.loads(output)

            def number(section: str, key: str) -> float:
                value = data[section][key]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"{section}.{key} must be numeric")
                value = float(value)
                if not math.isfinite(value) or value < 0:
                    raise ValueError(f"{section}.{key} must be finite and non-negative")
                return value

            download = number("download", "bandwidth") / 125_000
            upload = number("upload", "bandwidth") / 125_000
            latency = number("ping", "latency")
            server = data["server"]
            host = server["host"]
            country, location = server.get("country", ""), server.get("location", "")
            if not all(isinstance(value, str) for value in (host, country, location)) or not host:
                raise ValueError("invalid server metadata")
            return cls(
                download, upload, latency, host, ", ".join(filter(None, (country, location)))
            )
        except (ValueError, KeyError, TypeError, AttributeError, OverflowError) as exc:
            raise CheckerError(f"Invalid Ookla Speedtest JSON: {exc}") from exc


@dataclass
class Batch:
    samples: list[Measurement]
    errors: list[str]

    def summary(self) -> dict:
        if not self.samples:
            raise CheckerError("All speed tests failed: " + "; ".join(self.errors))
        return {
            "DownloadMbps": fmean(item.download_mbps for item in self.samples),
            "UploadMbps": fmean(item.upload_mbps for item in self.samples),
            "LatencyMs": fmean(item.latency_ms for item in self.samples),
            "SuccessfulTests": len(self.samples),
            "FailedTests": len(self.errors),
            "Samples": [asdict(item) for item in self.samples],
            "Errors": self.errors,
        }
