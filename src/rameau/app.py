"""Rameau Studio desktop app (PySide6 / Qt)."""

from __future__ import annotations

import html
import shutil
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QFont, QKeySequence
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QSplitter, QTabWidget, QTextBrowser, QToolBar,
    QVBoxLayout, QWidget, QCompleter,
)

from . import band
from .audio import AudioUnavailable, render_wav
from .session import Result, Session
from .sounds import SOUNDS, Sound, groove_category, pairing_note, recommended
from .style import builtin_styles, load_style

SAMPLES = Path(__file__).parent / "samples"
KEYS = ["Auto"] + [f"{n} major" for n in "C G D A E B F# Db Ab Eb Bb F".split()] + \
       [f"{n} minor" for n in "A E B F# C# G# D G C F Bb Eb".split()]

PAGE_CSS = """
<style>
 :root { color-scheme: light dark; }
 body { margin: 0; padding: 16px; background: #fbfaf7; font-family: -apple-system, 'Segoe UI', sans-serif; }
 .page { background: white; margin: 0 auto 16px; max-width: 1100px; box-shadow: 0 1px 4px rgba(0,0,0,.15); }
 .page svg { width: 100%; height: auto; display: block; }
 .empty { color: #777; text-align: center; margin-top: 20vh; font-size: 15px; line-height: 1.6; }
 pre { background: white; padding: 12px; }
 table { border-collapse: collapse; background: white; color: #1d1d1f; font-size: 13px; }
 th, td { border: 1px solid #ddd; padding: 6px 8px; vertical-align: top; text-align: left; color: #1d1d1f; }
 th.row { background: #f3f1ec; white-space: nowrap; }
 @media (prefers-color-scheme: dark) {
   body { background: #222; color: #ddd; }
   table { background: #2c2c2e; } th, td { color: #eee; border-color: #444; } th.row { background: #3a3a3c; }
 }
</style>
"""


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class Job(QRunnable):
    """Run a function off the UI thread."""

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.signals = _Signals()

    def run(self):
        try:
            self.signals.done.emit(self.fn(*self.args, **self.kwargs))
        except Exception as e:  # report to the UI
            self.signals.failed.emit(f"{e}\n\n{traceback.format_exc(limit=3)}")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Rameau Studio")
        self.resize(1400, 900)
        self.session = Session()
        self.result: Result | None = None
        self.pool = QThreadPool.globalInstance()
        self.styles = {name: load_style(name) for name in sorted(builtin_styles())}
        self.source_path: Path | None = None

        self.player = QMediaPlayer(self)
        self.audio_out = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_out)
        self.player.playbackStateChanged.connect(self._playback_changed)

        self._build_toolbar()
        self._build_body()
        self._fill_sounds()
        self._load_sample("old_hundredth.abc")
        self._refresh_fingerprint()
        self.statusBar().showMessage("Pick a melody and a style, then press Harmonize.")

    # ---------------------------------------------------------------- layout
    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        open_act = QAction("Open…", self)
        open_act.setShortcut(QKeySequence.Open)
        open_act.triggered.connect(self._open_file)
        tb.addAction(open_act)

        self.sample_box = QComboBox()
        self.sample_box.addItem("Samples…")
        for p in sorted(SAMPLES.glob("*.abc")):
            self.sample_box.addItem(p.stem.replace("_", " ").title(), p.name)
        self.sample_box.activated.connect(lambda i: i and self._load_sample(self.sample_box.itemData(i)))
        tb.addWidget(self.sample_box)
        tb.addSeparator()

        tb.addWidget(QLabel(" Style "))
        self.style_box = QComboBox()
        for name, s in self.styles.items():
            self.style_box.addItem(s.title, name)
        self.style_box.setCurrentIndex(max(0, self.style_box.findData("bach_chorale")))
        self.style_box.setToolTip("Which composer or era's habits to use")
        tb.addWidget(self.style_box)

        tb.addWidget(QLabel(" Key "))
        self.key_box = QComboBox()
        self.key_box.addItems(KEYS)
        tb.addWidget(self.key_box)

        tb.addWidget(QLabel(" Sound "))
        self.accomp_box = QComboBox()
        self.accomp_box.setEditable(True)
        self.accomp_box.setInsertPolicy(QComboBox.NoInsert)
        self.accomp_box.setMinimumWidth(260)
        self.accomp_box.setMaxVisibleItems(30)
        self.accomp_box.setToolTip("Sounds recommended for the style are listed first. "
                                   "Type to search 1,000+ MMA grooves (Swing, BossaNova, Waltz…).")
        try:
            self.grooves = band.list_grooves()
        except Exception:
            self.grooves = []
        self.groove_names = {g.name.lower(): g.name for g in self.grooves}
        tb.addWidget(self.accomp_box)

        tb.addWidget(QLabel(" Tempo "))
        self.tempo = QSpinBox()
        self.tempo.setRange(30, 240)
        self.tempo.setValue(80)
        tb.addWidget(self.tempo)
        tb.addSeparator()

        self.go_btn = QPushButton("Harmonize")
        self.go_btn.setDefault(True)
        self.go_btn.clicked.connect(self._run)
        tb.addWidget(self.go_btn)
        self.play_btn = QPushButton("▶ Play")
        self.play_btn.clicked.connect(self._toggle_play)
        self.play_btn.setEnabled(False)
        tb.addWidget(self.play_btn)

        export = QAction("Export…", self)
        export.setShortcut(QKeySequence.Save)
        export.triggered.connect(self._export)
        tb.addAction(export)

        # a full-width hint explaining how the chosen style and sound fit together
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("padding: 6px 10px; border-radius: 6px; background: palette(alternate-base);")

        self.style_box.currentIndexChanged.connect(lambda _: self._fill_sounds())
        self.accomp_box.currentIndexChanged.connect(lambda _: self._sound_changed())
        self.accomp_box.lineEdit().editingFinished.connect(self._update_hint)

    # ---------------------------------------------------------------- style + sound guidance
    def _style_key(self) -> str:
        return self.style_box.currentData()

    def _fill_sounds(self) -> None:
        """Rebuild the Sound menu: recommended sounds for this style first, then everything else."""
        box = self.accomp_box
        box.blockSignals(True)
        box.clear()
        style = self.styles[self._style_key()]

        def header(text):
            box.addItem(text)
            item = box.model().item(box.count() - 1)
            item.setEnabled(False)
            f = item.font()
            f.setBold(True)
            item.setFont(f)

        rec = recommended(self._style_key())
        header(f"Recommended for {style.title}")
        for snd in rec:
            box.addItem("   " + snd.name, ("sound", snd.key))
            box.setItemData(box.count() - 1, snd.why, Qt.ToolTipRole)
        others = [snd for snd in SOUNDS.values() if snd not in rec]
        header("Other ensembles")
        for snd in others:
            box.addItem("   " + snd.name, ("sound", snd.key))
            box.setItemData(box.count() - 1, snd.why, Qt.ToolTipRole)
        by_cat: dict[str, list] = {}
        for g in self.grooves:
            by_cat.setdefault(groove_category(g.family), []).append(g)
        for cat in sorted(by_cat, key=lambda c: (c == "Other", c)):
            header(f"Band grooves: {cat}")
            for g in by_cat[cat]:
                box.addItem("   " + g.name, ("groove", g.name))
                box.setItemData(box.count() - 1, f"{g.description} ({g.family})", Qt.ToolTipRole)
        box.completer().setCompletionMode(QCompleter.PopupCompletion)
        box.completer().setFilterMode(Qt.MatchContains)
        box.setCurrentIndex(1)  # first recommended sound
        box.blockSignals(False)
        self._sound_changed()

    def _current_sound(self) -> tuple[Sound | None, str | None]:
        """(ensemble or recommended band, raw groove name) for the Sound box."""
        box = self.accomp_box
        text = box.currentText().strip()
        data = box.currentData()
        if data and box.itemText(box.currentIndex()).strip() == text:
            kind, value = data
            return (SOUNDS[value], None) if kind == "sound" else (None, value)
        for snd in SOUNDS.values():
            if snd.name.lower() == text.lower():
                return snd, None
        if text.lower() in self.groove_names:
            return None, self.groove_names[text.lower()]
        return None, None

    def _sound_changed(self) -> None:
        snd, _ = self._current_sound()
        if snd is not None:
            self.tempo.setValue(snd.tempo[1])
        self._update_hint()

    def _update_hint(self) -> None:
        snd, groove = self._current_sound()
        style = self.styles[self._style_key()]
        if snd is None and groove is None:
            text = "Unknown sound: pick one from the list, or type part of a groove name (e.g. Bossa)."
        else:
            text = pairing_note(self._style_key(), style.title, snd, groove)
        self.hint.setText(f"💡 {text}")

    def _build_body(self) -> None:
        split = QSplitter(Qt.Horizontal)

        # left: input
        left = QTabWidget()
        mono = QFont("Menlo" if sys.platform == "darwin" else "Consolas" if sys.platform == "win32" else "Monospace")
        mono.setStyleHint(QFont.Monospace)
        self.melody_edit = QPlainTextEdit()
        self.melody_edit.setFont(mono)
        self.melody_edit.setPlaceholderText("Melody in ABC notation (or File ▸ Open a MusicXML/MIDI file)")
        self.melody_edit.textChanged.connect(lambda: setattr(self, "source_path", None) if self.melody_edit.hasFocus() else None)
        left.addTab(self.melody_edit, "Melody")
        self.chord_edit = QPlainTextEdit()
        self.chord_edit.setFont(mono)
        self.chord_edit.setPlainText("| Dm7 G7 | CM7 | Am7 D7 | Gm7 C7 |\n| FM7 | Bm7b5 E7 | Am | Am |")
        left.addTab(self.chord_edit, "Chords")
        left.setMinimumWidth(320)
        self.input_tabs = left
        left.currentChanged.connect(lambda i: self.go_btn.setText("Harmonize" if i == 0 else "Play chords"))
        split.addWidget(left)

        # centre: score / fingerprint
        self.center = QTabWidget()
        self.score_view = QWebEngineView()
        self.center.addTab(self.score_view, "Score")
        self.fp_view = QWebEngineView()
        self.center.addTab(self.fp_view, "Style fingerprints")
        self.text_view = QTextBrowser()
        self.center.addTab(self.text_view, "Explanation / MMA")
        self._show_html('<div class="empty">Your harmonized score will appear here.</div>')
        split.addWidget(self.center)

        # right: why panel
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(4, 4, 4, 4)
        rl.addWidget(QLabel("<b>Chords</b> (click one to see why)"))
        self.chord_list = QListWidget()
        self.chord_list.currentRowChanged.connect(self._show_reasons)
        rl.addWidget(self.chord_list, 2)
        self.why = QTextBrowser()
        self.why.setOpenLinks(False)
        self.why.anchorClicked.connect(self._alternative_clicked)
        rl.addWidget(self.why, 3)
        row = QHBoxLayout()
        self.unlock_btn = QPushButton("Clear locked chords")
        self.unlock_btn.clicked.connect(self._clear_locks)
        row.addWidget(self.unlock_btn)
        rl.addLayout(row)
        self.findings = QListWidget()
        self.findings.setMaximumHeight(120)
        rl.addWidget(QLabel("<b>Voice-leading check</b>"))
        rl.addWidget(self.findings)
        right.setMinimumWidth(340)
        split.addWidget(right)

        split.setSizes([330, 760, 380])
        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(6, 4, 6, 0)
        cl.addWidget(self.hint)
        cl.addWidget(split, 1)
        self.setCentralWidget(central)

    # ---------------------------------------------------------------- input
    def _load_sample(self, name: str) -> None:
        self.melody_edit.setPlainText((SAMPLES / name).read_text())
        self.source_path = None
        self.session.locks.clear()
        self.input_tabs.setCurrentIndex(0)

    def _open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open melody", str(Path.home()),
                                              "Music (*.abc *.musicxml *.xml *.mxl *.mid *.midi *.krn)")
        if not path:
            return
        p = Path(path)
        self.session.locks.clear()
        if p.suffix.lower() == ".abc":
            self.melody_edit.setPlainText(p.read_text())
            self.source_path = None
        else:
            self.source_path = p
            self.melody_edit.setPlainText(f"% Loaded from {p.name}; press Harmonize.\n")
        self.input_tabs.setCurrentIndex(0)

    def _title(self) -> str:
        if self.source_path:
            return self.source_path.stem.replace("_", " ").title()
        for line in self.melody_edit.toPlainText().splitlines():
            if line.startswith("T:"):
                return line[2:].strip()
        return "Melody"

    # ---------------------------------------------------------------- run
    def _run(self) -> None:
        if not self.go_btn.isEnabled():  # a job is already running
            return
        self._stop()
        style = self.styles[self.style_box.currentData()]
        key = None if self.key_box.currentText() == "Auto" else self._key_arg(self.key_box.currentText())
        snd, groove = self._current_sound()
        if snd is None and groove is None:
            self._update_hint()
            return
        if self.input_tabs.currentIndex() == 0:
            job = Job(self.session.harmonize_melody, self.melody_edit.toPlainText(), style, key, snd, groove,
                      self.tempo.value(), self._title(), self.source_path)
            self.statusBar().showMessage(f"Harmonizing in {style.title} style…")
        else:
            # A chord chart is played by a band; ensembles fall back to a band that suits the style.
            if snd is not None and snd.is_groove:
                groove = snd.groove_for(4)
            elif snd is not None:
                band_sound = next((x for x in recommended(self._style_key()) if x.is_groove), None)
                groove = band_sound.groove_for(4) if band_sound else "Hymn"
                self.hint.setText(f"💡 Chord charts are played by a band, so this uses {groove}. "
                                  "Four-voice writing from chords alone is coming.")
            job = Job(self.session.play_chords, self.chord_edit.toPlainText(), groove, self.tempo.value())
            self.statusBar().showMessage(f"Building the band ({groove})…")
        self.go_btn.setEnabled(False)
        job.signals.done.connect(self._finished)
        job.signals.failed.connect(self._failed)
        self.pool.start(job)

    @staticmethod
    def _key_arg(text: str) -> str:
        name, mode = text.split()
        name = name.replace("b", "-") if len(name) > 1 else name
        return name if mode == "major" else name.lower()

    @Slot(object)
    def _finished(self, result: Result) -> None:
        self.result = result
        self.go_btn.setEnabled(True)
        if result.svg_pages:
            self._show_html("".join(f'<div class="page">{svg}</div>' for svg in result.svg_pages))
        else:
            self._show_html(f'<pre>{html.escape(result.band_source or "")}</pre>')
        self.text_view.setMarkdown(result.explanation)
        self._fill_chords()
        self.statusBar().showMessage("Rendering sound…")
        job = Job(render_wav, result.midi, result.midi.with_suffix(".wav"))
        job.signals.done.connect(self._audio_ready)
        job.signals.failed.connect(lambda msg: self.statusBar().showMessage(f"No sound: {msg.splitlines()[0]}"))
        self.pool.start(job)

    @Slot(str)
    def _failed(self, msg: str) -> None:
        self.go_btn.setEnabled(True)
        self.statusBar().showMessage("Something went wrong.")
        QMessageBox.warning(self, "Rameau", msg)

    @Slot(object)
    def _audio_ready(self, wav: Path) -> None:
        self.player.setSource(QUrl.fromLocalFile(str(wav)))
        self.play_btn.setEnabled(True)
        h = self.result.harmonization if self.result else None
        if h:
            errs = sum(1 for f in self.result.realization.findings if f.severity == "error")
            self.statusBar().showMessage(f"{h.notes[0]} · {h.style.title} · {len(h.choices)} beats · "
                                         f"{errs} voice-leading errors. Press Play.")
        else:
            self.statusBar().showMessage("Ready. Press Play.")

    # ---------------------------------------------------------------- why panel
    def _fill_chords(self) -> None:
        self.chord_list.clear()
        self.findings.clear()
        self.why.clear()
        if not self.result or not self.result.harmonization:
            return
        h = self.result.harmonization
        for c in h.choices:
            mark = " 🔒" if c.locked else ""
            cad = "  ⟵ cadence" if c.cadence else ""
            item = QListWidgetItem(f"{c.beat.label:9} {c.symbol:8} {c.label:7} {c.confidence:4.0%}{mark}{cad}")
            item.setFont(QFont("Menlo" if sys.platform == "darwin" else "Consolas", 11))
            self.chord_list.addItem(item)
        self.chord_list.setCurrentRow(0)
        for f in self.result.realization.findings:
            self.findings.addItem(str(f))
        if not self.result.realization.findings:
            self.findings.addItem("No textbook voice-leading faults.")

    def _show_reasons(self, row: int) -> None:
        if row < 0 or not self.result or not self.result.harmonization:
            return
        c = self.result.harmonization.choices[row]
        alts = "".join(
            f'<li><a href="alt:{row}:{html.escape(a.label)}">{html.escape(a.symbol)} ({html.escape(a.label)})</a> '
            f"{a.probability:.0%}</li>" for a in c.alternatives)
        reasons = "".join(f"<li>{html.escape(r)}</li>" for r in c.reasons)
        self.why.setHtml(
            f"<h3>{html.escape(c.symbol)} &nbsp;<small>{html.escape(c.label)} · {html.escape(c.function)}</small></h3>"
            + (f"<p><b>{html.escape(c.cadence)}</b></p>" if c.cadence else "")
            + f"<p>Melody note is {html.escape(c.melody_role)}. Confidence {c.confidence:.0%}.</p>"
            f"<ul>{reasons}</ul><p><b>Try instead</b> (click to lock it in and re-harmonize):</p><ul>{alts}</ul>")

    def _alternative_clicked(self, url: QUrl) -> None:
        _, row, label = url.toString().split(":", 2)
        self.session.locks[int(row)] = label
        self._run()

    def _clear_locks(self) -> None:
        self.session.locks.clear()
        self._run()

    # ---------------------------------------------------------------- other views
    def _show_html(self, body: str) -> None:
        self.score_view.setHtml(f"<html><head>{PAGE_CSS}</head><body>{body}</body></html>")

    def _refresh_fingerprint(self) -> None:
        from .fingerprint import fingerprint_html

        intro = ("<h2>What makes each style sound like itself?</h2><p>Counted from every chord in the pieces "
                 "each style learned from. <i>Signature moves</i> are progressions a style uses far more often "
                 "than the others.</p>")
        self.fp_view.setHtml(f"<html><head>{PAGE_CSS}</head><body>{intro}"
                             f"{fingerprint_html(list(self.styles.values()))}</body></html>")

    # ---------------------------------------------------------------- playback
    def _toggle_play(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self._stop()
        else:
            self.player.play()

    def _stop(self) -> None:
        self.player.stop()

    def _playback_changed(self, state) -> None:
        self.play_btn.setText("■ Stop" if state == QMediaPlayer.PlayingState else "▶ Play")

    def _export(self) -> None:
        if not self.result:
            return
        folder = QFileDialog.getExistingDirectory(self, "Export to folder", str(Path.home()))
        if not folder:
            return
        out = Path(folder)
        stem = self._title().replace(" ", "_").lower()
        shutil.copy(self.result.midi, out / f"{stem}.mid")
        wav = self.result.midi.with_suffix(".wav")
        if wav.exists():
            shutil.copy(wav, out / f"{stem}.wav")
        (out / f"{stem}.md").write_text(self.result.explanation)
        if self.result.score is not None:
            from .render import write_musicxml

            write_musicxml(self.result.score, out / f"{stem}.musicxml")
        if self.result.band_source:
            (out / f"{stem}.mma").write_text(self.result.band_source)
        self.statusBar().showMessage(f"Exported to {out}")


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Rameau Studio")
    w = MainWindow()
    w.show()
    shot = __import__("os").environ.get("RAMEAU_SELFTEST_SHOT")
    if shot:  # developer self-test: harmonize, screenshot our own window, quit
        from PySide6.QtCore import QTimer

        def snap(tab: int, path: str, then=None):
            w.center.setCurrentIndex(tab)
            QTimer.singleShot(1500, lambda: (w.grab().save(path), then() if then else None))

        env = __import__("os").environ
        if env.get("RAMEAU_SELFTEST_STYLE"):
            w.style_box.setCurrentIndex(w.style_box.findData(env["RAMEAU_SELFTEST_STYLE"]))
        if env.get("RAMEAU_SELFTEST_SOUND"):
            i = w.accomp_box.findText("   " + env["RAMEAU_SELFTEST_SOUND"])
            w.accomp_box.setCurrentIndex(i)
        QTimer.singleShot(500, w._run)
        QTimer.singleShot(1200, lambda: w.chord_list.setCurrentRow(3))
        QTimer.singleShot(4000, lambda: snap(0, shot, lambda: snap(1, shot.replace(".png", "-fp.png"), app.quit)))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
