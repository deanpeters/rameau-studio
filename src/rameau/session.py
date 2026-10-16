"""One piece of music being worked on, independent of the user interface (used by the app; testable).

The work is a pipeline of stages, each cached so that changing a control re-runs only what it affects:

    melody -> harmony (chords) -> lines (four-part voicing) -> texture (score) -> performance (notes in
    seconds, a live-playable Program) -> files (MIDI, sheet music) on demand

See controls.py for which control belongs to which stage.
"""

from __future__ import annotations

import copy
import dataclasses
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from music21 import stream

from . import band, render
from .controls import STAGES, Controls, tune_levels, tune_style
from .harmonize import Harmonization, harmonize
from .music import load_melody
from .sounds import Sound
from .style import StyleModel
from .voicing import Realization, realize

COMP_LEVELS = {0: 88, 1: 54, 2: 76}  # melody, keyboard, bass


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
    program: object | None = None       # livesynth.Program for live playback
    stage: str | None = "harmony"       # earliest stage re-run to produce this result (None = none)
    beat_times: list[float] = field(default_factory=list)  # when each beat sounds (for the playhead)


@dataclass
class _Piece:
    melody: stream.Part
    style: StyleModel
    key: object
    sound: Sound | None
    groove: str | None
    title: str
    locks: dict[int, str]
    lock_reason: str | None = None
    intro: str = ""
    h: Harmonization | None = None
    r: Realization | None = None
    score: stream.Score | None = None
    band_source: str | None = None
    svg_pages: list[str] = field(default_factory=list)
    explanation: str = ""


