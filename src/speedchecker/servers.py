"""Speedtest server discovery, grouping and ordering.

A nearby speed-test server list is fetched from the Speedtest.net JS API (the
catalogue used for built-in throughput tests). VPN locations instead come from
``expressvpnctl get regions`` in the GUI. Nothing here needs the
external ``speedtest`` binary. When the network/API is unavailable the
caller can fall back to :func:`demo_servers` (offline simulation).
"""

import json
import math
import random
import urllib.request
from dataclasses import asdict, dataclass

from .models import CheckerError

SERVERS_API = "https://www.speedtest.net/api/js/servers?engine=js&https_functional=true&limit=500"
CONFIG_API = "https://www.speedtest.net/api/js/config"

# Ordering modes offered in the GUI / CLI.
SORT_MODES = ("file", "name", "country", "city", "sponsor", "host", "distance", "latency", "random")
GROUP_MODES = ("none", "country", "sponsor", "letter")


@dataclass
class Server:
    id: str = ""
    sponsor: str = ""
    city: str = ""  # Speedtest.net calls this "name"
    country: str = ""
    country_code: str = ""
    host: str = ""
    url: str = ""  # upload endpoint
    lat: float = 0.0
    lon: float = 0.0
    distance_km: float | None = None
    latency_ms: float | None = None  # filled after a ping sweep

    @property
    def label(self) -> str:
        return ", ".join(filter(None, (self.country, self.city))) or self.host

    @property
    def base_url(self) -> str:
        """Scheme://host[:port]/speedtest/ derived from the upload URL."""
        if "://" in self.url:
            scheme, rest = self.url.split("://", 1)
            path = rest.split("/", 1)[1] if "/" in rest else ""
            directory = path.rsplit("/", 1)[0] if "/" in path else ""
            return (
                f"{scheme}://{rest.split('/', 1)[0]}/{directory}/"
                if directory
                else f"{scheme}://{rest.split('/', 1)[0]}/"
            )
        return f"http://{self.host}/speedtest/"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Server":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    p = math.pi / 180
    a = (
        0.5
        - math.cos((lat2 - lat1) * p) / 2
        + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lon2 - lon1) * p)) / 2
    )
    return 12742 * math.asin(math.sqrt(max(0.0, a)))


