"""Era textures: how the voices *move* between the chords.

Chord choice is only half of a style's signature sound. The other half is texture: Bach's
inner voices flow in passing eighth notes; Palestrina's voices hold common tones and sigh into
suspensions at cadences; Classical accompaniment pulses in repeated notes under the tune.

``apply_texture`` turns the block chord on each beat into per-voice note events. The soprano is
always the melody and is left untouched.
"""

from __future__ import annotations

from dataclasses import dataclass

from music21 import roman

from .harmonize import Harmonization
from .voicing import Realization


@dataclass
class Event:
    rel: float       # offset within the beat (quarter notes)
    dur: float
    midi: int
    hold: bool       # may merge with the previous note if it has the same pitch


@dataclass(frozen=True)
class Texture:
    key: str
    name: str
    description: str
    passing: int = 0           # max passing notes per beat (lower voices)
    suspensions: bool = False  # 4-3 suspensions at cadences
    hold_common: bool = False  # hold a common tone even when the chord changes
    pulse: int = 1             # notes per beat in alto/tenor (2 = repeated eighths)
    hold_bass: bool = False    # sustain the bass while its note stays the same (continuo)


TEXTURES = {t.key: t for t in [
    Texture("block", "Block chords", "One chord per beat in all voices: the plainest texture, good for study."),
    Texture("chorale", "Bach chorale", "Inner voices and bass fill leaps of a third with passing notes, and "
            "cadences often 'sigh' with a 4-3 suspension.", passing=1, suspensions=True),
    Texture("polyphony", "Renaissance polyphony", "Voices hold common tones across chord changes, move smoothly "
            "and prepare dissonant suspensions at cadences.", passing=1, suspensions=True, hold_common=True),
    Texture("continuo", "Early Baroque continuo", "A sustained bass line under the voices, with suspensions at "
            "cadences.", suspensions=True, hold_bass=True, hold_common=True),
    Texture("romantic", "Romantic accompaniment", "A singing melody over flowing inner voices and a sustained "
            "bass, with passing notes for colour.", passing=1, pulse=2, hold_bass=True),
    Texture("classical", "Classical accompaniment", "Melody on top; the middle voices pulse in repeated eighth "
            "notes over a bass that marks each chord change.", pulse=2),
]}

STYLE_TEXTURE = {"bach_chorale": "chorale", "palestrina": "polyphony", "monteverdi": "continuo",
                 "classical": "classical", "romantic": "romantic"}


def texture_for(style_name: str) -> Texture:
    return TEXTURES[STYLE_TEXTURE.get(style_name, "block")]


def _scale_pcs(k) -> set[int]:
    pcs = {p.pitchClass for p in k.getScale().getPitches()}
    if k.mode == "minor":
        pcs.add((k.tonic.pitchClass + 11) % 12)
    return pcs


