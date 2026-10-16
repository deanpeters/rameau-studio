# Rameau Studio

[![tests](https://github.com/deanpeters/rameau-studio/actions/workflows/tests.yml/badge.svg)](https://github.com/deanpeters/rameau-studio/actions/workflows/tests.yml)

*Learn harmony by hearing it.*

Rameau generates and harmonizes music in the style of different composers and eras, then
shows **why** it sounds that way: the chords each style favours, how they move, how phrases
end. It is named after Jean-Philippe Rameau, whose *Treatise on Harmony* (1722) founded the
theory of chords it teaches.

Status: early development. See [PLAN.md](PLAN.md).

## Download

Builds for macOS (Apple Silicon), Windows and Linux are attached to each
[release](https://github.com/deanpeters/rameau-studio/releases). They're not code-signed yet:

- **macOS:** unzip, then right-click *Rameau Studio* → **Open** the first time (Gatekeeper warning).
- **Windows:** unzip and run `RameauStudio.exe`; choose **More info → Run anyway** on the SmartScreen prompt.
- **Linux:** untar and run `RameauStudio/RameauStudio`. For sound: `sudo apt install fluidsynth`.

## Styles

| Era | Styles | Learned from |
|---|---|---|
| Renaissance | Palestrina, Monteverdi | music21 corpus scores |
| Baroque | Bach chorale | 371 chorales |
| Classical / Romantic | Classical (Mozart, Haydn, Beethoven), Romantic (Chopin, Schubert, Schumann, Beach) | music21 corpus scores |
| 20th century | Dixieland, Jazz standards, Jazz ballad, Bossa nova & Latin, Blues, Pop & rock, Country | ~2,200 iReal Pro chord charts |

Train your own from a folder of scores or iReal Pro playlists: `rameau train-folder ./my_charts --name smooth_jazz`.

## What works today

- **Harmonize a melody** (ABC, MusicXML or MIDI) in a learned style. The built-in Bach style
  is learned from Bach's 371 chorales.
- **Explain every chord**: melody fit, how often the style makes that move, cadences, ranked
  alternatives.
- **Four-part voices** (soprano, alto, tenor, bass) with a voice-leading rule checker
  (parallel fifths and octaves, crossing, spacing, leading tone, sevenths).
- **Export** MIDI, MusicXML (opens in MuseScore and similar), SVG sheet music and a written explanation.
- **Play** through FluidSynth.
- **Style fingerprints**: compare the signature habits of styles side by side: chords, harmonic
  rhythm, melodic steps vs leaps, voice activity, modes and modulations.
- **Era textures**: Bach's passing notes and suspensions, Palestrina's held common tones,
  Monteverdi's continuo bass, Classical repeated-note accompaniment.
- **Generate from a pattern**: type chords (`| C Am | F G7 |`) or Roman numerals (`| I vi | IV V7 |`),
  or let a style invent a progression; Rameau composes a melody and four voices in that style.
- **Style + sound guidance**: each style recommends ensembles (choir + organ, string quartet,
  cornetts & sackbuts…) and explains unusual pairings.
- **Step-entry editing**: type notes (A–G, durations 1–5) or click an on-screen piano; live sheet music.
- **Open iReal Pro charts** in the Chords tab, shown as Roman numerals.
- **Optional AI mode** (bring your own Anthropic API key): a tutor that answers questions about the
  piece on screen, grounded in Rameau's analysis, and a melody composer. Default model:
  `claude-haiku-5-5`.

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

## AI mode (optional)

Rameau works fully without AI. To enable the tutor and AI composer, either:

- set the `ANTHROPIC_API_KEY` environment variable, or
- open **AI settings…** in the app and add one or more named keys (e.g. *Personal*, *Work*). Each
  is stored in your operating system's keychain (macOS Keychain, Windows Credential Manager,
  Linux Secret Service), never in a file.

Switch keys and models from the **Ask the tutor** tab or AI settings. The model list is loaded live
from Anthropic for the selected key (default `claude-haiku-5-5`); you can also type any model name,
or set `RAMEAU_AI_MODEL`.

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
