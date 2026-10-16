"""Read iReal Pro chord charts (``irealb://`` playlists) and learn styles from them.

The parsing follows infojunkie/ireal-musicxml (GPL-3.0), itself derived from daumling/ireal-renderer
and pianosnake/ireal-reader: charts are URL-encoded, lightly scrambled in 50-character blocks, and
written as a row of cells holding chords, bar lines and annotations.

Charts carry chords but no melody, so styles learned from them have no melody statistics; the
harmonizer then uses a music-theory prior (chord tones and jazz extensions) for melody fit.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from music21 import chord as m21chord
from music21 import key as m21key
from music21 import pitch

# --------------------------------------------------------------------------- unscrambling


def _obfusc50(s: str) -> str:
    out = list(s)
    for i in range(5):
        out[49 - i] = s[i]
        out[i] = s[49 - i]
    for i in range(10, 24):
        out[49 - i] = s[i]
        out[i] = s[49 - i]
    return "".join(out)


def unscramble(s: str) -> str:
    r = ""
    while len(s) > 51:
        r += _obfusc50(s[:50])
        s = s[50:]
    r += s
    return r.replace("Kcl", "| x").replace("LZ", " |").replace("XyQ", "   ")


# --------------------------------------------------------------------------- data model

@dataclass
class ChartChord:
    root: str          # e.g. "Bb"
    modifiers: str     # e.g. "-7", "^7", "7b9", "h7"
    bass: str | None   # slash bass, e.g. "E" in C/E


@dataclass
class Song:
    title: str
    composer: str
    style: str
    key: str
    time: tuple[int, int] = (4, 4)
    bars: list[list[ChartChord | None]] = field(default_factory=list)  # one chord per beat
    section_ends: set[int] = field(default_factory=set)               # bar indexes that end a section


_CHORD = re.compile(r"^([A-G][b#]?)((?:sus|alt|add|[+\-^\dhob#])*)(\*.+?\*)*(/[A-G][#b]?)?(\(.*?\))?")
_SPACE = re.compile(r"^([ Wp])()()(/[A-G][#b]?)?(\(.*?\))?")
_TOKENS = [re.compile(r"^\*[a-zA-Z]"), re.compile(r"^T\d\d"), re.compile(r"^N."), re.compile(r"^<.*?>"),
           _CHORD, _SPACE]


def _tokens(text: str) -> list:
    out = []
    text = text.strip()
    while text:
        for rx in _TOKENS:
            m = rx.match(text)
            if m:
                out.append(m if m.lastindex and m.lastindex > 1 or rx in (_CHORD, _SPACE) else m.group(0))
                text = text[len(m.group(0)):]
                break
        else:
            if text[0] != ",":
                out.append(text[0])
            text = text[1:]
    return out


def _parse_cells(music: str) -> tuple[list[list], set[int], tuple[int, int]]:
    """Bars as lists of cells (a chord, 'same', 'nc' or None for an empty cell)."""
    bars: list[list] = []
    current: list = []
    section_ends: set[int] = set()
    time = (4, 4)

    def close(section_end: bool = False):
        nonlocal current
        if current:
            bars.append(current)
            current = []
        if section_end and bars:
            section_ends.add(len(bars) - 1)

    for tok in _tokens(music):
        if isinstance(tok, re.Match):
            root = tok.group(1)
            if root in (" ",):
                current.append(None)
            elif root in ("W", "p"):
                current.append("same")
            else:
                bass = tok.group(4)[1:] if tok.group(4) else None
                mods = (tok.group(2) or "") + "".join(re.findall(r"\*(.+?)\*", tok.group(3) or ""))
                current.append(ChartChord(root, mods, bass))
            continue
        c = tok[0]
        if c in "|[{":
            close(section_end=c in "[{")
        elif c in "]}Z":
            close(section_end=True)
        elif c == "x" and bars:
            current = list(bars[-1])
        elif c == "r" and len(bars) >= 2:
            bars.append(list(bars[-2]))
            current = list(bars[-2])
        elif c == "n":
            current.append("nc")
        elif tok.startswith("T") and len(tok) == 3 and tok[1:].isdigit():
            num, den = int(tok[1]), int(tok[2])
            time = {(1, 2): (12, 8)}.get((num, den), (num, den))
    close(section_end=True)
    return bars, section_ends, time


def _to_beats(cells: list, beats: int) -> list:
    """Spread a bar's chords over its beats (a chord lasts until the next one)."""
    chords = [(i, c) for i, c in enumerate(cells) if c not in (None,)]
    if not chords:
        return [None] * beats
    n = max(len(cells), 1)
    out = []
    for b in range(beats):
        pos = b * n / beats
        current = None
        for i, c in chords:
            if i <= pos + 1e-9:
                current = c
        out.append(current if current is not None else chords[0][1])
    return out


