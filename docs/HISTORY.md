# How Rameau came to be: what we built and why

A plain-language record of the decisions behind Rameau Studio, in the order they were made
(October 2026). For what we learned along the way see [LESSONS.md](LESSONS.md); for where it's
going see [DIRECTION.md](DIRECTION.md).

## 1. The starting point: "a better LeMMA"

**What:** The first idea was a cross-platform fork of [MMA](https://github.com/infojunkie/mma)
(Musical MIDI Accompaniment), with a friendlier interface than
[LeMMA](https://welltemperedstudio.wordpress.com/code/lemma/), for Mac, Windows and Linux.

**Why we changed course:** MMA is already open Python, so there was nothing to reverse-engineer
(the reverse-engineering tool `morluto/rea` wasn't needed). Talking through the goals also showed
that a backing-track editor wasn't the real aim. The real aim was **outcomes**: harmonize a
melody, harmonize it *in a style*, build style libraries, and start from chord symbols as well as
melodies. We weren't trying to copy Band-in-a-Box.

## 2. The vision

> "At the end of the day, I want to generate music from different eras and composers either by
> supplying a melody or a style of pattern. This teaches us how harmonies work to create the
> signature sound of a composer or musical style or era."

That gives two halves of equal weight, **teaching and performance**. (An early draft said
"teaching first". That was wrong and was corrected.)

- **Generate:** give it a melody or a pattern, choose an era, and hear music in that style.
- **Reveal:** show what makes it sound like that era: which chords it favours, how they move, how
  phrases end.

## 3. Architecture: an explainable harmony engine, not a black box

**What:** The core is a harmony engine built on [music21](https://github.com/cuthbertLab/music21).
It *learns* each style from real scores, counting which chords appear, what follows what, what
melody notes sit over which chords, and how phrases end. It then harmonizes with a classic
probabilistic method: a hidden Markov model, decoded with Viterbi and forward-backward. MMA was
moved behind an adapter and plays the "backing band" grooves.

**Why:**
- **It can explain itself.** Every chord comes with reasons ("IV is likelier here on its own, but
  V/V leads better into the cadence"). A neural network can't easily say why it chose a chord, and
  explaining is half of the product.
- **It learns from small data.** 371 Bach chorales are enough. Big models such as DeepBach,
  ChatMusician or MuPT need large training sets, GPUs and licensing work. We kept them in view as
  an optional later "AI mode" rather than building on them.
- **It's honest about style.** A style is chord vocabulary + progressions + harmonic rhythm +
  voicing + texture + rules. All of these can be measured and compared between styles.

We considered Magenta and the ideas in a Perplexity research report (`Direct answer.pdf`). We
used them as design references, not dependencies.

## 4. Name and licence

- **Rameau**, after Jean-Philippe Rameau, whose *Traité de l'harmonie* (1722) founded the theory
  of chords the app teaches. "He literally wrote the book." The package and repo are
  `rameau-studio`, because `rameau` is taken on PyPI.
- **GPL-3.0-or-later.** We first thought about keeping the option to sell it some day, then
  decided that was over-thinking it. The GPL stops anyone from taking Rameau, closing it up and
  selling it, and it lets us build on other open-source work (MMA is GPL-2.0-or-later, iReal
  parsing is GPL-3, and music21, Qt, Verovio and FluidSynth are all compatible).

## 5. Platform: Python + Qt, built-in sound

Python + PySide6 (Qt), because music21 and MMA are both Python and Qt runs on all three operating
systems. Sound comes from FluidSynth with the GeneralUser GS SoundFont, so you need no external
synth. Notation is drawn by Verovio.

## 6. Building it up (in order)

1. **Bach harmonizer + explanations:** fingerprint training, HMM harmonizer, SATB voicing,
   voice-leading checker, Verovio score, MIDI/MusicXML export, CLI, desktop app.
2. **Style + sound together:** each style suggests matching ensembles ("Bach chorales were sung
   by a choir with the organ doubling the voices") and flags odd pairings ("Palestrina + bossa
   nova: a mashup").
3. **Public GitHub repo** with a firm rule: **no API keys in the code or repo, ever.** Keys come
   only from environment variables or the operating system's keychain.
4. **Era textures** (chorale suspensions, Renaissance held notes, continuo, Classical
   accompaniment) and **analysis fixes** (phrase endings, modal finals, local keys).
5. **Generate from a pattern:** chord symbols, Roman numerals or an invented progression, with a
   melody composed from the style's own melodic habits.
6. **AI mode (optional, bring your own key):** a tutor that answers questions about the score on
   screen, and a composer that writes melodies in ABC. It supports several named keys, Anthropic
   (Claude Haiku by default) and OpenAI, and you choose the model from a live list.
7. **More eras:** Romantic, plus seven 20th-century styles (jazz standards, ballad, bossa,
   Dixieland, blues, pop/rock, country) learned from ~2,200 iReal Pro charts. Only the statistics
   are committed, never the charts.
8. **Cross-platform for real:** CI on Windows/Linux/macOS, PyInstaller installers with the
   SoundFont and FluidSynth bundled, and a step-entry note editor.
9. **"It all sounds the same."** Dean's honest reaction was that the output was "just playing
   chords, not making music… muddy… basic strumming with different MIDI voices." This was the
   most important turn in the project. In response we built:
   - a **performance layer** (phrasing, breathing at cadences, swing, articulation, slight human
     timing),
   - **independent lines** (a bass that moves against the melody, not under it),
   - **ornaments learned from the corpus** (passing notes, suspensions, neighbours, at each
     style's own rate),
   - **real jazz and pop comping** (walking bass, Charleston rhythms, pianist voicings),
   - an **Adventure** control that picks less obvious chords the style really uses, while keeping
     its cadences.
10. **Live filter unit:** "can we make changes live instead of re-orchestrate and hit play every
    time?" Yes. The pipeline is now staged and cached (harmony → lines → texture → performance →
    mixer). A change re-runs only the stages after it, and the new version is swapped in at the
    next bar without stopping. Performance changes take ~0.01 s and harmony ~0.7 s.
11. **A calmer main screen:** "utilitarian… no taste… restraint and simplicity are key." We chose
    a hybrid design: an HTML/CSS canvas inside Qt (QWebEngine), with Qt still doing the real work.
    It has an era timeline, the score on a paper page, a colour-coded harmony strip, chord cards
    that explain themselves, and four dials (Character, Motion, Feel, Space). All the detailed
    controls are tucked behind ⚙.

## 7. Where things stand

The project is public at https://github.com/deanpeters/rameau-studio, with 65 tests passing on
three operating systems. Installers have been built and smoke-tested on all three. A public
v0.1.0 release has not been tagged yet; that waits on Dean's go-ahead.
