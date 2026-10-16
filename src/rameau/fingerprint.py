"""Style fingerprints: the measurable habits that give a composer or era its signature sound."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .music import pretty
from .style import StyleModel


@dataclass
class Fingerprint:
    style: StyleModel
    chords: int
    top_chords: list[tuple[str, float]]
    seventh_share: float
    chromatic_share: float
    root_position_share: float
    change_rate: float                     # share of beats where the chord changes
    top_moves: list[tuple[str, str, float]]
    cadence_endings: list[tuple[str, float]]
    authentic_share: float                 # phrase endings reached by dominant -> tonic
    strong_change: float = 0.0             # chord changes on strong beats
    weak_change: float = 0.0               # chord changes on weak beats
    stepwise: float = 0.0                  # top-voice moves by step (1-2 semitones)
    leaps: float = 0.0                     # top-voice leaps larger than a 4th
    activity: float = 0.0                  # notes per voice per beat
    modes: list[tuple[str, float]] = field(default_factory=list)
    modulations: list[tuple[str, float]] = field(default_factory=list)
    extended: float | None = None          # chords with 9ths/11ths/13ths/alterations (chord charts only)
    signature_moves: list[tuple[str, str, float, float]] = field(default_factory=list)  # a, b, share, x-times


def _merged(style: StyleModel):
    """Combine major and minor statistics (labels are relative to the key, so they line up)."""
    counts, trans, cad, approach, inv = Counter(), Counter(), Counter(), Counter(), Counter()
    for m in style.modes.values():
        counts.update(m.chord_counts)
        for a, row in m.transitions.items():
            for b, n in row.items():
                trans[(a, b)] += n
        cad.update(m.cadences)
        for final, row in m.cadence_approach.items():
            for prev, n in row.items():
                approach[(prev, final)] += n
        for c, row in m.inversions.items():
            for k, n in row.items():
                inv[int(k)] += n
    return counts, trans, cad, approach, inv


def _is_seventh(label: str) -> bool:
    return "7" in label.split("/")[0]


def _is_chromatic(label: str) -> bool:
    return "/" in label or label[:1] in "b#-"


TONICS = {"I", "i"}
DOMINANTS = {"V", "V7", "viio", "viio7", "viiø7"}


def fingerprint(style: StyleModel) -> Fingerprint:
    counts, trans, cad, approach, inv = _merged(style)
    total = sum(counts.values()) or 1
    moves = {k: v for k, v in trans.items() if k[0] != k[1]}
    moves_total = sum(moves.values()) or 1
    all_trans = sum(trans.values()) or 1
    cad_total = sum(cad.values()) or 1
    authentic = sum(n for (p, f), n in approach.items() if f in TONICS and p in DOMINANTS)
    rhythm = {"strong": [0, 0], "weak": [0, 0]}
    intervals, modes, mods = Counter(), Counter(), Counter()
    act = [0.0, 0.0]
    ext = [0, 0]
    for m in style.modes.values():
        ext[0] += m.extended[0]
        ext[1] += m.extended[1]
        for kind in rhythm:
            c, t = m.rhythm.get(kind, [0, 0])
            rhythm[kind][0] += c
            rhythm[kind][1] += t
        intervals.update({int(k): v for k, v in m.melody_intervals.items()})
        modes.update(m.modes)
        mods.update(m.modulations)
        act[0] += m.activity[0]
        act[1] += m.activity[1]
    moved = sum(v for k, v in intervals.items() if k != 0) or 1
    mods_total = sum(mods.values()) or 1
    modes_total = sum(modes.values()) or 1
    return Fingerprint(
        strong_change=rhythm["strong"][0] / (rhythm["strong"][1] or 1),
        weak_change=rhythm["weak"][0] / (rhythm["weak"][1] or 1),
        stepwise=sum(v for k, v in intervals.items() if abs(k) in (1, 2)) / moved,
        leaps=sum(v for k, v in intervals.items() if abs(k) > 5) / moved,
        activity=act[0] / (act[1] or 1),
        modes=[(k, v / modes_total) for k, v in modes.most_common(3)],
        modulations=[(k, v / mods_total) for k, v in mods.most_common(4) if k != "home"],
        extended=ext[0] / ext[1] if ext[1] else None,
        style=style,
        chords=total,
        top_chords=[(c, n / total) for c, n in counts.most_common(8)],
        seventh_share=sum(n for c, n in counts.items() if _is_seventh(c)) / total,
        chromatic_share=sum(n for c, n in counts.items() if _is_chromatic(c)) / total,
        root_position_share=inv.get(0, 0) / (sum(inv.values()) or 1),
        change_rate=sum(moves.values()) / all_trans,
        top_moves=[(a, b, n / moves_total) for (a, b), n in Counter(moves).most_common(6)],
        cadence_endings=[(c, n / cad_total) for c, n in cad.most_common(4)],
        authentic_share=authentic / cad_total,
    )


def compare(styles: list[StyleModel], min_count: int | None = None) -> list[Fingerprint]:
    """Fingerprints plus each style's signature moves: progressions it uses far more than the others."""
    fps = [fingerprint(s) for s in styles]
    shares = []
    for s in styles:
        _, trans, *_ = _merged(s)
        moves = {k: v for k, v in trans.items() if k[0] != k[1]}
        tot = sum(moves.values()) or 1
        shares.append(({k: v / tot for k, v in moves.items()}, moves))
    for i, fp in enumerate(fps):
        mine, raw = shares[i]
        others = [shares[j][0] for j in range(len(fps)) if j != i]
        # Small corpora need a lower bar (Romantic has ~17 pieces); large ones a higher one.
        floor = min_count if min_count is not None else max(6, min(25, int(sum(raw.values()) * 0.004)))
        if not others:
            continue
        sig = []
        for move, share in mine.items():
            if raw[move] < floor:
                continue
            other = sum(o.get(move, 0.0) for o in others) / len(others)
            ratio = share / max(other, 0.001)
            sig.append((move[0], move[1], share, ratio))
        sig.sort(key=lambda x: -x[3])
        fp.signature_moves = sig[:5]
    return fps


