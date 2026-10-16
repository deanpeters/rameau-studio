# PyInstaller recipe for Rameau Studio.  Build with:   uv run pyinstaller packaging/rameau.spec --noconfirm
#
# Optional extras picked up when present (CI downloads them):
#   packaging/assets/GeneralUser-GS.sf2        SoundFont bundled for out-of-the-box sound
#   packaging/assets/fluidsynth/               FluidSynth binaries (bundled on Windows)

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src" / "rameau"
ASSETS = ROOT / "packaging" / "assets"
APP_NAME = "Rameau Studio"

datas = [
    (str(SRC / "styles"), "rameau/styles"),
    (str(SRC / "samples"), "rameau/samples"),
    (str(ROOT / "LICENSE"), "."),
]
# The MMA engine is run from source files, so ship it as data (without machine-specific indexes).
for sub in ("MMA", "lib", "includes", "plugins"):
    for f in (ROOT / "engine" / "mma" / sub).rglob("*"):
        if f.is_file() and not f.name.startswith(".mmaDB") and "__pycache__" not in f.parts:
            datas.append((str(f), str(Path("engine/mma") / f.relative_to(ROOT / "engine" / "mma").parent)))
for name in ("mma.py", "LICENSE", "README", "UPSTREAM_COMMIT"):
    if (ROOT / "engine" / "mma" / name).exists():
        datas.append((str(ROOT / "engine" / "mma" / name), "engine/mma"))

datas += collect_data_files("verovio")
datas += collect_data_files("music21", excludes=["corpus/**"])  # the score corpus is only used for training
datas += collect_data_files("certifi")

for sf in ASSETS.glob("*.sf2"):
    datas.append((str(sf), "soundfonts"))
fluid = ASSETS / "fluidsynth"
if fluid.exists():
    for f in fluid.rglob("*"):
        if f.is_file():
            datas.append((str(f), str(Path("fluidsynth") / f.relative_to(fluid).parent)))

# Modules MMA imports that Rameau itself may not (MMA runs from source inside the packaged app).
hiddenimports = collect_submodules("music21") + [
    "array", "atexit", "copy", "ctypes", "datetime", "getopt", "hashlib", "pickle", "random", "struct",
    "tempfile", "textwrap", "types", "runpy", "keyring.backends",
]
if sys.platform != "win32":
    hiddenimports.append("fcntl")
else:
    hiddenimports += ["winreg", "keyring.backends.Windows"]
if sys.platform == "darwin":
    hiddenimports.append("keyring.backends.macOS")

excludes = ["tkinter", "matplotlib", "IPython", "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtDataVisualization",
            "PySide6.QtQuick3D", "PySide6.QtBluetooth", "PySide6.QtLocation", "PySide6.QtSensors",
            "PySide6.QtSerialPort", "PySide6.QtSql", "PySide6.QtDesigner", "PySide6.QtPdf"]

a = Analysis(
    [str(SRC / "__main__.py")],
    pathex=[str(ROOT / "src")],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="RameauStudio",
    console=False,
    argv_emulation=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="RameauStudio")
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        bundle_identifier="io.github.deanpeters.rameau-studio",
        info_plist={
            "CFBundleShortVersionString": "0.1.0",
            "NSHighResolutionCapable": True,
        },
    )
