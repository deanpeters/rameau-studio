"""Build a score from a harmonization and export it (MusicXML, MIDI, SVG notation, explanation)."""

from __future__ import annotations

import copy
from pathlib import Path

from music21 import clef, harmony, instrument, layout, metadata, note, stream, tempo

from .harmonize import Harmonization, chord_symbol
from .voicing import Realization

PART_INFO = [
    ("Soprano", clef.TrebleClef),
    ("Alto", clef.TrebleClef),
    ("Tenor", clef.Treble8vbClef),
    ("Bass", clef.BassClef),
]


def _voice_part(melody: stream.Part, h: Harmonization, r: Realization, voice: int, name: str, clef_cls) -> stream.Part:
    """A part with one note per beat, laid out on the melody's measures; repeated notes are merged."""
    part = stream.Part(id=name)
    part.partName = name
    beats_by_measure: dict[int, list[int]] = {}
    for t, c in enumerate(h.choices):
        beats_by_measure.setdefault(c.beat.measure, []).append(t)

    first = True
    for m in melody.getElementsByClass(stream.Measure):
        nm = stream.Measure(number=m.number)
        nm.paddingLeft = m.paddingLeft
        if first:
            nm.insert(0, clef_cls())
            if m.keySignature:
                nm.insert(0, copy.deepcopy(m.keySignature))
            ts = m.timeSignature or melody.recurse().getElementsByClass("TimeSignature").first()
            if ts:
                nm.insert(0, copy.deepcopy(ts))
            first = False
        else:
            if m.keySignature:
                nm.insert(0, copy.deepcopy(m.keySignature))
            if m.timeSignature:
                nm.insert(0, copy.deepcopy(m.timeSignature))
        prev_n = None
        for t in beats_by_measure.get(m.number, []):
            c = h.choices[t]
            midi = r.voicings[t][voice]
            pos = c.beat.offset - m.offset
            if prev_n is not None and prev_n.pitch.midi == midi and h.choices[t].label == h.choices[t - 1].label:
                prev_n.quarterLength += c.beat.duration
                continue
            n = note.Note(midi, quarterLength=c.beat.duration)
            nm.insert(pos, n)
            prev_n = n
            if voice == 3:
                n.addLyric(c.label)
        part.append(nm)
    return part


def build_score(melody: stream.Part, h: Harmonization, r: Realization, title: str = "Untitled") -> stream.Score:
    score = stream.Score()
    score.metadata = metadata.Metadata()
    score.metadata.title = title
    score.metadata.composer = f"Harmonized by Rameau in {h.style.title} style"

    sop = copy.deepcopy(melody)
    sop.id = "Soprano"
    sop.partName = "Soprano"
    if r.soprano_shift:
        sop.transpose(r.soprano_shift, inPlace=True)
    for el in list(sop.recurse().getElementsByClass((harmony.ChordSymbol, instrument.Instrument))):
        el.activeSite.remove(el)
    # Chord symbols above the melody, at each chord change.
    measures = {m.number: m for m in sop.getElementsByClass(stream.Measure)}
    prev = None
    for t, c in enumerate(h.choices):
        if c.label == prev:
            continue
        prev = c.label
        m = measures.get(c.beat.measure)
        if m is None:
            continue
        sym = chord_symbol(c.label, h.key, r.inversions[t])
        try:
            cs = harmony.ChordSymbol(sym.replace("b", "-") if len(sym) > 1 and sym[1] == "b" else sym)
            cs.writeAsChord = False
            m.insert(c.beat.offset - m.offset, cs)
        except Exception:
            pass

    parts = [sop] + [_voice_part(melody, h, r, i, name, cl) for i, (name, cl) in enumerate(PART_INFO) if i > 0]
    for p, inst in zip(parts, (instrument.Soprano(), instrument.Alto(), instrument.Tenor(), instrument.Bass())):
        p.insert(0, inst)
        score.insert(0, p)
    score.insert(0, layout.StaffGroup(parts, symbol="bracket"))
    return score


def add_tempo(score: stream.Score, bpm: int) -> None:
    first = score.parts[0].getElementsByClass(stream.Measure).first()
    if first is not None:
        for old in first.getElementsByClass(tempo.MetronomeMark):
            first.remove(old)
        first.insert(0, tempo.MetronomeMark(number=bpm))


def write_midi(score: stream.Score, path: Path, bpm: int = 72, program: int | None = 19) -> Path:
    """Write MIDI. ``program`` sets a General MIDI instrument for every part (19 = church organ)."""
    s = copy.deepcopy(score)
    add_tempo(s, bpm)
    if program is not None:
        for p in s.parts:
            for inst in list(p.recurse().getElementsByClass(instrument.Instrument)):
                inst.activeSite.remove(inst)
            organ = instrument.Instrument()
            organ.midiProgram = program
            p.insert(0, organ)
    s.write("midi", fp=str(path))
    return path


def write_musicxml(score: stream.Score, path: Path) -> Path:
    score.write("musicxml", fp=str(path))
    return path


def to_svg_pages(score: stream.Score, width: int = 2100, scale: int = 40) -> list[str]:
    """Render notation with Verovio. Returns one SVG string per page."""
    import tempfile

    import verovio

    with tempfile.TemporaryDirectory() as d:
        xml = Path(d) / "score.musicxml"
        score.write("musicxml", fp=str(xml))
        tk = verovio.toolkit()
        tk.setOptions({"pageWidth": width, "scale": scale, "adjustPageHeight": True, "footer": "none",
                       "header": "auto", "breaks": "auto", "lyricSize": 3.5})
        tk.loadData(xml.read_text())
        return [tk.renderToSVG(i) for i in range(1, tk.getPageCount() + 1)]


def explanation_markdown(h: Harmonization, r: Realization, title: str) -> str:
    lines = [f"# {title}: harmonized in {h.style.title} style", ""]
    lines += [f"- {n}" for n in h.notes]
    errors = [f for f in r.findings if f.severity == "error"]
    warnings = [f for f in r.findings if f.severity == "warning"]
    lines += [f"- Voice-leading check: {len(errors)} rule breaks, {len(warnings)} style warnings", ""]
    lines += ["| Where | Melody | Chord | Numeral | Function | Confidence | Alternatives |",
              "|---|---|---|---|---|---|---|"]
    prev = None
    for t, c in enumerate(h.choices):
        if c.label == prev and not c.beat.phrase_end:
            continue
        prev = c.label
        mel = c.beat.pitch.name.replace("-", "b") if c.beat.pitch is not None else "rest"
        alts = ", ".join(f"{a.symbol} ({a.label}) {a.probability:.0%}" for a in c.alternatives)
        cad = " **cadence**" if c.cadence else ""
        lines.append(f"| {c.beat.label} | {mel} | {chord_symbol(c.label, h.key, r.inversions[t])} | {c.label}{cad} | "
                     f"{c.function} | {c.confidence:.0%} | {alts} |")
    lines += ["", "## Why each chord", ""]
    prev = None
    for t, c in enumerate(h.choices):
        if c.label == prev and not c.beat.phrase_end:
            continue
        prev = c.label
        lines.append(f"**{c.beat.label}: {c.symbol} ({c.label})**, {c.function}" + (f"; {c.cadence}" if c.cadence else ""))
        lines += [f"- {reason}" for reason in c.reasons]
        lines.append("")
    if r.findings:
        lines += ["## Voice-leading notes", ""] + [f"- {f}" for f in r.findings]
    return "\n".join(lines)
