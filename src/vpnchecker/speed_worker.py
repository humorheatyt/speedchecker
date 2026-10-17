"""Isolated bundled speedtest process. stdout is newline-delimited JSON."""

import importlib.util
import json
import sys
import threading
import time
from pathlib import Path


def main():
    spec = importlib.util.spec_from_file_location(
        "bundled_speedtest", Path(__file__).resolve().parents[2] / "vendor" / "speedtest.py"
    )
    st = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(st)
    lock = threading.Lock()
    counters = {"download": 0, "upload": 0}
    last = {"download": time.monotonic(), "upload": time.monotonic()}
    previous = dict(counters)

    def emit(data):
        print(json.dumps(data), flush=True)

    def observe(direction, size):
        with lock:
            counters[direction] += size
            now = time.monotonic()
            if now - last[direction] >= 0.25:
                emit(
                    {
                        "type": "progress",
                        "phase": direction,
                        "bps": (counters[direction] - previous[direction])
                        * 8
                        / (now - last[direction]),
                        "bytes": counters[direction],
                    }
                )
                last[direction], previous[direction] = now, counters[direction]

    st.transfer_observer = observe
    try:
        emit({"type": "log", "text": "Fetching speedtest configuration and endpoints"})
        test = st.Speedtest(secure=True, timeout=float(sys.argv[1]))
        test.get_servers([int(sys.argv[2])] if sys.argv[2] else [])
        server = test.get_best_server()
        emit({"type": "log", "text": "Selected endpoint: " + json.dumps(server)})
        last["download"] = time.monotonic()
        test.download()
        last["upload"] = time.monotonic()
        test.upload(pre_allocate=False)
        emit({"type": "result", "result": test.results.dict()})
    except Exception as exc:
        emit({"type": "error", "text": str(exc)})
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
