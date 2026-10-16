from pathlib import Path

import pytest
from music21 import pitch

from rameau.harmonize import chord_symbol, harmonize
from rameau.music import _mark_abc_fermatas, chord_label, load_melody, melody_beats
from rameau.style import load_style
from rameau.voicing import realize

SAMPLES = Path(__file__).parents[1] / "src" / "rameau" / "samples"


@pytest.fixture(scope="module")
def bach():
    return load_style("bach_chorale")


def test_bach_style_learned_textbook_habits(bach):
    major = bach.mode("major")
    assert major.vocab[0] == "I"
    hit, total = major.transition_share("V7", "I")
    assert hit / total > 0.6  # dominant sevenths resolve home


def test_abc_fermatas_and_bar_accidentals_survive():
    text = "X:1\nM:4/4\nL:1/4\nK:C\n^G A G HC |]"
    assert "u" in _mark_abc_fermatas(text)
    beats = melody_beats(load_melody(text))
    assert [b.pitch.name for b in beats] == ["G#", "A", "G#", "C"]
    assert beats[-1].phrase_end


def test_minor_key_numerals_round_trip():
    from music21 import chord, key

    k = key.Key("e")
    label, inv = chord_label(chord.Chord(["D3", "F#4", "A4"]), k)
    assert label == "VII"
    assert chord_symbol(label, k) == "D"


@pytest.mark.parametrize("name,expected_key", [
    ("ode_to_joy", "D major"), ("old_hundredth", "G major"), ("twinkle", "C major"), ("greensleeves", "a minor"),
])
def test_samples_harmonize_cleanly(bach, name, expected_key):
    melody = load_melody(SAMPLES / f"{name}.abc")
    h = harmonize(melody, bach)
    assert str(h.key) == expected_key
    tonic = "i" if h.key.mode == "minor" else "I"
    # ends on the home chord (or a major home chord: the Picardy third)
    assert h.choices[-1].label in {tonic, "I"}
    r = realize(h)
    assert not [f for f in r.findings if f.severity == "error"]
    # soprano is the melody
    for c, v in zip(h.choices, r.voicings):
        if c.beat.pitch is not None:
            assert v[0] == c.beat.pitch.midi + r.soprano_shift


def test_locked_chord_is_respected(bach):
    melody = load_melody(SAMPLES / "twinkle.abc")
    h = harmonize(melody, bach, locks={4: "IV"})
    assert h.choices[4].label == "IV" and h.choices[4].locked


def test_every_choice_is_explained(bach):
    h = harmonize(load_melody(SAMPLES / "old_hundredth.abc"), bach)
    for c in h.choices:
        assert c.reasons and c.function
        assert 0 <= c.confidence <= 1
