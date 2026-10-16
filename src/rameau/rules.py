"""Voice-leading rules for four-part (SATB) writing.

Each rule returns plain-language findings so the app can teach with them, and the same
checker grades Rameau's own output and (later) a student's harmonization.
"""

from __future__ import annotations

from dataclasses import dataclass

VOICES = ("Soprano", "Alto", "Tenor", "Bass")
RANGES = {  # MIDI note numbers, comfortable choir ranges
    "Soprano": (60, 81),  # C4-A5
    "Alto": (55, 74),     # G3-D5
    "Tenor": (48, 69),    # C3-A4
    "Bass": (40, 62),     # E2-D4
}


@dataclass
class Finding:
    beat: int          # index of the (second) chord involved
    rule: str          # short rule name
    severity: str      # "error" (a classic textbook fault) or "warning" (style preference)
    voices: tuple[str, ...]
    message: str

    def __str__(self) -> str:
        return f"[{self.severity}] beat {self.beat + 1}: {self.message}"


# A voicing is a 4-tuple of MIDI numbers (S, A, T, B).
Voicing = tuple[int, int, int, int]


def _interval_class(a: int, b: int) -> int:
    return abs(a - b) % 12


def check_vertical(t: int, v: Voicing) -> list[Finding]:
    out = []
    for name, note in zip(VOICES, v):
        lo, hi = RANGES[name]
        if not lo <= note <= hi:
            out.append(Finding(t, "range", "warning", (name,), f"{name} is outside a comfortable range."))
    s, a, tn, b = v
    if not (s >= a >= tn >= b):
        out.append(Finding(t, "crossing", "error", VOICES, "Voices cross (a lower voice sings above a higher one)."))
    if s - a > 12:
        out.append(Finding(t, "spacing", "warning", ("Soprano", "Alto"), "More than an octave between soprano and alto."))
    if a - tn > 12:
        out.append(Finding(t, "spacing", "warning", ("Alto", "Tenor"), "More than an octave between alto and tenor."))
    return out


def check_motion(t: int, prev: Voicing, cur: Voicing, *, leading_tone_pc: int | None = None,
                 sevenths: tuple[int | None, int | None] = (None, None)) -> list[Finding]:
    """Rules about how voices move from chord ``t-1`` to chord ``t``.

    ``sevenths`` gives the pitch class of the chord 7th in the previous chord (if any).
    """
    out = []
    for i in range(4):
        for j in range(i + 1, 4):
            p_int = _interval_class(prev[i], prev[j])
            c_int = _interval_class(cur[i], cur[j])
            moved = prev[i] != cur[i] and prev[j] != cur[j]
            if not moved:
                continue
            same_dir = (cur[i] - prev[i]) * (cur[j] - prev[j]) > 0
            names = (VOICES[i], VOICES[j])
            if p_int == 7 and c_int == 7:
                out.append(Finding(t, "parallel fifths", "error", names,
                                   f"Parallel fifths between {names[0].lower()} and {names[1].lower()}: "
                                   "two voices a fifth apart move together, so they stop sounding independent."))
            elif p_int == 0 and c_int == 0:
                out.append(Finding(t, "parallel octaves", "error", names,
                                   f"Parallel octaves/unisons between {names[0].lower()} and {names[1].lower()}: "
                                   "the two parts merge into one line."))
            elif same_dir and c_int in (0, 7) and (i, j) == (0, 3) and abs(cur[0] - prev[0]) > 2:
                out.append(Finding(t, "hidden fifth/octave", "warning", names,
                                   "Outer voices leap into a fifth or octave in the same direction (a 'hidden' parallel)."))
    # Big leaps in inner voices sound awkward.
    for i in (1, 2):
        if abs(cur[i] - prev[i]) > 7:
            out.append(Finding(t, "leap", "warning", (VOICES[i],), f"{VOICES[i]} leaps more than a fifth."))
    # The leading tone in an outer voice should rise to the tonic.
    if leading_tone_pc is not None:
        for i in (0, 3):
            if prev[i] % 12 == leading_tone_pc and cur[i] - prev[i] not in (1,) and cur[i] != prev[i]:
                out.append(Finding(t, "leading tone", "warning", (VOICES[i],),
                                   f"The leading tone in the {VOICES[i].lower()} does not rise to the home note."))
    # A chord seventh should step down.
    seventh_pc = sevenths[0]
    if seventh_pc is not None:
        for i in range(4):
            if prev[i] % 12 == seventh_pc and not (cur[i] - prev[i] in (-1, -2) or cur[i] == prev[i]):
                out.append(Finding(t, "unresolved seventh", "warning", (VOICES[i],),
                                   f"The chord's 7th in the {VOICES[i].lower()} does not step down."))
    return out


def check_progression(voicings: list[Voicing], leading_tones: list[int | None],
                      sevenths: list[int | None]) -> list[Finding]:
    """Check a whole SATB realization.

    ``leading_tones[t]`` is the leading-tone pitch class to check when moving *into* chord t
    (None when chord t is not a home-chord resolution); ``sevenths[t]`` is chord t's 7th, if any.
    """
    out = []
    for t, v in enumerate(voicings):
        out += check_vertical(t, v)
        if t:
            out += check_motion(t, voicings[t - 1], v, leading_tone_pc=leading_tones[t],
                                sevenths=(sevenths[t - 1], sevenths[t]))
    return out
