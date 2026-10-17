# vpnchecker — Python ExpressVPN Speed Test

A complete Python port of [toriqo/expressvpnspeedtest](https://github.com/toriqo/expressvpnspeedtest).
Measure your connection without a VPN, benchmark multiple ExpressVPN locations, and save
averaged download/upload speeds, latency, connection time, and individual samples to JSON.

**[راهنمای فارسی](README.fa.md)** · Python **3.10+** · MIT · No Python runtime dependencies

> This is a command-line application, not a VPN service. Real benchmarks still use the
> installed **ExpressVPN `expressvpnctl`** and **official Ookla `speedtest`** executables,
> just as the Go original did. No Go compiler or Go source is needed.

## Quick start (offline demo)

```bash
git clone https://github.com/humorheatyt/vpnchecker.git
cd vpnchecker
# Until the Python port PR is merged, check out its branch:
git checkout arena/7b469e38-vpnchecker
python3 -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install .

vpnchecker --demo -s -r 3 locations.json
```

The demo requires **neither ExpressVPN nor Speedtest**, never changes your network, and
marks every report with `"Demo": true`. Its numbers are synthetic, not actual speed tests.
The equivalent entry points are `python -m vpnchecker` and `expressvpnspeedtest`.

## Real benchmarks

1. Install and activate ExpressVPN with your subscription. This implementation targets
   the **`expressvpnctl` interface**, not the older `expressvpn` CLI. Confirm:
   ```bash
   expressvpnctl get regions
   expressvpnctl get connectionstate
   ```
2. Install the [official Ookla Speedtest CLI](https://www.speedtest.net/apps/cli).
   The unrelated Python package named `speedtest-cli` is **not compatible** with its JSON
   schema/arguments. Run `speedtest` interactively once to review its terms, or explicitly
   pass `--accept-license` to accept the license and GDPR terms during a benchmark.
3. Disconnect your VPN, edit `locations.json`, and run:
   ```bash
   # Three consecutive measurements per baseline/location (recommended for comparison)
   vpnchecker -s -r 3 locations.json

   # Five concurrent measurements per baseline/location (original default)
   vpnchecker locations.json

   # Explicit report path and explicit Ookla terms acceptance
   vpnchecker -s -r 3 --accept-license -o results-my-run.json locations.json
   ```

### Network safety and measurement limits

- Speed tests can consume substantial bandwidth/data. Concurrent tests compete for the
  same connection; their **mean**, not their sum, is reported. Serial mode is usually
  easier to interpret. Parallel workers are capped at 32; all requested tests still run.
- A baseline intentionally measures **without ExpressVPN**. Do not use this tool if you
  require uninterrupted VPN protection. Other VPNs, proxies, or tunnels are not detected.
- An existing or transitioning ExpressVPN connection is left untouched unless you pass
  `--disconnect-existing`. With that option it is disconnected before the baseline and
  **is not restored** after the run. Unknown state values are rejected without this option.
- Locations are connected **one at a time**. After every attempted connection the tool
  disconnects in a `finally` block, even if connecting or testing failed. Cleanup failures
  abort further locations. Check your VPN manually if a disconnect command fails.
- Ctrl+C and SIGTERM request cleanup and save completed batches. Active parallel speed
  tests may take up to their timeout to finish first. Forced termination (SIGKILL), power
  loss, or repeated interruption cannot guarantee cleanup. Previously saved snapshots remain.
- Automatic reconnect/always-on modes and Network Lock may prevent disconnection or the
  baseline test. Check your client's configuration; the tool does not disable security settings.
- Real mode requires a platform/client version exposing the commands above. Demo mode and
  Python unit tests are portable; installing Python alone does not add platform VPN support.

## Input format

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

`country` is required; `city` and `region` are optional strings. Obtain current region IDs
from `expressvpnctl get regions`; the checked-in locations are examples, not a guaranteed
current server directory. Matching is case-insensitive and normalizes spaces/underscores
to hyphens. The exact `country-city` region takes precedence over a country-only region.
If no city matches, a country-only ID is used **only if that exact ID exists**. The tool
never chooses an arbitrary city. An explicit `region` overrides matching, with no fallback.
Unmatched locations are recorded as errors and skipped. Empty or malformed inputs are rejected.

## Options

```text
vpnchecker [options] input_file
```

| Option | Meaning |
| --- | --- |
| `-h`, `--help` | Show usage |
| `--version` | Show version |
| `-s`, `--serial` | Consecutive tests instead of concurrent tests |
| `-r N`, `--repeat N` | Number of tests per baseline and location; default 5, minimum 1 |
| `--repeatSpeedTest N` | Compatibility alias for `--repeat` |
| `-o PATH`, `--output PATH` | New JSON output path; existing files are never overwritten |
| `--command-timeout SEC` | Timeout per ExpressVPN subprocess; default 30 |
| `--connection-timeout SEC` | Timeout per connection/disconnection state wait; default 60 |
| `--speedtest-timeout SEC` | Timeout per speed measurement; default 180 |
| `--disconnect-existing` | Consent to disconnecting an existing VPN before the baseline |
| `--accept-license` | Pass Ookla's `--accept-license` and `--accept-gdpr` switches |
| `--demo` | Offline synthetic measurements; no external programs or network changes |

The state wait begins **after** its connect/disconnect command completes; each command and
wait has its own bound. All timeouts must be finite and positive.

Exit codes: **0** = complete success, **1** = failure or partial results (including skipped
locations/failed samples), **2** = invalid CLI usage, **130** = interrupted.

## Reports

Default filename: `results-<UTC timestamp with microseconds>.json`. A new report is reserved
without overwriting another run, then updated with atomic JSON snapshots after the baseline
and each location. Output parent directories are created automatically. A failed location
cannot erase previous results. An all-failed baseline aborts before connecting any location.

The original fields are retained: `MachineName`, `OS`, `WithoutVPN`, and `VPNStats`, with
`LocationName`, `TimeToConnect`, `VPNDownloadSpeed`, `VPNUploadSpeed`, `VPNLatency`, `Server`,
`Date/Time`, and `Mode` on each VPN row. Schema version 2 additionally includes:

- `Demo`, `Status`, `StartedAt`, `FinishedAt`, and `Settings`;
- `Baseline`: averaged numeric measurements and all successful baseline samples;
- per-row `Region`, `DownloadMbps`, `UploadMbps`, `LatencyMs`, `SuccessfulTests`, `FailedTests`,
  `Samples`, and `Errors`;
- top-level `Errors` for skipped locations and connection/run failures.

Bandwidth in Ookla's JSON is **bytes/second** and is divided by **125,000** to obtain decimal
Mbps. Averages use full precision for **all three metrics**, including the baseline.
Formatted legacy strings use two decimal places. Failed samples are excluded from averages
and counted, never treated as zero. `LocationName` names the requested **VPN location**;
`Samples[].server_location` names the separate **Speedtest server location**. `Server` lists
all distinct test hosts used, while individual samples preserve their provenance.
Timestamps are ISO 8601 UTC. Status is `running`, `completed`, `partial`, `failed`, or
`interrupted`. A saved `running` snapshot can indicate an abruptly terminated process.

Reports include the machine hostname, operating system and tested locations. Review them
before sharing; `results-*.json` files are intentionally ignored by Git. If you choose a
custom filename, keep that report out of version control yourself.

## Development and verification

```bash
python -m pip install -e '.[dev]'
python -m unittest discover -s tests -v
ruff check .
ruff format --check .
python -m build
```

The test suite covers input/schema validation, fractional unit conversion, exact region
priority, serial/parallel execution, baseline averaging, subprocess errors/timeouts,
license opt-in, connection polling, interruption cleanup, partial results, atomic writes,
CLI entry points and offline end-to-end runs. Tests do not require VPN credentials or run
real internet speed tests. GitHub Actions tests Python 3.10–3.14 on Linux and Python 3.12 on
Windows/macOS, checks formatting, and builds/installs the wheel.

```text
src/vpnchecker/
  cli.py         Arguments, exit codes, entry point
  models.py      Locations, validated Speedtest samples, averages
  backends.py    ExpressVPN/Ookla subprocesses and offline simulators
  benchmark.py   Measurement orchestration and cleanup
  storage.py     Atomic JSON reports
```

## Porting notes and attribution

Ported from [toriqo/expressvpnspeedtest](https://github.com/toriqo/expressvpnspeedtest) at
commit `311c65a8f68fa35031bc83f54f2fc314d072eb19`. The original MIT license and Flavius Andrei's
copyright notice are preserved in [LICENSE](LICENSE).

This is a Python reimplementation of the original workflow, not a wrapper around Go.
There are no Go sources, modules, or build steps. It deliberately fixes the original's
last-sample-only baseline, rounded-before-average bandwidth, last-sample latency,
country-before-city matching, and unbounded connection polling. It adds validation,
explicit handling of existing connections, partial reports, and offline testing.
Neither project is affiliated with ExpressVPN or Ookla.
