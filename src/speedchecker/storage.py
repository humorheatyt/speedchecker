"""Atomic JSON snapshots; never silently overwrite an earlier run."""

import json
import os
import tempfile
from pathlib import Path

from .models import CheckerError


class ReportStore:
    def __init__(self, path: Path):
        self.path = path

    def reserve(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("x", encoding="utf-8") as file:
                file.write("{}\n")
        except OSError as exc:
            raise CheckerError(f"Cannot create report {self.path}: {exc}") from exc

    def save(self, report: dict) -> None:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as file:
                temporary = file.name
                json.dump(report, file, indent=2, ensure_ascii=False, allow_nan=False)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        except (OSError, ValueError) as exc:
            raise CheckerError(f"Cannot save report {self.path}: {exc}") from exc
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
