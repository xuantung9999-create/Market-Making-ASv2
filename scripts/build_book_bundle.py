"""Build dashboard/runs/book-<date>.js from the recorded order book (Dashboard Redesign R5).

    python -m scripts.build_book_bundle                      # every coin found under data/live
    python -m scripts.build_book_bundle --symbols ANKRUSDT,COTIUSDT --root data/live

Reads data/live/<SYMBOL>/book and data/live/<SYMBOL>/trades through mm.recorder.load_live.
Needs recorded data on this machine; data/ is not in the repository."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from mm import bookstats, report
from mm.recorder import load_live


def find_symbols(root: Path) -> list[str]:
    return sorted(p.name for p in root.iterdir() if (p / "book").is_dir()) if root.is_dir() else []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m scripts.build_book_bundle")
    ap.add_argument("--root", default="data/live")
    ap.add_argument("--symbols", default=None, help="comma-separated; default: every folder under --root")
    ap.add_argument("--out", default="dashboard/runs")
    ap.add_argument("--validation", default="results/tape_validation.csv",
                    help="output of scripts.validate_tape; added to the bundle when the file exists")
    args = ap.parse_args(argv)
    root = Path(args.root)
    syms = [s.strip() for s in args.symbols.split(",")] if args.symbols else find_symbols(root)
    if not syms:
        print(f"no recorded books under {root}. Start the recorder first (run_recorder.bat).", file=sys.stderr)
        return 1
    frames = {}
    for s in syms:
        try:
            frames[s] = (load_live(root / s / "book"), load_live(root / s / "trades"))
        except FileNotFoundError as e:
            print(f"skipping {s}: {e}", file=sys.stderr)
    if not frames:
        return 1
    tv = None
    if Path(args.validation).exists():
        tv = bookstats.tape_validation(pd.read_csv(args.validation))
    depth = {}
    for s_ in frames:
        try:
            depth[s_] = load_live(root / s_ / "depth")
        except FileNotFoundError:
            pass                                   # recorded without --depth
    b = bookstats.book_bundle(frames, tape_validation=tv, depth=depth or None)
    path = report.write_bundle(b, args.out, slim=False)
    print(f"book bundle -> {path} ({path.stat().st_size / 1e3:.0f} kB), {len(frames)} coins")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
