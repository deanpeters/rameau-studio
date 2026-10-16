from rameau.music import load_melody, melody_beats
from rameau.stepentry import MelodyDoc, StepNote


def test_letters_follow_key_signature_and_nearest_octave():
    doc = MelodyDoc(key="D")
    assert doc.letter_to_midi("F") % 12 == 6   # F# in D major
    doc.insert(StepNote(doc.letter_to_midi("A"), 1.0))
    doc.insert(StepNote(doc.letter_to_midi("D"), 1.0))
    a, d = doc.notes[0].midi, doc.notes[1].midi
    assert abs(d - a) <= 6                       # nearest octave, not a big leap


def test_abc_round_trip_keeps_pitches_rhythm_and_fermatas():
    doc = MelodyDoc(title="Test", key="G", meter="3/4")
    for midi, dur in [(67, 1), (69, 1), (71, 1), (72, 1.5), (71, 0.5), (69, 1), (66, 1), (67, 2)]:
        doc.insert(StepNote(midi, dur))
    doc.notes[-1].fermata = True
    abc = doc.to_abc()
    assert "K:G" in abc and "M:3/4" in abc
    part = load_melody(abc)
    notes = list(part.flatten().notes)
    assert [n.pitch.midi for n in notes] == [67, 69, 71, 72, 71, 69, 66, 67]
    assert [float(n.quarterLength) for n in notes] == [1, 1, 1, 1.5, 0.5, 1, 1, 2]
    assert melody_beats(part)[-2].phrase_end or melody_beats(part)[-1].phrase_end


def test_notes_crossing_bar_lines_are_tied():
    doc = MelodyDoc(meter="4/4")
    doc.insert(StepNote(60, 3.0))
    doc.insert(StepNote(62, 2.0))   # crosses the bar line
    doc.insert(StepNote(64, 3.0))
    abc = doc.to_abc()
    assert "-" in abc               # tie
    total = sum(float(n.quarterLength) for n in load_melody(abc).flatten().notes)
    assert total == 8.0


def test_accidentals_outside_the_key_and_restoring_naturals():
    doc = MelodyDoc(key="C")
    for midi in (65, 66, 65, 67):   # F, F#, F (natural again), G
        doc.insert(StepNote(midi, 1.0))
    part = load_melody(doc.to_abc())
    assert [n.pitch.midi for n in part.flatten().notes] == [65, 66, 65, 67]


def test_edit_operations():
    doc = MelodyDoc()
    for m in (60, 62, 64):
        doc.insert(StepNote(m, 1.0))
    doc.move(-1)
    doc.transpose_selected(1)
    assert doc.notes[1].midi == 63
    doc.delete_selected()
    assert [n.midi for n in doc.notes] == [60, 64]


def test_pickup_bar_is_kept():
    from pathlib import Path

    abc = (Path(__file__).parents[1] / "src" / "rameau" / "samples" / "old_hundredth.abc").read_text(encoding="utf-8")
    original = load_melody(abc)
    doc = MelodyDoc.from_part(original, "Old Hundredth")
    assert doc.pickup == 1.0
    again = load_melody(doc.to_abc())
    first_bar = list(again.getElementsByClass("Measure"))[0]
    assert first_bar.duration.quarterLength == 1.0
    assert [n.pitch.midi for n in again.flatten().notes] == [n.pitch.midi for n in original.flatten().notes]
