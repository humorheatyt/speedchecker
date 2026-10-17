# SpeedChecker — Internet & VPN Speed Test

**[راهنمای فارسی](README.fa.md)** · Python **3.10+** · PyQt6 · MIT

Modern desktop app (PyQt6, dark theme, **English / فارسی** with RTL) + CLI for
measuring internet speed — directly against Speedtest.net servers, or through
ExpressVPN locations — with live gauges, live chart, history and live logs.

## Quick start — no project installation needed

```bash
git clone https://github.com/humorheatyt/speedchecker.git
cd speedchecker
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt    # installs ONLY PyQt6 — the project itself is not installed
python app.py                      # GUI
python app.py --cli --demo -s -r 3 locations.json   # CLI (offline demo)
```

`app.py` puts `src/` on `sys.path`; nothing of this project is installed into
your venv as a module.

## No external `speedtest` needed

SpeedChecker ships a **built-in pure-Python speed engine**
(`src/speedchecker/engine.py`): latency, multi-connection download and upload
against ordinary Speedtest.net servers, with live progress. If you prefer the
official Ookla binary, drop it into `vendor/` (see `vendor/README.md`) and it
is picked up automatically — still no system-wide install.

## GUI features

- **Home** — two separate speedometer gauges (download / upload), live
  instantaneous speed, live chart, latency & server readout, start/stop.
- **Locations** — fetches every region returned by `expressvpnctl get regions` (not Ookla servers). Ctrl-click to multi-select; selecting a group includes every endpoint; batch tests all displayed locations. The location is used to connect the VPN, while a separate Ookla test server measures throughput. Requires an activated ExpressVPN client and `expressvpnctl` in PATH for real tests.
- **Settings** — language EN/FA, speed unit (Mbps, Gbps, Kbps, bps, MB/s,
  GB/s, KB/s, MiB/s, KiB/s), repetitions per test, **connection / command /
  per-test timeouts**, phase duration, parallel connections, serial repeats,
  engine (Auto / Built-in / Ookla / Demo), Ookla license acceptance, and
  ExpressVPN connection (on by default), optional one-time direct baseline before VPN tests, and explicit permission to disconnect an existing tunnel. An already-connected VPN otherwise blocks the run.
- **History** — every test/connection (success *and* errors) is saved to
  `~/.speedchecker/history.json`; filter by status (errors only / success
  only), text, minimum download or maximum latency; export or clear.
- **Live Log** — everything executed/received is streamed live; saveable.

Offline **Demo mode** simulates servers and measurements end-to-end (handy
for trying the UI without a network).

## CLI

```bash
python app.py --cli locations.json                 # real run (built-in engine)
python app.py --cli --engine ookla locations.json  # force vendor/PATH Ookla binary
python app.py --cli --demo -s -r 3 locations.json  # offline simulation
```

Options: `-r/--repeat`, `-s/--serial`, `-o/--output`,
`--command-timeout`, `--connection-timeout`, `--speedtest-timeout`,
`--disconnect-existing`, `--accept-license`, `--engine {auto,builtin,ookla}`.

## Development

```bash
pip install -r requirements.txt pytest
python -m pytest tests/ -q
```

On headless Linux CI you may need Qt system libraries
(`libgl1 libegl1 libxkbcommon0 libfontconfig1`); desktop systems already have them.
