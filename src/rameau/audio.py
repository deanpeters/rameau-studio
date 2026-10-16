"""Sound: render MIDI to audio with FluidSynth and play it.

FluidSynth is used as a separate program (``fluidsynth`` on the PATH, or bundled with the
app later). The SoundFont is looked up in this order:

1. ``RAMEAU_SOUNDFONT`` environment variable
2. ``<user data dir>/soundfonts/*.sf2`` (GeneralUser GS is the recommended default)
3. SoundFonts that came with the FluidSynth install
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def user_data_dir() -> Path:
    system = platform.system()
    if system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    elif system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "rameau-studio"


def _bundle_dir() -> Path | None:
    return Path(sys._MEIPASS) if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS") else None


# Apps opened from the macOS Finder (or a Linux desktop menu) don't see the shell's PATH, so also look
# where package managers usually install FluidSynth.
_COMMON_BIN_DIRS = ["/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin", "/usr/bin", "/snap/bin"]


def fluidsynth_path() -> str | None:
    if os.environ.get("RAMEAU_FLUIDSYNTH"):
        return os.environ["RAMEAU_FLUIDSYNTH"]
    bundle = _bundle_dir()
    if bundle is not None:
        for name in ("fluidsynth.exe", "fluidsynth"):
            for candidate in (bundle / "fluidsynth" / "bin" / name, bundle / "fluidsynth" / name):
                if candidate.exists():
                    return str(candidate)
    found = shutil.which("fluidsynth")
    if found:
        return found
    for d in _COMMON_BIN_DIRS:
        candidate = Path(d) / "fluidsynth"
        if candidate.exists():
            return str(candidate)
    return None


def install_hint() -> str:
    system = platform.system()
    if system == "Darwin":
        return "Install FluidSynth with Homebrew: brew install fluid-synth  (https://brew.sh)"
    if system == "Windows":
        return "Download FluidSynth from https://github.com/FluidSynth/fluidsynth/releases and set RAMEAU_FLUIDSYNTH."
    return "Install FluidSynth with your package manager, e.g. sudo apt install fluidsynth"


def find_soundfont() -> Path | None:
    env = os.environ.get("RAMEAU_SOUNDFONT")
    if env and Path(env).exists():
        return Path(env)
    bundle = _bundle_dir()
    if bundle is not None and sorted((bundle / "soundfonts").glob("*.sf2")):
        return sorted((bundle / "soundfonts").glob("*.sf2"))[0]
    user = sorted((user_data_dir() / "soundfonts").glob("*.sf2"))
    preferred = [p for p in user if "generaluser" in p.name.lower()]
    if preferred or user:
        return (preferred or user)[0]
    fs = fluidsynth_path()
    if fs:
        prefix = Path(fs).resolve().parent.parent
        bundled = sorted((prefix / "share").rglob("*.sf2"))
        if bundled:
            return bundled[0]
    return None


class AudioUnavailable(RuntimeError):
    pass


def render_wav(midi: Path, wav: Path, sample_rate: int = 44100, gain: float = 0.6) -> Path:
    fs = fluidsynth_path()
    if not fs:
        raise AudioUnavailable(f"Sound needs FluidSynth, which wasn't found. {install_hint()}")
    sf = find_soundfont()
    if not sf:
        raise AudioUnavailable(f"No SoundFont found. Put a .sf2 file in {user_data_dir() / 'soundfonts'} "
                               "or set RAMEAU_SOUNDFONT.")
    cmd = [fs, "-ni", "-g", str(gain), "-r", str(sample_rate), "-F", str(wav), str(sf), str(midi)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not Path(wav).exists():
        raise AudioUnavailable(f"FluidSynth failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return Path(wav)


def play_file(wav: Path, wait: bool = False):
    """Play a WAV file with the operating system's player (used by the command line)."""
    system = platform.system()
    if system == "Windows":
        import winsound

        flags = winsound.SND_FILENAME | (0 if wait else winsound.SND_ASYNC)
        winsound.PlaySound(str(wav), flags)
        return None
    player = ["afplay"] if system == "Darwin" else (["paplay"] if shutil.which("paplay") else ["aplay", "-q"])
    proc = subprocess.Popen(player + [str(wav)])
    if wait:
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            print(file=sys.stderr)
    return proc
