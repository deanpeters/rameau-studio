"""Shared music helpers: loading melodies, slicing music into beats, naming chords."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from music21 import chord, converter, expressions, key, meter, note, pitch, roman, stream

ABC_SUFFIXES = {".abc"}
FORMAT_BY_SUFFIX = {".abc": "abc", ".xml": "musicxml", ".musicxml": "musicxml", ".mxl": "musicxml",
                    ".mid": "midi", ".midi": "midi", ".krn": "humdrum"}


@dataclass
class Beat:
    """One beat of the melody: the unit we choose a chord for."""

    index: int
    offset: float          # quarter notes from the start
    measure: int
    beat: int              # 1-based beat within the measure
    duration: float        # length of this beat in quarter notes
    pitch: pitch.Pitch | None  # melody pitch sounding at the beat (None = rest)
    onset: bool            # True if a melody note starts exactly on this beat
    phrase_end: bool       # True if a phrase ends here (fermata, long final note, ...)

    @property
    def label(self) -> str:
        return f"m{self.measure} b{self.beat}"


def load_melody(source: str | Path, fmt: str | None = None) -> stream.Part:
    """Load a melody from a file path or from ABC/MusicXML text.

    For multi-part files the first (top) part is used; chords are reduced to their top note.
    """
    if isinstance(source, Path) or (isinstance(source, str) and "\n" not in source and Path(source).exists()):
        path = Path(source)
        fmt = fmt or FORMAT_BY_SUFFIX.get(path.suffix.lower())
        if fmt == "abc":
            score = converter.parse(_mark_abc_fermatas(path.read_text()), format="abc")
            _restore_fermatas(score)
        else:
            score = converter.parse(str(path), format=fmt)
    else:
        text = str(source)
        if fmt is None:
            fmt = "musicxml" if text.lstrip().startswith("<") else "abc"
        score = converter.parse(_mark_abc_fermatas(text) if fmt == "abc" else text, format=fmt)
        _restore_fermatas(score)

    if isinstance(score, stream.Opus):
        score = score.scores[0]
    part = score.parts[0] if hasattr(score, "parts") and score.parts else score
    part = part.makeMeasures() if not part.getElementsByClass(stream.Measure) else part

    # Reduce any chords to their top note so the melody is a single line.
    for c in list(part.recurse().getElementsByClass(chord.Chord)):
        top = note.Note(max(c.pitches), quarterLength=c.quarterLength)
        top.expressions = list(c.expressions)
        c.activeSite.replace(c, top)
    return part


_ABC_TOKEN = re.compile(r'"[^"]*"|![^!\n]*!|\+[^+\n]*\+|\[[A-Za-z]:[^\]]*\]|.', re.S)


def _mark_abc_fermatas(text: str) -> str:
    """Prepare ABC text for music21, working around two gaps in its ABC reader.

    * Fermatas (H, !fermata!) are dropped, so turn them into up-bow marks ('u') that survive
      and are turned back into fermatas by ``_restore_fermatas``.
    * Accidentals should last until the bar line (^G ... G is G# twice), but music21 forgets
      them, so repeat the accidental explicitly on later notes in the same bar.
    """
    out = []
    for line in text.splitlines():
        if re.match(r"^\s*[A-Za-z]:", line) or line.lstrip().startswith("%"):
            out.append(line)
            continue
        buf: list[str] = []
        bar_acc: dict[str, str] = {}
        pending = ""
        for tok in _ABC_TOKEN.findall(line):
            if tok in ("!fermata!", "!H!", "+fermata+", "H"):
                buf.append("u")
            elif tok in ("u", "!upbow!", "+upbow+"):
                continue  # real up-bow marks would be mistaken for fermatas
            elif tok in "^_=" and len(tok) == 1:
                pending += tok
            elif len(tok) == 1 and tok in "ABCDEFGabcdefg":
                if pending:
                    bar_acc[tok] = pending
                    buf.append(pending + tok)
                else:
                    buf.append(bar_acc.get(tok, "") + tok)
                pending = ""
            else:
                if tok == "|":
                    bar_acc = {}
                buf.append(pending + tok)
                pending = ""
        out.append("".join(buf))
    return "\n".join(out)


def _restore_fermatas(score: stream.Stream) -> None:
    for n in score.recurse().notes:
        bows = [a for a in n.articulations if type(a).__name__ == "UpBow"]
        if bows:
            n.articulations = [a for a in n.articulations if a not in bows]
            n.expressions.append(expressions.Fermata())


def _has_fermata(n: note.GeneralNote) -> bool:
    return any(isinstance(e, expressions.Fermata) for e in n.expressions)


def beat_grid(part: stream.Stream) -> list[tuple[float, int, int, float]]:
    """(offset, measure number, beat number, beat length) for every beat in the part."""
    grid = []
    ts = None
    for m in part.getElementsByClass(stream.Measure):
        ts = m.timeSignature or ts or meter.TimeSignature("4/4")
        beat_len = ts.beatDuration.quarterLength
        bar_len = ts.barDuration.quarterLength
        start = m.offset
        # Pickup bars are shorter than a full bar; their beats are the *last* beats of the bar.
        present = m.duration.quarterLength
        skip = max(0.0, bar_len - present) if m.paddingLeft or (m.number in (0, 1) and present < bar_len) else 0.0
        b = 0
        while b * beat_len < bar_len - 1e-6:
            pos = b * beat_len - skip
            if -1e-6 <= pos < present - 1e-6:
                grid.append((start + pos, m.number, b + 1, beat_len))
            b += 1
    return grid


def melody_beats(part: stream.Part) -> list[Beat]:
    flat = part.flatten().notesAndRests.stream()
    notes = list(flat)
    has_fermatas = any(_has_fermata(n) for n in notes if n.isNote)
    last_note = next((n for n in reversed(notes) if n.isNote), None)
    beats: list[Beat] = []
    for i, (off, mnum, bnum, blen) in enumerate(beat_grid(part)):
        sounding = flat.getElementAtOrBefore(off)
        p = sounding.pitch if sounding is not None and sounding.isNote else None
        onset = sounding is not None and abs(sounding.offset - off) < 1e-6
        end = False
        if sounding is not None and sounding.isNote and onset:
            if _has_fermata(sounding) or sounding is last_note:
                end = True
            elif not has_fermatas:
                # Without fermatas: a note of 2+ beats followed by a rest or a bar line ends a phrase.
                nxt = flat.getElementAfterElement(sounding)
                long_note = sounding.quarterLength >= 2 * blen
                end = long_note and (nxt is None or nxt.isRest or abs((sounding.offset + sounding.quarterLength) % 4) < 1e-6)
        beats.append(Beat(i, off, mnum, bnum, blen, p, onset, end))
    # Never treat the opening as a cadence; the last note always ends a phrase (once).
    if beats:
        if len(beats) > 1:
            beats[0].phrase_end = False
        last_onset = max((b.index for b in beats if b.onset and b.pitch is not None), default=len(beats) - 1)
        for b in beats[last_onset + 1:]:
            b.phrase_end = False
        beats[last_onset].phrase_end = True
    return beats


def detect_key(part: stream.Stream) -> key.Key:
    """Key-profile analysis, nudged toward keys whose home note ends (or starts) the melody."""
    best = part.analyze("key")
    notes = [n for n in part.flatten().notes]
    if not notes:
        return best
    first, last = notes[0].pitches[-1].pitchClass, notes[-1].pitches[-1].pitchClass
    candidates = [best] + list(best.alternateInterpretations[:5])

    def score(k: key.Key) -> float:
        t = k.tonic.pitchClass
        return (k.correlationCoefficient + (0.3 if last == t else 0.0)
                + (0.1 if first in (t, (t + 7) % 12) else 0.0))

    return max(candidates, key=score)


def degree(p: pitch.Pitch, k: key.Key) -> int:
    """Melody note as semitones above the tonic (0-11)."""
    return (p.pitchClass - k.tonic.pitchClass) % 12


DEGREE_NAMES = {0: "1", 1: "♭2", 2: "2", 3: "♭3", 4: "3", 5: "4", 6: "♯4", 7: "5", 8: "♭6", 9: "6", 10: "♭7", 11: "7"}


def chord_label(c: chord.Chord, k: key.Key) -> tuple[str, int] | None:
    """Roman-numeral label (root position, e.g. 'V7', 'V/V', 'viio7') and inversion (0-3)."""
    if not (c.isTriad() or c.isSeventh()):
        return None
    root = c.root()
    others = sorted({p.pitchClass for p in c.pitches if p.pitchClass != root.pitchClass})
    pitches = [pitch.Pitch(root.name + "3")]
    for p in c.pitches:
        if p.pitchClass in others and all(q.pitchClass != p.pitchClass for q in pitches):
            pitches.append(pitch.Pitch(p.name + "4"))
    rp = chord.Chord(pitches)
    pcs = {p.pitchClass for p in rp.pitches}
    if pcs <= _key_pitch_classes(k):
        figure = roman.romanNumeralFromChord(rp, k).figure
    elif root.pitchClass == k.tonic.pitchClass and len(pcs) == 3:
        # A chromatic chord on the home note (e.g. A major in A minor, the "Picardy third")
        # is a coloured home chord, not the dominant of iv.
        figure = roman.romanNumeralFromChord(rp, k).figure
    else:
        # Chromatic chord: name it as a secondary dominant if that explains it (e.g. D7 in C = V7/V).
        figure = roman.romanNumeralFromChord(rp, k, preferSecondaryDominants=True).figure
    figure = _canonical(figure.replace("/o7", "ø7"), pcs, k)
    if figure is None or not _FIGURE_OK.match(figure):
        return None
    try:
        inv = c.inversion()
    except Exception:
        inv = 0
    return figure, int(inv) if inv in (0, 1, 2, 3) else 0


_NUMERAL = r"(?:vii|iii|vi|iv|ii|v|i|VII|III|VI|IV|II|V|I)"
_FIGURE_OK = re.compile(rf"^[b#-]?{_NUMERAL}(?:o|ø|\+)?7?(?:/[b#-]?{_NUMERAL})?$")


def _canonical(figure: str, pcs: set[int], k: key.Key) -> str | None:
    """Return a spelling of ``figure`` that music21 reads back as the same chord.

    romanNumeralFromChord writes e.g. 'bVII' in minor keys, but RomanNumeral() reads 'bVII' as a
    lowered subtonic (Db in E minor). Prefer the plain form ('VII') when that round-trips.
    """
    candidates = [figure]
    if figure[:1] in "b#-":
        candidates.insert(0, figure[1:])
    for f in candidates:
        try:
            if {p.pitchClass for p in roman.RomanNumeral(f, k).pitches} == pcs:
                return f
        except Exception:
            continue
    return None


def _key_pitch_classes(k: key.Key) -> set[int]:
    """Diatonic notes of the key; minor keys also include the raised 6th and 7th."""
    pcs = {p.pitchClass for p in k.getScale().getPitches()}
    if k.mode == "minor":
        t = k.tonic.pitchClass
        pcs |= {(t + 9) % 12, (t + 11) % 12}
    return pcs


def chord_pitches(label: str, k: key.Key) -> list[pitch.Pitch]:
    return list(roman.RomanNumeral(label, k).pitches)


FUNCTION_OF_DEGREE = {
    "I": "tonic (home)", "i": "tonic (home)",
    "vi": "tonic substitute", "VI": "tonic substitute", "iii": "tonic/dominant colour", "III": "relative major",
    "IV": "predominant (moving away)", "iv": "predominant (moving away)",
    "ii": "predominant (moving away)", "iio": "predominant (moving away)", "ii/o": "predominant (moving away)",
    "V": "dominant (tension)", "v": "dominant (weak tension)", "vii": "dominant (tension)",
    "VII": "subtonic",
}


def chord_function(label: str) -> str:
    if "/" in label and not label.startswith("ii/o"):
        target = label.split("/", 1)[1]
        return f"secondary dominant (points to {target})"
    base = label
    for suffix in ("o7", "/o7", "ø7", "7", "65", "43", "42", "6", "o"):
        if base.endswith(suffix) and len(base) > len(suffix):
            base = base[: -len(suffix)]
            break
    base = base.lstrip("#b-")
    return FUNCTION_OF_DEGREE.get(base, FUNCTION_OF_DEGREE.get(base.rstrip("o"), "colour chord"))
