"""Generate music from a pattern: a chord progression (typed or invented) becomes a melody and voices.

* ``parse_pattern``      chord symbols (C Am7 G/B) or Roman numerals (I vi ii7 V7) -> chords per beat
* ``invent_progression`` sample a progression from a style's learned habits (with cadences)
* ``compose_melody``     write a top line that fits the chords, using the style's melodic habits
* ``generate``           all of the above -> a melody Part plus locked chords, ready to harmonize
"""

from __future__ import annotations

import math
import random
import re

from music21 import harmony, key as m21key, meter, note, roman, stream

from .music import _FIGURE_OK, chord_label
from .style import StyleModel

SOPRANO = range(60, 80)  # C4..G5


# --------------------------------------------------------------------------- parsing

def _is_roman(token: str) -> bool:
    return bool(_FIGURE_OK.match(token.replace("°", "o").replace("ø", "ø")))


def _symbol_to_chord(sym: str):
    s = sym.replace("b", "-") if len(sym) > 1 and sym[1] == "b" else sym
    s = s.replace("M7", "maj7").replace("m7b5", "m7b5")
    return harmony.ChordSymbol(s)


def guess_key(symbols: list[str]) -> m21key.Key:
    """The key that makes the most chords diatonic, preferring one that starts/ends on its tonic."""
    chords = [_symbol_to_chord(s) for s in symbols]
    best, best_score = m21key.Key("C"), -1e9
    for tonic in ["C", "G", "D", "A", "E", "B", "F#", "D-", "A-", "E-", "B-", "F"]:
        for mode in ("major", "minor"):
            k = m21key.Key(tonic if mode == "major" else tonic.lower(), mode)
            scale = {p.pitchClass for p in k.getScale().getPitches()}
            if mode == "minor":
                scale |= {(k.tonic.pitchClass + 11) % 12, (k.tonic.pitchClass + 9) % 12}
            fit = sum(all(p.pitchClass in scale for p in c.pitches) for c in chords) / len(chords)
            ends = (chords[-1].root().pitchClass == k.tonic.pitchClass) + 0.5 * (chords[0].root().pitchClass ==
                                                                                k.tonic.pitchClass)
            score = fit + 0.3 * ends
            if score > best_score:
                best, best_score = k, score
    return best


def parse_pattern(text: str, beats_per_bar: int = 4, k: m21key.Key | None = None
                  ) -> tuple[list[list[str]], m21key.Key]:
    """Bars of Roman numerals (one per beat) and the key. Bars are separated by | or new lines."""
    bars = [b.split() for b in re.split(r"[|\n]", text) if b.strip()]
    tokens = [t for b in bars for t in b]
    if not tokens:
        raise ValueError("Type a chord pattern, e.g. | C Am | F G7 | C |  or  | I vi | IV V7 | I |")
    roman_input = all(_is_roman(t) for t in tokens)
    if not roman_input:
        k = k or guess_key(tokens)
    k = k or m21key.Key("C")
    out = []
    for bar in bars:
        labels = []
        for t in bar:
            if roman_input:
                labels.append(t.replace("°", "o"))
            else:
                lab = chord_label(_symbol_to_chord(t), k)
                if lab is None:
                    raise ValueError(f"Rameau can't place the chord '{t}' in {k}.")
                labels.append(lab[0])
        per, cells = beats_per_bar // len(labels), []
        for i, lab in enumerate(labels):
            n = per if i < len(labels) - 1 else beats_per_bar - per * (len(labels) - 1)
            cells += [lab] * max(1, n)
        out.append(cells[:beats_per_bar])
    return out, k


# --------------------------------------------------------------------------- inventing

def invent_progression(style: StyleModel, mode: str = "major", bars: int = 8, beats_per_bar: int = 4,
                       phrase_bars: int = 4, seed: int | None = None) -> list[list[str]]:
    """A chord progression in the style's habits: its harmonic rhythm, favourite moves and cadences."""
    rng = random.Random(seed)
    st = style.mode(mode)
    tonic = "i" if mode == "minor" else "I"
    vocab = [c for c in st.vocab if "/" not in c or rng.random() < 0.5] or st.vocab

    def pick(weights: dict[str, float]) -> str:
        items = [(c, w) for c, w in weights.items() if w > 0]
        total = sum(w for _, w in items)
        r = rng.random() * total
        for c, w in items:
            r -= w
            if r <= 0:
                return c
        return items[-1][0]

    total_beats = bars * beats_per_bar
    phrase_len = phrase_bars * beats_per_bar
    labels = [tonic]
    for t in range(1, total_beats):
        bar_beat = t % beats_per_bar
        strong = bar_beat == 0 or (beats_per_bar == 4 and bar_beat == 2)
        phrase_pos = t % phrase_len
        last = t == total_beats - 1
        cadence_beat = phrase_pos == phrase_len - beats_per_bar  # first beat of the phrase's last bar
        prev = labels[-1]
        if last or phrase_pos > phrase_len - beats_per_bar:
            labels.append(prev)  # a cadence chord is held to the end of its bar
            continue
        if cadence_beat:
            final_phrase = t >= total_beats - beats_per_bar
            if final_phrase:
                labels.append(tonic)
            else:
                labels.append(pick({c: st.p_cadence(c) for c in vocab}))
            continue
        if t > 0 and (t + 1) % phrase_len == phrase_len - beats_per_bar:
            # the beat before a cadence: approach the cadence chord the way the style does
            nxt = tonic if t + 1 >= total_beats - beats_per_bar else None
            if nxt:
                approach = st.cadence_approach.get(nxt, {})
                if approach:
                    labels.append(pick({c: n for c, n in approach.items() if c in vocab}))
                    continue
        if rng.random() > st.p_change(strong):
            labels.append(prev)
            continue
        row = {c: st.p_transition(prev, c) for c in vocab if c != prev}
        labels.append(pick(row))
    return [labels[i:i + beats_per_bar] for i in range(0, total_beats, beats_per_bar)]


