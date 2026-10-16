# Rameau — plan

*Learn harmony by hearing it.*

## Vision (Dean, 2026-10-15)

> "At the end of the day, I want to generate music from different eras and composers either
> by supplying a melody or a style of pattern. This teaches us how harmonies work to create
> the signature sound of a composer or musical style or era."

So Rameau has two equal halves that share one idea, the **style fingerprint**:

1. **Generate:** give it a melody *or* a pattern (a chord progression, a groove, a form) and
   pick an era/composer, and it produces music in that style.
2. **Reveal:** show *what makes it sound like that composer*: the chords they favour, how they
   move, how phrases end, how voices are spaced, and how that differs from other eras.

A cross-platform (macOS, Windows, Linux) desktop app that generates and harmonizes music in
a chosen era or composer's style, explains the choices, and plays it back with a built-in band.
Built on music21 (analysis), MMA (accompaniment), Verovio (notation) and FluidSynth (sound).
Named after Jean-Philippe Rameau, whose *Treatise on Harmony* (1722) founded the chord
theory the app teaches.

## Sources

| Piece | Repo | License | Role |
|---|---|---|---|
| MMA engine | [infojunkie/mma](https://github.com/infojunkie/mma) (25.05.3, Jun 2026) | GPL-2.0-or-later (verified in file headers; bundled `appdirs.py` is MIT) | **Accompaniment backend behind an adapter** (subprocess). Not the core. Fork only for small upstreamable patches. |
| music21 | [cuthbertLab/music21](https://github.com/cuthbertLab/music21) (10.5.0, Jun 2026) | BSD-3 (corpus items vary) | **Primary music library**: score model, import/export, analysis, Bach chorale corpus |
| Verovio | [rism-digital/verovio](https://github.com/rism-digital/verovio) | LGPL-3.0 | Notation rendering |
| ChoraleHarmonizer | [TimoKellerMath/ChoraleHarmonizer](https://github.com/TimoKellerMath/ChoraleHarmonizer) (3 commits) | MIT | Reference / possible collaboration: explicit voice-leading rules, corpus-calibrated weights |
| BacHMMachine | [arXiv 2109.07623](https://arxiv.org/abs/2109.07623) | Paper | Design reference: HMM keys/chords → constrained SATB voicing |
| CHAMELEON | [maximoskp/chameleon](https://github.com/maximoskp/chameleon) | **No license** (ideas only, no code) | Reference: learned and blended harmonic idioms |
| JJazzLab | [jjazzboss/JJazzLab](https://github.com/jjazzboss/JJazzLab) (5.2.1, Apr 2026) | LGPL-2.1, Java | Benchmark for the performance/backing-track experience; possible plugin host later |
| Impro-Visor | [Impro-Visor/Impro-Visor](https://github.com/Impro-Visor/Impro-Visor) (last push Dec 2023) | GPL-2.0, Java | Reference: jazz teaching, style extraction from MIDI + lead sheet |
| MMA upstream | [mellowood.ca/mma](https://www.mellowood.ca/mma/) (site still lists 21.09.3) | GPL | Docs, groove library reference |
| LeMMA | [geksiong/LeMMA](https://github.com/geksiong/LeMMA) (0.9a, last push 2019) | GPL-3.0 | Feature reference only, not code |
| iReal import | [infojunkie/ireal-musicxml](https://github.com/infojunkie/ireal-musicxml) (JS) | GPL-3.0 | Reference for a Python port of the parser |

## Name and license (decided 2026-10-15)

- **Name:** Rameau. Package and repo name **`rameau-studio`** (the bare `rameau` is taken on
  PyPI). Named after Jean-Philippe Rameau, who literally wrote the book on harmony:
  *Traité de l'harmonie* (1722).
- **License: GPL-3.0-or-later** (decided 2026-10-15). Anyone may use, change or even sell
  copies, but they must keep it under the GPL and publish their source. Nobody can take
  Rameau, close it up and sell it as their own product. We can freely build on other
  GPL projects (MMA, LilyPond, mingus), plus everything permissive (MIT/BSD/Apache:
  music21, ChoraleHarmonizer, magenta-js) and LGPL (Qt/PySide6, Verovio, FluidSynth).
- **Watch:** "GPL-2.0-only" code cannot be combined with GPL-3 (e.g. check Impro-Visor's
  file headers before reusing anything). MMA is GPL-2.0-or-later, so it's fine.
- **Keep the option open:** as long as we own the copyright in our own code (contributors
  sign a simple contributor agreement), we can still offer it under other terms later.
- **Data has its own licenses:** SoundFont, music21 corpus items and style-pack source
  pieces. Track these in `corpus.json` and a `THIRD_PARTY_LICENSES` file.

## Decisions (made)

- **Architecture (revised 2026-10-15 after the Perplexity review):** the product's core is
  an **explainable harmony engine built on music21**. The app owns the canonical score
  and harmonic-plan model. MMA is one replaceable realization backend. Pipeline:
  import (music21) → harmonic planning (keys, chord functions, ranked alternatives) →
  voicing/counterpoint (style-specific constraints) → arrangement/groove (MMA adapter)
  → performance events → FluidSynth / MIDI out. The score model also feeds Verovio
  (notation), MusicXML export and the explanation panel.
- **Neural models** may *propose* candidates. An explicit scorer accepts or rejects them
  and records the reasons, labeled as a rule assessment, not as the model's reasoning.
- **Style learning promise:** "learn statistical profiles from validated symbolic
  corpora" (pieces with chord/key annotations, or reliably detected chords), not "learn
  any style from any folder of MIDI."
- **Stack:** Python 3.12+ and PySide6 (Qt 6). MMA runs as a subprocess.
- **Playback:** bundled FluidSynth plus a freely redistributable General MIDI SoundFont
  (e.g. GeneralUser GS; check its license before bundling). Optional output to
  external MIDI devices and DAWs through python-rtmidi.
- **v1 scope:** chord sheet, full `.mma` editor, and imports from iReal Pro and MusicXML.

## Repo layout

```
rameau-studio/
  engine/            pinned copy of infojunkie/mma, run as a subprocess (patches kept small and upstreamable)
  src/rameau/
    app.py           QApplication entry
    model/           Song model (sections, bars, chords, groove, tempo, key)
    render/          Song -> .mma text; engine runner (in-process, captures errors)
    audio/           FluidSynth player, transport (play/stop/loop/position), MIDI out
    ui/
      chord_sheet/   Bar grid editor (QTableView + delegate)
      groove/        Groove browser (search, categories, preview-on-click)
      editor/        .mma code editor (QSyntaxHighlighter, error gutter)
    importers/       ireal.py, musicxml.py
  resources/         SoundFont, icons
  packaging/         PyInstaller/Briefcase specs, CI workflows
  tests/
```

### Engine integration

- MMA keeps global state in `MMA.gbl` and calls `sys.exit` on errors. Run each render
  in a **subprocess worker** (`python -m mma ...` from the bundled interpreter) for
  isolation. Optimise to in-process later only if it proves too slow.
- Build the groove index once at first launch (`mma -G`, about 2 s) and cache it in
  the user data directory.
- Parse MMA's error output (file:line) into editor markers.
- Changes to the fork should be small and upstreamable: a non-exiting error
  hook, a JSON groove listing, and machine-readable bar/time mapping for the
  playhead.

## v1 features

1. **Chord sheet:** bar grid; type chords (`Cmaj7`, `Am7/G`, `/` repeats); sections
   (A/B, repeats, endings); per-section groove, tempo, key; transpose; undo/redo.
2. **Groove browser:** all library grooves with descriptions; click to preview over
   the current bars; favourites.
3. **Transport:** play, stop, loop selection, tempo override, playhead follows the bar,
   per-track mute and volume (Bass, Chord, Drum, ...).
4. **Code view:** the generated `.mma` updates live. Users can switch a song to "text
   mode" and edit any `.mma` file directly, with syntax highlighting, error markers
   and autocomplete for commands and grooves.
5. **Import:** iReal Pro (`irealb://` links and HTML playlists, ported to
   Python) and MusicXML (`<harmony>` elements to chord bars, using stdlib
   ElementTree).
6. **Export:** `.mma`, `.mid`, and `.wav` (FluidSynth offline render).

## Packaging and CI

- GitHub Actions matrix: macOS (universal or arm64 + x86_64), Windows, Ubuntu.
- macOS: `.dmg`, signed and notarized (needs an Apple Developer ID, $99/yr).
  Windows: installer (MSIX or Inno Setup); code signing is optional at first.
  Linux: AppImage, Flatpak later.
- FluidSynth native libraries are bundled per platform. This is the main packaging risk,
  so prove it in Milestone 0.

## Built in session 1 (2026-10-15)

Working on macOS, 16 tests passing, two local commits:

- **Fingerprint engine:** learns chord vocabulary, moves, melody-over-chord, cadences and
  inversions from a corpus (`train.py`). Styles shipped: Bach chorales (371), Palestrina
  (400), Monteverdi (49), Classical (Mozart/Haydn/Beethoven).
- **Harmonizer** (`harmonize.py`): HMM / Viterbi with forward-backward alternatives, chord
  locking, plain-English reasons, including trade-offs ("IV is likelier here alone, but V/V
  connects better").
- **SATB voicing + rule checker** (`voicing.py`, `rules.py`): parallels, crossing, spacing,
  ranges, leading tone, sevenths.
- **Outputs** (`render.py`): MusicXML, MIDI, Verovio SVG notation, markdown explanation.
- **Band** (`band.py`): chord chart or harmonization → MMA groove (1,167 grooves) with the
  melody merged on top.
- **Sound** (`audio.py`): FluidSynth + GeneralUser GS.
- **Fingerprints** (`fingerprint.py`): side-by-side style comparison and signature moves.
- **CLI** (`rameau harmonize | styles | fingerprint | train-folder`) and **desktop app**
  (`rameau-studio`): melody/chord input, style/key/sound pickers, score, Why panel with
  click-to-try alternatives, voice-leading check, fingerprint tab, play, export.

Feedback from Dean after the first run (2026-10-15):
- **Guide style + sound together.** Each style should come with recommended sounds
  (instruments per voice, tempo range, texture or groove), a one-line "why" (e.g. Bach
  chorales were sung by a choir with the organ doubling the voices), and a gentle flag for
  unusual pairings ("Palestrina + Bossa Nova: a mashup; the harmony stays Renaissance").
  Grooves should be grouped and suggested per style rather than shown as 1,167 names.
- **AI mode, bring your own key** (future): in Settings, the user enters an API key and a model
  name (Anthropic, OpenAI, OpenRouter, or a local server such as Ollama/LM Studio). Uses:
  (a) **tutor**: chat about the current score ("why does Bach use V/V here?", "what would
  Mozart do differently?"), grounded in Rameau's own analysis and fingerprints;
  (b) **composer**: ask for melodies or variations in ABC, which Rameau then harmonizes,
  checks and explains; (c) **guide**: suggest style/sound pairings and next experiments.
  Keys stay on the user's machine (OS keychain); the app works fully without AI.
- *Built 2026-10-15:* style-aware **Sound** menu (recommended ensembles first, grooves grouped
  by family), per-voice instruments with doubling, default tempo per sound, and a hint bar
  explaining each pairing (recommended / time-travel / mashup).
- **Step-entry notation editing** (future): enter and edit melodies note by note on the
  staff, not only as ABC text.

Built in session 1, part 2 (2026-10-15), now public at https://github.com/deanpeters/rameau-studio:
- **Era textures** (`texture.py`): chorale (passing notes, 4-3 suspensions), polyphony (held common
  tones), continuo (held bass), classical (repeated-eighth accompaniment).
- **Analysis fixes**: phrase endings from rests/long notes on strong beats; home key from the
  piece's final (modal music) with mode names; per-phrase local keys (modulation tracking);
  learned harmonic rhythm (strong vs weak beats), melodic intervals, cadence melody notes,
  voice activity. The harmonizer now follows each style's harmonic rhythm.
- **Generate from a pattern** (`generate.py`): chord symbols or Roman numerals, or a progression
  invented from the style's statistics; melody composed by forward-filtering/backward-sampling
  over the style's melodic habits; new variation each press.
- **AI mode** (`ai.py`): bring-your-own-key tutor + composer, Claude Haiku by default, keys from
  env or OS keychain only; friendly errors (no key, bad key, rate limit, no credits).

Known limitations to address next:
- Local-key detection is cautious and under-counts Bach's modulations.
- AI mode was verified up to the API's billing check (the test account had no credits); a full
  live run still needs a funded key.
- Modal music (Palestrina, Monteverdi) is analysed as major/minor; add modal keys.
- Phrase endings without fermatas are guessed from long notes.
- Keys are analysed once per piece (no modulation tracking) in training and harmonizing.
- Generating from a pattern (chords → melody + voices) is not built yet; chords currently
  go to the MMA band only.
- AI composer track not started.
- Not yet tested on Windows/Linux; no installers yet.

## Milestones

- **M0 — Three spikes on one shared small test set (≈1–2 weeks):**
  1. *Harmony:* melody (ABC/MusicXML) → music21 → chord/key candidates from Bach chorale
     statistics → constrained SATB → ranked explanations → MIDI/MusicXML.
  2. *Accompaniment + packaging:* the same chord sequence → MMA subprocess → FluidSynth
     with looping, in a minimal PySide6 window, packaged and launched on all three
     operating systems from CI.
  3. *Reuse check (time-boxed, about half a day):* how far JJazzLab's extension APIs
     would get the same feature, to confirm or reject building our own app shell.
  Judge on harmonic plausibility, voice-leading violations, explanation accuracy and
  playback stability, not on matching Bach's notes.
- **M1 — Chord sheet app:** model, grid editor, groove browser, transport, save/open,
  MIDI export.
- **M2 — Code editor:** text mode, highlighting, error markers, open arbitrary `.mma`.
- **M3 — Imports:** iReal Pro, MusicXML.
- **M4 — Polish and release:** WAV export, mixer, preferences, signed installers,
  docs site.

## Target outcomes

| Outcome | Feasible? | Where |
|---|---|---|
| Harmonize a melody | Yes | M5 |
| Harmonize in a chosen style | Yes; style = chord vocabulary + progression statistics + harmonic rhythm + voicing/texture + rules | M5 (hand-built styles), M6 (learned) |
| Build style libraries from example pieces | Yes, if the pieces have chord symbols or the chords can be detected (easy for homophonic music like chorales, harder for dense textures) | M6 |
| Start from chord notation instead of a melody | Yes, and it's the easier direction: accompany in a style (MMA), voice the chords in a style, reharmonize them into a style, and later generate a melody over them | M1 (accompany), M5–M7 (voice, reharmonize), later (melody) |

## Product principle

**Equally a teaching tool and a performance tool** (corrected 2026-10-15; an earlier draft
wrongly said "teaching first").

- Every style is an explicit **fingerprint** (chord vocabulary, progressions, cadences, harmonic
  rhythm, voicing, texture, melodic habits) that can be shown, compared and edited.
- Two generation engines, used together:
  - **Fingerprint engine** (statistics + rules, built 2026-10-15): fast, runs on any laptop,
    explains every choice. Harmonizes melodies and chord patterns.
  - **AI composer** (e.g. MuPT, which reads and writes ABC; ChatMusician): writes richer,
    longer new music. Its output is always analyzed by the fingerprint engine, so even
    AI-written music comes with "here's why this sounds like Bach".
- AI composer paths, in order of effort:
  1. **Use a ready-trained model** (MuPT, ChatMusician) as-is, prompted with ABC.
  2. **Fine-tune it** on our era corpora (small LoRA adapters per era/composer): on Apple
     Silicon (MLX) for small models, or a rented GPU for a few dollars per run.
  3. **Train our own** small model from scratch if 1–2 fall short.
  The music21 era corpora (below) are the shared training data for both engines.
- Compare mode is central: the same melody as Palestrina, Bach, Mozart, Chopin and jazz,
  with their fingerprints side by side.

### Style library roadmap (data that ships with music21, so licensing is already clear)

| Era | Corpus in music21 | Pieces |
|---|---|---|
| Medieval | Trecento | 103 |
| Renaissance | Palestrina (1,318), Josquin (8) | 1,326 |
| Late Renaissance / early Baroque | Monteverdi madrigals | 97 |
| Baroque | Bach (chorales + more) | 433 |
| Classical | Mozart 16, Haydn 9, Beethoven 26 | 51 (thin; supplement) |
| Folk | Essen, O'Neill, Ryan's Mammoth | 1,100+ (melodies, for testing) |

Gaps to fill from other sources (check each license): Romantic (Chopin, Schubert), jazz and
pop (iReal Pro charts), plus harmonic-analysis corpora such as "When in Rome" (Roman-numeral
analyses across eras; verify license) and the DCML annotated corpora (Mozart and
Beethoven sonatas, Chopin mazurkas; often non-commercial licenses).

## Future: Style Lab and Harmonizer (post-v1)

### Two kinds of "style"

| | Groove styles (jazz, pop, latin, smooth jazz) | Voice-leading styles (Bach chorale/cantata, hymn) |
|---|---|---|
| What defines it | Chord vocabulary + accompaniment rhythm and texture | Counterpoint: independent lines, voice-leading rules, cadences |
| Output | Chords → MMA groove | SATB (or more voices) note-by-note |
| MMA's role | Central (124 stdlib groove files already, ~15 jazz) | Texture and playback: Baroque grooves (arpeggiated figuration, walking continuo, dance rhythms, block-chord chorale) + Solo/Riff tracks for harmonizer-written voices. The harmonizer makes the counterpoint decisions. |
| Learn from a corpus | Chord-progression statistics + rhythm patterns (MMA ships `util/mid2mma.py` to extract patterns from MIDI) | Chord-progression statistics + voice-leading statistics + rules |

### Style Pack (the unit you build or upload)

A folder or zip a user (or teacher) can create from a corpus:

- `harmony` — chord-transition and melody→chord probabilities (an HMM-style model),
  learned from the corpus and shown as tables and graphs.
- `rules` — hard and soft constraints (e.g. no parallel 5ths/8ves, resolve leading
  tone, voice ranges), each with a human-readable explanation.
- `texture` — an MMA groove (for groove styles) or a voicing model (for voice-leading
  styles).
- `corpus.json` — provenance: which pieces were used. Per-piece licensing, since Bach
  is public domain but a given MIDI encoding or a smooth-jazz transcription may not be.
- `notes.md` — the teaching narrative for this style.

### Harmonize a melody

1. **Melody input:** MIDI (pick a track), MusicXML, **ABC notation** (the abc2midi
   format), or typed in the app.
2. **Analysis:** key, phrases, cadence points, strong vs weak beats.
3. **Chord choice:** Viterbi search over the style's harmony model, constrained at
   cadences. Show the top-N alternatives per beat with their probabilities.
4. **Realization:** groove styles go to an MMA chord sheet + groove; voice-leading
   styles go to a constraint solver that writes the inner voices and checks the rules.
5. **Explain:** Roman-numeral analysis, highlighted rule hits and near-misses, and an
   "Why?" panel for each chord.

### Teaching modes

- **Exercise mode:** the student harmonizes a melody; the app grades it against the
  rules and the style model (parallels, spacing, doubling, unresolved tendencies).
- **Compare:** the same melody in Bach vs smooth jazz vs folk, side by side.
- **Practice:** loop, slow down, mute a voice to sing or play it, transpose.
- **Corpus explorer:** "What does Bach do after a V7?" answered from the uploaded pieces.

### Honest scope notes

- Chorale-style 4-part harmonization learned from a corpus is well understood
  (the 371 Bach chorales are the classic dataset, and come with music21).
- Generating a whole *cantata* (arias, recitatives, orchestration) is the job of the AI
  composer track, not the fingerprint engine. It is hard (scarce clean cantata data, GPU
  training), so start with shorter forms and grow.
- A neural model (e.g. Coconet/DeepBach-style) could be an optional backend later,
  but only with the explanation layer on top.
- Magenta (checked 2026-10-15): the main `magenta/magenta` repo and `note-seq` are
  **archived**. `magenta-js` (Apache-2.0, still maintained) ships Coconet (Bach
  4-part infilling) and ImprovRNN (melody over chords). `magenta-realtime` generates
  **audio**, not notes, so it's no use for notation or analysis. Verdict: not the
  foundation. Possible optional "Inspire me" generator whose output our analyzer
  then checks and explains.

### Technology implications

- **music21** (BSD license, works with GPL): parses ABC, MusicXML and MIDI; gives
  Roman-numeral analysis, key finding, voice-leading checks and the Bach chorale corpus.
  Adopting it **in v1 for imports** replaces the custom MusicXML parser and adds ABC for
  free.
- **Verovio** (LGPL): renders notation to SVG, so the app can show scores and
  highlight analysis on them. A teaching tool needs notation, not just a chord grid.
- Model training is plain statistics (counting, smoothing), which is fast and local,
  so no GPU is needed for the core.

### What this changes in v1 (to avoid painting ourselves into a corner)

- The Song model is **note-level** (melody + chords + optional voices), not just bars
  of chord symbols. MMA chord sheets are one *view* of it.
- Plan for a notation view (Verovio) from M2 onward.
- Use music21 for MusicXML/ABC import in M3.
- Keep the harmonizer behind a clean interface (`melody + style pack → harmony +
  explanations`) so groove and voice-leading engines can plug in.

### Later milestones

- **M5 — Melody input + groove harmonizer:** ABC/MIDI melody in, chords chosen by a
  hand-built jazz/pop model, played with MMA grooves, with a "Why?" panel.
- **M6 — Style Lab:** build a Style Pack from an uploaded corpus; corpus explorer.
- **M7 — Bach chorale harmonizer:** SATB realization, rule checker, exercise
  mode.
- **M8 — Groove learning:** extract an MMA groove from MIDI files (building on
  `mid2mma.py`).

## Open questions

- Should our engine fork be public, with fixes contributed back to infojunkie/mma?
- Which SoundFont to use (size vs quality; GeneralUser GS is about 30 MB).
- Apple signing account.
- Should Style Packs be shareable (a community library)? If so, we need a licensing and
  provenance policy for corpora.
- Who is the primary learner: a theory student (rules, grading) or a performer
  (practice, play-along)? This sets the order of M5–M8.
