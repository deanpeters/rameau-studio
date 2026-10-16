"""Command-line interface.

    rameau harmonize melody.abc --style bach_chorale --out out/
    rameau harmonize melody.abc --play
    rameau styles
    rameau fingerprint bach_chorale
    rameau train-folder ./my_pieces --name my_style --title "My style"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .style import builtin_styles, load_style


def _harmonize(args) -> int:
    from . import render
    from .harmonize import harmonize
    from .music import load_melody
    from .voicing import realize

    src = Path(args.melody)
    melody = load_melody(src)
    style = load_style(args.style)
    h = harmonize(melody, style, key=args.key)
    r = realize(h)
    title = args.title or src.stem.replace("_", " ").title()
    score = render.build_score(melody, h, r, title)

    out = Path(args.out or ".")
    out.mkdir(parents=True, exist_ok=True)
    stem = out / src.stem
    files = [
        render.write_midi(score, stem.with_suffix(".mid"), bpm=args.tempo),
        render.write_musicxml(score, stem.with_suffix(".musicxml")),
    ]
    md = stem.with_suffix(".md")
    md.write_text(render.explanation_markdown(h, r, title), encoding="utf-8")
    files.append(md)
    if args.svg:
        for i, svg in enumerate(render.to_svg_pages(score), 1):
            p = out / f"{src.stem}-{i}.svg"
            p.write_text(svg, encoding="utf-8")
            files.append(p)

    print("\n".join(h.notes))
    prev = None
    line = []
    for c in h.choices:
        if c.beat.beat == 1 and line:
            print("  " + " ".join(line))
            line = []
        line.append((c.symbol if c.label != prev else "·") + ("." if c.beat.phrase_end else ""))
        prev = c.label
    if line:
        print("  " + " ".join(line))
    errors = sum(1 for f in r.findings if f.severity == "error")
    print(f"Voice leading: {errors} rule breaks, {len(r.findings) - errors} warnings")
    print("Wrote:\n  " + "\n  ".join(str(f) for f in files))

    if args.play:
        from .audio import play_file, render_wav

        wav = render_wav(files[0], stem.with_suffix(".wav"))
        print(f"Playing {wav} (Ctrl-C to stop)")
        play_file(wav, wait=True)
    return 0


def _styles(args) -> int:
    for name, path in sorted(builtin_styles().items()):
        s = load_style(name)
        print(f"{name:20} {s.title}: {s.description} [{s.pieces} pieces]")
    return 0


def _fingerprint(args) -> int:
    from .fingerprint import fingerprint_markdown

    print(fingerprint_markdown([load_style(n) for n in args.styles]))
    return 0


def _train_folder(args) -> int:
    from .train import train_folder

    out = Path(args.out or f"{args.name}.json")
    m = train_folder(Path(args.folder), out, args.name, args.title or args.name)
    print(f"Trained {m.title} from {m.pieces} pieces -> {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="rameau", description="Rameau: learn harmony by hearing it.")
    sub = p.add_subparsers(dest="cmd", required=True)

    h = sub.add_parser("harmonize", help="harmonize a melody (ABC, MusicXML or MIDI) in a style")
    h.add_argument("melody")
    h.add_argument("--style", default="bach_chorale", help="built-in style name or a style .json file")
    h.add_argument("--key", help="force a key, e.g. G or e (default: detect)")
    h.add_argument("--out", help="output folder (default: current folder)")
    h.add_argument("--title")
    h.add_argument("--tempo", type=int, default=72)
    h.add_argument("--svg", action="store_true", help="also write sheet music as SVG")
    h.add_argument("--play", action="store_true", help="play the result")
    h.set_defaults(func=_harmonize)

    s = sub.add_parser("styles", help="list built-in styles")
    s.set_defaults(func=_styles)

    f = sub.add_parser("fingerprint", help="show (and compare) the signature habits of styles")
    f.add_argument("styles", nargs="+")
    f.set_defaults(func=_fingerprint)

    t = sub.add_parser("train-folder", help="learn a new style from a folder of harmonized pieces")
    t.add_argument("folder")
    t.add_argument("--name", required=True)
    t.add_argument("--title")
    t.add_argument("--out")
    t.set_defaults(func=_train_folder)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
