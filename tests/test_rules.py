from rameau.rules import check_motion, check_progression, check_vertical

# MIDI numbers: C4 = 60. Voicings are (soprano, alto, tenor, bass).


def rules(findings):
    return {f.rule for f in findings}


def test_parallel_fifths_between_outer_voices():
    # C major (S=G4 over B=C3) moving to D minor (S=A4 over B=D3): fifths in parallel
    prev = (67, 64, 60, 48)
    cur = (69, 65, 62, 50)
    assert "parallel fifths" in rules(check_motion(1, prev, cur))


def test_parallel_octaves():
    prev = (72, 64, 55, 48)  # C5 over C3
    cur = (74, 65, 57, 50)   # D5 over D3
    assert "parallel octaves" in rules(check_motion(1, prev, cur))


def test_contrary_motion_is_clean():
    prev = (72, 67, 64, 48)  # C major
    cur = (71, 67, 62, 55)   # G major, soprano down, bass up
    found = rules(check_motion(1, prev, cur))
    assert "parallel fifths" not in found and "parallel octaves" not in found


def test_voice_crossing_and_spacing():
    assert "crossing" in rules(check_vertical(0, (60, 64, 55, 48)))   # alto above soprano
    assert "spacing" in rules(check_vertical(0, (79, 64, 55, 48)))    # soprano 15 semitones above alto


def test_leading_tone_must_rise_in_outer_voice():
    # G7 -> C with leading tone B in the soprano falling to G
    prev = (71, 65, 62, 43)
    cur = (67, 64, 60, 48)
    assert "leading tone" in rules(check_motion(1, prev, cur, leading_tone_pc=11))


def test_unresolved_seventh():
    # G7 with the 7th (F) in the alto leaping up instead of stepping down
    prev = (71, 65, 62, 43)
    cur = (72, 67, 64, 48)
    assert "unresolved seventh" in rules(check_motion(1, prev, cur, sevenths=(5, None)))


def test_check_progression_flags_bad_example():
    voicings = [(67, 64, 60, 48), (69, 65, 62, 50)]
    found = check_progression(voicings, [None, None], [None, None])
    assert any(f.severity == "error" for f in found)
