"""Jazz and popular-music accompaniment: a real bass line and rhythmic chord "comping".

Four-part hymn writing is the wrong texture for a jazz standard or a pop song. Musicians in these
styles split the job differently:

* the **bass** plays a line: a walking line in swing, root-and-fifth in a two-beat or bossa nova,
  driving roots in rock, boom-chick in country;
* the **keyboard** "comps": short, rhythmic chord stabs (the Charleston rhythm in swing, syncopated
  hits in bossa nova, steady chords in pop), voiced like a pianist, with the 3rd and 7th at the core,
  colour tones (9ths, 13ths) on top, and each chord moving as little as possible from the last;
* the **melody** stays on top, untouched.

``comp(h, melody, style_name, seed)`` returns a score with Melody, Piano and Bass parts.
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass

from music21 import chord as m21chord
from music21 import clef, instrument, layout, metadata, note, roman, stream

FAMILIES = {
    "jazz_standards": "swing", "blues": "swing", "dixieland": "dixie", "jazz_ballad": "ballad",
    "bossa_latin": "bossa", "pop_rock": "pop", "country": "country",
}
SWING_FAMILIES = {"swing", "dixie", "ballad"}

# Comping rhythms: (start beat within the bar, length in beats). Two bars alternate for variety.
COMP = {
    "swing": [[(0, 0.5), (1.5, 1.0)], [(1.0, 0.5), (2.5, 1.0)]],       # Charleston and its variant
    "dixie": [[(0, 0.5), (1, 0.5), (2, 0.5), (3, 0.5)]] * 2,          # four to the bar
    "ballad": [[(0, 2.0), (2, 2.0)], [(0, 4.0)]],                      # sustained
    "bossa": [[(0, 1.0), (1.5, 0.5), (2.5, 1.0)], [(0.5, 0.5), (1.5, 1.0), (3, 0.5)]],
    "pop": [[(0, 1.0), (1, 1.0), (2, 1.0), (3, 1.0)]] * 2,
    "country": [[(1, 0.5), (3, 0.5)]] * 2,                             # the "chick" on 2 and 4
}
WALTZ_COMP = [[(1, 0.75), (2, 0.75)]] * 2


@dataclass
class ChordShape:
    root: int                 # pitch class
    tones: list[int]          # intervals above the root for the voicing (3rd and 7th first)
    fifth: int                # interval of the fifth (for the bass)


def _shape(label: str, k, extended: bool) -> ChordShape:
    rn = roman.RomanNumeral(label, k)
    root = rn.root().pitchClass
    ints = sorted({(p.pitchClass - root) % 12 for p in rn.pitches})
    third = next((i for i in ints if i in (3, 4)), 4)
    fifth = next((i for i in ints if i in (6, 7, 8)), 7)
    seventh = next((i for i in ints if i in (9, 10, 11)), None)
    if seventh is None:                       # triad: pianists add a 6th or 9th in jazz, keep it plain in pop
        tones = [third, fifth, 0] + ([14] if extended else [])
    elif third == 4 and seventh == 10:        # dominant: 3, 7, 9, 13
        tones = [third, seventh] + ([14, 21] if extended else [fifth])
    elif third == 4 and seventh == 11:        # major 7th: 3, 7, 9, (5)
        tones = [third, seventh, fifth] + ([14] if extended else [])
    elif third == 3 and fifth == 6:           # half-diminished / diminished
        tones = [third, fifth, seventh]
    else:                                     # minor 7th: b3, b7, 9, (5)
        tones = [third, seventh, fifth] + ([14] if extended else [])
    return ChordShape(root, tones, fifth)


def _voice(shape: ChordShape, previous: list[int] | None, ceiling: int) -> list[int]:
    """Place the chord's tones in the piano's middle register, as close as possible to the last chord."""
    centre = sum(previous) / len(previous) if previous else 60
    notes = []
    for iv in shape.tones:
        pc = (shape.root + iv) % 12
        options = [pc + 12 * o for o in range(3, 7)]
        pick = min(options, key=lambda m: abs(m - centre))
        while pick > ceiling and pick - 12 >= 48:
            pick -= 12
        notes.append(pick)
    notes = sorted(set(notes))
    while notes and notes[-1] - notes[0] > 16:   # keep the hand together
        notes[-1] -= 12
        notes = sorted(set(notes))
    return [n for n in notes if 48 <= n <= 79] or notes


def _bass_note(pc: int, previous: int | None, low: int = 36, high: int = 55) -> int:
    options = [pc + 12 * o for o in range(2, 5) if low <= pc + 12 * o <= high]
    if not options:
        options = [pc + 36]
    target = previous if previous is not None else 43
    return min(options, key=lambda m: abs(m - target))


def comp(h, melody, style_name: str, seed: int = 1, extended_share: float = 0.0) -> stream.Score:
    rng = random.Random(seed)
    family = FAMILIES.get(style_name, "pop")
    k = h.key
    choices = h.choices
    ts = melody.recurse().getElementsByClass("TimeSignature").first()
    beats_per_bar = ts.beatCount if ts else 4
    p_extend = min(0.9, extended_share * 3 + (0.5 if family in ("swing", "ballad", "bossa") else 0.0))

    # chord at every beat, and shapes (with colour tones chosen once per chord change)
    shapes, last_label, current = [], None, None
    for c in choices:
        if c.label != last_label:
            current = _shape(c.label, k, rng.random() < p_extend)
            last_label = c.label
        shapes.append(current)
    starts = [t == 0 or choices[t].label != choices[t - 1].label for t in range(len(choices))]

    def chord_at(offset: float) -> int:
        best = 0
        for t, c in enumerate(choices):
            if c.beat.offset <= offset + 1e-6:
                best = t
        return best

    # ---------------- bass line
    bass_events = []
    prev = None
    for t, c in enumerate(choices):
        b = c.beat
        sh = shapes[t]
        nxt_start = t + 1 < len(choices) and starts[t + 1]
        nxt_root = shapes[t + 1].root if t + 1 < len(choices) else sh.root
        pos = b.beat - 1
        if beats_per_bar == 3:                                    # waltz: root on 1 only
            if pos == 0:
                prev = _bass_note(sh.root, prev)
                bass_events.append((b.offset, b.duration * 3, prev))
            continue
        if family == "swing":                                     # walking quarter notes
            if starts[t] or pos == 0:
                n = _bass_note(sh.root, prev)
            elif nxt_start or pos == beats_per_bar - 1:
                target = _bass_note(nxt_root, prev)
                n = target + (1 if (prev or target) > target else -1)  # chromatic approach
            else:
                tones = [(sh.root + i) % 12 for i in (sh.tones[0], sh.fifth, 0)]
                cands = [_bass_note(pc, prev) for pc in tones]
                n = min((x for x in cands if x != prev), key=lambda x: abs(x - (prev or x)), default=cands[0])
            bass_events.append((b.offset, b.duration, n))
            prev = n
        elif family in ("dixie", "ballad", "country"):            # root on 1, fifth on 3
            if pos in (0, 2):
                pc = sh.root if (pos == 0 or starts[t]) else (sh.root + sh.fifth) % 12
                prev = _bass_note(pc, prev)
                bass_events.append((b.offset, 1.0 if family == "country" else 2.0, prev))
        elif family == "bossa":                                   # dotted root, then fifth
            if pos in (0, 2):
                root = _bass_note(sh.root, prev)
                fifth = _bass_note((sh.root + sh.fifth) % 12, root)
                bass_events += [(b.offset, 1.5, root), (b.offset + 1.5, 0.5, fifth)]
                prev = fifth
        else:                                                     # pop/rock: driving eighths on the root
            prev = _bass_note(sh.root, prev)
            bass_events += [(b.offset, 0.5, prev), (b.offset + 0.5, 0.5, prev)]

    # ---------------- comping
    comp_events = []
    measures = list(melody.getElementsByClass(stream.Measure))
    pattern = WALTZ_COMP if beats_per_bar == 3 else COMP[family]
    voicing = None
    sop = melody.flatten().getElementsByClass(note.Note).stream()  # not chord symbols
    for bar_index, m in enumerate(measures):
        for start, length in pattern[bar_index % len(pattern)]:
            off = m.offset + start - (max(0.0, m.barDuration.quarterLength - m.duration.quarterLength)
                                      if bar_index == 0 else 0.0)
            if off < m.offset - 1e-6 or off >= m.offset + m.duration.quarterLength - 1e-6:
                continue
            t = chord_at(off)
            mel = sop.getElementAtOrBefore(off)
            ceiling = (mel.pitches[-1].midi - 2) if mel is not None else 72
            voicing = _voice(shapes[t], voicing, ceiling)
            comp_events.append((off, length, voicing))

    return _score(melody, h, comp_events, bass_events, family)


def _score(melody, h, comp_events, bass_events, family) -> stream.Score:
    score = stream.Score()
    score.metadata = metadata.Metadata(title=h.style.title)
    mel = copy.deepcopy(melody)
    mel.partName = "Melody"
    for el in list(mel.recurse().getElementsByClass(instrument.Instrument)):
        el.activeSite.remove(el)

    from .render import spell

    def pitches_for(midis):
        return [spell(m, h.key) for m in (midis if isinstance(midis, (list, tuple)) else [midis])]

    def build(events, name, clef_cls, as_chord):
        part = stream.Part(id=name)
        part.partName = name
        first = True
        for m in melody.getElementsByClass(stream.Measure):
            nm = stream.Measure(number=m.number)
            nm.paddingLeft = m.paddingLeft
            if first:
                nm.insert(0, clef_cls())
                if m.keySignature:
                    nm.insert(0, copy.deepcopy(m.keySignature))
                tsig = m.timeSignature or melody.recurse().getElementsByClass("TimeSignature").first()
                if tsig:
                    nm.insert(0, copy.deepcopy(tsig))
                first = False
            end = m.offset + m.duration.quarterLength
            for off, length, pitches in events:
                if m.offset - 1e-6 <= off < end - 1e-6:
                    length = min(length, end - off)
                    spelled = pitches_for(pitches)
                    el = m21chord.Chord(spelled, quarterLength=length) if as_chord else note.Note(spelled[0],
                                                                                               quarterLength=length)
                    nm.insert(off - m.offset, el)
            nm.makeRests(fillGaps=True, inPlace=True, timeRangeFromBarDuration=True)
            part.append(nm)
        return part

    piano = build(comp_events, "Piano", clef.TrebleClef, True)
    bass = build(bass_events, "Bass", clef.BassClef, False)
    for p in (mel, piano, bass):
        score.insert(0, p)
    score.insert(0, layout.StaffGroup([mel, piano, bass], symbol="bracket"))
    return score
