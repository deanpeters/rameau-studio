"""Sounds that suit each style, and why.

A *sound* is either an ensemble that plays the four harmonized voices (each voice gets one or
more General MIDI instruments, so a choir can be doubled by an organ), or an MMA groove that
plays the chords as a backing band under the melody.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# General MIDI program numbers (0-based)
PIANO, HARPSICHORD, ORGAN = 0, 6, 19
NYLON_GUITAR = 24
VIOLIN, VIOLA, CELLO, CONTRABASS, STRINGS = 40, 41, 42, 43, 48
CHOIR, VOICE_OOHS = 52, 53
TRUMPET, TROMBONE, FRENCH_HORN = 56, 57, 60
OBOE, BASSOON, CLARINET, FLUTE, RECORDER = 68, 70, 71, 73, 74


@dataclass(frozen=True)
class Sound:
    key: str
    name: str
    why: str
    voices: tuple[tuple[int, ...], ...] | None = None   # SATB -> GM programs (doubling allowed)
    grooves: dict[int, str] = field(default_factory=dict)  # beats per bar -> MMA groove
    melody_program: int = FLUTE                          # melody instrument over a groove
    tempo: tuple[int, int, int] = (60, 80, 100)          # low, default, high

    @property
    def is_groove(self) -> bool:
        return self.voices is None

    def groove_for(self, beats_per_bar: int) -> str | None:
        return self.grooves.get(beats_per_bar) or (self.grooves.get(4) if beats_per_bar in (2, 4) else None)


SOUNDS: dict[str, Sound] = {s.key: s for s in [
    Sound("choir", "Choir (a cappella)", "Unaccompanied voices, the way this music was usually sung.",
          voices=((CHOIR,), (CHOIR,), (CHOIR,), (CHOIR,)), tempo=(50, 66, 90)),
    Sound("choir_organ", "Choir + organ", "Congregations sang chorales with the organ doubling every voice.",
          voices=((CHOIR, ORGAN), (CHOIR, ORGAN), (CHOIR, ORGAN), (CHOIR, ORGAN)), tempo=(55, 72, 90)),
    Sound("organ", "Organ", "Bach was an organist; organ chorales put all four voices under the hands and feet.",
          voices=((ORGAN,),) * 4, tempo=(55, 72, 90)),
    Sound("sackbuts", "Cornetts & sackbuts", "Renaissance churches often doubled or replaced voices with "
          "cornetts (played here by trumpets) and sackbuts (trombones).",
          voices=((TRUMPET,), (TRUMPET,), (TROMBONE,), (TROMBONE,)), tempo=(55, 70, 90)),
    Sound("recorders", "Recorder consort", "A family of recorders in four sizes, common in 16th-century homes.",
          voices=((RECORDER,),) * 4, tempo=(60, 80, 110)),
    Sound("continuo", "Voices + harpsichord continuo", "Early Baroque: singers over a bass line played by cello and "
          "harpsichord (the 'continuo', new in Monteverdi's time).",
          voices=((VOICE_OOHS,), (VOICE_OOHS,), (VOICE_OOHS, HARPSICHORD), (CELLO, HARPSICHORD)), tempo=(60, 84, 110)),
    Sound("lute_song", "Voice + lute", "A solo singer with the lower parts on a plucked lute (nylon guitar here).",
          voices=((VOICE_OOHS,), (NYLON_GUITAR,), (NYLON_GUITAR,), (NYLON_GUITAR,)), tempo=(60, 80, 100)),
    Sound("string_quartet", "String quartet", "Two violins, viola and cello: Haydn's and Mozart's favourite chamber group.",
          voices=((VIOLIN,), (VIOLIN,), (VIOLA,), (CELLO,)), tempo=(70, 100, 140)),
    Sound("harmonie", "Wind band (Harmonie)", "Classical-era wind ensembles played arrangements at courts and parties.",
          voices=((OBOE,), (CLARINET,), (FRENCH_HORN,), (BASSOON,)), tempo=(70, 96, 130)),
    Sound("piano", "Piano", "The Classical era's new instrument: all four voices on the keyboard.",
          voices=((PIANO,),) * 4, tempo=(60, 96, 140)),
    Sound("strings", "String orchestra", "All four voices on a warm string section.",
          voices=((STRINGS,), (STRINGS,), (STRINGS,), (CONTRABASS, CELLO)), tempo=(55, 76, 110)),
    # grooves: the melody on top, the band plays the chords
    Sound("hymn_walk", "Hymn with walking bass (band)", "A keyboard plays the chords while the bass walks, "
          "a little like a Baroque continuo.", grooves={4: "HymnWalk", 3: "HymnWalk"}, melody_program=OBOE,
          tempo=(60, 76, 100)),
    Sound("alberti", "Broken chords (band)", "Chords played as flowing arpeggios, like a Classical 'Alberti bass' "
          "or Bach's C-major Prelude.", grooves={4: "Arpeggio8", 3: "ArpeggioWaltz8"}, melody_program=VIOLIN,
          tempo=(70, 92, 130)),
    Sound("march", "March (band)", "A steady march, the kind of music the Classical era loved for parades.",
          grooves={4: "March", 2: "March", 6: "68March"}, melody_program=TRUMPET, tempo=(90, 112, 130)),
    Sound("waltz", "Waltz (band)", "Viennese waltz: arrived just after the Classical era (Schubert, Strauss).",
          grooves={3: "VieneseWaltz1Sus"}, melody_program=VIOLIN, tempo=(120, 160, 190)),
]}

# What suits each style, best first. Unknown styles get a sensible general list.
STYLE_SOUNDS: dict[str, list[str]] = {
    "palestrina": ["choir", "sackbuts", "recorders", "organ"],
    "monteverdi": ["continuo", "lute_song", "choir", "recorders"],
    "bach_chorale": ["choir_organ", "organ", "choir", "strings", "hymn_walk"],
    "classical": ["string_quartet", "piano", "harmonie", "alberti", "march"],
}
DEFAULT_SOUNDS = ["choir", "organ", "piano", "strings", "alberti"]

# Rough dates, used to explain unusual pairings.
STYLE_PERIOD = {"palestrina": (1550, 1600), "monteverdi": (1590, 1640), "bach_chorale": (1720, 1750),
                "classical": (1760, 1810)}
SOUND_PERIOD = {"string_quartet": 1755, "harmonie": 1760, "piano": 1770, "waltz": 1800, "march": 1750,
                "alberti": 1730, "continuo": 1600, "sackbuts": 1450, "recorders": 1400, "choir": 1000,
                "organ": 1300, "choir_organ": 1600, "lute_song": 1500, "strings": 1650, "hymn_walk": 1650}


def recommended(style: str) -> list[Sound]:
    return [SOUNDS[k] for k in STYLE_SOUNDS.get(style, DEFAULT_SOUNDS)]


def pairing_note(style_key: str, style_title: str, sound: Sound | None, groove: str | None = None) -> str:
    """One friendly sentence about how this style and sound fit together."""
    style_title = style_title.split(" (")[0]
    if sound is None and groove:
        return (f"Mashup: {style_title} harmony played by a {groove} band. The chords stay {style_title}'s; "
                "the rhythm and instruments come from the groove. A good way to hear what harmony "
                "contributes versus rhythm.")
    if sound is None:
        return ""
    if sound.key in STYLE_SOUNDS.get(style_key, []):
        return f"Recommended for {style_title}: {sound.why}"
    period = STYLE_PERIOD.get(style_key)
    born = SOUND_PERIOD.get(sound.key)
    if period and born and born > period[1] + 20:
        return (f"Time-travel pairing: {sound.name} came about {born - period[1]} years after {style_title}. "
                f"The harmony stays {style_title}'s. {sound.why}")
    if period and born and born < period[0] - 150:
        return f"An older sound than {style_title}, but it works. {sound.why}"
    return sound.why


GROOVE_CATEGORIES = [
    ("Classical-friendly", ("hymn", "arpeggio", "march", "waltz", "lullaby", "stringballad", "spiritual")),
    ("Latin", ("bossa", "samba", "rhumba", "mambo", "chacha", "tango", "beguine", "salsa", "merengue", "son",
               "bolero", "afro", "cuban", "calypso")),
    ("Jazz & swing", ("swing", "jazz", "bebop", "bigband", "dixie", "ragtime", "charleston", "strut", "softshoe",
                      "foxtrot", "quickstep", "evans", "jive")),
    ("Blues, soul & gospel", ("blues", "boggie", "rb", "soul", "doowop", "gospel")),
    ("Rock & pop", ("rock", "pop", "8beat", "twist", "ska", "funk", "trance", "fusion", "boneym")),
    ("Country & folk", ("country", "folk", "bluegrass", "western", "zydeco", "polka", "hillcountry")),
    ("Show & ballad", ("ballad", "broadway", "showtune", "desert", "lullaby")),
]


def groove_category(family: str) -> str:
    f = family.lower()
    for name, keys in GROOVE_CATEGORIES:
        if any(k in f for k in keys):
            return name
    return "Other"