def parse_playlist(text: str) -> list[Song]:
    m = re.search(r"(irealb(?:ook)?)://([^\"\s]*)", text)
    if not m:
        raise ValueError("No irealb:// link found.")
    old = m.group(1) == "irealbook"
    parts = urllib.parse.unquote(m.group(2)).split("===")
    if len(parts) > 1:
        parts = parts[:-1]  # last part is the playlist name
    songs = []
    for part in parts:
        f = part.split("=")
        try:
            if old:
                title, composer, style, key, music = f[0], f[1], f[2], f[3], f[5]
            else:
                title, composer, style, key = f[0], f[1], f[3], f[4]
                music = unscramble(f[6].split("1r34LbKcu7")[1])
            cells, ends, time = _parse_cells(music)
            beats = time[0] if time[1] == 4 else max(2, time[0] // 3)
            bars = []
            prev = None
            for bar in cells:
                filled = []
                for c in _to_beats(bar, beats):
                    c = prev if c == "same" else (None if c == "nc" else c)
                    filled.append(c)
                    if isinstance(c, ChartChord):
                        prev = c
                bars.append(filled)
            title = re.sub(r"(.*)(, )(A|The)$", r"\3 \1", title.strip())
            songs.append(Song(title, composer.strip(), style.strip(), key.strip(), time, bars, ends))
        except Exception:
            continue
    return songs


def parse_file(path: Path) -> list[Song]:
    return parse_playlist(Path(path).read_text(encoding="utf-8", errors="replace"))


# --------------------------------------------------------------------------- chords -> Roman numerals

def song_key(song: Song) -> m21key.Key:
    k = song.key.strip()
    minor = k.endswith("-")
    name = k.rstrip("-").replace("b", "-") if len(k.rstrip("-")) > 1 else k.rstrip("-")
    return m21key.Key(name.lower() if minor else name, "minor" if minor else "major")


def chord_intervals(mods: str) -> tuple[list[int], bool]:
    """Core chord (intervals above the root) for an iReal quality, and whether it has extensions."""
    extended = bool(re.search(r"9|11|13|alt|add|b5|#5|b9|#9|#11|b13", mods))
    if mods.startswith("-"):
        if "^" in mods:
            return [0, 3, 7, 11], extended
        return ([0, 3, 7, 10] if re.search(r"7|9|11|13", mods) else [0, 3, 7]), extended
    if mods.startswith("h"):
        return [0, 3, 6, 10], extended
    if mods.startswith("o"):
        return ([0, 3, 6, 9] if "7" in mods else [0, 3, 6]), extended
    if mods.startswith("^"):
        return [0, 4, 7, 11], extended
    if mods.startswith("+") and "7" not in mods:
        return [0, 4, 8], extended
    if re.search(r"7|9|11|13|alt", mods):
        return [0, 4, 7, 10], extended
    return [0, 4, 7], extended  # major triad, 6, 69, 2, add9, sus, 5


def to_label(c: ChartChord, k: m21key.Key) -> tuple[str, int, bool] | None:
    """(Roman numeral, inversion, extended?) for a chart chord in key k."""
    from .music import chord_label

    ints, extended = chord_intervals(c.modifiers)
    root = pitch.Pitch(c.root.replace("b", "-") if len(c.root) > 1 else c.root)
    pitches = [root.transpose(i) for i in ints]
    lab = chord_label(m21chord.Chord([p.nameWithOctave for p in pitches]), k)
    if lab is None:
        return None
    inv = 0
    if c.bass:
        bass_pc = pitch.Pitch(c.bass.replace("b", "-") if len(c.bass) > 1 else c.bass).pitchClass
        rel = (bass_pc - root.pitchClass) % 12
        inv = {3: 1, 4: 1, 6: 2, 7: 2, 8: 2, 9: 3, 10: 3, 11: 3}.get(rel, 0) if rel in ints else 0
    return lab[0], inv, extended


# --------------------------------------------------------------------------- training

CHART_SOURCE = "https://raw.githubusercontent.com/infojunkie/ireal-musicxml/main/test/data/{}.txt"

CHART_STYLES = {
    "jazz_standards": dict(file="jazz1460", genres=None, title="Jazz standards",
                           description="Learned from 1,460 jazz standards (iReal Pro charts): ii-V-I progressions, "
                                       "seventh chords everywhere, and rich extensions."),
    "jazz_ballad": dict(file="jazz1460", genres=("ballad", "slow swing", "even 8ths"), title="Jazz ballad",
                        description="Slow jazz ballads and even-8ths tunes: lush, extended seventh chords at a "
                                    "relaxed pace (the closest relative of smooth jazz in these charts)."),
    "bossa_latin": dict(file="jazz1460", genres=("bossa", "latin", "samba"), title="Bossa nova & Latin jazz",
                        description="Bossa nova, samba and Latin jazz: gentle major-seventh colours and "
                                    "chromatic ii-V chains."),
    "dixieland": dict(file="dixieland1", genres=None, title="Dixieland (early jazz)",
                      description="Early New Orleans and Chicago jazz (1910s-20s): dominant chains, "
                                  "major triads and sixths, few extensions."),
    "blues": dict(file="blues50", genres=None, title="Blues",
                  description="Blues forms: dominant-seventh chords on I, IV and V."),
    "pop_rock": dict(file="pop400", genres=None, title="Pop & rock",
                     description="Pop, rock, soul and ballads: triads, borrowed bVII and bVI chords, "
                                 "plagal (IV-I) moves."),
    "country": dict(file="country", genres=None, title="Country",
                    description="Country and country ballads: I-IV-V triads and secondary dominants."),
}


def download_charts(name: str, folder: Path) -> Path:
    import urllib.request

    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{name}.txt"
    if not out.exists():
        urllib.request.urlretrieve(CHART_SOURCE.format(name), out)
    return out


def count_song(song: Song, acc: dict) -> bool:
    """Add one chart's chord statistics into ``acc`` (keyed by mode), like train.count_score."""
    try:
        k = song_key(song)
    except Exception:
        return False
    stats = acc["minor" if k.mode == "minor" else "major"]
    stats["modes"]["Aeolian (minor)" if k.mode == "minor" else "Ionian (major)"] += 1
    beats_per_bar = len(song.bars[0]) if song.bars else 4
    labels = []
    for bi, bar in enumerate(song.bars):
        for beat, c in enumerate(bar):
            lab = to_label(c, k) if isinstance(c, ChartChord) else None
            labels.append((bi, beat, lab))
    prev, first = None, True
    for bi, beat, lab in labels:
        if lab is None:
            prev = None
            continue
        label, inv, extended = lab
        stats["chord_counts"][label] += 1
        stats["inversions"][label][str(inv)] += 1
        stats["extended"][0] += int(extended)
        stats["extended"][1] += 1
        if first:
            stats["start"][label] += 1
            first = False
        if prev is not None:
            stats["transitions"][prev][label] += 1
            strong = beat == 0 or (beats_per_bar == 4 and beat == 2)
            slot = stats["rhythm"]["strong" if strong else "weak"]
            slot[1] += 1
            slot[0] += int(label != prev)
        prev = label
    # Cadences: the chord that starts the last bar of each section, approached by the chord before it.
    for end in sorted(song.section_ends):
        idx = [i for i, (bi, beat, lab) in enumerate(labels) if bi == end and beat == 0 and lab]
        if not idx:
            continue
        i = idx[0]
        final = labels[i][2][0]
        stats["cadences"][final] += 1
        stats["phrases"] += 1
        j = i - 1
        while j >= 0 and labels[j][2] and labels[j][2][0] == final:
            j -= 1
        if j >= 0 and labels[j][2]:
            stats["cadence_approach"][final][labels[j][2][0]] += 1
    return True


def train_chart_style(name: str, out: Path, cache: Path):
    from collections import defaultdict

    from .style import MODES, StyleModel
    from .train import _blank, _finish

    cfg = CHART_STYLES[name]
    songs = parse_file(download_charts(cfg["file"], cache))
    if cfg["genres"]:
        songs = [s for s in songs if any(g in s.style.lower() for g in cfg["genres"])]
    acc = {m: _blank() for m in MODES}
    for m in MODES:
        acc[m]["extended"] = [0, 0]
    used = sum(count_song(s, acc) for s in songs)
    modes = {}
    for m in MODES:
        stats = _finish(acc[m])
        stats.extended = acc[m]["extended"]
        stats.mode_name = m
        modes[m] = stats
    model = StyleModel(name, cfg["title"], cfg["description"],
                       f"iReal Pro charts '{cfg['file']}' via infojunkie/ireal-musicxml test data "
                       f"({used} songs; chord statistics only)", used, modes)
    model.has_melody = False
    model.save(out)
    return model


def song_to_pattern(song: Song) -> str:
    """A chart as Roman numerals, four bars per line, for the Chords tab."""
    k = song_key(song)
    bars = []
    for bar in song.bars:
        labels = []
        for c in bar:
            lab = to_label(c, k) if isinstance(c, ChartChord) else None
            from .music import pretty

            name = pretty(lab[0]) if lab else (labels[-1] if labels else "I" if k.mode == "major" else "i")
            if not labels or labels[-1] != name:
                labels.append(name)
        bars.append(" ".join(labels))
    lines = ["| " + " | ".join(bars[i:i + 4]) + " |" for i in range(0, len(bars), 4)]
    return "\n".join(lines)


def train_from_files(files: list[Path], out: Path, name: str, title: str):
    """Learn a chord-chart style from your own iReal Pro playlists (exported as text or HTML)."""
    from .style import MODES, StyleModel
    from .train import _blank, _finish

    songs = [s for f in files for s in parse_file(f)]
    acc = {m: _blank() for m in MODES}
    for m in MODES:
        acc[m]["extended"] = [0, 0]
    used = sum(count_song(s, acc) for s in songs)
    modes = {}
    for m in MODES:
        stats = _finish(acc[m])
        stats.extended = acc[m]["extended"]
        stats.mode_name = m
        modes[m] = stats
    model = StyleModel(name, title, f"Learned from {used} iReal Pro charts", ", ".join(f.name for f in files),
                       used, modes)
    model.has_melody = False
    model.save(out)
    return model
