"""Style models: the learned harmonic habits of a musical style.

A style model is plain statistics, so every number it uses can be shown to a learner:

- ``start``       how often each chord opens a piece
- ``transitions`` how often chord B follows chord A
- ``emissions``   how often each melody scale degree sits on top of each chord
- ``cadences``    how often each chord ends a phrase (at a fermata)
- ``inversions``  how often each chord appears in root position, 1st, 2nd or 3rd inversion

Counts are kept separately for major and minor keys.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

MODES = ("major", "minor")

# Smoothing so unseen-but-possible combinations are unlikely rather than impossible.
TRANSITION_ALPHA = 0.05
EMISSION_ALPHA = 0.01
CADENCE_ALPHA = 0.05


@dataclass
class ModeStats:
    vocab: list[str] = field(default_factory=list)
    chord_counts: dict[str, int] = field(default_factory=dict)
    start: dict[str, int] = field(default_factory=dict)
    transitions: dict[str, dict[str, int]] = field(default_factory=dict)
    emissions: dict[str, dict[str, int]] = field(default_factory=dict)  # chord -> degree(0-11 as str) -> n
    cadences: dict[str, int] = field(default_factory=dict)
    cadence_approach: dict[str, dict[str, int]] = field(default_factory=dict)  # final -> prev -> n
    inversions: dict[str, dict[str, int]] = field(default_factory=dict)  # chord -> "0".."3" -> n
    # harmonic rhythm: [chord changes, beats] on strong and weak beats
    rhythm: dict[str, list[int]] = field(default_factory=dict)
    melody_intervals: dict[str, int] = field(default_factory=dict)  # top-voice steps in semitones
    cadence_melody: dict[str, int] = field(default_factory=dict)    # top-voice degree at phrase ends
    modulations: dict[str, int] = field(default_factory=dict)       # local key relation -> phrases
    phrases: int = 0
    activity: list[float] = field(default_factory=lambda: [0.0, 0.0])  # [note onsets, voice-beats]
    modes: dict[str, int] = field(default_factory=dict)              # Dorian, Phrygian, ... -> pieces

    # ---- probabilities -------------------------------------------------
    def _total(self, d: dict[str, int]) -> int:
        return sum(d.values())

    def p_start(self, chord: str) -> float:
        n = len(self.vocab)
        return (self.start.get(chord, 0) + TRANSITION_ALPHA) / (self._total(self.start) + TRANSITION_ALPHA * n)

    def p_transition(self, prev: str, chord: str) -> float:
        row = self.transitions.get(prev, {})
        n = len(self.vocab)
        return (row.get(chord, 0) + TRANSITION_ALPHA) / (self._total(row) + TRANSITION_ALPHA * n)

    def p_emission(self, chord: str, degree: int) -> float:
        row = self.emissions.get(chord, {})
        return (row.get(str(degree), 0) + EMISSION_ALPHA) / (self._total(row) + EMISSION_ALPHA * 12)

    def p_cadence(self, chord: str) -> float:
        n = len(self.vocab)
        return (self.cadences.get(chord, 0) + CADENCE_ALPHA) / (self._total(self.cadences) + CADENCE_ALPHA * n)

    def p_chord(self, chord: str) -> float:
        return self.chord_counts.get(chord, 0) / max(1, self._total(self.chord_counts))

    def transition_share(self, prev: str, chord: str) -> tuple[int, int]:
        """Raw evidence: (times prev->chord seen, times prev seen followed by anything)."""
        row = self.transitions.get(prev, {})
        return row.get(chord, 0), self._total(row)

    def emission_share(self, chord: str, degree: int) -> tuple[int, int]:
        row = self.emissions.get(chord, {})
        return row.get(str(degree), 0), self._total(row)

    def p_change(self, strong: bool) -> float:
        """How often the chord changes on a strong / weak beat (harmonic rhythm)."""
        changed, total = self.rhythm.get("strong" if strong else "weak", [0, 0])
        return (changed + 1) / (total + 2)

    def p_change_overall(self) -> float:
        c = sum(v[0] for v in self.rhythm.values())
        t = sum(v[1] for v in self.rhythm.values())
        return (c + 1) / (t + 2)

    def p_interval(self, semitones: int) -> float:
        total = sum(self.melody_intervals.values())
        return (self.melody_intervals.get(str(semitones), 0) + 0.2) / (total + 0.2 * 25)

    def inversion_probs(self, chord: str) -> dict[int, float]:
        row = self.inversions.get(chord, {})
        total = self._total(row)
        if not total:
            return {0: 0.7, 1: 0.25, 2: 0.04, 3: 0.01}
        return {int(k): v / total for k, v in row.items()}


@dataclass
class StyleModel:
    name: str
    title: str
    description: str
    source: str
    pieces: int
    modes: dict[str, ModeStats]

    def mode(self, mode: str) -> ModeStats:
        return self.modes["minor" if mode == "minor" else "major"]

    # ---- persistence ---------------------------------------------------
    def to_json(self) -> dict:
        return {
            "format": "rameau-style/1",
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "source": self.source,
            "pieces": self.pieces,
            "modes": {m: vars(s) for m, s in self.modes.items()},
        }

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_json(), indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def from_json(cls, data: dict) -> "StyleModel":
        return cls(
            name=data["name"],
            title=data["title"],
            description=data["description"],
            source=data["source"],
            pieces=data["pieces"],
            modes={m: ModeStats(**s) for m, s in data["modes"].items()},
        )

    @classmethod
    def load(cls, path: Path) -> "StyleModel":
        return cls.from_json(json.loads(Path(path).read_text(encoding="utf-8")))


def builtin_styles() -> dict[str, Path]:
    """Style files shipped with Rameau, keyed by name."""
    folder = resources.files("rameau") / "styles"
    return {Path(str(p)).stem: Path(str(p)) for p in folder.iterdir() if str(p).endswith(".json")}


def load_style(name_or_path: str) -> StyleModel:
    styles = builtin_styles()
    if name_or_path in styles:
        return StyleModel.load(styles[name_or_path])
    return StyleModel.load(Path(name_or_path))


def log(p: float) -> float:
    return math.log(p) if p > 0 else -1e9
