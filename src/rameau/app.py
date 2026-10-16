"""Rameau Studio desktop app (PySide6 / Qt)."""

from __future__ import annotations

import html
import re
import shutil
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QFont, QKeySequence
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication, QComboBox, QCompleter, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
    QPushButton, QSpinBox, QSplitter, QTabWidget, QTextBrowser, QToolBar, QVBoxLayout, QWidget,
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
    """Run a function off the UI thread.

    Start jobs with ``MainWindow.start_job`` (not ``pool.start`` directly): it keeps the job and its
    signal object alive until the result has been delivered on the UI thread. Letting Python collect
    them earlier crashes Qt when it delivers the queued signal (seen as SIGSEGV in QObjectWrapper::event).
    """

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.setAutoDelete(False)
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.signals = _Signals()

    def run(self):
        try:
            self.signals.done.emit(self.fn(*self.args, **self.kwargs))
        except Exception as e:  # report to the UI
            self.signals.failed.emit(f"{e}\n\n{traceback.format_exc(limit=3)}")


def _fill_model_box(box: QComboBox, current: str, models=None, provider: str = "anthropic") -> None:
    """Fill a model dropdown: live models if known, else a built-in list; keep the current choice."""
    from . import ai

    box.blockSignals(True)
    box.clear()
    fallback = ai.FALLBACK_MODELS if provider == ai.ANTHROPIC else []
    for model_id, label in (models or fallback):
        box.addItem(f"{label}  ·  {model_id}" if label != model_id else model_id, model_id)
    if current:
        i = box.findData(current)
        if i < 0:
            box.addItem(current, current)
            i = box.count() - 1
        box.setCurrentIndex(i)
    elif box.count() == 0:
        box.setEditText("")
        box.lineEdit().setPlaceholderText("Loading models… (or type a model name)")
    box.blockSignals(False)


def _profile_label(name: str) -> str:
    from . import ai

    if name in (ai.ENV_ANTHROPIC, ai.ENV_OPENAI):
        return name
    try:
        info = ai.profile_info(name)
    except ai.AIUnavailable:
        return name
    provider = "OpenAI" if info["provider"] == ai.OPENAI else "Anthropic"
    return f"{name}  ({provider}{', ' + info['base_url'] if info.get('base_url') else ''})"


def _fill_profile_box(box: QComboBox, select: str | None, empty: str) -> None:
    from . import ai

    box.blockSignals(True)
    box.clear()
    names = ai.list_profiles()
    for n in names:
        box.addItem(_profile_label(n), n)
    if not names:
        box.addItem(empty, None)
    if select in names:
        box.setCurrentIndex(names.index(select))
    box.blockSignals(False)


def _model_from_box(box: QComboBox) -> str:
    """The model id chosen or typed in an editable model dropdown."""
    text = box.currentText().strip()
    i = box.findText(text)
    return (box.itemData(i) if i >= 0 else text) or text


