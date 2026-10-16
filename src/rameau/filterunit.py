"""The Filter unit and Mixer panels: shape the music while it plays."""

from __future__ import annotations

import dataclasses

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QPushButton,
    QScrollArea, QSlider, QSpinBox, QToolButton, QVBoxLayout, QWidget,
)

from .controls import GM_NAMES, ORNAMENT_KINDS, PRESETS, Controls

SLIDERS = [  # (field, label, group, min, max, scale, tooltip)
    ("adventure", "Adventure", "Harmony", 0, 100, 100,
     "0 = the style's safest chords. Higher = less obvious chords the style really uses."),
    ("bass_independence", "Bass independence", "Lines", 0, 200, 100,
     "How much the bass moves as its own melody, against the tune (0 = plain block chords)."),
    ("ornament_density", "Ornaments", "Texture", 0, 200, 100,
     "Passing notes, neighbors, suspensions... 100% = the style's own rates, 0 = none."),
    ("expression", "Expression", "Performance", 0, 200, 100, "Dynamics, accents and voice balance (0 = flat)."),
    ("rubato", "Rubato", "Performance", 0, 200, 100, "Slowing into cadences and held fermatas (0 = strict time)."),
    ("articulation", "Articulation", "Performance", -100, 100, 100, "How connected the notes are."),
    ("humanize", "Humanize", "Performance", 0, 200, 100, "Tiny human variations in timing and loudness."),
    ("reverb", "Reverb", "Room", 0, 100, 100, "From a dry studio to a cathedral (instant)."),
]
KIND_LABELS = {"passing": "Passing", "neighbor": "Neighbor", "anticipation": "Anticipation",
               "arpeggio": "Arpeggio", "suspension": "Suspension"}


