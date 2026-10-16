"""The output should behave like music, not blocks of chords."""
from pathlib import Path

import mido
import pytest

from rameau.session import Session
from rameau.sounds import SOUNDS
from rameau.style import load_style

SAMPLES = Path(__file__).parents[1] / "src" / "rameau" / "samples"
JAZZ = "| ii7 V7 | IM7 vi7 | ii7 V7 | IM7 |"


def velocities(midi_path):
    return [m.velocity for t in mido.MidiFile(str(midi_path)).tracks for m in t
            if m.type == "note_on" and m.velocity > 0]


def test_performance_varies_dynamics_and_balances_voices():
    r = Session().harmonize_melody((SAMPLES / "old_hundredth.abc").read_text(encoding="utf-8"),
                                   load_style("bach_chorale"), sound=SOUNDS["choir_organ"], tempo=72)
    v = velocities(r.midi)
    assert max(v) - min(v) >= 30          # not one flat loudness
    mf = mido.MidiFile(str(r.midi))
    assert mf.length > 33 * 60 / 72        # cadences broaden, fermatas are held


def test_bach_inner_voices_move_between_beats():
    r = Session().harmonize_melody((SAMPLES / "old_hundredth.abc").read_text(encoding="utf-8"),
                                   load_style("bach_chorale"), sound=SOUNDS["organ"])
    eighths = sum(1 for p in list(r.score.parts)[1:] for n in p.flatten().notes if n.quarterLength == 0.5)
    assert eighths >= 10                   # passing and neighbor notes learned from the chorales
    assert not [f for f in r.realization.findings if f.severity == "error"]


@pytest.mark.parametrize("style,sound", [("jazz_standards", "jazz_piano"), ("bossa_latin", "cool_ep"),
                                         ("pop_rock", "piano"), ("country", "piano")])
def test_popular_styles_get_bass_and_comping(style, sound):
    r = Session().generate_from_pattern(JAZZ, load_style(style), "F", SOUNDS[sound], seed=2)
    names = [p.partName for p in r.score.parts]
    assert names == ["Melody", "Piano", "Bass"]
    piano = [c for c in r.score.parts[1].flatten().notes]
    assert piano and all(len(c.pitches) >= 2 for c in piano)


def test_jazz_walking_bass_moves_on_every_beat():
    r = Session().generate_from_pattern(JAZZ, load_style("jazz_standards"), "F", SOUNDS["jazz_piano"], seed=2)
    bass = [n.pitch.midi for n in r.score.parts[2].flatten().notes]
    assert len(bass) >= 15                 # quarter notes
    assert sum(1 for a, b in zip(bass, bass[1:]) if a != b) >= len(bass) * 0.7
