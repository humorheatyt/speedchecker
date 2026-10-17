# Speedchecker — Live internet speed & ExpressVPN dashboard

A Python app for measuring your connection and comparing ExpressVPN locations. It includes a
responsive, Persian-language live dashboard, a command-line interface, JSON reports, and an
offline demo. The repository/package is named **speedchecker**.

**[راهنمای فارسی](README.fa.md)** · Python **3.10+** · MIT · Runs on Windows, macOS and Linux

## Quick start

```bash
git clone https://github.com/humorheatyt/speedchecker.git
cd speedchecker
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows PowerShell:
# .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:8000**. The dashboard starts in safe demo mode; click **Start test**
to see the live UI without touching the network. Demo results are synthetic and are clearly
labelled. Turn off **Demo mode** when you are ready to run a real test.

The dashboard includes live download/upload/ping readings, a speed chart, per-location results,
a JSON download, test-count and serial/parallel settings, and adjustable display units such as
`Mbps`, `MB/s`, `Kbps`, `KB/s`, `Gbps`, `GB/s`, `bps`, `B/s`, `KiB/s`, `MiB/s`, and `GiB/s`.
Latency can also be displayed in milliseconds, seconds, or microseconds. Changing units updates
the dashboard immediately; saved measurements remain normalized to Mbps for accuracy.

## Speedtest is bundled — no separate CLI install

The project vendors the open-source **speedtest-cli 2.1.3** Python implementation in
`src/speedchecker/_vendor/`, including its Apache-2.0 license. Speedchecker uses it directly as
a library, so you do **not** need to download/install the separate `speedtest` executable or the
`speedtest-cli` PyPI package. `pip install -r requirements.txt` installs the app and its web
runtime dependencies; the speed-test engine is already in the clone and in the built package.

This bundled engine is not Ookla's proprietary official CLI. An optional adapter for the
official Ookla `speedtest` executable remains available with
`--speedtest-backend ookla`; that optional mode still requires the executable and explicit
`--accept-license`. The default bundled engine does not require either.

> A real ExpressVPN comparison still needs an active ExpressVPN installation exposing
> `expressvpnctl` and an authenticated account. Speedchecker is a benchmark tool, not a VPN
> service. The GUI and demo work without ExpressVPN.

## Real VPN benchmarks

1. Install and activate ExpressVPN on a supported machine. This project targets the
   `expressvpnctl` interface. Verify:
   ```bash
   expressvpnctl get regions
   expressvpnctl get connectionstate
   ```
2. Disconnect your current VPN before measuring the baseline. In the dashboard, turn off
   **Demo mode** and start a test. The CLI equivalent is:
   ```bash
   speedchecker -s -r 3 locations.json
   ```
3. If an ExpressVPN connection is already active, Speedchecker refuses to disconnect it unless
   you explicitly enable **Allow disconnecting the current VPN** in the GUI, or add
   `--disconnect-existing` in the CLI. The original connection is **not restored** after the run.

Speed tests can consume substantial bandwidth/data. Serial tests are recommended for meaningful
comparisons; parallel tests compete for the same connection. The app connects to configured VPN
locations one at a time and disconnects in a cleanup step after each attempt.

## Location list

Edit the root `locations.json` file to select VPN locations supported by your current
ExpressVPN client. Example:

```json
{
  "locations": [
    {"country": "Netherlands", "city": "Amsterdam"},
    {"country": "Romania", "city": "Bucharest"},
    {"country": "Canada", "city": "Toronto"},
    {"country": "USA", "city": "New York", "region": "usa-new-york"}
  ]
}
```

`country` is required; `city` and `region` are optional. Find current region IDs with
`expressvpnctl get regions`. An explicit `region` must match exactly (case-insensitive); without
one, the city-country region takes priority. The sample list is not a guarantee that these
locations are still available on your account.

## CLI options

```text
speedchecker [options] input_file
```

| Option | Meaning |
| --- | --- |
| `-h`, `--help` | Show usage |
| `--version` | Show version |
| `-s`, `--serial` | Run measurements one after another |
| `-r N`, `--repeat N` | Tests per baseline/location; default 5 |
| `-o PATH`, `--output PATH` | New JSON report path; existing files are never overwritten |
| `--unit UNIT` | Save the preferred speed display unit in report settings |
| `--command-timeout SEC` | Timeout per ExpressVPN command; default 30 |
| `--connection-timeout SEC` | Timeout for VPN state waits; default 60 |
| `--speedtest-timeout SEC` | Timeout per speed measurement; default 180 |
| `--disconnect-existing` | Explicitly allow disconnecting an existing VPN |
| `--demo` | Offline synthetic measurements; no network/VPN changes |
| `--speedtest-backend bundled` | Use the included Python engine (default) |
| `--speedtest-backend ookla` | Optional official Ookla CLI adapter |
| `--accept-license` | Accept Ookla terms for the optional `ookla` backend |

Other launch options are `python app.py`, `python -m speedchecker`, and the legacy
`vpnchecker` / `expressvpnspeedtest` command names. The separately bundled Speedtest module can
also be run with `speedchecker-speedtest`.

Exit codes: **0** = complete success, **1** = failure or partial results, **2** = invalid CLI
usage, **130** = interrupted.

## Reports and data safety

The dashboard offers the latest saved report as JSON. CLI reports are written to
`results-<UTC timestamp>.json` by default; a path passed with `-o` is never overwritten. Snapshots
are saved atomically after the baseline and every VPN location. A report includes machine name,
OS, selected settings, raw Mbps results, samples, location/server details, and any errors. Review
it before sharing; `results-*.json` is ignored by Git.

The baseline is intentionally measured without ExpressVPN. Existing VPN connections are left
untouched unless you explicitly consent to disconnecting them. A connection made by the tool is
always disconnected after a location test, and the app does not reconnect it afterward. Automatic
reconnect, Network Lock, other VPNs and proxies can affect measurements. Ctrl+C in the CLI or
**Stop safely** in the dashboard finishes the current measurement and attempts VPN cleanup; a
forced process kill or power loss cannot guarantee cleanup.

`app.py` binds to `0.0.0.0` so Arena's preview and other local interfaces can reach it. Run the
control dashboard only on a trusted machine/network; it can initiate speed tests and VPN
connections. Set `SPEEDCHECKER_HOST=127.0.0.1` to restrict it to loopback when running locally.
Use `PORT=8000` or `SPEEDCHECKER_PORT` to change the port.

## Development and verification

```bash
python -m pip install -e '.[dev]'
python -m unittest discover -s tests -v
ruff check .
ruff format --check .
python -m build
```

Tests use mocks and offline demo data; they do not require ExpressVPN credentials or make real
speed tests. The web UI has no CDN/runtime asset dependencies.

## License and attribution

This project is MIT-licensed. The bundled `speedtest-cli` source is Copyright 2012 Matt Martz and
is licensed under Apache-2.0; its license and provenance notice are included beside the source.
The VPN comparison workflow is a Python port of
[toriqo/expressvpnspeedtest](https://github.com/toriqo/expressvpnspeedtest). Speedchecker is not
affiliated with ExpressVPN or Ookla.
