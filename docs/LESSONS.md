# What we learned

Lessons from building Rameau, grouped by theme. Each one cost us a bug or a rethink.

## About music and the product

- **Correct isn't the same as musical.** The first harmonizations broke no rules and were dull:
  block chords in a different instrument. What makes a style recognisable is mostly *how* it's
  played (phrasing, independent lines, ornaments, comping rhythms), not only *which* chords it
  uses. Performance has to be a first-class layer, not decoration.
- **You learn by contrast.** "Bach uses V/V" means little on its own. It means a lot next to
  Palestrina (who almost never does) and a jazz ballad (who does it all the time with added 9ths).
  Hence the era timeline (same tune, different centuries) and the signature-sounds view, which
  compares a style with its neighbours in time.
- **Explanations must be plain language.** Percentages ("p = 0.12") became "less common" and
  "rare". Function names became colours (home, moving away, tension, colour).
- **Style and sound belong together.** Palestrina on a funk groove is a mashup, so the app should
  say so gently rather than forbid it.
- **Hearing changes live is how people learn.** Re-rendering and pressing play again breaks the
  connection between a change and what it does. Swapping the new version in at the next bar keeps
  it.
- **Adventure needs guard rails.** Unconstrained sampling sounded random. Keeping each style's
  cadences and final chord fixed while loosening the middle kept it sounding like the style.
- **Restraint beats more controls.** The detailed sliders are still there, but behind ⚙. The main
  screen has four musical dials that each move several settings together.

## About the analysis

- **music21 has blind spots we had to patch.** The ABC reader drops fermatas and bar-scoped
  accidentals, minor-key V7 came back as "V75#3", and offsets need rounding before you can
  compare them. Always check its labels against what a musician would write.
- **Chord naming is a teaching decision.** We made "7" always mean dominant (major sevenths are
  "M7"), so students aren't misled.
- **Modal music needs modal keys.** Renaissance pieces end on their modal final, so the key
  comes from the final, with mode names.
- **Some analysis is still weak, and we should say so.** Classical cadences are under-detected
  from the top line alone, and local-key detection under-counts Bach's modulations. These are
  listed as known limitations, not hidden.
- **Chord charts have no melody.** The iReal Pro styles learn progressions but not melody-over-
  chord habits, so they fall back on a music-theory prior. That's honest and works well enough.

## About engineering

- **Keep Qt objects alive until their signals arrive.** The app's worst crashes came from
  background-job objects being garbage-collected before Qt delivered their results. `start_job`
  now holds on to them.
- **Some libraries are bound to one thread.** Verovio only had its fonts on the first thread that
  used it, so it now runs on one dedicated thread.
- **Never commit machine-generated caches.** A committed MMA groove index (`.mmaDB`) held paths
  from one machine and broke CI everywhere else. It's now rebuilt when stale.
- **Windows needs explicit UTF-8, and no blocking dialogs in CI.** An error dialog in a windowed
  build hung the Windows job for its whole time limit, so CLI errors now exit with a code.
- **Pin downloads directly.** Looking up FluidSynth through the GitHub API hit rate limits, so we
  pinned a direct release URL.
- **Stage and cache the pipeline.** Splitting the work into harmony → lines → texture →
  performance → mixer made live changes possible, and made each stage easier to test.
- **A web canvas inside Qt is a good compromise.** HTML/CSS gives taste and typography cheaply.
  Qt keeps the audio, files and native menus, and a small bridge (`ui/bridge.py`) drives the same
  widgets the rest of the app uses, so behaviour stays in one place.

## About security

- **Secrets never touch the repo or the settings file.** API keys come only from environment
  variables or the OS keychain (`keyring`). The settings file stores only profile names and
  models, and refuses anything that looks like a key. `.gitignore` blocks `.env`, `*.key`,
  `*.pem` and `secrets.*`, and every push is preceded by a scan for secrets.
- **Friendly failures matter.** "Credit balance too low" or "invalid key" should read as a clear
  next step, not a stack trace. The app also works fully without AI.

## About working together

- **Announce builds and give short progress updates.** Long silent builds left Dean in the dark.
- **Don't project.** When AI research suggested big models (MuPT, SymphonyNet, DeepBach), the
  right question was "how is that different from what I want?" The answer kept us on an
  explainable engine, with trained models as an optional later layer.
- **Honest feedback is the best input.** "It all sounds the same" and "no taste" led to the two
  biggest improvements.