def _p(x: float) -> str:
    return f"{x:.0%}"


def table_rows(fps: list[Fingerprint]) -> list[tuple[str, list[str]]]:
    rows = [
        ("Learned from", [f"{fp.style.pieces} {'scores' if fp.style.has_melody else 'chord charts'}"
                          for fp in fps]),
        ("Chords analysed", [f"{fp.chords:,}" for fp in fps]),
        ("Favourite chords", [", ".join(f"{pretty(c)} {_p(s)}" for c, s in fp.top_chords[:5]) for fp in fps]),
        ("Seventh chords", [_p(fp.seventh_share) for fp in fps]),
        ("Extended chords (9ths, 11ths, 13ths, altered)", [_p(fp.extended) if fp.extended is not None
                                                           else "not in scores" for fp in fps]),
        ("Chromatic chords (secondary dominants, borrowed)", [_p(fp.chromatic_share) for fp in fps]),
        ("Root position (bass on the chord's root)", [_p(fp.root_position_share) for fp in fps]),
        ("Chord changes on a beat", [_p(fp.change_rate) for fp in fps]),
        ("Harmonic rhythm: changes on strong / weak beats", [f"{_p(fp.strong_change)} / {_p(fp.weak_change)}"
                                                               for fp in fps]),
        ("Melody moves by step / leaps beyond a 4th", [f"{_p(fp.stepwise)} / {_p(fp.leaps)}" if fp.style.has_melody
                                                        else "no melody in charts" for fp in fps]),
        ("Voice activity (notes per voice per beat)", [f"{fp.activity:.2f}" if fp.style.has_melody else "n/a"
                                                        for fp in fps]),
        ("Modes (by the piece's final)", [", ".join(f"{k} {_p(v)}" for k, v in fp.modes) or "n/a" for fp in fps]),
        ("Phrases that move to another key", [", ".join(f"{pretty(k)} {_p(v)}" for k, v in fp.modulations) or "none"
                                              for fp in fps]),
        ("Most common moves", ["<br>".join(f"{pretty(a)} → {pretty(b)} {_p(s)}" for a, b, s in fp.top_moves[:4])
                               for fp in fps]),
        ("Phrases end on", [", ".join(f"{pretty(c)} {_p(s)}" for c, s in fp.cadence_endings[:3]) for fp in fps]),
        ("Endings by dominant → home", [_p(fp.authentic_share) for fp in fps]),
    ]
    if len(fps) > 1:
        rows.append(("Signature moves (vs the others)",
                     ["<br>".join(f"{pretty(a)} → {pretty(b)} ({x:.1f}× more)" for a, b, _, x in fp.signature_moves[:4])
                      or "n/a"
                      for fp in fps]))
    return rows


def fingerprint_markdown(styles: list[StyleModel]) -> str:
    fps = compare(styles)
    rows = table_rows(fps)
    head = "| | " + " | ".join(fp.style.title for fp in fps) + " |"
    sep = "|---" * (len(fps) + 1) + "|"
    lines = ["# Style fingerprints", "", head, sep]
    lines += [f"| {name} | " + " | ".join(vals) + " |" for name, vals in rows]
    return "\n".join(lines)


def fingerprint_html(styles: list[StyleModel]) -> str:
    import html

    fps = compare(styles)
    head = "".join(f"<th>{html.escape(fp.style.title)}</th>" for fp in fps)
    body = "".join(
        f"<tr><th class=row>{html.escape(name)}</th>" + "".join(f"<td>{v}</td>" for v in vals) + "</tr>"
        for name, vals in table_rows(fps))
    notes = "".join(f"<p><b>{html.escape(fp.style.title)}</b>: {html.escape(fp.style.description)}</p>" for fp in fps)
    return f"<table><tr><th></th>{head}</tr>{body}</table>{notes}"
