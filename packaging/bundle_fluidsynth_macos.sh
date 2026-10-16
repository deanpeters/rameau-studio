#!/usr/bin/env bash
# Copy Homebrew's FluidSynth and the libraries it needs into packaging/assets/fluidsynth, rewritten to
# load from inside the app, then ad-hoc sign them (Apple Silicon refuses unsigned binaries).
set -euo pipefail
DEST="$(cd "$(dirname "$0")" && pwd)/assets/fluidsynth"
rm -rf "$DEST"
mkdir -p "$DEST/bin" "$DEST/libs"
cp "$(brew --prefix)/bin/fluidsynth" "$DEST/bin/fluidsynth"
chmod u+w "$DEST/bin/fluidsynth"
dylibbundler -of -b -x "$DEST/bin/fluidsynth" -d "$DEST/libs" -p @executable_path/../libs/ > /dev/null
for f in "$DEST/libs/"*.dylib "$DEST/bin/fluidsynth"; do
  codesign --force --sign - "$f"
done
"$DEST/bin/fluidsynth" --version | head -1
