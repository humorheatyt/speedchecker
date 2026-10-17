#!/usr/bin/env python3
"""SpeedChecker entry point — run the project without installing it.

    pip install -r requirements.txt
    python app.py            # modern PyQt6 GUI (default)
    python app.py --cli …    # command-line interface, e.g.:
    python app.py --cli --demo -s -r 3 locations.json

The project package lives in ``src/`` and is added to ``sys.path`` here,
so the project itself is *not* installed into your venv as a module —
only the dependencies from requirements.txt are.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        from speedchecker.cli import main

        raise SystemExit(main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        raise SystemExit(0)
    from speedchecker.gui import main

    raise SystemExit(main(sys.argv[1:]))
