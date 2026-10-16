import pytest
from music21 import key

from rameau.generate import compose_melody, generate, invent_progression, parse_pattern
from rameau.harmonize import harmonize
from rameau.style import load_style
from rameau.voicing import realize


@pytest.fixture(scope="module")
def bach():
    return load_style("bach_chorale")


def test_parse_chord_symbols_and_guess_key():
    bars, k = parse_pattern("| G Em | C D7 | G |")
    assert str(k) == "G major"
    assert bars[0] == ["I", "I", "vi", "vi"] and bars[1][2] == "V7"


def test_parse_roman_numerals_in_given_key():
    bars, k = parse_pattern("| i iv | V7 i |", k=key.Key("d"))
    assert bars == [["i", "i", "iv", "iv"], ["V7", "V7", "i", "i"]]


def test_invented_progression_ends_home(bach):
    for seed in range(5):
        bars = invent_progression(bach, "major", 8, 4, seed=seed)
        assert len(bars) == 8 and bars[-1][-1] == "I"


def test_composed_melody_fits_and_ends_on_tonic(bach):
    k = key.Key("G")
    labels = ["I"] * 4 + ["IV"] * 2 + ["V"] * 2 + ["I"] * 4
    mel = compose_melody(labels, bach, k, seed=1)
    assert len(mel) == len(labels)
    assert mel[-1] % 12 == k.tonic.pitchClass
    assert all(60 <= m < 80 for m in mel)


def test_generate_then_harmonize_keeps_the_pattern(bach):
    k = key.Key("C")
    bars, _ = parse_pattern("| I vi | IV V7 | I |", k=k)
    melody, locks = generate(bach, bars, k, seed=2)
    h = harmonize(melody, bach, key=k, locks=locks, lock_reason="From your pattern.")
    assert [c.label for c in h.choices] == [c for bar in bars for c in bar]
    r = realize(h)
    assert not [f for f in r.findings if f.severity == "error"]