class Session:
    def __init__(self) -> None:
        self.workdir = Path(tempfile.mkdtemp(prefix="rameau-"))
        self.locks: dict[int, str] = {}
        self.controls = Controls()
        self.piece: _Piece | None = None
        self.result: Result | None = None
        self._run = 0

    # ------------------------------------------------------------------ files
    def _next_run(self) -> None:
        """Start a new render; delete files from renders older than the previous one."""
        self._run += 1
        for f in self.workdir.glob("*-*.*"):
            try:
                n = int(f.stem.rsplit("-", 1)[1])
            except (IndexError, ValueError):
                continue
            if n < self._run - 1:
                f.unlink(missing_ok=True)

    def _new_file(self, stem: str, suffix: str = ".mid") -> Path:
        """A fresh file per render, so audio being played is never overwritten underneath the player."""
        return self.workdir / f"{stem}-{self._run}{suffix}"

    # ------------------------------------------------------------------ entry points
    def harmonize_melody(self, melody_text: str, style: StyleModel, key: str | None = None,
                         sound: Sound | None = None, groove: str | None = None, tempo: int | None = None,
                         title: str = "Melody", source_path: Path | None = None, adventure: float | None = None,
                         controls: Controls | None = None) -> Result:
        """Harmonize and render. Play with ``sound`` (an ensemble or recommended band) or a raw MMA ``groove``."""
        self.controls = self._merge_controls(controls, tempo, adventure)
        melody = load_melody(source_path) if source_path else load_melody(melody_text)
        self.piece = _Piece(melody, style, key or None, sound, groove, title, self.locks)
        return self._run_from("harmony")

    def generate_from_pattern(self, pattern_text: str, style: StyleModel, key: str | None = None,
                              sound: Sound | None = None, groove: str | None = None, tempo: int | None = None,
                              seed: int | None = None, title: str = "From a chord pattern",
                              controls: Controls | None = None) -> Result:
        """Compose a melody for the chord pattern in the style, then voice and render it."""
        from music21 import key as m21key

        from .generate import generate, parse_pattern

        self.controls = self._merge_controls(controls, tempo, None)
        if seed is not None:
            self.controls = dataclasses.replace(self.controls, variation=seed)
        k = m21key.Key(key) if key else None
        bars, k = parse_pattern(pattern_text, 4, k)
        melody, locks = generate(style, bars, k, 4, seed=seed)
        self.piece = _Piece(melody, style, k, sound, groove, title, locks,
                            lock_reason="From your chord pattern; the melody was composed to fit it.",
                            intro=f"Melody composed by Rameau from your chord pattern, using {style.title}'s melodic "
                                  f"habits (seed {seed}).\n\n")
        return self._run_from("harmony")

    def update(self, controls: Controls) -> Result | None:
        """Apply new control values, re-running only the stages they affect."""
        if self.piece is None:
            self.controls = controls
            return None
        stage = controls.stage_changed(self.controls)
        self.controls = controls
        if stage is None:
            return dataclasses.replace(self.result, stage=None) if self.result else None
        return self._run_from(stage)

    def _merge_controls(self, controls: Controls | None, tempo: int | None, adventure: float | None) -> Controls:
        c = controls or self.controls
        if tempo is not None:
            c = dataclasses.replace(c, tempo=tempo)
        if adventure is not None:
            c = dataclasses.replace(c, adventure=adventure)
        return c

    # ------------------------------------------------------------------ the pipeline
    def _run_from(self, stage: str) -> Result:
        p, c = self.piece, self.controls
        order = STAGES.index(stage)
        if order <= 0 or p.h is None:
            p.h = harmonize(p.melody, p.style, key=p.key, locks=p.locks, adventure=c.adventure,
                            seed=c.variation + 1, lock_reason=p.lock_reason)
        if order <= 1 or p.r is None:
            p.r = realize(p.h, bass_independence=c.bass_independence)
            p.explanation = p.intro + render.explanation_markdown(p.h, p.r, p.title)
        rebuilt = order <= 2 or p.score is None
        if rebuilt:
            p.score = self._texture(p, c)
        self._next_run()
        midi = self._new_file("song")
        program = self._perform(p, c, midi, rebuild_band=order <= 3)
        if rebuilt:
            p.svg_pages = render.to_svg_pages(p.score)
        self.result = Result(p.title, p.melody, p.h, p.r, p.score, midi, p.explanation, p.svg_pages,
                             p.band_source, program, stage, self._beat_times(p, c))
        return self.result

    def _beat_times(self, p: _Piece, c: Controls) -> list[float]:
        from .performance import beat_times, melody_style_from

        if p.sound is not None and not p.sound.is_groove:
            return beat_times(p.h, c.tempo, tune_style(melody_style_from(p.h), c))
        return [b.beat.offset * 60.0 / c.tempo for b in p.h.choices]  # band grooves keep strict time

    def _comping(self, p: _Piece) -> bool:
        from .comping import FAMILIES

        return p.h.style.name in FAMILIES and p.sound is not None and not p.sound.is_groove

    def _texture(self, p: _Piece, c: Controls) -> stream.Score:
        kinds = c.ornament_kinds
        if self._comping(p):
            from .comping import comp

            # The walking bass is the bass, so chord symbols are written without slash (inversion) basses.
            plain = dataclasses.replace(p.r, inversions=[0] * len(p.r.inversions))
            base = render.build_score(p.melody, p.h, plain, p.title, seed=c.variation, density=0.0)
            stats = p.h.style.mode(p.h.key.mode)
            share = stats.extended[0] / stats.extended[1] if stats.extended[1] else 0.0
            score = comp(p.h, base.parts[0], p.h.style.name, seed=c.variation, extended_share=share)
            score.metadata.title = p.title
            return score
        return render.build_score(p.melody, p.h, p.r, p.title, seed=c.variation, density=c.ornament_density,
                                  kinds=kinds)

    def _perform(self, p: _Piece, c: Controls, midi: Path, rebuild_band: bool):
        from .livesynth import program_from_midi
        from .performance import melody_style_from, performance_program, write_midi

        reverb = round(127 * max(0.0, min(1.0, c.reverb)))
        if p.sound is not None and not p.sound.is_groove:
            style = tune_style(melody_style_from(p.h), c)
            if self._comping(p):
                voices = [p.sound.voices[0], p.sound.voices[1], p.sound.voices[3]]
                program = performance_program(p.score, p.h, voices, c.tempo, style, seed=c.variation,
                                              levels=tune_levels(COMP_LEVELS, c))
            else:
                from .performance import VOICE_LEVEL

                program = performance_program(p.score, p.h, p.sound.voices, c.tempo, style, seed=c.variation,
                                              levels=tune_levels(VOICE_LEVEL, c))
            for ch in program.channels.values():
                ch.reverb = reverb
            write_midi(program, midi)
            p.band_source = None
            return program
        # A band groove (MMA): the band is arranged by MMA; the live mixer still works on it.
        ts = p.melody.recurse().getElementsByClass("TimeSignature").first()
        ts_text = ts.ratioString if ts else "4/4"
        groove, melody_program = p.groove, 73
        if p.sound is not None:
            groove = p.sound.groove_for(int(ts_text.split("/")[0]))
            melody_program = p.sound.melody_program
            if groove is None:
                raise ValueError(f"{p.sound.name} has no groove for {ts_text} time. Pick another sound.")
        groove = groove or "Hymn"
        bars, pickup = band.bars_from_harmonization(p.h, p.r)
        p.band_source = band.mma_source(bars, groove, c.tempo, ts_text, p.title, pickup)
        band.render_band(p.band_source, self._new_file("band"))
        mel = copy.deepcopy(p.score)
        for part in list(mel.parts)[1:]:
            mel.remove(part)
        render.write_midi(mel, self._new_file("melody"), bpm=c.tempo, program=None)
        band.merge_midi(self._new_file("band"), self._new_file("melody"), midi, overlay_program=melody_program)
        program = program_from_midi(midi, {0: "Melody", 9: "Drums"})
        for ch in program.channels.values():
            ch.reverb = reverb
        return program

    # ------------------------------------------------------------------ chord charts with a band only
    def play_chords(self, chord_text: str, groove: str, tempo: int = 100, time_signature: str = "4/4",
                    title: str = "Chord chart") -> Result:
        from .livesynth import program_from_midi

        beats = int(time_signature.split("/")[0])
        bars = band.expand_to_beats(band.parse_chord_text(chord_text), beats)
        if not bars:
            raise ValueError("Type some chords, e.g. | Dm7 G7 | CM7 |")
        src = band.mma_source(bars, groove, tempo, time_signature, title)
        self._next_run()
        midi = band.render_band(src, self._new_file("song"))
        text = f"# {title}\n\nGroove: {groove}, {tempo} BPM\n\n```\n{src}\n```"
        self.piece = None
        self.result = Result(title, None, None, None, None, midi, text, [], src, program_from_midi(midi))
        return self.result
