"""The step-entry editor widget: type or click notes, see them as sheet music, feed the harmonizer."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPen
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QToolButton, QVBoxLayout,
    QWidget,
)

from .stepentry import DURATIONS, MelodyDoc, StepNote

KEY_CHOICES = [("C major", "C"), ("G major", "G"), ("D major", "D"), ("A major", "A"), ("E major", "E"),
               ("F major", "F"), ("B♭ major", "B-"), ("E♭ major", "E-"), ("A♭ major", "A-"),
               ("A minor", "a"), ("E minor", "e"), ("D minor", "d"), ("G minor", "g"), ("B minor", "b"),
               ("C minor", "c"), ("F# minor", "f#")]
METERS = ["4/4", "3/4", "2/4", "6/8", "3/2"]
DURATION_LABELS = {1: ("1/1", "Whole note"), 2: ("1/2", "Half note"), 3: ("1/4", "Quarter note"),
                   4: ("1/8", "Eighth note"), 5: ("1/16", "Sixteenth note")}


class PianoKeyboard(QWidget):
    """Two clickable octaves; arrows shift the range."""

    noteClicked = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.base = 60  # C4
        self.setMinimumHeight(90)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFocusPolicy(Qt.NoFocus)
        self.highlight: int | None = None

    def _keys(self):
        whites, blacks = [], []
        w = self.width() / 15
        x = 0.0
        for i in range(25):
            midi = self.base + i
            if midi % 12 in (1, 3, 6, 8, 10):
                blacks.append((QRectF(x - w * 0.3, 0, w * 0.6, self.height() * 0.6), midi))
            else:
                whites.append((QRectF(x, 0, w, self.height() - 1), midi))
                x += w
        return whites, blacks

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        whites, blacks = self._keys()
        for rect, midi in whites:
            p.setBrush(QColor("#f6d8a8") if midi == self.highlight else QColor("white"))
            p.setPen(QPen(QColor("#555")))
            p.drawRect(rect)
            if midi % 12 == 0:
                p.drawText(rect.adjusted(0, 0, 0, -4), Qt.AlignBottom | Qt.AlignHCenter, f"C{midi // 12 - 1}")
        for rect, midi in blacks:
            p.setBrush(QColor("#c98a3a") if midi == self.highlight else QColor("#222"))
            p.drawRect(rect)

    def mousePressEvent(self, event) -> None:
        whites, blacks = self._keys()
        pos = event.position()
        for rect, midi in blacks + whites:  # black keys sit on top
            if rect.contains(pos):
                self.noteClicked.emit(midi)
                return

    def shift(self, octaves: int) -> None:
        self.base = max(36, min(72, self.base + 12 * octaves))
        self.update()


class StepEntryWidget(QWidget):
    """Note-by-note melody entry. Emits ``changed`` with fresh ABC after every edit."""

    changed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.doc = MelodyDoc()
        self.duration_key = 3
        self.dotted = False
        self.setFocusPolicy(Qt.StrongFocus)

        top = QHBoxLayout()
        self.title = QLineEdit(self.doc.title)
        self.title.setPlaceholderText("Title")
        self.title.editingFinished.connect(self._meta_changed)
        top.addWidget(self.title, 2)
        self.key_box = QComboBox()
        for label, name in KEY_CHOICES:
            self.key_box.addItem(label, name)
        self.key_box.currentIndexChanged.connect(self._meta_changed)
        top.addWidget(self.key_box)
        self.meter_box = QComboBox()
        self.meter_box.addItems(METERS)
        self.meter_box.currentIndexChanged.connect(self._meta_changed)
        top.addWidget(self.meter_box)

        durs = QHBoxLayout()
        self.dur_group = QButtonGroup(self)
        for k, (symbol, name) in DURATION_LABELS.items():
            b = QToolButton()
            b.setText(symbol)
            b.setToolTip(f"{name}  (key {k})")
            b.setMinimumWidth(34)
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setChecked(k == self.duration_key)
            self.dur_group.addButton(b, k)
            durs.addWidget(b)
        self.dur_group.idClicked.connect(self._set_duration)
        self.dot_btn = self._button("dot", self._toggle_dot, checkable=True, tip="Dotted: 1½ times as long  (key .)")
        durs.addWidget(self.dot_btn)
        durs.addStretch(1)

        actions = QHBoxLayout()
        for text, fn, tip in (("Rest", self._rest, "Add a rest  (key R)"),
                              ("𝄐", self._fermata, "Fermata: end a phrase here  (Shift+F)"),
                              ("⌫", self._delete, "Delete the selected note  (Backspace)"),
                              ("Clear", self._clear, "Start over"),
                              ("Lower", lambda: self._shift(-1), "Show a lower octave on the piano"),
                              ("Higher", lambda: self._shift(1), "Show a higher octave on the piano")):
            actions.addWidget(self._button(text, fn, tip=tip))
        actions.addStretch(1)

        self.score = QWebEngineView()
        self.score.setFocusPolicy(Qt.NoFocus)
        self.score.setMinimumHeight(160)
        self.piano = PianoKeyboard()
        self.piano.noteClicked.connect(self._add_midi)
        help_ = QLabel("Type A–G for notes, 1–5 for durations, . dot, R rest, ⇧F fermata, ↑/↓ semitone "
                       "(with ⌘/Ctrl: octave), ←/→ select, ⌫ delete. Or click the piano.")
        help_.setWordWrap(True)
        help_.setStyleSheet("color: gray;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addLayout(top)
        lay.addLayout(durs)
        lay.addLayout(actions)
        lay.addWidget(self.score, 1)
        lay.addWidget(self.piano)
        lay.addWidget(help_)

        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(120)
        self._render_timer.timeout.connect(self._render)
        self._refresh()

    # ---------------------------------------------------------------- helpers
    def _button(self, text, fn, checkable=False, tip: str = "") -> QPushButton:
        b = QPushButton(text)
        b.setToolTip(tip)
        b.setFocusPolicy(Qt.NoFocus)
        b.setCheckable(checkable)
        b.clicked.connect(fn)
        return b

    def _duration(self) -> float:
        d = DURATIONS[self.duration_key]
        return d * 1.5 if self.dotted else d

    def _refresh(self) -> None:
        self.changed.emit(self.doc.to_abc())
        sel = self.doc.notes[self.doc.selected] if 0 <= self.doc.selected < len(self.doc.notes) else None
        self.piano.highlight = sel.midi if sel else None
        self.piano.update()
        self._render_timer.start()

    def _render(self) -> None:
        """Draw the melody from the same ABC the harmonizer will read, with the selected note in colour."""
        from music21 import metadata, stream

        from .music import load_melody
        from .render import to_svg_pages

        try:
            part = load_melody(self.doc.to_abc()) if self.doc.notes else None
        except Exception as e:
            self.score.setHtml(f"<p>Couldn't read the melody: {e}</p>")
            return
        if part is None:
            from music21 import meter, note

            part = stream.Part()
            part.insert(0, self.doc.music21_key)
            part.insert(0, meter.TimeSignature(self.doc.meter))
            part.append(note.Rest(quarterLength=self.doc.bar_length()))
            part = part.makeMeasures()
        elif 0 <= self.doc.selected < len(self.doc.notes):
            target = self.doc.offset_of(self.doc.selected)
            for n in part.flatten().notesAndRests:
                if abs(n.offset - target) < 1e-6:
                    n.style.color = "#d0452f"
                    break
        score = stream.Score()
        score.metadata = metadata.Metadata(title=self.doc.title)
        score.insert(0, part)
        try:
            svg = "".join(f"<div>{p}</div>" for p in to_svg_pages(score, width=1400, scale=50))
        except Exception as e:
            svg = f"<p>Couldn't draw the score: {e}</p>"
        self.score.setHtml("<html><head><style>body{margin:6px;background:white} svg{width:100%;height:auto;"
                           f"display:block}}</style></head><body>{svg}</body></html>")

    # ---------------------------------------------------------------- actions
    def load(self, doc: MelodyDoc) -> None:
        self.doc = doc
        self.title.setText(doc.title)
        i = self.key_box.findData(doc.key)
        if i < 0:
            self.key_box.addItem(doc.key, doc.key)
            i = self.key_box.count() - 1
        self.key_box.blockSignals(True)
        self.key_box.setCurrentIndex(i)
        self.key_box.blockSignals(False)
        self.meter_box.blockSignals(True)
        if self.meter_box.findText(doc.meter) < 0:
            self.meter_box.addItem(doc.meter)
        self.meter_box.setCurrentText(doc.meter)
        self.meter_box.blockSignals(False)
        self._refresh()

    def _meta_changed(self, *_):
        self.doc.title = self.title.text().strip() or "My melody"
        self.doc.key = self.key_box.currentData() or "C"
        self.doc.meter = self.meter_box.currentText()
        self._refresh()

    def _set_duration(self, k: int) -> None:
        self.duration_key = k
        self.dur_group.button(k).setChecked(True)

    def _toggle_dot(self) -> None:
        self.dotted = not self.dotted
        self.dot_btn.setChecked(self.dotted)

    def _add_midi(self, midi: int) -> None:
        self.doc.insert(StepNote(midi, self._duration()))
        self._refresh()

    def _rest(self) -> None:
        self.doc.insert(StepNote(None, self._duration()))
        self._refresh()

    def _fermata(self) -> None:
        if 0 <= self.doc.selected < len(self.doc.notes):
            n = self.doc.notes[self.doc.selected]
            n.fermata = not n.fermata
            self._refresh()

    def _delete(self) -> None:
        self.doc.delete_selected()
        self._refresh()

    def _clear(self) -> None:
        self.doc.notes.clear()
        self.doc.selected = -1
        self._refresh()

    def _shift(self, octaves: int) -> None:
        self.piano.shift(octaves)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key, text = event.key(), event.text().upper()
        mods = event.modifiers()
        octave = bool(mods & (Qt.ControlModifier | Qt.MetaModifier))
        if text in "ABCDEFG" and text and not octave:
            if text == "F" and mods & Qt.ShiftModifier:
                self._fermata()
            else:
                self._add_midi(self.doc.letter_to_midi(text))
        elif text in ("1", "2", "3", "4", "5"):
            self._set_duration(int(text))
        elif text == ".":
            self._toggle_dot()
        elif text == "R":
            self._rest()
        elif key == Qt.Key_Up:
            self.doc.transpose_selected(12 if octave else 1)
            self._refresh()
        elif key == Qt.Key_Down:
            self.doc.transpose_selected(-12 if octave else -1)
            self._refresh()
        elif key == Qt.Key_Left:
            self.doc.move(-1)
            self._refresh()
        elif key == Qt.Key_Right:
            self.doc.move(1)
            self._refresh()
        elif key in (Qt.Key_Backspace, Qt.Key_Delete):
            self._delete()
        else:
            super().keyPressEvent(event)
