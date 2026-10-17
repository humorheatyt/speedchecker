# vendor/ — bundled Ookla Speedtest CLI (optional)

You do **not** need this: SpeedChecker ships a built-in pure-Python speed
engine (`src/speedchecker/engine.py`) that works right after cloning.

If you prefer the official Ookla binary, download *Speedtest CLI* from
https://www.speedtest.net/apps/cli and place the executable here:

```
vendor/speedtest        (Linux/macOS, chmod +x)
vendor/speedtest.exe    (Windows)
```

It is then picked up automatically (engine = Auto / Ookla), both in the
GUI and the CLI — no system-wide installation required. The binary itself
is not committed to git (see `.gitignore`); only this README is.
