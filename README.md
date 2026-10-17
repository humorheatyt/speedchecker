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
(`src/speedchecker/engine.py`): ping, multi-connection download and upload
against ordinary Speedtest.net servers, with live progress. **Auto uses this
live engine first** and falls back to the official Ookla binary if needed. Ookla
returns its measurements only when the test finishes, so choose Built-in/Auto
for live gauges. The optional binary can be placed in `vendor/` (see
`vendor/README.md`); it is never installed system-wide.

## GUI features

- **Home** — two separate speedometer gauges (download / upload), live
  instantaneous speed, live chart, measured Ping (ms) & test-server readout,
  start/stop. Gauges auto-scale for the selected unit, including MB/s.
- **Locations** — fetches every region returned by `expressvpnctl get regions` (not Ookla servers). Ctrl-click to multi-select; selecting a group (e.g. a country) selects every endpoint inside it and Ctrl-clicking the group toggles them all. Tests run in the exact order you selected the endpoints, and the selection survives re-sorting, re-grouping and search filtering. Batch test uses the selection when there is one, otherwise every displayed location. The location is used to connect the VPN, while a separate Ookla test server measures throughput. Requires an activated ExpressVPN client and `expressvpnctl` in PATH for real tests.
- **Settings** — language EN/FA, speed unit (Mbps, Gbps, Kbps, bps, MB/s,
  GB/s, KB/s, MiB/s, KiB/s), repetitions per test, **connection / command /
  per-test timeouts**, phase duration, parallel connections (built-in
  engine), engine (Auto / Built-in / Ookla / Demo), Ookla license acceptance, and
  ExpressVPN connection (on by default), optional one-time direct baseline before VPN tests, and explicit permission to disconnect an existing tunnel. An already-connected VPN otherwise blocks the run. Auto uses the live Built-in engine first and falls back to Ookla if needed; the explicit Ookla choice tries Ookla first and uses Built-in on failure. Successful Ookla runs only provide final values. Downloading the optional CLI does not silently switch engines.
- **History** — every test/connection (success *and* errors) is saved to
  `~/.speedchecker/history.json`; successful and partial runs retain the measured
  Ping (ms), which is shown in the Home view, log, and history table. Filter by
  status, text, minimum download or maximum ping; export or clear.
- **Live Log** — everything executed/received is streamed live; saveable.

Offline **Demo mode** simulates servers and measurements end-to-end (handy
for trying the UI without a network).

## CLI

```bash
python app.py --cli locations.json                 # Auto: built-in first, Ookla fallback
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
