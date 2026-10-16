import threading
from pathlib import Path

from rameau import render
from rameau.harmonize import harmonize
from rameau.music import load_melody
from rameau.style import load_style
from rameau.voicing import realize

SAMPLES = Path(__file__).parents[1] / "src" / "rameau" / "samples"


def test_notation_renders_from_many_threads():
    """Regression: Verovio fonts failed to load on any thread but the first."""
    m = load_melody(SAMPLES / "twinkle.abc")
    h = harmonize(m, load_style("bach_chorale"))
    score = render.build_score(m, h, realize(h), "Twinkle")
    pages = []
    threads = [threading.Thread(target=lambda: pages.append(render.to_svg_pages(score))) for _ in range(3)]
    for t in threads:
        t.start()
        t.join()
    assert len(pages) == 3 and all(p and "<svg" in p[0] for p in pages)
