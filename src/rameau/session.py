"""One harmonization job, independent of the user interface (used by the app; testable on its own)."""

from __future__ import annotations

import copy
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from music21 import stream

from . import band, render
from .harmonize import Harmonization, harmonize
from .music import load_melody
from .sounds import Sound
from .style import StyleModel
from .voicing import Realization, realize


@dataclass
class Result:
    title: str
    melody: stream.Part | None
    harmonization: Harmonization | None
    realization: Realization | None
    score: stream.Score | None
    midi: Path
    explanation: str
    svg_pages: list[str] = field(default_factory=list)
    band_source: str | None = None


class Session:
    def __init__(self) -> None:
        self.workdir = Path(tempfile.mkdtemp(prefix="rameau-"))
        self.locks: dict[int, str] = {}

    def harmonize_melody(self, melody_text: str, style: StyleModel, key: str | None = None,
                         sound: Sound | None = None, groove: str | None = None, tempo: int = 80,
                         title: str = "Melody", source_path: Path | None = None) -> Result:
        """Harmonize and render. Play with ``sound`` (an ensemble or recommended band) or a raw MMA ``groove``."""
        melody = load_melody(source_path) if source_path else load_melody(melody_text)
        h = harmonize(melody, style, key=key or None, locks=self.locks)
        r = realize(h)
        score = render.build_score(melody, h, r, title)
        midi = self.workdir / "song.mid"
        band_src = None
        ts = melody.recurse().getElementsByClass("TimeSignature").first()
        ts_text = ts.ratioString if ts else "4/4"
        melody_program = 73
        if sound is not None and not sound.is_groove:
            render.write_ensemble_midi(score, midi, sound.voices, bpm=tempo)
        else:
            if sound is not None:
                groove = sound.groove_for(int(ts_text.split("/")[0]))
                melody_program = sound.melody_program
                if groove is None:
                    raise ValueError(f"{sound.name} has no groove for {ts_text} time. Pick another sound.")
            groove = groove or "Hymn"
            bars, pickup = band.bars_from_harmonization(h, r)
            band_src = band.mma_source(bars, groove, tempo, ts_text, title, pickup)
            band.render_band(band_src, self.workdir / "band.mid")
            mel = copy.deepcopy(score)
            for p in list(mel.parts)[1:]:
                mel.remove(p)
            render.write_midi(mel, self.workdir / "melody.mid", bpm=tempo, program=None)
            band.merge_midi(self.workdir / "band.mid", self.workdir / "melody.mid", midi,
                            overlay_program=melody_program)
        return Result(title, melody, h, r, score, midi, render.explanation_markdown(h, r, title),
                      render.to_svg_pages(score), band_src)

    def play_chords(self, chord_text: str, groove: str, tempo: int = 100, time_signature: str = "4/4",
                    title: str = "Chord chart") -> Result:
        beats = int(time_signature.split("/")[0])
        bars = band.expand_to_beats(band.parse_chord_text(chord_text), beats)
        if not bars:
            raise ValueError("Type some chords, e.g. | Dm7 G7 | CM7 |")
        src = band.mma_source(bars, groove, tempo, time_signature, title)
        midi = band.render_band(src, self.workdir / "song.mid")
        text = f"# {title}\n\nGroove: {groove}, {tempo} BPM\n\n```\n{src}\n```"
        return Result(title, None, None, None, None, midi, text, [], src)