def _passing_note(a: int, b: int, scale: set[int]) -> int | None:
    """A scale note strictly between a and b (they must be a third apart)."""
    if not 3 <= abs(b - a) <= 4:
        return None
    step = 1 if b > a else -1
    mids = [n for n in range(a + step, b, step) if n % 12 in scale]
    return mids[len(mids) // 2] if mids else None


VOICE_KEYS = {1: "alto", 2: "tenor", 3: "bass"}
LEARNED_TEXTURES = {"chorale", "polyphony", "continuo", "romantic"}
MAX_ORNAMENTS_PER_BEAT = 2


def _diatonic_step(a: int, direction: int, scale: set[int]) -> int | None:
    for d in (1, 2):
        x = a + direction * d
        if x % 12 in scale:
            return x
    return None


def _learned_ornaments(h: Harmonization, r: Realization, ev, scale: set[int], seed: int) -> bool:
    """Ornament the lower voices at the rates the style's own corpus uses them. Returns False when the
    style has no ornament data (e.g. styles learned from chord charts)."""
    import random

    stats = h.style.mode(h.key.mode)
    if not any(stats.p_ornament(v, "passing") is not None for v in VOICE_KEYS.values()):
        return False
    rng = random.Random(seed)
    V = r.voicings
    T = len(V)
    for t in range(T - 1):
        b = h.choices[t].beat
        if b.duration < 1 or b.phrase_end:
            continue
        used = 0
        changing = h.choices[t + 1].label != h.choices[t].label
        for v in rng.sample([3, 2, 1], 3):  # no fixed voice always gets first pick
            if used >= MAX_ORNAMENTS_PER_BEAT or len(ev[v][t]) != 1:
                continue
            name = VOICE_KEYS[v]
            a, n = V[t][v], V[t + 1][v]
            chord_pcs = {p.pitchClass for p in roman.RomanNumeral(h.choices[t].label, h.key).pitches}
            options = []  # (probability, kind, second-half note)
            mid = _passing_note(a, n, scale)
            if mid is not None:
                options.append((stats.p_ornament(name, "passing"), "passing", mid))
            if a == n:
                step = _diatonic_step(a, -1 if rng.random() < 0.6 else 1, scale)
                if step is not None:
                    options.append((stats.p_ornament(name, "neighbor"), "neighbor", step))
            if a != n:
                options.append((stats.p_ornament(name, "anticipation"), "anticipation", n))
            arps = [x for x in range(a - 7, a + 8) if x % 12 in chord_pcs and x not in (a, n) and abs(x - a) > 2]
            if arps:
                options.append((stats.p_ornament(name, "arpeggio"), "arpeggio", rng.choice(arps)))
            for p, kind, x in options:
                if p is None or rng.random() >= p or _parallel_risk(V, t, v, x):
                    continue
                d = ev[v][t][0].dur / 2
                ev[v][t] = [Event(0.0, d, a, ev[v][t][0].hold), Event(d, d, x, False)]
                used += 1
                break
        # Suspensions: hold the previous note into a changing chord, then resolve down by step.
        if t > 0 and h.choices[t].label != h.choices[t - 1].label:
            for v in (1, 2, 3):
                if len(ev[v][t]) != 1:
                    continue
                prev, cur = V[t - 1][v], V[t][v]
                p = stats.p_ornament(VOICE_KEYS[v], "suspension")
                if p and prev - cur in (1, 2) and rng.random() < p:
                    d = ev[v][t][0].dur / 2
                    ev[v][t] = [Event(0.0, d, prev, True), Event(d, d, cur, False)]
                    break
    return True


def apply_texture(h: Harmonization, r: Realization, texture: Texture, seed: int = 1) -> list[list[list[Event]]]:
    """events[voice][beat] -> notes for voices 1..3 (alto, tenor, bass). Index 0 (soprano) is empty."""
    T = len(h.choices)
    scale = _scale_pcs(h.key)
    V = r.voicings
    ev: list[list[list[Event]]] = [[[] for _ in range(T)] for _ in range(4)]

    for t in range(T):
        dur = h.choices[t].beat.duration
        same_chord = t > 0 and h.choices[t].label == h.choices[t - 1].label
        for v in (1, 2, 3):
            hold = same_chord or texture.hold_common or (v == 3 and texture.hold_bass)
            if texture.pulse > 1 and v in (1, 2):
                n = texture.pulse
                ev[v][t] = [Event(i * dur / n, dur / n, V[t][v], False) for i in range(n)]
            else:
                ev[v][t] = [Event(0.0, dur, V[t][v], hold)]

    # Ornaments learned from the style's corpus (passing, neighbor, anticipation, arpeggio, suspension),
    # used at the corpus's own rates. Fall back to the simple rule-based passing notes otherwise.
    learned = texture.key in LEARNED_TEXTURES and _learned_ornaments(h, r, ev, scale, seed)
    if texture.passing and not learned:
        for t in range(T - 1):
            if h.choices[t].beat.duration < 1 or h.choices[t + 1].beat.phrase_end and texture.suspensions:
                continue
            used = 0
            for v in (3, 2, 1):
                if used >= texture.passing or len(ev[v][t]) != 1:
                    continue
                mid = _passing_note(V[t][v], V[t + 1][v], scale)
                if mid is None or _parallel_risk(V, t, v, mid):
                    continue
                d = ev[v][t][0].dur / 2
                ev[v][t] = [Event(0.0, d, V[t][v], ev[v][t][0].hold), Event(d, d, mid, False)]
                used += 1

    # Cadential 4-3 suspension: the note above the leading tone is held into the dominant chord,
    # then resolves down a step.
    if texture.suspensions:
        k = h.key
        for t in range(2, T):
            c = h.choices[t]
            if not c.beat.phrase_end or h.choices[t - 1].label not in ("V", "V7"):
                continue
            lt = roman.RomanNumeral(h.choices[t - 1].label, k).third.pitchClass
            for v in (1, 2):
                if V[t - 1][v] % 12 == lt and V[t - 2][v] - V[t - 1][v] in (1, 2) and len(ev[v][t - 1]) == 1:
                    d = ev[v][t - 1][0].dur / 2
                    ev[v][t - 1] = [Event(0.0, d, V[t - 2][v], True), Event(d, d, V[t - 1][v], False)]
                    if ev[v][t - 2] and ev[v][t - 2][-1].midi != V[t - 2][v]:
                        ev[v][t - 2][-1] = Event(ev[v][t - 2][-1].rel, ev[v][t - 2][-1].dur, V[t - 2][v],
                                                 ev[v][t - 2][-1].hold)
                    break
    return ev


def _parallel_risk(V, t: int, v: int, mid: int) -> bool:
    """Would a passing note at the half-beat form parallel fifths/octaves with the next beat?"""
    for w in range(4):
        if w == v:
            continue
        a1, b1 = mid, V[t][w]
        a2, b2 = V[t + 1][v], V[t + 1][w]
        if a1 == a2 or b1 == b2:
            continue
        if abs(a1 - b1) % 12 in (0, 7) and abs(a2 - b2) % 12 == abs(a1 - b1) % 12:
            return True
    return False
