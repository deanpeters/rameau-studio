"""Choose chords for a melody in a learned style, and explain every choice.

The search is a hidden Markov model (Viterbi): for each beat it weighs
  * melody fit   - how often the style puts this melody note over this chord
  * flow         - how often the style moves from the previous chord to this one
  * cadence      - at phrase endings, how often the style ends a phrase on this chord
and picks the best overall path. Forward-backward probabilities give ranked
alternatives for every beat, so a learner can see what else was plausible.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from music21 import key as m21key
from music21 import roman

from .music import DEGREE_NAMES, Beat, chord_function, degree, detect_key, melody_beats
from .style import ModeStats, StyleModel, log

FINAL_TONIC_BONUS = 8.0  # pieces almost always end on the home chord


@dataclass
class Alternative:
    label: str
    symbol: str
    probability: float


@dataclass
class ChordChoice:
    beat: Beat
    label: str                      # roman numeral, e.g. "V7/V"
    symbol: str                     # chord symbol, e.g. "D7"
    function: str                   # e.g. "dominant (tension)"
    melody_role: str                # e.g. "the 3rd of the chord"
    confidence: float               # posterior probability of this chord at this beat
    alternatives: list[Alternative]
    reasons: list[str]
    cadence: str | None = None      # e.g. "authentic cadence"
    locked: bool = False


@dataclass
class Harmonization:
    style: StyleModel
    key: m21key.Key
    choices: list[ChordChoice]
    log_score: float
    notes: list[str] = field(default_factory=list)

    @property
    def labels(self) -> list[str]:
        return [c.label for c in self.choices]


# ---------------------------------------------------------------------------
# chord naming

_QUALITY_SUFFIX = {
    (4, 7, None): "", (3, 7, None): "m", (3, 6, None): "dim", (4, 8, None): "aug",
    (4, 7, 10): "7", (4, 7, 11): "M7", (3, 7, 10): "m7", (3, 6, 10): "m7b5", (3, 6, 9): "dim7",
    (3, 7, 11): "mM7", (4, 8, 10): "aug7",
}


def chord_symbol(label: str, k: m21key.Key, inversion: int = 0) -> str:
    """Pop/jazz chord symbol for a roman numeral, e.g. V7 in C -> 'G7'. Uses MMA-compatible suffixes."""
    rn = roman.RomanNumeral(label, k)
    root = rn.root()
    ints = sorted({(p.pitchClass - root.pitchClass) % 12 for p in rn.pitches} - {0})
    third = next((i for i in ints if i in (3, 4)), 4)
    fifth = next((i for i in ints if i in (6, 7, 8)), 7)
    seventh = next((i for i in ints if i in (9, 10, 11)), None) if len(ints) >= 3 else None
    suffix = _QUALITY_SUFFIX.get((third, fifth, seventh), "")
    name = root.name.replace("-", "b") + suffix
    if inversion:
        bass = [p for p in rn.pitches if (p.pitchClass - root.pitchClass) % 12 in
                ({1: (3, 4), 2: (6, 7, 8), 3: (9, 10, 11)}[inversion])]
        if bass:
            name += "/" + bass[0].name.replace("-", "b")
    return name


def melody_role(label: str, k: m21key.Key, pc: int) -> str:
    rn = roman.RomanNumeral(label, k)
    interval = (pc - rn.root().pitchClass) % 12
    return {0: "the root", 3: "the 3rd", 4: "the 3rd", 6: "the 5th", 7: "the 5th", 8: "the 5th",
            9: "the 7th", 10: "the 7th", 11: "the 7th"}.get(interval, "a non-chord tone")


def cadence_name(prev: str | None, final: str, k: m21key.Key) -> str | None:
    tonic = "i" if k.mode == "minor" else "I"
    dominants = {"V", "V7", "viio", "viio7", "viiø7"}
    if final == tonic and prev in dominants:
        return "authentic cadence (dominant → home: a full stop)"
    if final == tonic and prev in {"IV", "iv", "ii", "iiø7"}:
        return "plagal cadence (the 'Amen' cadence)"
    if final in {"V", "V7"}:
        return "half cadence (ends on tension: a comma, not a full stop)"
    if prev in {"V", "V7"} and final in {"vi", "VI", "bVI"}:
        return "deceptive cadence (expected home, went to vi instead)"
    if final == tonic:
        return "cadence on the home chord"
    return None


# ---------------------------------------------------------------------------
# scoring

def _emission(stats: ModeStats, chord: str, b: Beat, k: m21key.Key) -> float:
    if b.pitch is None:
        return 0.0
    return log(stats.p_emission(chord, degree(b.pitch, k)))


def _local(stats: ModeStats, chord: str, b: Beat, k: m21key.Key, is_last: bool, tonic: str) -> float:
    s = _emission(stats, chord, b, k)
    if b.phrase_end:
        s += log(stats.p_cadence(chord))
    if is_last and chord == tonic:
        s += math.log(FINAL_TONIC_BONUS)
    return s


def harmonize(melody, style: StyleModel, key: m21key.Key | str | None = None,
              locks: dict[int, str] | None = None, n_alternatives: int = 3) -> Harmonization:
    """Harmonize ``melody`` (a music21 Part) in ``style``.

    ``locks`` maps beat index -> roman numeral the user wants fixed; the rest is re-solved around it.
    """
    k = m21key.Key(key) if isinstance(key, str) else key or detect_key(melody)
    stats = style.mode(k.mode)
    tonic = "i" if k.mode == "minor" else "I"
    beats = melody_beats(melody)
    locks = locks or {}
    vocab = list(stats.vocab)
    for lab in locks.values():
        if lab not in vocab:
            vocab.append(lab)
    n, T = len(vocab), len(beats)
    if T == 0:
        raise ValueError("The melody has no notes.")

    trans = [[log(stats.p_transition(a, b)) for b in vocab] for a in vocab]
    local = []
    for t, b in enumerate(beats):
        row = [_local(stats, c, b, k, t == T - 1, tonic) for c in vocab]
        if t in locks:
            row = [0.0 if c == locks[t] else -1e9 for c in vocab]
        local.append(row)

    # Viterbi (best path)
    score = [log(stats.p_start(c)) + local[0][j] for j, c in enumerate(vocab)]
    back = []
    for t in range(1, T):
        new, ptr = [], []
        for j in range(n):
            best_i = max(range(n), key=lambda i: score[i] + trans[i][j])
            new.append(score[best_i] + trans[best_i][j] + local[t][j])
            ptr.append(best_i)
        score, back = new, back + [ptr]
    j = max(range(n), key=lambda i: score[i])
    best_score = score[j]
    path = [j]
    for ptr in reversed(back):
        j = ptr[j]
        path.append(j)
    path.reverse()

    # Forward-backward (how likely each chord is at each beat, over all paths)
    def lse(xs):
        m = max(xs)
        return m + math.log(sum(math.exp(x - m) for x in xs)) if m > -1e8 else m

    fwd = [[log(stats.p_start(c)) + local[0][j] for j, c in enumerate(vocab)]]
    for t in range(1, T):
        fwd.append([lse([fwd[t - 1][i] + trans[i][j] for i in range(n)]) + local[t][j] for j in range(n)])
    bwd = [[0.0] * n for _ in range(T)]
    for t in range(T - 2, -1, -1):
        bwd[t] = [lse([trans[i][j] + local[t + 1][j] + bwd[t + 1][j] for j in range(n)]) for i in range(n)]
    total = lse(fwd[-1])
    posteriors = [[math.exp(fwd[t][j] + bwd[t][j] - total) for j in range(n)] for t in range(T)]

    labels = [vocab[j] for j in path]
    choices = []
    for t, (b, lab) in enumerate(zip(beats, labels)):
        post = posteriors[t]
        ranked = sorted(range(n), key=lambda j: -post[j])
        alts = [Alternative(vocab[j], chord_symbol(vocab[j], k), post[j]) for j in ranked if vocab[j] != lab][:n_alternatives]
        prev = labels[t - 1] if t else None
        nxt = labels[t + 1] if t + 1 < T else None
        cad = cadence_name(prev, lab, k) if b.phrase_end else None
        role = melody_role(lab, k, b.pitch.pitchClass) if b.pitch is not None else "(rest)"
        choices.append(ChordChoice(
            beat=b, label=lab, symbol=chord_symbol(lab, k), function=chord_function(lab), melody_role=role,
            confidence=post[vocab.index(lab)], alternatives=alts,
            reasons=_reasons(stats, style, k, b, lab, prev, nxt, role, cad, t in locks),
            cadence=cad, locked=t in locks,
        ))
        top = alts[0] if alts else None
        if top is not None and top.probability > choices[-1].confidence and t not in locks:
            choices[-1].reasons.append(
                f"Trade-off: on this beat alone {top.symbol} ({top.label}) is more likely "
                f"({top.probability:.0%} vs {choices[-1].confidence:.0%}), but {lab} connects better with the "
                f"chords around it, so the best overall progression uses {lab}.")

    notes = [f"Key: {k.tonic.name.replace('-', 'b')} {k.mode} (detected from the melody)" if key is None
             else f"Key: {k.tonic.name.replace('-', 'b')} {k.mode}",
             f"Style: {style.title}, learned from {style.pieces} pieces",
             f"{sum(1 for b in beats if b.phrase_end)} phrase endings found"]
    return Harmonization(style, k, choices, best_score, notes)


def _pct(a: int, b: int) -> str:
    return f"{a / b:.0%}" if b else "n/a"


def _reasons(stats: ModeStats, style: StyleModel, k, b: Beat, lab: str, prev: str | None, nxt: str | None,
             role: str, cad: str | None, locked: bool) -> list[str]:
    who = style.title
    out = []
    if locked:
        out.append("You locked this chord; the other chords were chosen to fit around it.")
    if b.pitch is not None:
        deg = degree(b.pitch, k)
        hit, tot = stats.emission_share(lab, deg)
        out.append(f"Melody fit: the melody note {b.pitch.name.replace('-', 'b')} (scale degree {DEGREE_NAMES[deg]}) "
                   f"is {role} of {lab}. When {who} uses {lab}, the top voice is on this degree {_pct(hit, tot)} of the time.")
    if prev is not None:
        hit, tot = stats.transition_share(prev, lab)
        if prev == lab:
            out.append(f"Flow: repeating {lab} keeps the harmony steady under a moving melody ({_pct(hit, tot)} of the time in {who}).")
        else:
            out.append(f"Flow: after {prev}, {who} moves to {lab} {_pct(hit, tot)} of the time.")
    else:
        out.append(f"Opening: {who} starts on {lab} in {_pct(stats.start.get(lab, 0), sum(stats.start.values()))} of pieces.")
    if b.phrase_end:
        c_hit, c_tot = stats.cadences.get(lab, 0), sum(stats.cadences.values())
        out.append(f"Phrase ending: {who} ends {_pct(c_hit, c_tot)} of phrases on {lab}" + (f": a {cad}." if cad else "."))
    if nxt is not None and nxt != lab:
        hit, tot = stats.transition_share(lab, nxt)
        out.append(f"Leads to: {nxt} next, a move {who} makes {_pct(hit, tot)} of the time from {lab}.")
    return out
