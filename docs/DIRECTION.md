# Where Rameau is going

The north star stays the same: **generate music from different eras and composers, from a melody
or a pattern, and show how harmony creates each one's signature sound.** Teaching and performance
carry equal weight.

## Principles we'll keep

1. **Explainable first.** Every musical choice can be traced back to something learned from real
   music, and explained in plain words.
2. **Musical, not just correct.** Performance, independent lines and texture are as important as
   chord choice.
3. **Live.** Changes are heard while the music plays.
4. **Restraint.** The main screen stays simple. Depth is available but tucked away.
5. **Open and safe.** GPL-3.0-or-later, and no secrets in the repo. AI is optional and
   bring-your-own-key.

## Next (near term)

- **Release v0.1.0** on GitHub with the installers (waiting for Dean's go-ahead). Rebuild the
  installers with the new main screen first and check live audio in the packaged app.
- **Score follows the music:** light up notes in the score as they play. Loop a range of bars,
  not only the whole piece.
- **Main-screen polish:** check the light theme, and handle long pieces in the harmony strip
  (labels are truncated when chords are short).
- **Better analysis:** detect cadences from the bass and harmony (fixes Classical), find more
  modulations in Bach, and add proper modal keys for Renaissance music.
- **Step entry:** undo, click-to-select notes, MIDI keyboard input.
- **Live band grooves:** today only the mixer and tempo change live for MMA grooves; make more of
  them live.

## Later

- **Style Lab:** build your own style from a folder of scores, MIDI or iReal Pro charts ("smooth
  jazz", "Bach cantatas"), browse what it learned, and share Style Packs with their source
  licences recorded.
- **Melody from MIDI or ABC** (via abc2midi), with cleaner MIDI import.
- **Teaching modes:** exercises ("harmonize this line, then compare with Bach"), guided
  journeys through the eras, and voice-leading feedback in plain words.
- **Groove learning:** extract an accompaniment pattern from MIDI files (building on MMA's
  `mid2mma.py`).
- **AI, carefully layered:** the tutor and composer already exist. Next, an optional trained
  model (our own, or an existing one made for this) to propose ideas, with Rameau's engine still
  checking and explaining every choice.
- **Distribution:** signed installers, Intel Mac support, smaller downloads, FluidSynth bundled on
  Linux.

## Questions still open

- Who comes first: the theory student (rules, grading) or the performer (play-along, practice)?
  This decides the order of teaching modes versus performance features.
- Should Style Packs become a shared community library? If so, we need a provenance and
  licensing policy for corpora.
- Do we contribute fixes back to MMA upstream?