# --------------------------------------------------------------------------- melody

def compose_melody(labels: list[str], style: StyleModel, k: m21key.Key, beats_per_bar: int = 4,
                   phrase_ends: set[int] | None = None, seed: int | None = None,
                   temperature: float = 0.8) -> list[int]:
    """One melody note per beat (MIDI), sampled so it fits the chords and moves like the style's melodies."""
    rng = random.Random(seed)
    st = style.mode(k.mode)
    T = len(labels)
    phrase_ends = phrase_ends or {T - 1}
    tonic_pc = k.tonic.pitchClass
    cad_total = sum(st.cadence_melody.values())

    def local(t: int, m: int) -> float:
        deg = (m - tonic_pc) % 12
        s = math.log(st.p_emission(labels[t], deg))
        chord_pcs = {p.pitchClass for p in roman.RomanNumeral(labels[t], k).pitches}
        if m % 12 not in chord_pcs:
            s -= 2.5  # melody notes on the beat are usually chord tones
        if t in phrase_ends and cad_total:
            s += math.log((st.cadence_melody.get(str(deg), 0) + 0.5) / (cad_total + 6))
        if t == T - 1:
            s += 3.0 if deg == 0 else -3.0
        return s / temperature

    def step(a: int, b: int) -> float:
        return math.log(st.p_interval(max(-12, min(12, b - a)))) / temperature

    notes = list(SOPRANO)
    # forward pass (log-sum-exp), then sample backwards: a different melody each time
    fwd = [[local(0, m) - 0.02 * abs(m - 70) for m in notes]]
    for t in range(1, T):
        row = []
        for b in notes:
            xs = [fwd[t - 1][i] + step(a, b) for i, a in enumerate(notes)]
            mx = max(xs)
            row.append(mx + math.log(sum(math.exp(x - mx) for x in xs)) + local(t, b))
        fwd.append(row)

    def sample(weights: list[float]) -> int:
        mx = max(weights)
        ps = [math.exp(w - mx) for w in weights]
        r = rng.random() * sum(ps)
        for i, p in enumerate(ps):
            r -= p
            if r <= 0:
                return i
        return len(ps) - 1

    j = sample(fwd[-1])
    out = [notes[j]]
    for t in range(T - 2, -1, -1):
        j = sample([fwd[t][i] + step(a, out[-1]) for i, a in enumerate(notes)])
        out.append(notes[j])
    return list(reversed(out))


def melody_part(midis: list[int], k: m21key.Key, beats_per_bar: int, phrase_ends: set[int],
                title: str = "Generated") -> stream.Part:
    """A playable melody: repeated notes become longer notes; phrase endings are held."""
    from music21 import expressions

    part = stream.Part()
    part.insert(0, k)
    part.insert(0, meter.TimeSignature(f"{beats_per_bar}/4"))
    t = 0
    while t < len(midis):
        length = 1
        while (t + length < len(midis) and midis[t + length] == midis[t] and (t + length) % beats_per_bar
               and t + length - 1 not in phrase_ends):
            length += 1
        n = note.Note(midis[t], quarterLength=length)
        if t + length - 1 in phrase_ends or t in phrase_ends:
            n.expressions.append(expressions.Fermata())
        part.append(n)
        t += length
    return part.makeMeasures()


def generate(style: StyleModel, pattern_bars: list[list[str]], k: m21key.Key, beats_per_bar: int = 4,
             phrase_bars: int = 4, seed: int | None = None) -> tuple[stream.Part, dict[int, str]]:
    """A melody for the chord pattern, plus the chords as locks for the harmonizer."""
    labels = [c for bar in pattern_bars for c in bar]
    phrase_len = phrase_bars * beats_per_bar
    phrase_ends = {t for t in range(len(labels)) if (t + 1) % phrase_len == phrase_len - beats_per_bar + 1}
    phrase_ends |= {len(labels) - beats_per_bar if len(labels) >= beats_per_bar else len(labels) - 1}
    midis = compose_melody(labels, style, k, beats_per_bar, phrase_ends, seed)
    # hold the last bar's tonic
    last_bar = len(labels) - beats_per_bar
    for t in range(max(0, last_bar), len(labels)):
        midis[t] = midis[max(0, last_bar)]
    return melody_part(midis, k, beats_per_bar, phrase_ends), {t: lab for t, lab in enumerate(labels)}
