"""Launch the Speedchecker live dashboard with ``python app.py``."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from speedchecker.web import create_app  # noqa: E402

app = create_app()


if __name__ == "__main__":
    host = os.environ.get("SPEEDCHECKER_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", os.environ.get("SPEEDCHECKER_PORT", "8000")))
    print(f"Speedchecker dashboard is ready at http://127.0.0.1:{port}")
    app.run(host=host, port=port, debug=False, threaded=True)
