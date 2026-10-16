"""Learn a style model from a corpus of four-part harmonizations.

The built-in Bach model is trained on the 371 Bach chorales that ship with music21:

    uv run python -m rameau.train bach_chorale
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import Callable, Iterable

from music21 import chord, corpus, stream

from .music import chord_label, degree, melody_beats
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
    }


def count_score(score: stream.Score, acc: dict) -> bool:
    """Add one harmonized score's statistics into ``acc`` (keyed by mode). Returns False if skipped."""
    if len(score.parts) < 3:
        return False
    k = score.analyze("key")
    stats = acc[k.mode if k.mode in MODES else "major"]
    soprano = score.parts[0]
    chords = score.chordify().flatten().getElementsByClass(chord.Chord).stream()

    prev = None
    first = True
    for b in melody_beats(soprano):
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
        if b.phrase_end:
            stats["cadences"][label] += 1
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