def _get_json(url: str, timeout: float, log) -> object:
    log(f"GET {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "speedchecker/2.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (fixed https host)
        payload = response.read()
    log(f"  <- {len(payload)} bytes from {url.split('/')[2]}")
    return json.loads(payload.decode("utf-8", "replace"))


# Cached last successful fetch — reused when a later fetch fails
# (e.g. DNS blocked inside a VPN tunnel).
_CACHED_SERVERS: list[Server] | None = None


def fetch_servers(timeout: float = 15.0, log=lambda msg: None) -> list[Server]:
    """Download the API's nearby speed-test servers (not VPN locations).

    The ``config`` endpoint is deprecated (404 on speedtest.net) — its failure
    is ignored silently and distance sorting is simply unavailable.  If the
    main server list cannot be fetched but a previous successful fetch is
    cached, the cached list is returned so a VPN tunnel with broken DNS does
    not make every later test fail.
    """
    global _CACHED_SERVERS
    try:
        client_lat = client_lon = None
        try:
            config = _get_json(CONFIG_API, timeout, log)
            client = config.get("client", {}) if isinstance(config, dict) else {}
            client_lat, client_lon = float(client.get("lat", 0)), float(client.get("lon", 0))
            if not math.isfinite(client_lat) or not math.isfinite(client_lon) or (
                client_lat == 0 and client_lon == 0
            ):
                raise ValueError("invalid coordinates")
        except Exception as exc:  # config is optional; distance just stays unknown
            msg = str(exc)
            # The old /api/js/config endpoint now returns 404 — not an error.
            if "404" in msg or "Not Found" in msg:
                log("Client location not available — distance will be shown as — (config endpoint deprecated).")
            else:
                log(f"Client location unavailable (continuing without distance): {exc}")
        raw = _get_json(SERVERS_API, timeout, log)
        if not isinstance(raw, list) or not raw:
            raise CheckerError("Speedtest.net returned an empty server list.")
        servers = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                server = Server(
                    id=str(item.get("id", "")),
                    sponsor=str(item.get("sponsor", "")),
                    city=str(item.get("name", "")),
                    country=str(item.get("country", "")),
                    country_code=str(item.get("cc", "")),
                    host=str(item.get("host", "")),
                    url=str(item.get("url", "")),
                    lat=float(item.get("lat", 0) or 0),
                    lon=float(item.get("lon", 0) or 0),
                )
            except (TypeError, ValueError):
                continue
            if client_lat is not None and (server.lat or server.lon):
                server.distance_km = round(
                    _haversine_km(client_lat, client_lon, server.lat, server.lon), 1
                )
            servers.append(server)
        if not servers:
            raise CheckerError("No usable servers in the Speedtest.net response.")
        log(f"Loaded {len(servers)} servers.")
        _CACHED_SERVERS = list(servers)
        return servers
    except CheckerError:
        raise
    except Exception as exc:
        # If we have a cached list (e.g. fetched before VPN), reuse it when
        # DNS inside the tunnel is broken. This keeps VPN tests from failing
        # outright when speedtest.net cannot be resolved via the tunnel.
        if _CACHED_SERVERS is not None:
            log(f"Server list fetch failed ({exc}) — using {len(_CACHED_SERVERS)} cached servers.")
            return list(_CACHED_SERVERS)
        raise CheckerError(f"Cannot fetch server list: {exc}") from exc


def sort_servers(servers: list[Server], mode: str, *, seed: int | None = None) -> list[Server]:
    """Return a new list ordered by *mode* (see SORT_MODES)."""
    result = list(servers)
    if mode == "file":
        return result
    if mode == "random":
        random.Random(seed).shuffle(result)
        return result
    keys = {
        "name": lambda s: (s.label.casefold(), s.host),
        "country": lambda s: (s.country.casefold(), s.city.casefold(), s.host),
        "city": lambda s: (s.city.casefold(), s.country.casefold(), s.host),
        "sponsor": lambda s: (s.sponsor.casefold(), s.label.casefold()),
        "host": lambda s: s.host.casefold(),  # by endpoint
        "distance": lambda s: (s.distance_km is None, s.distance_km or 0.0, s.label.casefold()),
        "latency": lambda s: (s.latency_ms is None, s.latency_ms or 0.0, s.label.casefold()),
    }
    if mode not in keys:
        raise CheckerError(f"Unknown sort mode {mode!r}; choose from {', '.join(SORT_MODES)}")
    return sorted(result, key=keys[mode])


def ordered_servers(hosts: list[str], servers: list[Server]) -> list[Server]:
    """Map endpoint IDs (in the user's selection order) back to servers.

    Unknown or duplicated IDs are dropped, so the result is exactly what was
    selected, in the order it was selected.
    """
    by_host: dict[str, Server] = {}
    for server in servers:
        by_host.setdefault(server.host, server)
    return [by_host[host] for host in dict.fromkeys(hosts) if host in by_host]


def group_servers(servers: list[Server], mode: str) -> dict[str, list[Server]]:
    """Group like ExpressVPN does: e.g. one section per country."""
    if mode == "none":
        return {"": list(servers)}
    if mode not in GROUP_MODES:
        raise CheckerError(f"Unknown group mode {mode!r}; choose from {', '.join(GROUP_MODES)}")
    groups: dict[str, list[Server]] = {}
    for server in servers:
        key = {
            "country": server.country or "—",
            "sponsor": server.sponsor or "—",
            "letter": (server.country[:1] or "#").upper(),
        }[mode]
        groups.setdefault(key, []).append(server)
    return dict(sorted(groups.items(), key=lambda kv: kv[0].casefold()))


_DEMO = [
    ("Netherlands", "Amsterdam", "NL", "KPN", "ams.speed.invalid:8080"),
    ("Germany", "Frankfurt", "DE", "Demo ISP", "fra.speed.invalid:8080"),
    ("Germany", "Berlin", "DE", "Demo ISP", "ber.speed.invalid:8080"),
    ("Romania", "Bucharest", "RO", "Demo ISP", "otp.speed.invalid:8080"),
    ("Canada", "Toronto", "CA", "Demo ISP", "yyz.speed.invalid:8080"),
    ("United States", "New York", "US", "Demo ISP", "nyc.speed.invalid:8080"),
    ("United Kingdom", "London", "GB", "Demo ISP", "lon.speed.invalid:8080"),
    ("France", "Paris", "FR", "Demo ISP", "par.speed.invalid:8080"),
    ("Japan", "Tokyo", "JP", "Demo ISP", "tok.speed.invalid:8080"),
    ("Singapore", "Singapore", "SG", "Demo ISP", "sin.speed.invalid:8080"),
]


def demo_servers() -> list[Server]:
    """Offline simulated catalogue (never touches the network)."""
    return [
        Server(
            id=str(i + 1),
            sponsor=sponsor,
            city=city,
            country=country,
            country_code=cc,
            host=host,
            url=f"http://{host}/speedtest/upload.php",
            distance_km=100.0 * (i + 1),
        )
        for i, (country, city, cc, sponsor, host) in enumerate(_DEMO)
    ]


def load_servers_file(path, log=lambda msg: None) -> list[Server]:
    """Load a server/location list from JSON.

    Accepts the project ``locations.json`` format (``{"locations": [...]}``),
    a plain list of server objects, or ``{"servers": [...]}``.
    """
    from pathlib import Path

    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CheckerError(f"Cannot read servers file {path}: {exc}") from exc
    if isinstance(data, dict) and isinstance(data.get("locations"), list):
        servers = []
        for item in data["locations"]:
            country, city = str(item.get("country", "")), str(item.get("city", ""))
            servers.append(
                Server(
                    sponsor="ExpressVPN location",
                    city=city,
                    country=country,
                    host=str(item.get("region") or "-".join(filter(None, (country, city))))
                    .lower()
                    .replace(" ", "-"),
                    url="",
                )
            )
        log(f"Loaded {len(servers)} locations from {path}")
        return servers
    items = data.get("servers") if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise CheckerError('Servers file must contain a "servers"/"locations" array.')
    servers = [Server.from_dict(item) for item in items if isinstance(item, dict)]
    log(f"Loaded {len(servers)} servers from {path}")
    return servers


# ExpressVPN region identifiers are NOT Ookla hosts or server IDs. Keep the
# entire identifier for `expressvpnctl connect`; the split is display-only.
_COMPOUND_COUNTRIES = (
    "united-states", "united-kingdom", "south-africa", "new-zealand",
    "hong-kong", "czech-republic", "united-arab-emirates", "south-korea",
    "saudi-arabia", "north-macedonia", "costa-rica", "sri-lanka",
)


def express_region(region: str) -> Server:
    """Represent each VPN endpoint without pretending it is a speed-test host."""
    normalized = region.strip().lower().replace(" ", "-")
    prefix = next((c for c in _COMPOUND_COUNTRIES if normalized.startswith(c + "-")), None)
    parts = region.strip().split("-")
    country = (prefix or parts[0]).replace("-", " ").title()
    city = region.strip()[len(prefix or parts[0]):].lstrip("- ").replace("-", " ")
    return Server(host=region.strip(), country=country, city=city, sponsor="ExpressVPN")