class FilterUnit(QWidget):
    """Musical controls. Emits ``changed`` (debounced) with a new Controls value."""

    changed = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.controls = Controls()
        self._sliders: dict[str, tuple[QSlider, int, QLabel]] = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(220)
        self._timer.timeout.connect(lambda: self.changed.emit(self.controls))

        top = QHBoxLayout()
        top.addWidget(QLabel("<b>Filter unit</b>"))
        self.presets = QComboBox()
        self.presets.addItem("Presets…")
        for name in PRESETS:
            self.presets.addItem(name)
        for name in self._user_presets():
            self.presets.addItem(f"★ {name}", name)
        self.presets.activated.connect(self._preset_chosen)
        top.addWidget(self.presets, 1)
        save = QPushButton("Save…")
        save.setToolTip("Save the current settings as your own preset")
        save.clicked.connect(self._save_preset)
        top.addWidget(save)

        grid = QGridLayout()
        grid.setVerticalSpacing(4)
        groups: dict[str, QFormLayout] = {}
        col = 0
        for group in ("Harmony", "Lines", "Texture", "Performance", "Room"):
            box = QGroupBox(group)
            form = QFormLayout(box)
            form.setContentsMargins(6, 2, 6, 2)
            form.setVerticalSpacing(2)
            groups[group] = form
            # one row of columns: [Harmony / Lines / Room] [Texture] [Performance]
            place = {"Harmony": (0, 0, 1), "Lines": (1, 0, 1), "Room": (2, 0, 1), "Texture": (0, 1, 3),
                     "Performance": (0, 2, 3)}[group]
            grid.addWidget(box, place[0], place[1], place[2], 1)
            col += 1
        for name, label, group, lo, hi, scale, tip in SLIDERS:
            sl = QSlider(Qt.Horizontal)
            sl.setRange(lo, hi)
            sl.setToolTip(tip)
            sl.setMinimumWidth(90)
            value = QLabel()
            value.setMinimumWidth(38)
            row = QHBoxLayout()
            row.addWidget(sl, 1)
            row.addWidget(value)
            w = QWidget()
            w.setLayout(row)
            groups[group].addRow(label, w)
            self._sliders[name] = (sl, scale, value)
            sl.valueChanged.connect(lambda v, n=name: self._slider_moved(n, v))

        # ornament kinds + variation
        kinds = QGridLayout()
        kinds.setContentsMargins(0, 0, 0, 0)
        self._kind_boxes = {}
        for i, k in enumerate(ORNAMENT_KINDS):
            cb = QCheckBox(KIND_LABELS[k])
            cb.setChecked(True)
            cb.toggled.connect(self._kinds_changed)
            self._kind_boxes[k] = cb
            kinds.addWidget(cb, i // 2, i % 2)
        kw = QWidget()
        kw.setLayout(kinds)
        groups["Texture"].addRow(kw)
        var_row = QHBoxLayout()
        self.variation = QSpinBox()
        self.variation.setRange(1, 9999)
        self.variation.valueChanged.connect(lambda v: self._set("variation", v))
        dice = QToolButton()
        dice.setText("🎲")
        dice.setToolTip("A new variation of the same settings")
        dice.clicked.connect(lambda: self.variation.setValue(self.variation.value() % 9999 + 1))
        var_row.addWidget(self.variation)
        var_row.addWidget(dice)
        vw = QWidget()
        vw.setLayout(var_row)
        groups["Texture"].addRow("Variation", vw)

        # swing
        swing_row = QHBoxLayout()
        self.swing_auto = QCheckBox("style's own")
        self.swing_auto.setChecked(True)
        self.swing = QSlider(Qt.Horizontal)
        self.swing.setRange(0, 100)
        self.swing.setEnabled(False)
        self.swing.setToolTip("0 = straight eighths ... 100 = hard swing")
        self.swing_auto.toggled.connect(self._swing_changed)
        self.swing.valueChanged.connect(lambda _: self._swing_changed())
        swing_row.addWidget(self.swing_auto)
        swing_row.addWidget(self.swing, 1)
        sw = QWidget()
        sw.setLayout(swing_row)
        groups["Performance"].addRow("Swing", sw)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.addLayout(top)
        lay.addLayout(grid)
        self.set_controls(self.controls, emit=False)

    # ---------------------------------------------------------------- state
    def set_controls(self, c: Controls, emit: bool = True) -> None:
        self.controls = c
        for name, (sl, scale, label) in self._sliders.items():
            sl.blockSignals(True)
            sl.setValue(round(getattr(c, name) * scale))
            sl.blockSignals(False)
            label.setText(self._fmt(name, getattr(c, name)))
        for k, cb in self._kind_boxes.items():
            cb.blockSignals(True)
            cb.setChecked(k in c.ornament_kinds)
            cb.blockSignals(False)
        self.variation.blockSignals(True)
        self.variation.setValue(c.variation)
        self.variation.blockSignals(False)
        self.swing_auto.blockSignals(True)
        self.swing_auto.setChecked(c.swing is None)
        self.swing_auto.blockSignals(False)
        self.swing.setEnabled(c.swing is not None)
        self.swing.blockSignals(True)
        self.swing.setValue(round((c.swing or 0) * 100))
        self.swing.blockSignals(False)
        if emit:
            self._timer.start()

    @staticmethod
    def _fmt(name: str, v: float) -> str:
        if name == "articulation":
            return "legato" if v < -0.15 else ("detached" if v > 0.15 else "natural")
        return f"{v:.0%}"

    def _set(self, name: str, value) -> None:
        self.controls = dataclasses.replace(self.controls, **{name: value})
        self._timer.start()

    def _slider_moved(self, name: str, v: int) -> None:
        sl, scale, label = self._sliders[name]
        value = v / scale
        label.setText(self._fmt(name, value))
        self._set(name, value)

    def _kinds_changed(self) -> None:
        self._set("ornament_kinds", [k for k, cb in self._kind_boxes.items() if cb.isChecked()])

    def _swing_changed(self) -> None:
        self.swing.setEnabled(not self.swing_auto.isChecked())
        self._set("swing", None if self.swing_auto.isChecked() else self.swing.value() / 100)

    # ---------------------------------------------------------------- presets
    def _user_presets(self) -> dict:
        from .ai import load_settings

        return load_settings().get("presets", {})

    def _preset_chosen(self, index: int) -> None:
        if index == 0:
            return
        key = self.presets.itemData(index) or self.presets.itemText(index)
        if key in PRESETS:
            c = PRESETS[key]
        else:
            c = Controls.from_dict(self._user_presets()[key])
        self.set_controls(dataclasses.replace(c, tempo=self.controls.tempo))

    def _save_preset(self) -> None:
        from .ai import load_settings, save_settings

        name, ok = QInputDialog.getText(self, "Save preset", "Name for these settings:")
        if not ok or not name.strip():
            return
        settings = load_settings()
        settings.setdefault("presets", {})[name.strip()] = self.controls.to_dict()
        save_settings(settings)
        self.presets.addItem(f"★ {name.strip()}", name.strip())


class MixerPanel(QWidget):
    """One strip per channel: instrument, volume, pan, mute, solo. Changes are heard instantly."""

    channelChanged = Signal(int, dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(4, 2, 4, 2)
        self._lay.addWidget(QLabel("<b>Mixer</b> <span style='color:gray'>(instant)</span>"))
        self._rows = QWidget()
        self._grid = QGridLayout(self._rows)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setVerticalSpacing(2)
        self._grid.setAlignment(Qt.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._rows)
        self._lay.addWidget(scroll, 1)
        self._channels: dict = {}

    def set_program(self, program) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if program is None:
            return
        for c_i, head in enumerate(("Part", "Instrument", "Volume", "Pan", "M", "S")):
            self._grid.addWidget(QLabel(f"<small><b>{head}</b></small>"), 0, c_i)
        for row, (ch, c) in enumerate(sorted(program.channels.items()), start=1):
            self._grid.addWidget(QLabel(c.name), row, 0)
            self._grid.setRowMinimumHeight(row, 24)
            inst = QComboBox()
            if ch == 9:
                inst.addItem("Drum kit")
                inst.setEnabled(False)
            else:
                inst.addItems([f"{i + 1:3} {n}" for i, n in enumerate(GM_NAMES)])
                inst.setCurrentIndex(c.program)
                inst.currentIndexChanged.connect(lambda i, ch=ch: self.channelChanged.emit(ch, {"program": i}))
            self._grid.addWidget(inst, row, 1)
            vol = QSlider(Qt.Horizontal)
            vol.setRange(0, 127)
            vol.setValue(c.volume)
            vol.setMaximumWidth(140)
            vol.valueChanged.connect(lambda v, ch=ch: self.channelChanged.emit(ch, {"volume": v}))
            self._grid.addWidget(vol, row, 2)
            pan = QSlider(Qt.Horizontal)
            pan.setRange(0, 127)
            pan.setValue(c.pan)
            pan.setMaximumWidth(70)
            pan.valueChanged.connect(lambda v, ch=ch: self.channelChanged.emit(ch, {"pan": v}))
            self._grid.addWidget(pan, row, 3)
            for col, field_name, val in ((4, "mute", c.mute), (5, "solo", c.solo)):
                cb = QCheckBox()
                cb.setChecked(val)
                cb.toggled.connect(lambda on, ch=ch, f=field_name: self.channelChanged.emit(ch, {f: on}))
                self._grid.addWidget(cb, row, col)
        self._grid.setColumnStretch(1, 1)
