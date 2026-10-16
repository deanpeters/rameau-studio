"""The bridge between the canvas (HTML/CSS/JS) and the app (Python/Qt).

The canvas is a face over the existing controls: every action here drives the same widgets and
session the rest of the app uses, so behaviour stays in one place.
"""

from __future__ import annotations

import html
import json
import re

from PySide6.QtCore import QObject, Signal, Slot

ERA_SHORT = {
    "palestrina": "Palestrina", "monteverdi": "Monteverdi", "bach_chorale": "Bach", "classical": "Classical",
    "romantic": "Romantic", "dixieland": "Dixieland", "jazz_standards": "Jazz", "blues": "Blues",
    "jazz_ballad": "Jazz ballad", "bossa_latin": "Bossa nova", "country": "Country", "pop_rock": "Pop & rock",
}
JOURNEYS = [
    {"title": "A hymn, as Bach would harmonize it", "text": "Old Hundredth for choir and organ: one chord per beat, "
     "a walking bass, sighing suspensions.", "sample": "old_hundredth.abc", "style": "bach_chorale",
     "sound": "choir_organ"},
    {"title": "…the same hymn, 150 years earlier", "text": "Palestrina's gentler harmony: open chords, held notes, "
     "suspensions at every cadence.", "sample": "old_hundredth.abc", "style": "palestrina", "sound": "choir"},
    {"title": "…and as a late-night jazz ballad", "text": "Seventh chords with 9ths and 13ths, a walking bass, "
     "brushed time.", "sample": "old_hundredth.abc", "style": "jazz_ballad", "sound": "cool_ep"},
]


def function_class(text: str) -> str:
    t = text.lower()
    if "secondary" in t or "colour" in t or "subtonic" in t or "relative" in t:
        return "colour"
    if "tonic" in t:
        return "home"
    if "predominant" in t:
        return "away"
    if "dominant" in t:
        return "tension"
    return "colour"


def likelihood(p: float) -> str:
    return "the usual choice" if p >= 0.5 else "common" if p >= 0.25 else "less common" if p >= 0.08 else "rare"


def md_to_html(text: str) -> str:
    """Just enough Markdown for tutor answers: paragraphs, lists, bold, italics."""
    out, in_list = [], False
    for line in text.splitlines():
        line = html.escape(line)
        line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
        line = re.sub(r"(?<!\*)\*(?!\s)(.+?)\*", r"<i>\1</i>", line)
        m = re.match(r"^\s*(?:[-*]|\d+\.)\s+(.*)", line)
        if m:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{m.group(1)}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if line.strip():
            out.append(f"<p>{line}</p>")
    if in_list:
        out.append("</ul>")
    return "".join(out)


