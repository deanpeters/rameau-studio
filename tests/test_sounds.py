from pathlib import Path

import mido

from rameau import band
from rameau.session import Session
from rameau.sounds import SOUNDS, STYLE_SOUNDS, pairing_note, recommended
from rameau.style import builtin_styles, load_style

SAMPLES = Path(__file__).parents[1] / "src" / "rameau" / "samples"


def test_every_builtin_style_has_recommendations():
    for name in builtin_styles():
        assert name in STYLE_SOUNDS, f"{name} needs recommended sounds"
        assert recommended(name)


def test_recommended_grooves_exist_in_mma():
    names = {g.name for g in band.list_grooves()}
    for snd in SOUNDS.values():
        for groove in snd.grooves.values():
            assert groove in names, f"{snd.key}: MMA has no groove {groove}"


def test_pairing_notes_explain_fit_and_mashups():
    assert pairing_note("bach_chorale", "Bach", SOUNDS["choir_organ"]).startswith("Recommended")
    assert "Time-travel" in pairing_note("palestrina", "Palestrina", SOUNDS["string_quartet"])
    assert "Mashup" in pairing_note("bach_chorale", "Bach", None, "BossaNova")


def test_choir_and_organ_double_every_voice():
    s = Session()
    r = s.harmonize_melody((SAMPLES / "twinkle.abc").read_text(encoding="utf-8"), load_style("bach_chorale"),
                           sound=SOUNDS["choir_organ"])
    programs = {m.program for t in mido.MidiFile(str(r.midi)).tracks for m in t if m.type == "program_change"}
    assert {52, 19} <= programs


def test_band_sound_uses_waltz_groove_in_three_four():
    s = Session()
    r = s.harmonize_melody((SAMPLES / "greensleeves.abc").read_text(encoding="utf-8"), load_style("classical"),
                           sound=SOUNDS["alberti"])
    assert "Groove ArpeggioWaltz8" in r.band_source


def test_stale_groove_index_is_rebuilt(tmp_path, monkeypatch):
    """Regression: an index built elsewhere (different absolute paths) must be rebuilt, not trusted."""
    db = band.ENGINE / "lib" / "stdlib" / ".mmaDB"
    band.ensure_groove_database()
    original = db.read_bytes()
    try:
        db.write_bytes(b"### mmaDB ... stale index pointing at /somewhere/else/lib/stdlib\n")
        assert not band._database_is_current()
        band.ensure_groove_database()
        assert band._database_is_current()
    finally:
        if not band._database_is_current():
            db.write_bytes(original)
