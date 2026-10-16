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


def fluidsynth_path() -> str | None:
    return os.environ.get("RAMEAU_FLUIDSYNTH") or shutil.which("fluidsynth")


def find_soundfont() -> Path | None:
    env = os.environ.get("RAMEAU_SOUNDFONT")
    if env and Path(env).exists():
        return Path(env)
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
        raise AudioUnavailable("FluidSynth was not found. Install it (macOS: brew install fluid-synth; "
                               "Linux: apt install fluidsynth; Windows: see fluidsynth.org) "
                               "or set RAMEAU_FLUIDSYNTH.")
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