class CanvasBridge(QObject):
    pieceChanged = Signal(str)
    stateChanged = Signal(str)
    catalogChanged = Signal(str)
    toast = Signal(str)
    tutorAnswer = Signal(str)
    fingerprintChanged = Signal(str)

    def __init__(self, window) -> None:
        super().__init__(window)
        self.w = window
        self._last_state = None
        self._tutor_history = []

    # ---------------------------------------------------------------- pushes from Python
    def push_catalog(self) -> None:
        from ..sounds import SOUNDS, STYLE_PERIOD, recommended
        from ..stepentry import MelodyDoc  # noqa: F401  (ensures package import order)

        w = self.w
        styles = []
        for key, s in w.styles.items():
            lo, hi = STYLE_PERIOD.get(key, (1900, 1950))
            styles.append({"key": key, "title": s.title, "short": ERA_SHORT.get(key, s.title), "year": (lo + hi) // 2,
                           "description": s.description})
        styles.sort(key=lambda s: s["year"])
        rec = recommended(w._style_key())
        others = [s for s in SOUNDS.values() if s not in rec]
        sounds = [{"key": s.key, "name": s.name, "why": s.why} for s in rec + others]
        samples = []
        from pathlib import Path

        from ..app import SAMPLES

        for p in sorted(Path(SAMPLES).glob("*.abc")):
            title = next((ln[2:].strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.startswith("T:")),
                         p.stem)
            samples.append({"file": p.name, "title": title})
        grooves = sorted({g.name for g in w.grooves if g.library == "stdlib" and not re.search(
            r"(Intro|End|Fill|Sus|Plus|\d)$", g.name)})
        from .. import ai

        payload = {"styles": styles, "sounds": sounds, "samples": samples, "grooves": grooves,
                   "journeys": [{"title": j["title"], "text": j["text"]} for j in JOURNEYS],
                   "ai": ai.active_profile() is not None, "dark": w.palette().window().color().lightness() < 128}
        self.catalogChanged.emit(json.dumps(payload))

    def push_piece(self, result) -> None:
        from ..harmonize import chord_symbol

        if result is None or result.harmonization is None:
            self.pieceChanged.emit(json.dumps({"title": result.title if result else "", "chords": [], "svg": [],
                                               "beatTimes": [], "totalBeats": 0}))
            return
        h, r = result.harmonization, result.realization
        groups = []
        for t, c in enumerate(h.choices):
            if groups and groups[-1]["label"] == c.label and not h.choices[t - 1].beat.phrase_end:
                groups[-1]["beats"] += 1
                continue
            alts = [{"label": a.label, "name": a.name, "symbol": a.symbol, "likelihood": likelihood(a.probability)}
                    for a in c.alternatives]
            groups.append({
                "label": c.label, "name": c.name, "beat": t, "beats": 1,
                "symbol": chord_symbol(c.label, h.key, r.inversions[t] if r else 0),
                "function": function_class(c.function), "functionText": c.function, "cadence": c.cadence,
                "reasons": [x for x in c.reasons], "alternatives": alts, "locked": c.locked,
                "where": f"bar {c.beat.measure}, beat {c.beat.beat}",
            })
        key = f"{h.key.tonic.name.replace('-', '♭')} {h.key.mode}"
        payload = {"title": result.title, "key": key, "styleTitle": h.style.title, "svg": result.svg_pages,
                   "chords": groups, "beatTimes": result.beat_times, "totalBeats": len(h.choices),
                   "anyLocked": any(c.locked for c in h.choices)}
        self.pieceChanged.emit(json.dumps(payload))

    def push_state(self) -> None:
        from ..controls import macros_from

        w = self.w
        lp = w.live_player
        snd, groove = w._current_sound()
        state = {
            "playing": bool(lp.playing) if lp else False,
            "position": round(lp.position(), 2) if lp else 0.0,
            "loop": w.loop_box.isChecked(),
            "tempo": w.tempo.value(),
            "canPlay": w.play_btn.isEnabled(),
            "styleKey": w._style_key(),
            "soundKey": snd.key if snd else (f"groove:{groove}" if groove else ""),
            "macros": macros_from(w.filter.controls),
        }
        text = json.dumps(state)
        if text != self._last_state:
            self._last_state = text
            self.stateChanged.emit(text)

    # ---------------------------------------------------------------- calls from the canvas
    @Slot()
    def ready(self) -> None:
        self.push_catalog()
        self.push_piece(self.w.result)
        self.push_state()

    @Slot(str)
    def chooseStyle(self, key: str) -> None:
        w = self.w
        i = w.style_box.findData(key)
        if i >= 0 and i != w.style_box.currentIndex():
            w.style_box.setCurrentIndex(i)  # also refreshes the recommended sounds
            self.push_catalog()
            title = w.styles[key].title
            if w.session.piece is not None:
                self.toast.emit(f"Now in {title} style" + (" · heard from the next bar" if w.live_player and
                                                           w.live_player.playing else ""))
                w.rerun_keep_playing()

    @Slot(str)
    def chooseSound(self, key: str) -> None:
        w = self.w
        if key.startswith("groove:"):
            w.accomp_box.setEditText(key.split(":", 1)[1])
            w._sound_changed()
        else:
            for i in range(w.accomp_box.count()):
                if w.accomp_box.itemData(i) == ("sound", key):
                    w.accomp_box.setCurrentIndex(i)
                    break
        if w.session.piece is not None:
            w.rerun_keep_playing()
        self.push_state()

    @Slot(str, float)
    def setMacro(self, name: str, value: float) -> None:
        from ..controls import apply_macro

        self.w.filter.set_controls(apply_macro(self.w.filter.controls, name, value))

    @Slot(int, str)
    def tryAlternative(self, beat: int, label: str) -> None:
        self.w.session.locks[beat] = label
        self.w.rerun_keep_playing()

    @Slot()
    def clearLocks(self) -> None:
        self.w.session.locks.clear()
        self.w.rerun_keep_playing()

    @Slot()
    def togglePlay(self) -> None:
        self.w._toggle_play()
        self.push_state()

    @Slot()
    def rewind(self) -> None:
        self.w._rewind()

    @Slot(bool)
    def setLoop(self, on: bool) -> None:
        self.w.loop_box.setChecked(on)
        self.push_state()

    @Slot(int)
    def setTempo(self, bpm: int) -> None:
        self.w.tempo.setValue(bpm)
        self.push_state()

    @Slot(str)
    def loadSample(self, name: str) -> None:
        self.w._load_sample(name)
        self.w._run()

    @Slot(str)
    def tuneAction(self, act: str) -> None:
        w = self.w
        if act == "edit":
            w.show_tune_drawer(0)
        elif act == "open":
            w._open_file()
            w._run()
        elif act == "chords":
            w.show_tune_drawer(2)
        elif act == "ireal":
            w._open_ireal()
            w.show_tune_drawer(2)
        elif act == "ai":
            w._ai_compose()

    @Slot(int)
    def journey(self, i: int) -> None:
        j = JOURNEYS[i]
        w = self.w
        w._load_sample(j["sample"])
        w.style_box.setCurrentIndex(w.style_box.findData(j["style"]))
        self.push_catalog()
        self.chooseSound(j["sound"])
        w._run()

    @Slot()
    def toggleAdvanced(self) -> None:
        dock = self.w.filter_dock
        dock.setVisible(not dock.isVisible())

    @Slot()
    def requestFingerprint(self) -> None:
        """Compare the current style with its neighbours in time: the contrast is what teaches."""
        from ..fingerprint import fingerprint_html
        from ..sounds import STYLE_PERIOD

        w = self.w
        keys = sorted(w.styles, key=lambda k: sum(STYLE_PERIOD.get(k, (1900, 1950))))
        i = keys.index(w._style_key())
        trio = keys[max(0, i - 1): i + 2] if 0 < i < len(keys) - 1 else (keys[:3] if i == 0 else keys[-3:])
        intro = (f"<h2>What makes {html.escape(w.styles[w._style_key()].title)} sound like itself?</h2>"
                 "<p style='color:var(--muted)'>Measured from every chord in the music each style learned from, beside its "
                 "neighbours in time. <i>Signature moves</i> are progressions a style uses far more than the others.</p>")
        self.fingerprintChanged.emit(intro + fingerprint_html([w.styles[k] for k in trio]))

    @Slot(str)
    def askTutor(self, question: str) -> None:
        from .. import ai
        from ..app import Job
        from ..fingerprint import fingerprint_markdown

        w = self.w
        context = (w.result.explanation if w.result else "(No piece harmonized yet.)") + "\n\n" + \
            fingerprint_markdown(list(w.styles.values()))
        job = Job(ai.ask_tutor, question, context, list(self._tutor_history))

        def done(answer: str) -> None:
            self._tutor_history = (self._tutor_history + [ai.TutorTurn("user", question),
                                                          ai.TutorTurn("assistant", answer)])[-12:]
            self.tutorAnswer.emit(json.dumps({"who": "ai", "html": md_to_html(answer)}))

        job.signals.done.connect(done)
        job.signals.failed.connect(lambda msg: self.tutorAnswer.emit(json.dumps(
            {"who": "err", "html": html.escape(msg.split("\n\n")[0]) + " (AI settings are in the AI menu.)"})))
        w.start_job(job)
