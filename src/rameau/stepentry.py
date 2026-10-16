"""Step-entry melody editing: a simple note model, ABC export, and the editor widget.

Keyboard (like MuseScore / Sibelius note input):
    A-G         add a note (nearest octave to the previous note, spelled in the key)
    1-5         duration: 1 whole, 2 half, 3 quarter, 4 eighth, 5 sixteenth
    .           toggle dotted duration
    R           add a rest
    Shift+F     toggle a fermata (phrase ending) on the selected note
    Up/Down     selected note up/down a semitone; with Ctrl/Cmd: an octave
    Left/Right  select the previous/next note
    Backspace   delete the selected note
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from music21 import key as m21key

DURATIONS = {1: 4.0, 2: 2.0, 3: 1.0, 4: 0.5, 5: 0.25}  # key -> quarter notes
LETTER_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


@dataclass
class StepNote:
    midi: int | None      # None = rest
    duration: float       # in quarter notes
    fermata: bool = False


@dataclass
class MelodyDoc:
    title: str = "My melody"
    key: str = "C"         # music21 key name: "C", "G", "e", "B-", ...
    meter: str = "4/4"
    pickup: float = 0.0    # length of an opening upbeat bar in quarter notes (0 = starts on beat 1)
    notes: list[StepNote] = field(default_factory=list)
    selected: int = -1     # index of the selected note (-1 = none)

    # ------------------------------------------------------------------ editing
    @property
    def music21_key(self) -> m21key.Key:
        return m21key.Key(self.key)

    def last_pitch(self) -> int:
        for n in reversed(self.notes[: self.selected + 1] if self.selected >= 0 else self.notes):
            if n.midi is not None:
                return n.midi
        return 67  # G4: middle of a soprano range

    def letter_to_midi(self, letter: str) -> int:
        """The pitch for a typed letter: spelled by the key signature, nearest the previous note."""
        k = self.music21_key
        pc = LETTER_PC[letter.upper()]
        for p in k.alteredPitches:
            if p.step == letter.upper():
                pc = (pc + int(p.alter)) % 12
        prev = self.last_pitch()
        candidates = [pc + 12 * octave for octave in range(2, 8)]
        return min(candidates, key=lambda m: (abs(m - prev), m))

    def insert(self, note: StepNote) -> None:
        pos = self.selected + 1 if self.selected >= 0 else len(self.notes)
        self.notes.insert(pos, note)
        self.selected = pos

    def delete_selected(self) -> None:
        if 0 <= self.selected < len(self.notes):
            del self.notes[self.selected]
            self.selected = min(self.selected, len(self.notes) - 1) if self.selected > 0 else (0 if self.notes else -1)
            if self.selected > len(self.notes) - 1:
                self.selected = len(self.notes) - 1

    def transpose_selected(self, semitones: int) -> None:
        if 0 <= self.selected < len(self.notes) and self.notes[self.selected].midi is not None:
            self.notes[self.selected].midi = max(36, min(96, self.notes[self.selected].midi + semitones))

    def move(self, step: int) -> None:
        if self.notes:
            self.selected = max(0, min(len(self.notes) - 1, self.selected + step))

    # ------------------------------------------------------------------ export
    def offset_of(self, index: int) -> float:
        """Where note ``index`` starts, in quarter notes from the beginning."""
        return float(sum(n.duration for n in self.notes[:index]))

    def bar_length(self) -> float:
        num, den = (int(x) for x in self.meter.split("/"))
        return num * 4 / den

    def to_abc(self) -> str:
        """ABC text for the melody, with correct bar lines, ties across bars and accidentals."""
        from .render import spell

        k = self.music21_key
        key_alter = {p.step: int(p.alter) for p in k.alteredPitches}
        tonic = k.tonic.name.replace("-", "b")
        abc_key = tonic + ("m" if k.mode == "minor" else "")
        out = [f"X:1", f"T:{self.title}", f"M:{self.meter}", "L:1/16", f"K:{abc_key}"]
        bar_len = Fraction(self.bar_length()).limit_denominator(16)
        pickup = Fraction(self.pickup).limit_denominator(16)
        pos = bar_len - pickup if 0 < pickup < bar_len else Fraction(0)  # an upbeat bar ends early
        bar_acc: dict[tuple[str, int], int] = {}
        body: list[str] = []

        def length(q: Fraction) -> str:
            units = q * 4  # L:1/16 -> a quarter note is 4 units
            if units.denominator == 1:
                return "" if units == 1 else str(units.numerator)
            return f"{units.numerator}/{units.denominator}"

        def pitch_text(midi: int) -> str:
            p = spell(midi, k)
            alter = int(p.accidental.alter) if p.accidental is not None else 0
            expected = bar_acc.get((p.step, p.octave), key_alter.get(p.step, 0))
            acc = ""
            if alter != expected:
                acc = {-2: "__", -1: "_", 0: "=", 1: "^", 2: "^^"}[alter]
                bar_acc[(p.step, p.octave)] = alter
            letter = p.step if p.octave <= 4 else p.step.lower()
            octave_marks = "," * max(0, 4 - p.octave) if p.octave < 4 else "'" * max(0, p.octave - 5)
            return acc + letter + octave_marks

        for n in self.notes:
            remaining = Fraction(n.duration).limit_denominator(16)
            first = True
            while remaining > 0:
                room = bar_len - pos
                chunk = min(remaining, room)
                token = ("H" if n.fermata and first else "") + \
                        ("z" if n.midi is None else pitch_text(n.midi)) + length(chunk)
                remaining -= chunk
                if remaining > 0 and n.midi is not None:
                    token += "-"  # tie into the next bar
                body.append(token)
                first = False
                pos += chunk
                if pos >= bar_len:
                    body.append("|")
                    pos = Fraction(0)
                    bar_acc = {}
        text = " ".join(body).replace(" |", " |")
        if not text.rstrip().endswith("|"):
            text += " |"
        out.append(text.rstrip("|").rstrip() + " |]")
        return "\n".join(out)

    @classmethod
    def from_part(cls, part, title: str = "My melody") -> "MelodyDoc":
        """Load an existing melody (music21 Part) for editing."""
        from .music import detect_key

        k = detect_key(part)
        ts = part.recurse().getElementsByClass("TimeSignature").first()
        doc = cls(title=title, key=k.tonic.name if k.mode == "major" else k.tonic.name.lower(),
                  meter=ts.ratioString if ts else "4/4")
        measures = list(part.getElementsByClass("Measure"))
        if measures and measures[0].duration.quarterLength < doc.bar_length() - 1e-6:
            doc.pickup = float(measures[0].duration.quarterLength)
        for n in part.flatten().notesAndRests:
            if n.duration.quarterLength <= 0:
                continue
            fermata = any(type(e).__name__ == "Fermata" for e in getattr(n, "expressions", []))
            if n.isRest:
                doc.notes.append(StepNote(None, float(n.quarterLength)))
            else:
                doc.notes.append(StepNote(n.pitches[-1].midi, float(n.quarterLength), fermata))
        doc.selected = len(doc.notes) - 1
        return doc
