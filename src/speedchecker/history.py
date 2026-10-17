"""Persistent test/connection history with filtering.

Stored as JSON (default ``~/.speedchecker/history.json``); every finished
test — success **or** error — is appended so the History tab can filter
e.g. only failures, only connected runs, or runs above a speed threshold.
"""

import json
from pathlib import Path

from .models import CheckerError

STATUSES = ("all", "ok", "error")


def default_history_path() -> Path:
    return Path.home() / ".speedchecker" / "history.json"


class HistoryStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else default_history_path()

    def load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CheckerError(f"Cannot read history {self.path}: {exc}") from exc
        return data if isinstance(data, list) else []

    def append(self, record: dict) -> list[dict]:
        records = self.load()
        records.append(record)
        self.save(records)
        return records

    def save(self, records: list[dict]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except OSError as exc:
            raise CheckerError(f"Cannot save history {self.path}: {exc}") from exc

    def clear(self) -> None:
        self.save([])


def filter_history(
    records: list[dict],
    *,
    status: str = "all",
    text: str = "",
    min_download: float | None = None,
    max_latency: float | None = None,
) -> list[dict]:
    """Pure filter used by the GUI History tab (and unit-tested)."""
    if status not in STATUSES:
        raise CheckerError(f"Unknown history status filter {status!r}; choose from {STATUSES}")
    needle = text.strip().casefold()
    result = []
    for record in records:
        if status != "all" and record.get("status") != status:
            continue
        if needle and needle not in json.dumps(record, ensure_ascii=False).casefold():
            continue
        if min_download is not None and (record.get("download_mbps") or 0) < min_download:
            continue
        if max_latency is not None and (
            record.get("latency_ms") is None or record["latency_ms"] > max_latency
        ):
            continue
        result.append(record)
    return result
