"""The "filter unit": musical controls users can change while the music plays.

Each control belongs to a stage of the pipeline. Changing a control re-runs only that stage and the
ones after it:

    harmony (chords)  ->  lines (voice leading)  ->  texture (ornaments, comping)  ->  performance  ->  mixer
    Adventure            Bass independence           Ornament density/kinds          Expression,     instrument,
                                                     Variation                       Rubato, Swing,  volume, pan,
                                                                                     Articulation,   mute/solo,
                                                                                     Humanize, Tempo reverb (instant)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields

ORNAMENT_KINDS = ("passing", "neighbor", "anticipation", "arpeggio", "suspension")
STAGES = ("harmony", "lines", "texture", "performance")


@dataclass
class Controls:
    # harmony
    adventure: float = 0.0            # 0 = safest chords ... 1 = most adventurous
    # lines
    bass_independence: float = 1.0    # 0 = plain block-chord bass ... 2 = very melodic, contrary bass
    # texture
    ornament_density: float = 1.0     # 0 = none, 1 = the style's own rates, 2 = twice as busy
    ornament_kinds: list[str] = field(default_factory=lambda: list(ORNAMENT_KINDS))
    variation: int = 1                # a different random realization of the same choices
    # performance
    expression: float = 1.0           # dynamics and accents: 0 = flat ... 2 = dramatic
    rubato: float = 1.0               # slowing into cadences and held fermatas: 0 = strict time
    swing: float | None = None        # None = the style's own feel; 0 = straight ... 1 = hard swing
    articulation: float = 0.0         # -1 legato ... 0 natural ... +1 detached
    humanize: float = 1.0             # tiny timing/loudness variations: 0 = machine-exact
    tempo: int = 80
    # mixer (applied instantly)
    reverb: float = 0.35              # 0 = dry ... 1 = cathedral

    def stage_changed(self, other: "Controls") -> str | None:
        """The earliest pipeline stage whose controls differ (None = only mixer or nothing)."""
        groups = {
            "harmony": ("adventure",),
            "lines": ("bass_independence",),
            "texture": ("ornament_density", "ornament_kinds", "variation"),
            "performance": ("expression", "rubato", "swing", "articulation", "humanize", "tempo"),
        }
        for stage in STAGES:
            if any(getattr(self, f) != getattr(other, f) for f in groups[stage]):
                return stage
        return None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Controls":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})


def tune_style(style, c: Controls):
    """Apply performance controls to a performance Style (see performance.py)."""
    import dataclasses

    swing_on = style.swing if c.swing is None else c.swing > 0.02
    ratio = style.swing_ratio if c.swing is None else 0.5 + 0.25 * c.swing
    return dataclasses.replace(
        style,
        rit=1 - (1 - style.rit) * c.rubato,
        fermata=1 + (style.fermata - 1) * c.rubato,
        final_rit=1 - (1 - style.final_rit) * c.rubato,
        rit_beats=style.rit_beats if c.rubato > 0 else 0,
        swell=round(style.swell * c.expression),
        accent=round(style.accent * c.expression),
        humanize_ms=style.humanize_ms * c.humanize,
        humanize_vel=round(style.humanize_vel * c.humanize),
        swing=swing_on,
        swing_ratio=ratio,
        articulation=c.articulation,
    )


def tune_levels(levels: dict[int, int], c: Controls) -> dict[int, int]:
    """Expression also controls voice balance: 0 makes every part equally loud."""
    mean = sum(levels.values()) / len(levels)
    return {k: round(mean + (v - mean) * min(1.5, c.expression)) for k, v in levels.items()}


PRESETS: dict[str, Controls] = {
    "Plain study (blocks, strict time)": Controls(bass_independence=0.0, ornament_density=0.0, expression=0.0,
                                                  rubato=0.0, humanize=0.0),
    "Natural (the style as learned)": Controls(),
    "Expressive": Controls(expression=1.6, rubato=1.5, humanize=1.3),
    "Flowing (busy inner voices)": Controls(bass_independence=1.6, ornament_density=1.8, articulation=-0.4),
    "Adventurous harmony": Controls(adventure=0.6),
    "Late-night jazz": Controls(swing=0.75, expression=0.8, rubato=0.4, articulation=-0.2, reverb=0.5),
    "Bright and crisp": Controls(articulation=0.6, expression=1.2, rubato=0.3, reverb=0.15),
}

# General MIDI instrument names (program numbers 0-127), for the mixer's instrument menus.
GM_NAMES = [
    "Acoustic Grand Piano", "Bright Piano", "Electric Grand", "Honky-tonk Piano", "Electric Piano 1",
    "Electric Piano 2", "Harpsichord", "Clavinet", "Celesta", "Glockenspiel", "Music Box", "Vibraphone",
    "Marimba", "Xylophone", "Tubular Bells", "Dulcimer", "Drawbar Organ", "Percussive Organ", "Rock Organ",
    "Church Organ", "Reed Organ", "Accordion", "Harmonica", "Tango Accordion", "Nylon Guitar", "Steel Guitar",
    "Jazz Guitar", "Clean Electric Guitar", "Muted Guitar", "Overdriven Guitar", "Distortion Guitar",
    "Guitar Harmonics", "Acoustic Bass", "Fingered Bass", "Picked Bass", "Fretless Bass", "Slap Bass 1",
    "Slap Bass 2", "Synth Bass 1", "Synth Bass 2", "Violin", "Viola", "Cello", "Contrabass", "Tremolo Strings",
    "Pizzicato Strings", "Orchestral Harp", "Timpani", "String Ensemble 1", "String Ensemble 2",
    "Synth Strings 1", "Synth Strings 2", "Choir Aahs", "Voice Oohs", "Synth Voice", "Orchestra Hit",
    "Trumpet", "Trombone", "Tuba", "Muted Trumpet", "French Horn", "Brass Section", "Synth Brass 1",
    "Synth Brass 2", "Soprano Sax", "Alto Sax", "Tenor Sax", "Baritone Sax", "Oboe", "English Horn",
    "Bassoon", "Clarinet", "Piccolo", "Flute", "Recorder", "Pan Flute", "Blown Bottle", "Shakuhachi",
    "Whistle", "Ocarina", "Square Lead", "Sawtooth Lead", "Calliope Lead", "Chiff Lead", "Charang Lead",
    "Voice Lead", "Fifths Lead", "Bass + Lead", "New Age Pad", "Warm Pad", "Polysynth Pad", "Choir Pad",
    "Bowed Pad", "Metallic Pad", "Halo Pad", "Sweep Pad", "Rain", "Soundtrack", "Crystal", "Atmosphere",
    "Brightness", "Goblins", "Echoes", "Sci-fi", "Sitar", "Banjo", "Shamisen", "Koto", "Kalimba", "Bagpipe",
    "Fiddle", "Shanai", "Tinkle Bell", "Agogo", "Steel Drums", "Woodblock", "Taiko Drum", "Melodic Tom",
    "Synth Drum", "Reverse Cymbal", "Guitar Fret Noise", "Breath Noise", "Seashore", "Bird Tweet",
    "Telephone Ring", "Helicopter", "Applause", "Gunshot",
]


# --------------------------------------------------------------------------- macro dials
# Four musical dials on the main screen, each moving several detailed controls together.
# Defaults sit in the middle of Motion and Feel (the style "as learned").

MACROS = ("character", "motion", "feel", "space")


def macros_from(c: Controls) -> dict[str, float]:
    """Where the four dials sit for these detailed settings (an approximate inverse of apply_macro)."""
    clamp = lambda v: max(0.0, min(1.0, v))
    return {
        "character": clamp(c.adventure / 0.7),
        "motion": clamp((c.ornament_density / 2 + (c.bass_independence - 0.4) / 1.2) / 2),
        "feel": clamp((c.expression / 2 + c.rubato / 2) / 2),
        "space": clamp(c.reverb),
    }


def apply_macro(c: Controls, name: str, v: float) -> Controls:
    import dataclasses

    v = max(0.0, min(1.0, v))
    if name == "character":
        return dataclasses.replace(c, adventure=round(0.7 * v, 3))
    if name == "motion":
        return dataclasses.replace(c, ornament_density=round(2 * v, 3), bass_independence=round(0.4 + 1.2 * v, 3))
    if name == "feel":
        return dataclasses.replace(c, expression=round(2 * v, 3), rubato=round(2 * v, 3),
                                   humanize=round(0.4 + 1.2 * v, 3))
    if name == "space":
        return dataclasses.replace(c, reverb=round(v, 3))
    raise ValueError(name)
