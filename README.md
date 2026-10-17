# Speedchecker

![Speedchecker desktop — offline demo](docs/desktop.png)
[راهنمای فارسی](README.fa.md)

A local PyQt6 desktop studio for benchmarking ExpressVPN locations, with a bundled
open-source speedtest client. Clone, install **dependencies only**, and run `app.py`.
The project itself is not installed into your virtual environment.

## Quick start (Python 3.10+)

```sh
git clone https://github.com/humorheatyt/speedchecker.git
cd speedchecker
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

A desktop session is required. On minimal Debian/Ubuntu installations install the
Qt runtime libraries using your package manager, for example:

```sh
sudo apt install libgl1 libegl1 libopengl0 libxcb-cursor0 libxkbcommon-x11-0 libdbus-1-3
```

On Linux Wayland, if the Qt platform plugin is unavailable, use an X11 desktop or
`QT_QPA_PLATFORM=xcb python app.py`. `offscreen` is for automated tests, not an interactive GUI.

For real VPN tests install and activate ExpressVPN with **`expressvpnctl`** available
in PATH. This tool does not install or bypass the provider's VPN client/subscription.
The existing `expressvpnctl get regions`, `get connectionstate`, `connect <alias>`,
`disconnect` interface must be supported by your ExpressVPN version.

**No separate speedtest CLI installation is needed.** `vendor/speedtest.py` is
speedtest-cli 2.1.3 (Apache-2.0), committed with its license and local change notes.
This is the community HTTP client, **not** the proprietary Ookla binary; endpoints
may be unavailable and results can differ from the official application.

## Desktop workflow

1. Choose real mode or **Offline demo (synthetic)**. Demo never modifies networking.
2. **Load ALL VPN locations** before testing. The full provider alias list is loaded
   in a background thread. Search, group by alias prefix, or order by provider order,
   alphabetical/reverse, location prefix, random, or an imported JSON plan.
3. Check locations or highlight one and choose **Test highlighted location**.
   “Check visible” selects all locations in the current filter. Group headers are
   not testable servers. The checked visible rows are the batch plan.
4. Settings: repetitions, 1–32 concurrent measurements **on the same VPN location**,
   command timeout, connection-state timeout, complete test deadline, HTTP socket
   timeout, pause between locations, baseline toggle and optional numeric speedtest
   endpoint ID (empty = automatic nearest endpoint).
5. Select speed units (Mbps, MB/s, Kbps, KB/s, Gbps, GB/s, KiB/s, MiB/s) and size
   units (B, KB, MB, GB, KiB, MiB). History is always stored losslessly in Mbps.
6. **Live & logs** shows per-attempt transfer samples, download/upload chart,
   executed commands, stdout/stderr, selected endpoint metadata, results and errors.
   Each concurrent sample is labelled with attempt and location; it is not an
   aggregate of simultaneous tests. Upload live bytes count bytes supplied to the
   HTTP stack, not acknowledged payload. The chart autoscales over recent samples.
7. **History** includes every completed/failed/cancelled attempt and connection
   failures (attempt 0), UTC timestamps, endpoint, settings and demo marking. Filter
   by status, real/demo, text/date/location/endpoint/error, and minimum download Mbps.
   Click columns to sort, including numeric speed/latency, then export filtered
   rows as JSON/CSV. Exports keep canonical Mbps, regardless of display units.

JSON plans use the original schema (`region` is the explicit provider alias):

```json
{"locations": [
  {"country": "Germany", "city": "Frankfurt", "region": "germany-frankfurt"},
  {"country": "Japan", "city": "Tokyo", "region": "japan-tokyo"}
]}
```

Aliases must match the list returned by your provider. Import validates all entries
before accepting the plan and preserves file order. Geographic groups are inferred
from alias prefixes, not an official ExpressVPN continent catalogue.

### Safety and concurrency

A normal host has one ExpressVPN tunnel. **Different VPN locations cannot be tested
simultaneously on it**. Locations run sequentially; repetitions on each location
may run concurrently. These compete for bandwidth, so use one worker for comparable
line-speed measurements. True parallel location tests need separate isolated
network namespaces/VMs and are not provided here.

The app refuses to disrupt an already active VPN unless you explicitly enable
“Allow disconnecting current VPN”. The original connection **is not restored**.
Connections made by the app are disconnected even after a test/connect failure.
A disconnect failure aborts the batch instead of testing on an unknown tunnel.
Stop kills active speedtest child processes, stops scheduling new attempts, and
waits for bounded VPN state/cleanup operations. Close is refused until cleanup
finishes. Hard-killing the application or losing power cannot guarantee cleanup.

History: `~/.speedchecker/history.sqlite3`. Timestamped session logs:
`~/.speedchecker/logs/`. Preferences use the OS Qt settings store. Logs contain
provider aliases, endpoint metadata and diagnostic output: review before sharing.
There is no automatic log deletion; remove old logs yourself when appropriate.
Use only one running real-testing instance; other VPN apps/scripts can interfere.

## Direct CLI (optional)

```sh
python app.py --cli locations.json --demo -s -r 2
python app.py --cli locations.json -s -r 3 --connection-timeout 60 --speedtest-timeout 180
python app.py --cli --help
```

The CLI defaults to the bundled client. For compatibility with an already installed
proprietary Ookla executable only, use `--backend ookla --accept-license`.
CLI reports are atomic JSON snapshots (`results-*.json`), not desktop SQLite history.
`src/vpnchecker` is retained as the internal compatibility namespace; the repository,
application and user-facing launch path are Speedchecker. No `pip install .` needed.

## Tests

```sh
pip install -r requirements.txt ruff
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
ruff check .
ruff format --check .
python app.py --cli locations.json --demo -s -r 2
```

Tests use isolated fake subprocesses and offline VPNs, including cancellation,
whole-test deadline, bounded workers, persistence and cleanup failures. GUI tests
use Qt's offscreen platform and skip with an explicit reason if native Qt libraries
are missing. Real ExpressVPN activation and speedtest.net reachability must be
verified on the target desktop; sandbox tests are not proof of live VPN throughput.
