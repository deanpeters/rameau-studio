"""Learn a style model from a corpus of four-part harmonizations.

The built-in Bach model is trained on the 371 Bach chorales that ship with music21:

    uv run python -m rameau.train bach_chorale
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import Callable, Iterable

from music21 import chord, corpus, key, stream

from .music import beats_per_bar, chord_label, degree, melody_beats, piece_key
from .style import MODES, ModeStats, StyleModel

MIN_CHORD_COUNT = 12  # rarer chords are dropped from the vocabulary


def _blank():
    return {
        "chord_counts": defaultdict(int),
        "start": defaultdict(int),
        "transitions": defaultdict(lambda: defaultdict(int)),
        "emissions": defaultdict(lambda: defaultdict(int)),
        "cadences": defaultdict(int),
        "cadence_approach": defaultdict(lambda: defaultdict(int)),
        "inversions": defaultdict(lambda: defaultdict(int)),
        "rhythm": {"strong": [0, 0], "weak": [0, 0]},
        "melody_intervals": defaultdict(int),
        "cadence_melody": defaultdict(int),
        "modulations": defaultdict(int),
        "phrases": 0,
        "activity": [0.0, 0.0],
        "modes": defaultdict(int),
    }


def _key_for(k):
    return k.mode if k.mode in MODES else "major"


def _local_key(score_notes: stream.Stream, home: key.Key, start: float, end: float) -> key.Key:
    """Key of one phrase, if it clearly moved to a closely related key; otherwise the home key."""
    seg = score_notes.getElementsByOffset(start, end, includeEndBoundary=False, mustBeginInSpan=False).stream()
    if len(seg) < 8:
        return home
    try:
        lk = seg.analyze("key")
    except Exception:
        return home
    if lk.tonic.pitchClass == home.tonic.pitchClass and lk.mode == home.mode:
        return home
    home_fit = next((a.correlationCoefficient for a in [lk] + list(lk.alternateInterpretations)
                     if a.tonic.pitchClass == home.tonic.pitchClass and a.mode == home.mode), -1.0)
    closely_related = abs(lk.sharps - home.sharps) <= 1
    return lk if closely_related and lk.correlationCoefficient - home_fit >= 0.15 else home


def _relation(local: key.Key, home: key.Key) -> str:
    """Name a local key relative to the home key, e.g. 'V' (the dominant) or 'vi' (relative minor)."""
    if local is home:
        return "home"
    tonic = chord.Chord([local.tonic, local.tonic.transpose("M3" if local.mode == "major" else "m3"),
                         local.tonic.transpose("P5")])
    lab = chord_label(tonic, home)
    return lab[0] if lab else "other"


def count_score(score: stream.Score, acc: dict) -> bool:
    """Add one harmonized score's statistics into ``acc`` (keyed by mode). Returns False if skipped."""
    if len(score.parts) < 3:
        return False
    home, mode_name = piece_key(score)
    soprano = score.parts[0]
    chords = score.chordify().flatten().getElementsByClass(chord.Chord).stream()
    notes = score.flatten().notes.stream()
    beats = melody_beats(soprano)
    if not beats:
        return False

    # Split into phrases and find each phrase's local key (modulation tracking).
    segments, a = [], 0
    for b in beats:
        if b.phrase_end:
            segments.append((a, b.index))
            a = b.index + 1
    if a < len(beats):
        segments.append((a, len(beats) - 1))
    key_of = {}
    for a, z in segments:
        lk = _local_key(notes, home, beats[a].offset, beats[z].offset + beats[z].duration) if z - a >= 5 else home
        rel = _relation(lk, home)
        acc[_key_for(home)]["modulations"][rel] += 1
        acc[_key_for(home)]["phrases"] += 1
        for i in range(a, z + 1):
            key_of[i] = lk

    g = acc[_key_for(home)]
    g["modes"][mode_name] += 1
    g["activity"][0] += sum(len(p.flatten().notes) for p in score.parts)
    g["activity"][1] += len(beats) * len(score.parts)

    prev, prev_key, first, prev_pitch = None, None, True, None
    for b in beats:
        k = key_of.get(b.index, home)
        stats = acc[_key_for(k)]
        if k is not prev_key:
            prev = None
        prev_key = k
        if b.pitch is not None and b.onset:
            if prev_pitch is not None:
                step = max(-12, min(12, b.pitch.midi - prev_pitch))
                g["melody_intervals"][str(step)] += 1
            prev_pitch = b.pitch.midi
        c = chords.getElementAtOrBefore(b.offset)
        lab = chord_label(c, k) if c is not None else None
        if lab is None or b.pitch is None:
            prev = None
            continue
        label, inv = lab
        stats["chord_counts"][label] += 1
        stats["emissions"][label][str(degree(b.pitch, k))] += 1
        stats["inversions"][label][str(inv)] += 1
        if first:
            stats["start"][label] += 1
            first = False
        if prev is not None:
            stats["transitions"][prev][label] += 1
            strong = b.beat == 1 or (beats_per_bar(soprano, b.offset) == 4 and b.beat == 3)
            slot = stats["rhythm"]["strong" if strong else "weak"]
            slot[1] += 1
            slot[0] += int(label != prev)
        if b.phrase_end:
            stats["cadences"][label] += 1
            stats["cadence_melody"][str(degree(b.pitch, k))] += 1
            if prev is not None:
                stats["cadence_approach"][label][prev] += 1
        prev = label
    return True


