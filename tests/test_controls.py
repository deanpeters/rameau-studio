import dataclasses
from pathlib import Path

from rameau.controls import PRESETS, Controls
from rameau.session import Session
from rameau.sounds import SOUNDS
from rameau.style import load_style

SAMPLES = Path(__file__).parents[1] / "src" / "rameau" / "samples"


def test_each_control_maps_to_the_right_stage():
    base = Controls()
    assert dataclasses.replace(base, adventure=0.5).stage_changed(base) == "harmony"
    assert dataclasses.replace(base, bass_independence=0.2).stage_changed(base) == "lines"
    assert dataclasses.replace(base, ornament_density=1.5).stage_changed(base) == "texture"
    assert dataclasses.replace(base, swing=0.7).stage_changed(base) == "performance"
    assert dataclasses.replace(base, reverb=0.9).stage_changed(base) is None


def session():
    s = Session()
    s.harmonize_melody((SAMPLES / "old_hundredth.abc").read_text(encoding="utf-8"), load_style("bach_chorale"),
                       sound=SOUNDS["organ"], tempo=72)
    return s


def test_ornament_density_zero_and_two():
    s = session()
    plain = s.update(dataclasses.replace(s.controls, ornament_density=0.0))
    busy = s.update(dataclasses.replace(s.controls, ornament_density=2.0))
    count = lambda r: sum(1 for p in list(r.score.parts)[1:] for n in p.flatten().notes if n.quarterLength == 0.5)
    assert count(plain) == 0 and count(busy) > 10


def test_flat_expression_and_strict_time():
    s = session()
    r = s.update(dataclasses.replace(s.controls, expression=0.0, rubato=0.0, humanize=0.0))
    melody_vel = {n.velocity for n in r.program.notes if r.program.channels[n.channel].name == "Soprano"}
    assert len(melody_vel) <= 3                      # (only the strong-beat accent is gone too)
    assert abs(r.program.length - (33 * 60 / 72 + 0.5)) < 1.0


def test_performance_changes_skip_the_score():
    s = session()
    before = s.result.score
    r = s.update(dataclasses.replace(s.controls, articulation=0.8))
    assert r.stage == "performance" and r.score is before


def test_presets_are_valid():
    for name, c in PRESETS.items():
        assert Controls.from_dict(c.to_dict()) == c, name
