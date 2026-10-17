# Validation

Validated in the development Linux sandbox with Python 3.11:

- `pip install -r requirements.txt` inside a fresh virtual environment; no installation of this project.
- 71 unittest cases passed, **no skips**, including 7 real PyQt6 offscreen widget tests.
- `ruff check .`, `ruff format --check .`, `git diff --check` passed.
- `python app.py --cli locations.json --demo -s -r 2` completed with an atomic JSON report.
- Desktop demo exercised location loading/filtering, full measurement flow, transfer
  chart, units, history, numeric sorting, JSON validation/order and cancellation.
- Screenshot `desktop.png` is an actual rendering of the offline demo, not a mockup.

The minimal sandbox lacks native Qt runtime packages and cannot access the Debian
package mirrors. For offscreen testing only, GLVND, xkbcommon and libdbus runtime
libraries were built under `/tmp` from upstream source, then supplied through
`LD_LIBRARY_PATH`. These are environment-only test dependencies, not application
files and are not committed or bundled. Normal desktop installations should use
their OS runtime packages as explained in the README. CI installs those packages.

Not validated here: actual ExpressVPN activation/connection, public speedtest.net
availability and real throughput. The sandbox cannot reach those services. Fake
executable integration tests verify subprocess orchestration and failure cleanup;
they do not claim to replace a real end-to-end network test on the target desktop.