def _finish(raw: dict) -> ModeStats:
    keep = {c for c, n in raw["chord_counts"].items() if n >= MIN_CHORD_COUNT}

    def plain(d):
        return {k: (plain(v) if isinstance(v, dict) else v) for k, v in d.items()}

    def filt1(d):
        return {k: v for k, v in d.items() if k in keep}

    def filt2(d):
        return {k: filt1(v) for k, v in d.items() if k in keep}

    vocab = sorted(keep, key=lambda c: -raw["chord_counts"][c])
    return ModeStats(
        vocab=vocab,
        chord_counts=filt1(plain(raw["chord_counts"])),
        start=filt1(plain(raw["start"])),
        transitions=filt2(plain(raw["transitions"])),
        emissions={k: v for k, v in plain(raw["emissions"]).items() if k in keep},
        cadences=filt1(plain(raw["cadences"])),
        cadence_approach=filt2(plain(raw["cadence_approach"])),
        inversions={k: v for k, v in plain(raw["inversions"]).items() if k in keep},
        rhythm=raw["rhythm"],
        melody_intervals=plain(raw["melody_intervals"]),
        cadence_melody=plain(raw["cadence_melody"]),
        modulations=plain(raw["modulations"]),
        phrases=raw["phrases"],
        activity=raw["activity"],
        modes=plain(raw["modes"]),
    )


def train(scores: Iterable[stream.Score], name: str, title: str, description: str, source: str,
          progress: Callable[[int, str], None] | None = None) -> StyleModel:
    acc = {m: _blank() for m in MODES}
    used = 0
    for i, s in enumerate(scores):
        try:
            if count_score(s, acc):
                used += 1
        except Exception as e:  # one odd file should never stop training
            if progress:
                progress(i, f"skipped: {e}")
            continue
        if progress:
            progress(i, "ok")
    return StyleModel(name, title, description, source, used, {m: _finish(acc[m]) for m in MODES})


def bach_chorales() -> Iterable[stream.Score]:
    for name in corpus.chorales.Iterator(returnType="filename"):
        yield corpus.parse(name)


def train_bach(out: Path) -> StyleModel:
    def progress(i, msg):
        if i % 25 == 0 or msg != "ok":
            print(f"  chorale {i + 1}: {msg}", file=sys.stderr)

    model = train(
        bach_chorales(),
        name="bach_chorale",
        title="Bach chorale",
        description="Four-part harmony learned from J.S. Bach's chorale harmonizations: one chord per beat, "
                    "strong cadences at each fermata, frequent secondary dominants.",
        source="music21 corpus: 371 Bach chorales (public-domain music; encodings from the music21 corpus)",
        progress=progress,
    )
    model.save(out)
    return model


def train_folder(folder: Path, out: Path, name: str, title: str) -> StyleModel:
    """Train a style from a folder of harmonized scores (MusicXML, MIDI, Humdrum, ABC)."""
    from music21 import converter

    files = sorted(p for p in folder.rglob("*") if p.suffix.lower() in {".xml", ".musicxml", ".mxl", ".mid", ".midi", ".krn", ".abc"})

    def scores():
        for p in files:
            yield converter.parse(str(p))

    model = train(scores(), name=name, title=title, description=f"Learned from {len(files)} files in {folder.name}",
                  source=str(folder))
    model.save(out)
    return model


CORPUS_STYLES = {
    "palestrina": dict(composers=["palestrina"], title="Palestrina (Renaissance)", limit=400,
                       description="Renaissance sacred polyphony (masses): modal, mostly root-position triads, "
                                   "very few sevenths or chromatic chords."),
    "classical": dict(composers=["mozart", "haydn", "beethoven"], title="Classical (Mozart, Haydn, Beethoven)",
                      limit=None,
                      description="Classical-era chamber music: clear tonic-dominant phrases, cadential 6/4s, "
                                  "dominant sevenths and secondary dominants."),
    "monteverdi": dict(composers=["monteverdi"], title="Monteverdi madrigals", limit=None,
                       description="Late-Renaissance / early-Baroque madrigals: expressive dissonance and "
                                   "bold chord successions."),
}


def train_corpus_style(name: str, out: Path) -> StyleModel:
    """Train one of the multi-era styles from the music21 corpus."""
    cfg = CORPUS_STYLES[name]
    paths = []
    for composer in cfg["composers"]:
        paths += sorted(corpus.getComposer(composer))
    if cfg["limit"]:
        step = max(1, len(paths) // cfg["limit"])
        paths = paths[::step][: cfg["limit"]]

    def scores():
        for p in paths:
            s = corpus.parse(p)
            if isinstance(s, stream.Opus):
                yield from s.scores
            else:
                yield s

    def progress(i, msg):
        if i % 50 == 0 or msg != "ok":
            print(f"  {name} {i + 1}: {msg}", file=sys.stderr)

    model = train(scores(), name=name, title=cfg["title"], description=cfg["description"],
                  source=f"music21 corpus: {', '.join(cfg['composers'])} ({len(paths)} files)", progress=progress)
    model.save(out)
    return model


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "bach_chorale"
    target = Path(__file__).parent / "styles" / f"{which}.json"
    target.parent.mkdir(exist_ok=True)
    m = train_bach(target) if which == "bach_chorale" else train_corpus_style(which, target)
    for mode, s in m.modes.items():
        print(f"{mode}: {sum(s.chord_counts.values())} chords, vocabulary {len(s.vocab)}: {s.vocab[:15]}")
    print(f"saved {target} from {m.pieces} pieces")
