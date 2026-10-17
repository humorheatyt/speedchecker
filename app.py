"""Run from a checkout: python app.py (no installation of this project)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

if __name__ == "__main__":
    if "--cli" in sys.argv:
        sys.argv.remove("--cli")
        from vpnchecker.cli import main
    else:
        from vpnchecker.gui import main
    raise SystemExit(main())
