# Rameau Studio

*Learn harmony by hearing it.*

Rameau generates and harmonizes music in the style of different composers and eras, then
shows **why** it sounds that way: the chords each style favours, how they move, how phrases
end. It is named after Jean-Philippe Rameau, whose *Treatise on Harmony* (1722) founded the
theory of chords it teaches.

Status: early development. See [PLAN.md](PLAN.md).

## What works today

- **Harmonize a melody** (ABC, MusicXML or MIDI) in a learned style. The built-in Bach style
  is learned from Bach's 371 chorales.
- **Explain every chord**: melody fit, how often the style makes that move, cadences, ranked
  alternatives.
- **Four-part voices** (soprano, alto, tenor, bass) with a voice-leading rule checker
  (parallel fifths and octaves, crossing, spacing, leading tone, sevenths).
- **Export** MIDI, MusicXML (opens in MuseScore and similar), SVG sheet music and a written explanation.
- **Play** through FluidSynth.
- **Style fingerprints**: compare the signature habits of styles side by side.

## Try it

```bash
uv sync
uv run rameau harmonize src/rameau/samples/old_hundredth.abc --out out --svg --play
uv run rameau fingerprint bach_chorale palestrina classical
uv run rameau styles
```

Playback needs FluidSynth (`brew install fluid-synth`, `apt install fluidsynth`) and a
SoundFont. Put [GeneralUser GS](https://schristiancollins.com/generaluser.php) in
`~/Library/Application Support/rameau-studio/soundfonts/` (macOS),
`%APPDATA%\rameau-studio\soundfonts\` (Windows) or `~/.local/share/rameau-studio/soundfonts/` (Linux).

## How it works

1. **Learn** (`rameau/train.py`): count chords, chord-to-chord moves, melody notes over each
   chord, phrase endings and inversions in a corpus of harmonized pieces.
2. **Choose chords** (`rameau/harmonize.py`): a hidden Markov model picks the best chord path
   for the melody; forward-backward probabilities give alternatives for every beat.
3. **Write voices** (`rameau/voicing.py`): every legal SATB spacing is scored and the
   smoothest path is chosen, avoiding textbook faults (`rameau/rules.py`).
4. **Render** (`rameau/render.py`): score, notation, MIDI, explanation.

## License

GPL-3.0-or-later. Uses music21 (BSD), Verovio (LGPL), PySide6/Qt (LGPL), FluidSynth (LGPL)
and MMA (GPL-2.0-or-later, in `engine/mma`).
