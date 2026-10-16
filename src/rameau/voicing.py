"""Turn a chord choice per beat into four singing voices (SATB).

The melody is the soprano. For every beat we list every legal way to place alto, tenor and
bass on chord tones (ranges, spacing, complete chord, sensible doubling), then pick the
smoothest path through them with dynamic programming, penalising textbook faults such as
parallel fifths. The finished voicing is graded by ``rules.check_progression``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import product

from music21 import roman

from .harmonize import Harmonization
from .rules import RANGES, Finding, Voicing, check_progression

PENALTY = {
    "parallel": 60.0,
    "hidden_outer": 6.0,
    "inner_leap": 3.0,
    "leading_tone": 12.0,
    "seventh": 12.0,
    "overlap": 4.0,
    "doubled_leading_tone": 15.0,
    "doubled_seventh": 15.0,
    "doubled_third_root_pos": 1.5,
    "missing_fifth": 1.0,
}
MAX_CANDIDATES = 60


@dataclass
class ChordTones:
    root: int
    third: int
    fifth: int
    seventh: int | None

    @property
    def pcs(self) -> set[int]:
        return {x for x in (self.root, self.third, self.fifth, self.seventh) if x is not None}

    def by_inversion(self, inv: int) -> int | None:
        return {0: self.root, 1: self.third, 2: self.fifth, 3: self.seventh}.get(inv)


def chord_tones(label: str, k) -> ChordTones:
    rn = roman.RomanNumeral(label, k)
    root = rn.root().pitchClass
    pcs = {p.pitchClass for p in rn.pitches}
    third = next((p for p in pcs if (p - root) % 12 in (3, 4)), (root + 4) % 12)
    fifth = next((p for p in pcs if (p - root) % 12 in (6, 7, 8)), (root + 7) % 12)
    seventh = next((p for p in pcs if (p - root) % 12 in (9, 10, 11)), None) if len(pcs) >= 4 else None
    return ChordTones(root, third, fifth, seventh)


@dataclass
class Realization:
    voicings: list[Voicing]
    inversions: list[int]
    findings: list[Finding] = field(default_factory=list)
    soprano_shift: int = 0  # semitones the melody was moved to fit a soprano range

    def bass_symbol_inversion(self, t: int) -> int:
        return self.inversions[t]


def _notes_in_range(pc: int, lo: int, hi: int) -> list[int]:
    return [n for n in range(lo, hi + 1) if n % 12 == pc]


def _candidates(s: int, ct: ChordTones, inv_probs: dict[int, float], leading_pc: int) -> list[tuple[float, Voicing, int]]:
    out = []
    pcs = ct.pcs
    max_inv = 3 if ct.seventh is not None else 2
    for inv in range(max_inv + 1):
        bass_pc = ct.by_inversion(inv)
        if bass_pc is None:
            continue
        p_inv = inv_probs.get(inv, 0.0)
        inv_cost = -math.log(p_inv + 0.01) * 1.5
        for b in _notes_in_range(bass_pc, *RANGES["Bass"]):
            for t, a in product(range(RANGES["Tenor"][0], RANGES["Tenor"][1] + 1),
                                range(RANGES["Alto"][0], RANGES["Alto"][1] + 1)):
                if t % 12 not in pcs or a % 12 not in pcs:
                    continue
                if not (s >= a >= t >= b) or s - a > 12 or a - t > 12 or t - b > 19 or s == a:
                    continue
                v = (s, a, t, b)
                present = [x % 12 for x in v]
                if ct.root not in present or ct.third not in present:
                    continue
                if ct.seventh is not None and ct.seventh not in present:
                    continue
                cost = inv_cost
                if present.count(leading_pc) > 1 and ct.third == leading_pc or present.count(leading_pc) > 1:
                    cost += PENALTY["doubled_leading_tone"]
                if ct.seventh is not None and present.count(ct.seventh) > 1:
                    cost += PENALTY["doubled_seventh"]
                if inv == 0 and present.count(ct.third) > 1:
                    cost += PENALTY["doubled_third_root_pos"]
                if ct.fifth not in present:
                    cost += PENALTY["missing_fifth"]
                # Prefer the middle of each range.
                cost += 0.05 * (abs(a - 67) + abs(t - 57) + abs(b - 48))
                out.append((cost, v, inv))
    out.sort(key=lambda x: x[0])
    return out[:MAX_CANDIDATES]


def _transition_cost(p: Voicing, c: Voicing, leading_pc: int | None, prev_seventh: int | None) -> float:
    cost = 0.0
    # smoothness: inner voices count most, bass a little
    cost += 1.0 * (abs(c[1] - p[1]) + abs(c[2] - p[2])) + 0.3 * abs(c[3] - p[3])
    for i in range(4):
        for j in range(i + 1, 4):
            if p[i] == c[i] or p[j] == c[j]:
                continue
            pi, ci = abs(p[i] - p[j]) % 12, abs(c[i] - c[j]) % 12
            if (pi == 7 and ci == 7) or (pi == 0 and ci == 0):
                cost += PENALTY["parallel"]
    if (c[0] - p[0]) * (c[3] - p[3]) > 0 and abs(c[0] - c[3]) % 12 in (0, 7) and abs(c[0] - p[0]) > 2:
        cost += PENALTY["hidden_outer"]
    for i in (1, 2):
        if abs(c[i] - p[i]) > 5:
            cost += PENALTY["inner_leap"] * (abs(c[i] - p[i]) - 5)
    # voice overlap: a voice moves past where its neighbour just was
    if c[1] < p[2] or c[2] > p[1] or c[2] < p[3] or c[3] > p[2]:
        cost += PENALTY["overlap"]
    if leading_pc is not None:
        for i in range(4):
            if p[i] % 12 == leading_pc and c[i] != p[i] and c[i] - p[i] != 1 and i in (0, 3):
                cost += PENALTY["leading_tone"]
            elif p[i] % 12 == leading_pc and c[i] - p[i] not in (1, 0, -3, -4) and i in (1, 2):
                cost += PENALTY["leading_tone"] / 3  # inner voices may drop to the 5th
    if prev_seventh is not None:
        for i in range(4):
            if p[i] % 12 == prev_seventh and not (c[i] - p[i] in (-1, -2) or c[i] == p[i]):
                cost += PENALTY["seventh"]
    return cost


def _soprano_shift(midis: list[int]) -> int:
    lo, hi = RANGES["Soprano"]
    best, best_out = 0, 1e9
    for shift in range(-24, 25, 12):
        out = sum(max(0, lo - (m + shift)) + max(0, (m + shift) - hi) for m in midis)
        if out < best_out or (out == best_out and abs(shift) < abs(best)):
            best, best_out = shift, out
    return best


def realize(h: Harmonization) -> Realization:
    k = h.key
    stats = h.style.mode(k.mode)
    leading_pc = (k.tonic.pitchClass + 11) % 12
    tonic_pc = k.tonic.pitchClass

    # Melody pitches per beat (rests hold the previous note for voicing purposes).
    sop, last = [], None
    for c in h.choices:
        last = c.beat.pitch.midi if c.beat.pitch is not None else last
        sop.append(last)
    first = next((m for m in sop if m is not None), 72)
    sop = [m if m is not None else first for m in sop]
    shift = _soprano_shift(sop)
    sop = [m + shift for m in sop]

    tones = [chord_tones(c.label, k) for c in h.choices]
    cands = []
    for s, c, ct in zip(sop, h.choices, tones):
        cs = _candidates(s, ct, stats.inversion_probs(c.label), leading_pc)
        if not cs:  # melody too low/high or a non-chord tone clash: relax by allowing a bare chord
            cs = [(50.0, (s, max(s - 5, RANGES["Alto"][0]), max(s - 12, RANGES["Tenor"][0]),
                          _notes_in_range(ct.root, *RANGES["Bass"])[0]), 0)]
        cands.append(cs)

    # leading-tone check applies when the next chord contains the tonic (a resolution)
    lt_into = [None] + [leading_pc if tonic_pc in tones[t].pcs else None for t in range(1, len(tones))]

    T = len(cands)
    cost = [c for c, _, _ in cands[0]]
    back: list[list[int]] = []
    for t in range(1, T):
        new, ptr = [], []
        prev_sev = tones[t - 1].seventh
        for c_cost, cv, _ in cands[t]:
            best_i, best = 0, 1e18
            for i, (_, pv, _) in enumerate(cands[t - 1]):
                if pv == cv:
                    total = cost[i]  # holding the same voicing is free
                else:
                    total = cost[i] + _transition_cost(pv, cv, lt_into[t], prev_sev)
                if total < best:
                    best, best_i = total, i
            new.append(best + c_cost)
            ptr.append(best_i)
        cost, back = new, back + [ptr]
    j = min(range(len(cost)), key=lambda i: cost[i])
    path = [j]
    for ptr in reversed(back):
        j = ptr[j]
        path.append(j)
    path.reverse()

    voicings = [cands[t][path[t]][1] for t in range(T)]
    inversions = [cands[t][path[t]][2] for t in range(T)]
    findings = check_progression(voicings, lt_into, [ct.seventh for ct in tones])
    return Realization(voicings, inversions, findings, shift)
