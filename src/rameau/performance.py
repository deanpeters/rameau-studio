"""Turn a harmonized score into an expressive MIDI performance.

A score is not a performance. Played literally, four parts at one loudness, perfectly legato and
metronomic, become a wall of chords. This module "performs" the notes the way musicians do:

* **Balance**  the melody sings out; inner voices sit underneath; the bass is firm.
* **Metre**    strong beats get a little more weight than weak beats and off-beats.
* **Phrasing** each phrase swells toward its cadence and relaxes after it.
* **Timing**   the music broadens (ritardando) into each cadence; fermatas are held; the last
               cadence slows the most. Tiny human timing variations keep it from sounding mechanical.
* **Articulation** repeated notes are re-struck with a small gap; moving lines stay legato.
* **Doubling** when an instrument doubles a voice (organ under a choir), it plays softer, supporting
               rather than smothering.
"""

from __future__ import annotations

import bisect
import random
from dataclasses import dataclass
from pathlib import Path

import mido

VOICE_LEVEL = {0: 86, 1: 58, 2: 60, 3: 72}   # soprano, alto, tenor, bass (MIDI velocity)
DOUBLING_DROP = 20                             # second instrument on a voice plays this much softer
TICKS = 960                                    # ticks per second (we write a fixed 60 BPM tempo map)


@dataclass
class Style:
    rit: float = 0.82          # tempo factor on the cadence beat (lower = slower)
    rit_beats: int = 2         # beats of slowing before each cadence
    fermata: float = 1.8       # how long a phrase-ending note is held, relative to its written length
    final_rit: float = 0.7     # extra slowing into the very last cadence
    swell: int = 10            # loudness rise toward each cadence
    accent: int = 7            # strong-beat emphasis
    humanize_ms: float = 7.0
    humanize_vel: int = 3
    swing: bool = False        # play written eighths long-short (off-beats at 2/3 of the beat)


