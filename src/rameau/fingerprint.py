"""Style fingerprints: the measurable habits that give a composer or era its signature sound."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

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
    return Fingerprint(
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


def compare(styles: list[StyleModel], min_count: int = 25) -> list[Fingerprint]:
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
        if not others:
            continue
        sig = []
        for move, share in mine.items():
            if raw[move] < min_count:
                continue
            other = sum(o.get(move, 0.0) for o in others) / len(others)
            ratio = share / max(other, 0.001)
            sig.append((move[0], move[1], share, ratio))
        sig.sort(key=lambda x: -x[3])
        fp.signature_moves = sig[:5]
    return fps


def _p(x: float) -> str:
    return f"{x:.0%}"


def fingerprint_markdown(styles: list[StyleModel]) -> str:
    fps = compare(styles)
    head = "| | " + " | ".join(fp.style.title for fp in fps) + " |"
    sep = "|---" * (len(fps) + 1) + "|"
    rows = [
        ("Pieces learned from", [str(fp.style.pieces) for fp in fps]),
        ("Chords analysed", [f"{fp.chords:,}" for fp in fps]),
        ("Favourite chords", [", ".join(f"{c} {_p(s)}" for c, s in fp.top_chords[:5]) for fp in fps]),
        ("Seventh chords", [_p(fp.seventh_share) for fp in fps]),
        ("Chromatic chords (secondary dominants, borrowed)", [_p(fp.chromatic_share) for fp in fps]),
        ("Root position (bass on the chord's root)", [_p(fp.root_position_share) for fp in fps]),
        ("Chord changes on a beat", [_p(fp.change_rate) for fp in fps]),
        ("Most common moves", ["<br>".join(f"{a} → {b} {_p(s)}" for a, b, s in fp.top_moves[:4]) for fp in fps]),
        ("Phrases end on", [", ".join(f"{c} {_p(s)}" for c, s in fp.cadence_endings[:3]) for fp in fps]),
        ("Endings by dominant → home", [_p(fp.authentic_share) for fp in fps]),
    ]
    if len(fps) > 1:
        rows.append(("Signature moves (vs the others)",
                     ["<br>".join(f"{a} → {b} ({x:.1f}× more)" for a, b, _, x in fp.signature_moves[:4]) or "n/a"
                      for fp in fps]))
    lines = ["# Style fingerprints", "", head, sep]
    lines += [f"| {name} | " + " | ".join(vals) + " |" for name, vals in rows]
    return "\n".join(lines)
