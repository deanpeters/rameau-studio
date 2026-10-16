"""Live playback: drive FluidSynth directly so changes are heard while the music plays.

Instead of rendering a WAV file and playing it, Rameau sends notes to FluidSynth (the same synthesizer,
used as a library through ctypes) from a small scheduler thread. Mixer changes (instrument, volume,
pan, mute, reverb) are applied instantly; musical changes swap in new notes ahead of the playhead.

If libfluidsynth can't be loaded, ``LiveSynth.create()`` returns None and the app falls back to
rendering a file.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import platform
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- library loading


def _candidate_libs() -> list[str]:
    names = []
    if os.environ.get("RAMEAU_FLUIDSYNTH_LIB"):
        names.append(os.environ["RAMEAU_FLUIDSYNTH_LIB"])
    bundle = Path(sys._MEIPASS) if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS") else None
    system = platform.system()
    if bundle is not None:
        for sub in ("fluidsynth/libs", "fluidsynth/bin", "fluidsynth/lib", "fluidsynth"):
            d = bundle / sub
            if d.exists():
                names += [str(p) for p in sorted(d.glob("*fluidsynth*")) if p.suffix in (".dylib", ".dll", ".so")
                          or ".so." in p.name]
    found = ctypes.util.find_library("fluidsynth") or ctypes.util.find_library("libfluidsynth-3")
    if found:
        names.append(found)
    if system == "Darwin":
        names += ["/opt/homebrew/lib/libfluidsynth.dylib", "/usr/local/lib/libfluidsynth.dylib",
                  "/opt/local/lib/libfluidsynth.dylib"]
    elif system == "Windows":
        names += ["libfluidsynth-3.dll", "fluidsynth.dll"]
    else:
        names += ["libfluidsynth.so.3", "libfluidsynth.so"]
    return names


def _load_library():
    for name in _candidate_libs():
        try:
            if platform.system() == "Windows" and os.path.isabs(name):
                os.add_dll_directory(os.path.dirname(name))
            return ctypes.CDLL(name)
        except OSError:
            continue
    return None


# --------------------------------------------------------------------------- synth


class LiveSynth:
    """A thin, thread-safe wrapper over the parts of the FluidSynth C API Rameau needs."""

    def __init__(self, lib, soundfont: Path, gain: float = 0.6) -> None:
        self.lib = lib
        self._lock = threading.Lock()
        p, i, d, s = ctypes.c_void_p, ctypes.c_int, ctypes.c_double, ctypes.c_char_p
        sig = {
            "new_fluid_settings": ([], p), "delete_fluid_settings": ([p], None),
            "fluid_settings_setnum": ([p, s, d], i), "fluid_settings_setint": ([p, s, i], i),
            "fluid_settings_setstr": ([p, s, s], i),
            "new_fluid_synth": ([p], p), "delete_fluid_synth": ([p], None),
            "new_fluid_audio_driver": ([p, p], p), "delete_fluid_audio_driver": ([p], None),
            "fluid_synth_sfload": ([p, s, i], i), "fluid_synth_noteon": ([p, i, i, i], i),
            "fluid_synth_noteoff": ([p, i, i], i), "fluid_synth_cc": ([p, i, i, i], i),
            "fluid_synth_program_change": ([p, i, i], i), "fluid_synth_all_notes_off": ([p, i], i),
            "fluid_synth_set_gain": ([p, ctypes.c_float], None),
        }
        for name, (args, res) in sig.items():
            fn = getattr(lib, name)
            fn.argtypes, fn.restype = args, res
        self.settings = lib.new_fluid_settings()
        lib.fluid_settings_setnum(self.settings, b"synth.gain", gain)
        lib.fluid_settings_setint(self.settings, b"synth.chorus.active", 0)
        lib.fluid_settings_setnum(self.settings, b"synth.reverb.room-size", 0.45)
        lib.fluid_settings_setnum(self.settings, b"synth.reverb.level", 0.5)
        lib.fluid_settings_setnum(self.settings, b"synth.reverb.damp", 0.4)
        if platform.system() == "Linux":
            lib.fluid_settings_setstr(self.settings, b"audio.driver", b"pulseaudio")
        self.synth = lib.new_fluid_synth(self.settings)
        if lib.fluid_synth_sfload(self.synth, str(soundfont).encode(), 1) < 0:
            raise RuntimeError(f"FluidSynth couldn't load {soundfont}")
        self.driver = lib.new_fluid_audio_driver(self.settings, self.synth)
        if not self.driver and platform.system() == "Linux":  # fall back to ALSA
            lib.fluid_settings_setstr(self.settings, b"audio.driver", b"alsa")
            self.driver = lib.new_fluid_audio_driver(self.settings, self.synth)
        if not self.driver:
            raise RuntimeError("FluidSynth couldn't open the audio device")

    @classmethod
    def create(cls) -> "LiveSynth | None":
        from .audio import find_soundfont

        lib = _load_library()
        sf = find_soundfont()
        if lib is None or sf is None or os.environ.get("RAMEAU_NO_LIVE"):
            return None
        try:
            return cls(lib, sf)
        except Exception:
            return None

    # thread-safe primitives
    def noteon(self, ch: int, key: int, vel: int) -> None:
        with self._lock:
            self.lib.fluid_synth_noteon(self.synth, ch, key, vel)

    def noteoff(self, ch: int, key: int) -> None:
        with self._lock:
            self.lib.fluid_synth_noteoff(self.synth, ch, key)

    def cc(self, ch: int, ctrl: int, value: int) -> None:
        with self._lock:
            self.lib.fluid_synth_cc(self.synth, ch, ctrl, max(0, min(127, value)))

    def program(self, ch: int, prog: int) -> None:
        with self._lock:
            self.lib.fluid_synth_program_change(self.synth, ch, prog)

    def all_notes_off(self) -> None:
        with self._lock:
            for ch in range(16):
                self.lib.fluid_synth_all_notes_off(self.synth, ch)

    def close(self) -> None:
        with self._lock:
            if self.driver:
                self.lib.delete_fluid_audio_driver(self.driver)
                self.driver = None
            if self.synth:
                self.lib.delete_fluid_synth(self.synth)
                self.synth = None
            if self.settings:
                self.lib.delete_fluid_settings(self.settings)
                self.settings = None


# --------------------------------------------------------------------------- events and player


@dataclass(order=True)
class NoteEvent:
    start: float               # seconds
    end: float
    channel: int
    pitch: int
    velocity: int


@dataclass
class Channel:
    name: str
    program: int
    volume: int = 100          # CC7
    pan: int = 64              # CC10
    reverb: int = 40           # CC91
    mute: bool = False
    solo: bool = False


@dataclass
class Program:
    """Everything the player needs: notes in seconds, channels, bar starts (for swapping on a bar line)."""
    notes: list[NoteEvent]
    channels: dict[int, Channel]
    bar_times: list[float] = field(default_factory=list)
    length: float = 0.0


class Player:
    """Schedules a Program on a synth in real time, with loop, seek and live swaps."""

    LOOKAHEAD = 0.004  # seconds

    def __init__(self, synth) -> None:
        self.synth = synth
        self.program: Program | None = None
        self._pending: tuple[Program, float] | None = None
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._playing = False
        self._t0 = 0.0          # wall-clock time at which song position 0 would have played
        self._pos0 = 0.0
        self.loop: tuple[float, float] | None = None
        self._sounding: set[tuple[int, int]] = set()
        self.on_finished = None

    # ---------------------------------------------------------------- state
    @property
    def playing(self) -> bool:
        return self._playing

    def position(self) -> float:
        with self._lock:
            if not self._playing:
                return self._pos0
            return time.perf_counter() - self._t0

    def load(self, program: Program) -> None:
        with self._lock:
            was = self._playing
            pos = self.position()
            self.stop()
            self.program = program
            self._apply_channels()
            if was:
                self.play(min(pos, program.length))

    @staticmethod
    def carry_mixer(old: Program | None, new: Program) -> None:
        """Keep the user's mixer settings (instrument, volume, pan, mute, solo) on matching channels."""
        if old is None:
            return
        for ch, c in new.channels.items():
            o = old.channels.get(ch)
            if o is not None and o.name == c.name:
                c.program, c.volume, c.pan, c.mute, c.solo = o.program, o.volume, o.pan, o.mute, o.solo

    def swap(self, program: Program, at: str = "bar") -> float:
        """Replace the music ahead of the playhead. ``at``: "now", "beat" or "bar". Returns the swap time.
        The user's mixer settings carry over to the new music."""
        with self._lock:
            self.carry_mixer(self._pending[0] if self._pending else self.program, program)
            if not self._playing or self.program is None:
                self.program = program
                self._apply_channels()
                return self._pos0
            now = self.position() + 0.05
            when = now
            if at == "bar" and program.bar_times:
                when = next((b for b in program.bar_times if b >= now), now)
            self._pending = (program, when)
            return when

    def _apply_channels(self) -> None:
        if self.program is None:
            return
        solo = any(c.solo for c in self.program.channels.values())
        for ch, c in self.program.channels.items():
            self.synth.program(ch, c.program)
            audible = not c.mute and (c.solo or not solo)
            self.synth.cc(ch, 7, c.volume if audible else 0)
            self.synth.cc(ch, 10, c.pan)
            self.synth.cc(ch, 91, c.reverb)
            self.synth.cc(ch, 93, 0)

    def set_channel(self, ch: int, **changes) -> None:
        """Instant mixer change: program, volume, pan, reverb, mute, solo."""
        with self._lock:
            if self.program is None or ch not in self.program.channels:
                return
            for k, v in changes.items():
                setattr(self.program.channels[ch], k, v)
            if self._pending:
                for k, v in changes.items():
                    if ch in self._pending[0].channels:
                        setattr(self._pending[0].channels[ch], k, v)
            self._apply_channels()

    # ---------------------------------------------------------------- transport
    def play(self, from_s: float | None = None) -> None:
        with self._lock:
            if self.program is None:
                return
            if self._playing:
                self.stop()
            start = self._pos0 if from_s is None else from_s
            if start >= self.program.length - 0.01:
                start = self.loop[0] if self.loop else 0.0
            self._pos0 = start
            self._t0 = time.perf_counter() - start
            self._playing = True
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, args=(start,), name="rameau-player", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            if self._playing:
                self._pos0 = self.position()
            self._playing = False
            self._stop.set()
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout=1.0)
        self._thread = None
        self._release_all()

    def rewind(self) -> None:
        was = self._playing
        self.stop()
        self._pos0 = self.loop[0] if self.loop else 0.0
        if was:
            self.play()

    def _release_all(self) -> None:
        for ch, pitch in list(self._sounding):
            self.synth.noteoff(ch, pitch)
        self._sounding.clear()
        self.synth.all_notes_off()

    # ---------------------------------------------------------------- scheduler
    def _schedule_from(self, program: Program, pos: float) -> list[tuple[float, int, int, int, int]]:
        """(time, on?, channel, pitch, velocity) from ``pos`` onward; notes already sounding are skipped."""
        out = []
        for n in program.notes:
            if n.end <= pos:
                continue
            if n.start >= pos - 1e-6:
                out.append((n.start, 1, n.channel, n.pitch, n.velocity))
            out.append((n.end, 0, n.channel, n.pitch, 0))
        out.sort(key=lambda e: (e[0], e[1]))
        return out

    def _run(self, start: float) -> None:
        with self._lock:
            program = self.program
            queue = self._schedule_from(program, start)  # from the requested position, not "now"
        i = 0
        while not self._stop.is_set():
            pos = self.position()
            with self._lock:
                pending = self._pending
            if pending is not None and pos >= pending[1] - self.LOOKAHEAD:
                new, when = pending
                with self._lock:
                    self._pending = None
                    self.program = program = new
                    self._apply_channels()
                self._release_all()
                queue, i = self._schedule_from(program, when), 0
            end = (self.loop[1] if self.loop else program.length)
            if pos >= end:
                if self.loop:
                    self._release_all()
                    with self._lock:
                        self._t0 = time.perf_counter() - self.loop[0]
                        queue, i = self._schedule_from(program, self.loop[0]), 0
                    continue
                self._release_all()
                with self._lock:
                    self._playing = False
                    self._pos0 = 0.0
                if self.on_finished:
                    self.on_finished()
                return
            while i < len(queue) and queue[i][0] <= pos + self.LOOKAHEAD:
                t, on, ch, pitch, vel = queue[i]
                c = program.channels.get(ch)
                if on:
                    if c is not None and not c.mute:
                        self.synth.noteon(ch, pitch, vel)
                        self._sounding.add((ch, pitch))
                else:
                    self.synth.noteoff(ch, pitch)
                    self._sounding.discard((ch, pitch))
                i += 1
            nxt = queue[i][0] if i < len(queue) else end
            time.sleep(max(0.0005, min(0.005, nxt - self.position() - self.LOOKAHEAD)))


def program_from_midi(path: Path, names: dict[int, str] | None = None) -> Program:
    """Load a finished MIDI file (e.g. an MMA band arrangement) for live playback with a live mixer."""
    import mido

    mf = mido.MidiFile(str(path))
    notes, channels, active = [], {}, {}
    t = 0.0
    for msg in mf:  # merged tracks, msg.time in seconds
        t += msg.time
        if msg.type == "program_change":
            channels.setdefault(msg.channel, Channel(names.get(msg.channel, f"Channel {msg.channel + 1}")
                                                      if names else f"Channel {msg.channel + 1}", msg.program))
            channels[msg.channel].program = msg.program
        elif msg.type == "note_on" and msg.velocity > 0:
            active[(msg.channel, msg.note)] = (t, msg.velocity)
        elif msg.type in ("note_off", "note_on"):
            start = active.pop((msg.channel, msg.note), None)
            if start:
                notes.append(NoteEvent(start[0], t, msg.channel, msg.note, start[1]))
    for ch in {n.channel for n in notes}:
        channels.setdefault(ch, Channel("Drums" if ch == 9 else f"Channel {ch + 1}", 0))
    notes.sort()
    return Program(notes, channels, [], max((n.end for n in notes), default=0.0))
