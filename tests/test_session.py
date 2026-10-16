from pathlib import Path

from rameau.session import Session
from rameau.sounds import SOUNDS
from rameau.style import load_style

SAMPLES = Path(__file__).parents[1] / "src" / "rameau" / "samples"


def test_each_render_gets_its_own_files_and_old_ones_are_cleaned():
    """Regression: re-rendering overwrote the WAV the player was reading, crashing the app."""
    s = Session()
    text = (SAMPLES / "twinkle.abc").read_text(encoding="utf-8")
    style = load_style("bach_chorale")
    paths = []
    for _ in range(4):
        r = s.harmonize_melody(text, style, sound=SOUNDS["organ"])
        r.midi.with_suffix(".wav").write_bytes(b"x")  # stand-in for rendered audio
        paths.append(r.midi)
    assert len(set(paths)) == 4  # never the same file twice
    assert paths[-1].exists() and paths[-2].exists()
    assert not paths[0].exists() and not paths[0].with_suffix(".wav").exists()
