"""Download the official Ookla CLI into this project's ignored vendor directory."""

import io
import os
import platform
import tarfile
import urllib.request
import zipfile
from pathlib import Path

from .models import CheckerError

OFFICIAL_PAGE = "https://www.speedtest.net/apps/cli"
VERSION = "1.2.0"
ARCHIVES = {
    ("Linux", "x86_64"): ("linux-x86_64.tgz", "speedtest"),
    ("Windows", "AMD64"): ("win64.zip", "speedtest.exe"),
}


def download_ookla(log=lambda message: None, *, destination: Path | None = None) -> Path:
    """Download/extract only the executable; never run an installer or modify PATH."""
    target = ARCHIVES.get((platform.system(), platform.machine()))
    if not target:
        raise CheckerError(f"Unsupported platform; download the CLI manually from {OFFICIAL_PAGE}")
    suffix, name = target
    url = f"https://install.speedtest.net/app/cli/ookla-speedtest-{VERSION}-{suffix}"
    dest = destination or Path(__file__).resolve().parents[2] / "vendor" / name
    log(f"Downloading official Ookla CLI from {url}")
    try:
        with urllib.request.urlopen(url, timeout=45) as response:
            # Bound memory, even if the server omits Content-Length.
            archive = response.read(60_000_001)
        if len(archive) > 60_000_000:
            raise CheckerError("Ookla archive exceeds 60 MB limit")
        if suffix.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
                info = next((i for i in bundle.infolist() if Path(i.filename).name == name), None)
                if info is None:  # do not extract anything else
                    raise CheckerError("Ookla executable missing from archive")
                if info.file_size > 60_000_000:
                    raise CheckerError("Invalid executable in Ookla archive")
                data = bundle.read(info)
        else:
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
                member = next((m for m in bundle.getmembers() if Path(m.name).name == name), None)
                if member is None:
                    raise CheckerError("Ookla executable missing from archive")
                if not member.isfile() or member.size > 60_000_000:
                    raise CheckerError("Invalid executable in Ookla archive")
                data = bundle.extractfile(member).read()
        if not data or len(data) > 60_000_000:
            raise CheckerError("Invalid Ookla executable")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".download")
        try:
            tmp.write_bytes(data)
            tmp.chmod(0o755)
            os.replace(tmp, dest)
        finally:
            tmp.unlink(missing_ok=True)
        log(f"Ookla CLI ready at {dest} (not installed system-wide)")
        return dest
    except (OSError, ValueError, KeyError, tarfile.TarError, zipfile.BadZipFile) as exc:
        raise CheckerError(f"Ookla download failed: {exc}") from exc
