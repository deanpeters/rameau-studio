"""Smoke-test a packaged Rameau Studio build: run its command-line modes with time limits.

    python packaging/smoke_test.py <path to the RameauStudio executable>

On failure, prints the app's log (packaged windowed builds write errors to <user data>/rameau.log).
"""

import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def user_log() -> Path:
    system = platform.system()
    if system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    elif system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "rameau-studio" / "rameau.log"


def run(exe: str, *args: str, timeout: int = 180) -> None:
    print(f"$ {Path(exe).name} {' '.join(args)}", flush=True)
    env = {**os.environ, "RAMEAU_TRACE": "1"}
    try:
        proc = subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as e:
        print(f"TIMED OUT after {timeout}s\n--- stdout\n{e.stdout}\n--- stderr\n{e.stderr}")
        dump_log()
        sys.exit(1)
    print(proc.stdout[-2000:], proc.stderr[-2000:], sep="\n")
    if proc.returncode != 0:
        print(f"FAILED with exit code {proc.returncode}")
        dump_log()
        sys.exit(1)


def dump_log() -> None:
    log = user_log()
    print(f"--- {log}")
    print(log.read_text(encoding="utf-8", errors="replace")[-6000:] if log.exists() else "(no log)")


def main() -> None:
    exe = sys.argv[1]
    out = ROOT / "smoke"
    out.mkdir(exist_ok=True)
    run(exe, "styles")
    run(exe, "harmonize", str(ROOT / "src" / "rameau" / "samples" / "twinkle.abc"), "--out", str(out), "--svg")
    run(exe, "band", "| Dm7 G7 | CM7 |", "--groove", "BossaNova", "--out", str(out / "band.mid"))
    for name in ("twinkle.mid", "twinkle.musicxml", "twinkle-1.svg", "band.mid"):
        if not (out / name).exists():
            print(f"MISSING {name}")
            dump_log()
            sys.exit(1)
    print("smoke test passed:", sorted(p.name for p in out.iterdir()))


if __name__ == "__main__":
    main()
