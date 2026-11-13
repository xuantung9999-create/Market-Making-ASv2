"""v2.1 Task 13 pass rule: does the Markov microprice beat the existing micro_bp out of sample?

    python -m scripts.eval_markov                     # COTIUSDT, ANKRUSDT, SKLUSDT from data/live

Each test day is scored with a table fitted on the 3 days before it (mm.markov.fit_daily). A coin
passes if ``markov_bp`` has the higher R2 than ``micro_bp`` at all three horizons (1, 5, 30 s), R2 pooled
over its test days weighted by rows. Task 13 passes if at least 2 of the 3 coins pass; otherwise keep
``micro_bp`` and delete mm/markov.py. Needs 4 or more recorded days per coin."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from mm import markov
from mm.calibrate import infer_tick
from mm.recorder import load_live

COINS = ["COTIUSDT", "ANKRUSDT", "SKLUSDT"]
HORIZONS = (1, 5, 30)


def evaluate_coin(book: pd.DataFrame, trades: pd.DataFrame | None, symbol: str, tick: float | None = None) -> dict:
    tick = tick or infer_tick(np.r_[book["bid"].to_numpy(), book["ask"].to_numpy()])
    tables = markov.fit_daily(book, tick, train_days=3)
    day = book["recv_us"].to_numpy(np.int64) // markov.DAY
    acc = {h: {"markov": 0.0, "micro": 0.0, "n": 0} for h in HORIZONS}
    for d, table in tables.items():
        rep = markov.r2_report(book[day == d], table, tick, HORIZONS)
        for h in HORIZONS:
            n = rep[h]["n"]
            acc[h]["n"] += n
            for k in ("markov", "micro"):
                acc[h][k] += rep[h][k] * n
    out = {"symbol": symbol, "test_days": len(tables)}
    for h in HORIZONS:
        n = max(acc[h]["n"], 1)
        out[f"markov_{h}s"], out[f"micro_{h}s"] = acc[h]["markov"] / n, acc[h]["micro"] / n
    out["pass"] = len(tables) > 0 and all(out[f"markov_{h}s"] > out[f"micro_{h}s"] for h in HORIZONS)
    return out


def verdict(rows: list[dict]) -> bool:
    return sum(1 for r in rows if r["pass"]) >= 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m scripts.eval_markov")
    ap.add_argument("--root", default="data/live")
    ap.add_argument("--symbols", default=",".join(COINS))
    args = ap.parse_args(argv)
    rows = []
    for s in [x.strip() for x in args.symbols.split(",") if x.strip()]:
        try:
            rows.append(evaluate_coin(load_live(Path(args.root) / s / "book"), None, s))
        except FileNotFoundError as e:
            print(f"{s}: {e}", file=sys.stderr)
    if not rows:
        print("no recorded books found; record 4+ days first", file=sys.stderr)
        return 1
    df = pd.DataFrame(rows)
    print(df.round(4).to_string(index=False))
    ok = verdict(rows)
    print("\nTask 13:", "PASS (keep markov_bp)" if ok else "FAIL (keep micro_bp, delete mm/markov.py)")
    Path("results").mkdir(exist_ok=True)
    df.to_csv("results/eval_markov.csv", index=False)
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