class AISettingsDialog(QDialog):
    """Manage named API keys (stored in the OS keychain) for Anthropic and OpenAI, and pick key and model."""

    def __init__(self, parent: "MainWindow") -> None:
        from . import ai

        super().__init__(parent)
        self.main = parent
        self.setWindowTitle("AI settings")
        self.setMinimumWidth(640)
        form = QFormLayout(self)
        intro = QLabel("Keys are stored in your system keychain, never in Rameau's files. ANTHROPIC_API_KEY and "
                       "OPENAI_API_KEY environment variables appear as their own entries. Each key remembers "
                       "its own model.")
        intro.setWordWrap(True)
        form.addRow(intro)

        row = QHBoxLayout()
        self.profiles = QComboBox()
        self.profiles.setMinimumWidth(300)
        row.addWidget(self.profiles, 1)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove)
        row.addWidget(remove)
        form.addRow("Use API key", row)

        add_row = QHBoxLayout()
        self.provider = QComboBox()
        self.provider.addItem("Anthropic (Claude)", ai.ANTHROPIC)
        self.provider.addItem("OpenAI or compatible", ai.OPENAI)
        self.provider.currentIndexChanged.connect(self._provider_changed)
        self.new_name = QLineEdit()
        self.new_name.setPlaceholderText("Name, e.g. Personal")
        self.new_key = QLineEdit()
        self.new_key.setEchoMode(QLineEdit.Password)
        self.new_key.setPlaceholderText("sk-ant-…")
        add_row.addWidget(self.provider)
        add_row.addWidget(self.new_name, 1)
        add_row.addWidget(self.new_key, 2)
        form.addRow("Add API key", add_row)
        url_row = QHBoxLayout()
        self.base_url = QLineEdit()
        self.base_url.setPlaceholderText("Optional server address for OpenAI-compatible services, e.g. "
                                         "http://localhost:11434/v1 (Ollama)")
        self.base_url.setEnabled(False)
        add = QPushButton("Add key")
        add.clicked.connect(self._add)
        url_row.addWidget(self.base_url, 1)
        url_row.addWidget(add)
        form.addRow("Server", url_row)

        mrow = QHBoxLayout()
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setInsertPolicy(QComboBox.NoInsert)
        self.model.setMinimumWidth(320)
        mrow.addWidget(self.model, 1)
        self.refresh = QPushButton("Load models for this key")
        self.refresh.clicked.connect(self._load_models)
        mrow.addWidget(self.refresh)
        form.addRow("Model", mrow)
        self.status = QLabel("Anthropic default: claude-haiku-5-5. OpenAI default: the newest 'mini' chat model. "
                             "You can also type any model name.")
        self.status.setWordWrap(True)
        form.addRow(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        self._fill_profiles(ai.active_profile())
        self._show_models(ai.active_profile())
        self.profiles.currentIndexChanged.connect(lambda _: self._profile_selected())

    def _current(self) -> str | None:
        return self.profiles.currentData()

    def _fill_profiles(self, select: str | None) -> None:
        _fill_profile_box(self.profiles, select, "(no keys yet: add one below)")

    def _provider_changed(self) -> None:
        from . import ai

        openai = self.provider.currentData() == ai.OPENAI
        self.base_url.setEnabled(openai)
        self.new_key.setPlaceholderText("sk-… (leave empty for a local server)" if openai else "sk-ant-…")

    def _show_models(self, name: str | None) -> None:
        from . import ai

        if not name:
            return
        _fill_model_box(self.model, ai.model_name(name), self.main._model_cache.get(name), ai.provider_of(name))

    def _profile_selected(self) -> None:
        self._show_models(self._current())
        self._load_models()

    def _add(self) -> None:
        from . import ai

        try:
            ai.add_profile(self.new_name.text(), self.new_key.text(), provider=self.provider.currentData(),
                           base_url=self.base_url.text().strip() or None)
        except Exception as e:
            QMessageBox.warning(self, "AI settings", str(e))
            return
        name = self.new_name.text().strip()
        self.new_name.clear()
        self.new_key.clear()
        self.base_url.clear()
        self._fill_profiles(name)
        self._show_models(name)
        self.status.setText(f"Saved '{name}' to your keychain. Checking it…")
        self._load_models()

    def _remove(self) -> None:
        from . import ai

        name = self._current()
        if not name:
            return
        try:
            ai.remove_profile(name)
        except ValueError as e:
            QMessageBox.information(self, "AI settings", str(e))
            return
        self._fill_profiles(ai.active_profile())
        self._show_models(ai.active_profile())
        self.status.setText(f"Removed '{name}'.")

    def _load_models(self) -> None:
        from . import ai

        name = self._current()
        if not name:
            return
        self.status.setText(f"Loading the models available to '{name}'…")
        job = Job(ai.list_models, name)
        job.signals.done.connect(lambda models: self._models_ready(name, models))
        job.signals.failed.connect(lambda msg: self.status.setText(f"'{name}': {msg.splitlines()[0]}"))
        self.main.start_job(job)

    def _models_ready(self, name: str, models) -> None:
        from . import ai

        self.main._model_cache[name] = models
        if name != self._current():
            return
        current = _model_from_box(self.model) or ai.model_name(name)
        if not current and models:
            undated = [m for m, _ in models if not re.search(r"-\d{4}-\d{2}-\d{2}$", m)]
            current = (undated or [models[0][0]])[0]
        _fill_model_box(self.model, current, models, ai.provider_of(name))
        self.status.setText(f"'{name}' works: {len(models)} models available.")

    def _save(self) -> None:
        from . import ai

        name = self._current()
        if name:
            ai.set_active_profile(name)
            model = _model_from_box(self.model)
            if model:
                ai.set_model(model, name)
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Rameau Studio")
        self.resize(1400, 900)
        self.session = Session()
        self.result: Result | None = None
        self.pool = QThreadPool.globalInstance()
        self._jobs: set = set()
        QApplication.instance().aboutToQuit.connect(lambda: self.pool.waitForDone(10000))
        self.styles = {name: load_style(name) for name in sorted(builtin_styles())}
        self.source_path: Path | None = None

        self.player = QMediaPlayer(self)
        self.audio_out = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_out)
        self.player.playbackStateChanged.connect(self._playback_changed)

        self._build_toolbar()
        self._build_body()
        self._fill_sounds()
        self._refresh_ai_bar()
        self._load_models()
        self._load_sample("old_hundredth.abc")
        self._refresh_fingerprint()
        self.statusBar().showMessage("Pick a melody and a style, then press Harmonize.")

    def start_job(self, job: "Job") -> None:
        """Run a background job, keeping it alive until its result reaches the UI thread."""
        self._jobs.add(job)

        def release(*_):
            QTimer.singleShot(0, lambda: self._jobs.discard(job))

        job.signals.done.connect(release)
        job.signals.failed.connect(release)
        self.pool.start(job)

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

        tb.addWidget(QLabel(" Adventure "))
        from PySide6.QtWidgets import QSlider

        self.adventure = QSlider(Qt.Horizontal)
        self.adventure.setRange(0, 100)
        self.adventure.setValue(0)
        self.adventure.setFixedWidth(90)
        self.adventure.setToolTip("0 = the style's safest, most typical chords. Higher = sample less obvious chords "
                                  "the style really uses (secondary dominants, deceptive cadences...). "
                                  "Each Harmonize gives a new variation.")
        tb.addWidget(self.adventure)

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
        ai_act = QAction("AI settings…", self)
        ai_act.triggered.connect(self._ai_settings)
        tb.addAction(ai_act)

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
        mel_page = QWidget()
        ml = QVBoxLayout(mel_page)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.addWidget(self.melody_edit, 1)
        ai_btn = QPushButton("✨ Compose a melody with AI…")
        ai_btn.setToolTip("Optional: An AI model writes a melody from your description (needs an Anthropic or OpenAI key)")
        ai_btn.clicked.connect(self._ai_compose)
        ml.addWidget(ai_btn)
        left.addTab(mel_page, "Melody")

        from .stepentry_ui import StepEntryWidget

        self.step_editor = StepEntryWidget()
        self.step_editor.changed.connect(self._step_changed)
        step_page = QWidget()
        sl = QVBoxLayout(step_page)
        sl.setContentsMargins(0, 0, 0, 0)
        load_btn = QPushButton("Edit the Melody tab's tune here")
        load_btn.setToolTip("Load the current ABC melody into the note editor")
        load_btn.clicked.connect(self._load_into_step_editor)
        sl.addWidget(load_btn)
        sl.addWidget(self.step_editor, 1)
        left.addTab(step_page, "Step entry")

        chord_page = QWidget()
        cl2 = QVBoxLayout(chord_page)
        cl2.setContentsMargins(0, 0, 0, 0)
        self.chord_edit = QPlainTextEdit()
        self.chord_edit.setFont(mono)
        self.chord_edit.setPlainText("| I vi | IV V7 | I IV | V I |\n| vi ii | V7/V V | I IV | V7 I |")
        self.chord_edit.setToolTip("Chord symbols (| C Am | F G7 |) or Roman numerals (| I vi | IV V7 |). "
                                   "One bar between bars lines or per line.")
        cl2.addWidget(self.chord_edit, 1)
        row = QHBoxLayout()
        invent = QPushButton("🎲 Invent in this style")
        invent.setToolTip("Let the chosen style write an 8-bar progression from its own habits")
        invent.clicked.connect(self._invent)
        row.addWidget(invent)
        open_chart = QPushButton("Open iReal Pro chart…")
        open_chart.setToolTip("Load a song from an iReal Pro playlist (exported as text or HTML) as Roman numerals")
        open_chart.clicked.connect(self._open_ireal)
        row.addWidget(open_chart)
        self.pattern_mode = QComboBox()
        self.pattern_mode.addItems(["Compose melody + voices", "Band plays the chords only"])
        row.addWidget(self.pattern_mode)
        cl2.addLayout(row)
        left.addTab(chord_page, "Chords")
        left.setMinimumWidth(380)
        self.input_tabs = left
        self.seed = 0
        left.currentChanged.connect(lambda i: self.go_btn.setText("Harmonize" if i in (0, 1) else "Compose"))
        left.currentChanged.connect(lambda i: i == 1 and self.step_editor.setFocus())
        split.addWidget(left)

        # centre: score / fingerprint
        self.center = QTabWidget()
        self.score_view = QWebEngineView()
        self.center.addTab(self.score_view, "Score")
        self.fp_view = QWebEngineView()
        self.center.addTab(self.fp_view, "Style fingerprints")
        self.text_view = QTextBrowser()
        self.center.addTab(self.text_view, "Explanation / MMA")
        tutor = QWidget()
        tl = QVBoxLayout(tutor)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("API key"))
        self.ai_profile_box = QComboBox()
        self.ai_profile_box.setMinimumWidth(200)
        self.ai_profile_box.setToolTip("Which saved API key (Anthropic or OpenAI) to use. Environment entries "
                                       "come from ANTHROPIC_API_KEY / OPENAI_API_KEY.")
        self.ai_profile_box.currentIndexChanged.connect(
            lambda _: self._profile_switched(self.ai_profile_box.currentData()))
        bar.addWidget(self.ai_profile_box)
        bar.addWidget(QLabel("Model"))
        self.ai_model_box = QComboBox()
        self.ai_model_box.setEditable(True)
        self.ai_model_box.setInsertPolicy(QComboBox.NoInsert)
        self.ai_model_box.setMinimumWidth(260)
        self.ai_model_box.activated.connect(lambda _: self._model_switched())
        self.ai_model_box.lineEdit().editingFinished.connect(self._model_switched)
        bar.addWidget(self.ai_model_box)
        manage = QPushButton("Manage keys…")
        manage.clicked.connect(self._ai_settings)
        bar.addWidget(manage)
        bar.addStretch(1)
        tl.addLayout(bar)
        self._model_cache: dict = {}
        self.tutor_log = QTextBrowser()
        self.tutor_log.setHtml("<p><b>Ask the tutor</b> about the piece on screen: <i>Why does Bach use V/V here? "
                               "What would Palestrina do differently? Why is this cadence called authentic?</i></p>"
                               "<p style='color:gray'>Optional AI mode: needs an Anthropic or OpenAI API key "
                               "(AI settings…). Answers are grounded in Rameau's own analysis.</p>")
        tl.addWidget(self.tutor_log, 1)
        qrow = QHBoxLayout()
        self.tutor_input = QLineEdit()
        self.tutor_input.setPlaceholderText("Ask about this harmonization…")
        self.tutor_input.returnPressed.connect(self._ask_tutor)
        qrow.addWidget(self.tutor_input, 1)
        ask = QPushButton("Ask")
        ask.clicked.connect(self._ask_tutor)
        qrow.addWidget(ask)
        tl.addLayout(qrow)
        self.center.addTab(tutor, "Ask the tutor (AI)")
        self.tutor_history = []
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

        split.setSizes([440, 700, 360])
        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(6, 4, 6, 0)
        cl.addWidget(self.hint)
        cl.addWidget(split, 1)
        self.setCentralWidget(central)

    # ---------------------------------------------------------------- input
    def _load_sample(self, name: str) -> None:
        self.melody_edit.setPlainText((SAMPLES / name).read_text(encoding="utf-8"))
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
            self.melody_edit.setPlainText(p.read_text(encoding="utf-8"))
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
        self._release_audio()
        style = self.styles[self.style_box.currentData()]
        key = None if self.key_box.currentText() == "Auto" else self._key_arg(self.key_box.currentText())
        snd, groove = self._current_sound()
        if snd is None and groove is None:
            self._update_hint()
            return
        if self.input_tabs.currentIndex() in (0, 1):  # Melody (ABC) or Step entry
            job = Job(self.session.harmonize_melody, self.melody_edit.toPlainText(), style, key, snd, groove,
                      self.tempo.value(), self._title(), self.source_path, self.adventure.value() / 100)
            self.statusBar().showMessage(f"Harmonizing in {style.title} style…")
        elif self.pattern_mode.currentIndex() == 0:
            self.seed += 1
            job = Job(self.session.generate_from_pattern, self.chord_edit.toPlainText(), style, key, snd, groove,
                      self.tempo.value(), self.seed)
            self.statusBar().showMessage(f"Composing a melody in {style.title} style (variation {self.seed})…")
        else:
            # A chord chart is played by a band; ensembles fall back to a band that suits the style.
            if snd is not None and snd.is_groove:
                groove = snd.groove_for(4)
            elif snd is not None:
                band_sound = next((x for x in recommended(self._style_key()) if x.is_groove), None)
                groove = band_sound.groove_for(4) if band_sound else "Hymn"
                self.hint.setText(f"💡 'Band plays the chords only' needs a band, so this uses {groove}. "
                                  "Choose 'Compose melody + voices' to hear the ensemble.")
            job = Job(self.session.play_chords, self.chord_edit.toPlainText(), groove, self.tempo.value())
            self.statusBar().showMessage(f"Building the band ({groove})…")
        self.go_btn.setEnabled(False)
        job.signals.done.connect(self._finished)
        job.signals.failed.connect(self._failed)
        self.start_job(job)

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
        self.start_job(job)

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
            item = QListWidgetItem(f"{c.beat.label:9} {c.symbol:8} {c.name:7} {c.confidence:4.0%}{mark}{cad}")
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
            f'<li><a href="alt:{row}:{html.escape(a.label)}">{html.escape(a.symbol)} ({html.escape(a.name)})</a> '
            f"{a.probability:.0%}</li>" for a in c.alternatives)
        reasons = "".join(f"<li>{html.escape(r)}</li>" for r in c.reasons)
        self.why.setHtml(
            f"<h3>{html.escape(c.symbol)} &nbsp;<small>{html.escape(c.name)} · {html.escape(c.function)}</small></h3>"
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

    # ---------------------------------------------------------------- step entry
    def _step_changed(self, abc: str) -> None:
        if self.input_tabs.currentIndex() == 1:  # only while editing there, so samples aren't overwritten
            self.melody_edit.setPlainText(abc)
            self.source_path = None
            self.session.locks.clear()

    def _load_into_step_editor(self) -> None:
        from .music import load_melody
        from .stepentry import MelodyDoc

        try:
            part = load_melody(self.source_path) if self.source_path else load_melody(self.melody_edit.toPlainText())
        except Exception as e:
            QMessageBox.warning(self, "Rameau", f"Couldn't read the melody: {e}")
            return
        self.step_editor.load(MelodyDoc.from_part(part, self._title()))
        self.step_editor.setFocus()

    # ---------------------------------------------------------------- patterns
    def _invent(self) -> None:
        from .generate import invent_progression

        style_key = self._style_key()
        mode = "minor" if "minor" in self.key_box.currentText() else "major"
        self.seed += 1
        bars = invent_progression(self.styles[style_key], mode, 8, 4, seed=self.seed)
        lines = []
        for i in range(0, len(bars), 4):
            cells = []
            for bar in bars[i:i + 4]:
                from .music import pretty

                compact = [pretty(c) for j, c in enumerate(bar) if j == 0 or c != bar[j - 1]]
                cells.append(" ".join(compact))
            lines.append("| " + " | ".join(cells) + " |")
        self.chord_edit.setPlainText("\n".join(lines))
        self.hint.setText(f"💡 Invented from {self.styles[style_key].title}'s own habits: its favourite moves, "
                          "how often it changes chord, and how its phrases end. Press Compose to hear it.")

    def _open_ireal(self) -> None:
        from .ireal import parse_file, song_key, song_to_pattern

        path, _ = QFileDialog.getOpenFileName(self, "Open iReal Pro playlist", str(Path.home()),
                                              "iReal Pro playlists (*.txt *.html *.htm);;All files (*)")
        if not path:
            return
        try:
            songs = parse_file(Path(path))
        except Exception as e:
            QMessageBox.warning(self, "Rameau", f"That file doesn't contain an iReal Pro playlist ({e}).")
            return
        titles = [f"{s.title}  ({s.style}, {s.key})" for s in songs]
        choice, ok = QInputDialog.getItem(self, "Choose a song", f"{len(songs)} songs:", titles, 0, False)
        if not ok:
            return
        song = songs[titles.index(choice)]
        k = song_key(song)
        self.chord_edit.setPlainText(song_to_pattern(song))
        name = k.tonic.name.replace("-", "b")
        label = f"{name} {k.mode}"
        if self.key_box.findText(label) >= 0:
            self.key_box.setCurrentText(label)
        self.hint.setText(f"💡 {song.title}: shown as Roman numerals in {label}, so you can see the harmony's "
                          "shape in any key. Press Compose to hear a melody written over it.")

    # ---------------------------------------------------------------- AI mode
    def _ai_settings(self) -> None:
        AISettingsDialog(self).exec()
        self._refresh_ai_bar()

    # quick switchers above the tutor chat
    def _refresh_ai_bar(self) -> None:
        from . import ai

        _fill_profile_box(self.ai_profile_box, ai.active_profile(), "No key: open Manage keys…")
        active = ai.active_profile()
        if active:
            _fill_model_box(self.ai_model_box, ai.model_name(active), self._model_cache.get(active),
                            ai.provider_of(active))

    def _profile_switched(self, name: str | None) -> None:
        from . import ai

        if name and name in ai.list_profiles():
            ai.set_active_profile(name)
            self.statusBar().showMessage(f"AI key: {name}")
            _fill_model_box(self.ai_model_box, ai.model_name(name), self._model_cache.get(name),
                            ai.provider_of(name))
            self._load_models(name)

    def _model_switched(self) -> None:
        from . import ai

        model = _model_from_box(self.ai_model_box)
        active = ai.active_profile()
        if model and active and model != ai.model_name(active):
            ai.set_model(model, active)
            self.statusBar().showMessage(f"AI model for {active}: {model}")

    def _load_models(self, profile: str | None = None) -> None:
        """Fetch the models this key can use (free API call) and refresh the dropdown."""
        from . import ai

        profile = profile or ai.active_profile()
        if not profile:
            return
        job = Job(ai.list_models, profile)
        job.signals.done.connect(lambda models: self._models_loaded(profile, models))
        job.signals.failed.connect(lambda msg: self.statusBar().showMessage(
            f"Model list unavailable: {msg.splitlines()[0]}"))
        self.start_job(job)

    def _models_loaded(self, profile: str, models) -> None:
        from . import ai

        self._model_cache[profile] = models
        if profile == ai.active_profile():
            current = ai.model_name(profile)
            if not current and models:
                undated = [m for m, _ in models if not re.search(r"-\d{4}-\d{2}-\d{2}$", m)]
                current = (undated or [models[0][0]])[0]
            _fill_model_box(self.ai_model_box, current, models, ai.provider_of(profile))

    def _ai_compose(self) -> None:
        from . import ai

        text, ok = QInputDialog.getText(self, "Compose with AI", "Describe the melody you'd like:",
                                        text="a gentle hymn tune in G major with two phrases")
        if not ok:
            return
        style = self.styles[self._style_key()]
        self.statusBar().showMessage("Asking the AI for a melody…")
        job = Job(ai.compose_melody, text, style.title, 8)
        job.signals.done.connect(self._ai_composed)
        job.signals.failed.connect(lambda msg: QMessageBox.information(self, "AI mode", msg.split("\n\n")[0]))
        self.start_job(job)

    @Slot(object)
    def _ai_composed(self, result) -> None:
        abc, description = result
        self.melody_edit.setPlainText(abc)
        self.source_path = None
        self.session.locks.clear()
        self.input_tabs.setCurrentIndex(0)
        self.statusBar().showMessage(f"AI melody: {description}  Press Harmonize.")

    def _ask_tutor(self) -> None:
        from . import ai
        from .fingerprint import fingerprint_markdown

        q = self.tutor_input.text().strip()
        if not q:
            return
        self.tutor_input.clear()
        context = (self.result.explanation if self.result else "(No piece harmonized yet.)") + "\n\n" + \
            fingerprint_markdown(list(self.styles.values()))
        self.tutor_log.append(f"<p><b>You:</b> {html.escape(q)}</p>")
        history = list(self.tutor_history)
        job = Job(ai.ask_tutor, q, context, history)
        job.signals.done.connect(lambda answer: self._tutor_answer(q, answer))
        job.signals.failed.connect(lambda msg: self.tutor_log.append(
            f"<p style='color:#b35'><b>AI mode:</b> {html.escape(msg.split(chr(10) * 2)[0])}</p>"))
        self.start_job(job)

    def _tutor_answer(self, question: str, answer: str) -> None:
        from .ai import TutorTurn

        self.tutor_history += [TutorTurn("user", question), TutorTurn("assistant", answer)]
        self.tutor_history = self.tutor_history[-12:]
        self.tutor_log.append("<p><b>Tutor:</b></p>")
        self.tutor_log.insertHtml("")
        cursor = self.tutor_log.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertMarkdown(answer + "\n\n")

    # ---------------------------------------------------------------- playback
    def _toggle_play(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self._stop()
        else:
            self.player.play()

    def _stop(self) -> None:
        self.player.stop()

    def _release_audio(self) -> None:
        """Stop playback and let go of the current audio file before a new one is made."""
        self.player.stop()
        self.player.setSource(QUrl())
        self.play_btn.setEnabled(False)

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
        (out / f"{stem}.md").write_text(self.result.explanation, encoding="utf-8")
        if self.result.score is not None:
            from .render import write_musicxml

            write_musicxml(self.result.score, out / f"{stem}.musicxml")
        if self.result.band_source:
            (out / f"{stem}.mma").write_text(self.result.band_source, encoding="utf-8")
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
        if env.get("RAMEAU_SELFTEST_TAB") == "step":
            from PySide6.QtTest import QTest

            w._load_into_step_editor()
            w.input_tabs.setCurrentIndex(1)
            ed = w.step_editor
            for k in "4EDC":
                QTest.keyClick(ed, k)
            QTest.keyClick(ed, Qt.Key_F, Qt.ShiftModifier)
        if env.get("RAMEAU_SELFTEST_TAB") == "chords":
            w.input_tabs.setCurrentIndex(2)
            w._invent()
        if env.get("RAMEAU_SELFTEST_REPEAT"):
            # stress test: re-render while audio is playing (regression for the overwritten-WAV crash)
            def cycle(n):
                if n == 0:
                    w.grab().save(shot)
                    app.quit()
                    return
                w.player.play()
                QTimer.singleShot(1500, lambda: (w._run(), QTimer.singleShot(6000, lambda: cycle(n - 1))))
            QTimer.singleShot(500, w._run)
            QTimer.singleShot(6000, lambda: cycle(int(env["RAMEAU_SELFTEST_REPEAT"])))
            return app.exec()
        QTimer.singleShot(500, w._run)
        QTimer.singleShot(1200, lambda: w.chord_list.setCurrentRow(3))
        first_tab = int(env.get("RAMEAU_SELFTEST_CENTER", "0"))
        QTimer.singleShot(4000, lambda: snap(first_tab, shot, lambda: snap(1, shot.replace(".png", "-fp.png"), app.quit)))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