def _swing(q: float) -> float:
    """Swing feel: an eighth note on the off-beat sounds at 2/3 of the beat instead of 1/2."""
    base = float(int(q // 1))
    f = q - base
    return base + (f * 4 / 3 if f <= 0.5 else 2 / 3 + (f - 0.5) * 2 / 3)


def _beat_map(h, bpm: int, style: Style) -> tuple[list[float], list[float]]:
    """Piecewise-linear map from score position (quarter notes) to seconds, with ritardandos and fermatas."""
    beats = [c.beat for c in h.choices]
    ends = [i for i, b in enumerate(beats) if b.phrase_end]
    last_end = ends[-1] if ends else len(beats) - 1
    spq = 60.0 / bpm
    q_points, s_points = [beats[0].offset if beats else 0.0], [0.0]
    for i, b in enumerate(beats):
        factor = 1.0
        for e in ends:
            d = e - i
            if 0 < d <= style.rit_beats:            # approaching a cadence: broaden
                k = 1 - d / (style.rit_beats + 1)
                factor = 1 / (1 - (1 - style.rit) * k)
            elif d == 0:
                factor = (style.fermata if b.onset else 1.15) / (style.final_rit if e == last_end else 1.0)
        seconds = b.duration * spq * factor
        q_points.append(b.offset + b.duration)
        s_points.append(s_points[-1] + seconds)
    return q_points, s_points


def _to_seconds(q: float, q_points: list[float], s_points: list[float], spq: float) -> float:
    if q <= q_points[0]:
        return s_points[0] + (q - q_points[0]) * spq
    if q >= q_points[-1]:
        return s_points[-1] + (q - q_points[-1]) * spq
    i = bisect.bisect_right(q_points, q) - 1
    span = q_points[i + 1] - q_points[i]
    frac = (q - q_points[i]) / span if span else 0.0
    return s_points[i] + frac * (s_points[i + 1] - s_points[i])


def _phrase_arc(h) -> list[int]:
    """Extra loudness per beat: rising toward each cadence, relaxing after it."""
    beats = [c.beat for c in h.choices]
    ends = [i for i, b in enumerate(beats) if b.phrase_end] or [len(beats) - 1]
    arc, start = [0.0] * len(beats), 0
    for e in ends:
        n = max(1, e - start)
        for i in range(start, e + 1):
            x = (i - start) / n
            arc[i] = (x / 0.7) if x < 0.7 else (1 - (x - 0.7) / 0.3 * 0.6)  # rise to 70%, ease toward cadence
        start = e + 1
    return [round(a, 3) for a in arc]


def perform(score, h, voices, bpm: int, path: Path, style: Style | None = None, seed: int = 1,
            levels: dict[int, int] | None = None) -> Path:
    """Write an expressive MIDI file. ``voices[i]`` lists General MIDI programs for part i (doubling allowed).
    ``levels`` overrides the loudness of each part (default: soprano, alto, tenor, bass)."""
    levels = levels or VOICE_LEVEL
    style = style or Style()
    rng = random.Random(seed)
    spq = 60.0 / bpm
    q_points, s_points = _beat_map(h, bpm, style)
    arc = _phrase_arc(h)
    beat_starts = [c.beat.offset for c in h.choices]
    strong = {c.beat.offset for c in h.choices if c.beat.beat == 1}
    medium = {c.beat.offset for c in h.choices if c.beat.beat == 3}

    mf = mido.MidiFile(type=1, ticks_per_beat=TICKS)
    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage("set_tempo", tempo=1_000_000, time=0))  # 60 BPM: 1 beat = 1 second
    mf.tracks.append(meta)

    channel = 0
    for part_index, part in enumerate(score.parts):
        notes = [n for n in part.flatten().notes if n.quarterLength > 0]
        programs = voices[min(part_index, len(voices) - 1)]
        for dbl, program in enumerate(programs):
            if channel == 9:
                channel += 1  # channel 10 is drums
            events = []
            for k, n in enumerate(notes):
                q0, q1 = float(n.offset), float(n.offset + n.quarterLength)
                w0, w1 = (_swing(q0), _swing(q1)) if style.swing else (q0, q1)
                t0 = _to_seconds(w0, q_points, s_points, spq)
                t1 = _to_seconds(w1, q_points, s_points, spq)
                nxt = notes[k + 1] if k + 1 < len(notes) else None
                same_next = nxt is not None and abs(float(nxt.offset) - q1) < 1e-6 and \
                    nxt.pitches[-1].midi == n.pitches[-1].midi
                gap = 0.07 if same_next else 0.02
                if part_index > 0 and n.quarterLength <= 1 and style.swing is False and len(n.pitches) > 1:
                    gap = max(gap, 0.25 * (t1 - t0))  # keyboard chords in pop and Latin are played detached
                if k > 0 or q0 > beat_starts[0]:
                    t0 += rng.uniform(-style.humanize_ms, style.humanize_ms) / 1000
                t1 = max(t0 + 0.05, t1 - gap)
                bi = max(0, bisect.bisect_right(beat_starts, q0) - 1)
                vel = levels.get(part_index, 64) + round(arc[bi] * style.swell)
                if q0 in strong:
                    vel += style.accent
                elif q0 in medium:
                    vel += style.accent // 2
                elif abs(q0 - round(q0)) > 1e-6:
                    vel -= 6  # off-beat ornaments are lighter
                vel += rng.randint(-style.humanize_vel, style.humanize_vel) - dbl * DOUBLING_DROP
                vel = max(20, min(118, vel))
                for p in n.pitches:
                    events.append((t0, 1, p.midi, vel))
                    events.append((t1, 0, p.midi, 0))
            track = mido.MidiTrack()
            track.append(mido.Message("program_change", channel=channel, program=program, time=0))
            track.append(mido.Message("control_change", channel=channel, control=91, value=40, time=0))  # reverb
            track.append(mido.Message("control_change", channel=channel, control=93, value=0, time=0))   # chorus
            last = 0
            for t, on, pitch, vel in sorted(events, key=lambda e: (e[0], e[1])):
                tick = max(0, int(round(max(0.0, t) * TICKS)))
                kind = "note_on" if on else "note_off"
                track.append(mido.Message(kind, channel=channel, note=pitch, velocity=vel if on else 0,
                                          time=tick - last))
                last = tick
            mf.tracks.append(track)
            channel = min(15, channel + 1)
    mf.save(str(path))
    return Path(path)


def melody_style_from(h) -> Style:
    """Style-appropriate expression: churchy chorales broaden more than dance-like music."""
    name = getattr(h.style, "name", "")
    if name in ("bach_chorale", "palestrina", "monteverdi"):
        return Style(rit=0.78, fermata=1.9, final_rit=0.65, swell=10)
    if name in ("classical", "romantic"):
        return Style(rit=0.85, fermata=1.5, final_rit=0.7, swell=12)
    from .comping import FAMILIES, SWING_FAMILIES

    swing = FAMILIES.get(name) in SWING_FAMILIES
    return Style(rit=0.92, fermata=1.25, final_rit=0.8, swell=8, accent=9, swing=swing)  # jazz/pop: steadier time
