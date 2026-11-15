"""Rebuild each testnet symbol's position from the start of its data, keeping all history.

Before carry (task L1b) every restart began at pos 0 while the account kept its coins, so each session
only saw its own inventory. The clean ledger is: flat at the first fill ever recorded, plus every fill
since. This script replays that ledger, lists every restart that reset the session's count (with the
inventory the reset hid), checks the result against the exchange balances logged in session.jsonl,
and compares it with the carried state file.

    python -m scripts.rebuild_ledger                       # report only, changes nothing
    python -m scripts.rebuild_ledger --write               # + write <SYM>/ledger_genesis.json (new file)
    python -m scripts.rebuild_ledger --write --write-exec  # + rewrite state/<SYM>_exec.json (backup kept)

Fill, order and session files are never modified. ``--write-exec`` should only be used with the bots
stopped, since a running bot overwrites its state file at every checkpoint.
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from mm.paper import DAY_US
from mm.testnet import Executor, now_us


def _ts(us: int) -> str:
    return datetime.fromtimestamp(us / 1e6, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def read_fills(folder: Path) -> list[dict]:
    rows = []
    for f in sorted(folder.glob("fills_*.jsonl")):
        for line in f.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return sorted(rows, key=lambda r: r.get("ts_us", 0))


def read_sessions(folder: Path) -> list[dict]:
    p = folder / "session.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def replay(fills: list[dict]) -> dict:
    """Clean ledger from flat at the first fill. Also finds resets: a fill whose recorded pre-fill pos
    (``pos - side*qty``, what the running session believed) differs from the previous fill's recorded pos."""
    pos = 0.0
    resets, path = [], []
    prev_rec = None
    for r in fills:
        q, side = float(r["qty"]), int(r["side"])
        if r.get("pos") is not None:
            rec_pre = float(r["pos"]) - side * q
            if prev_rec is not None and abs(rec_pre - prev_rec) > 1e-9:
                resets.append({"ts_us": r["ts_us"], "session_had": prev_rec, "restarted_at": rec_pre,
                               "ledger": pos, "mid": float(r.get("mid") or r["price"])})
            prev_rec = float(r["pos"])
        pos += side * q
        path.append((int(r["ts_us"]), pos))
    return {"pos": pos, "resets": resets, "path": path}


def ledger_pos_at(path: list[tuple[int, float]], ts: int) -> float:
    p = 0.0
    for t, v in path:
        if t >= ts:
            break
        p = v
    return p


def analyse(out_dir: Path, sym: str, lot_usd: float) -> Optional[dict]:
    folder = out_dir / sym
    fills = read_fills(folder)
    if not fills:
        return None
    rp = replay(fills)
    first = fills[0]
    start_flat = abs(float(first.get("pos", first["side"] * first["qty"])) - first["side"] * first["qty"]) < 1e-9
    # genesis base balance implied by every session start that logged its free balance (orders were cancelled
    # before the balance was read, so free == total then)
    implied = []
    for s in read_sessions(folder):
        if s.get("op") == "start" and s.get("base_free") is not None:
            implied.append({"ts_us": s["ts_us"], "base_free": float(s["base_free"]),
                            "ledger_pos": ledger_pos_at(rp["path"], s["ts_us"]),
                            "genesis_base": float(s["base_free"]) - ledger_pos_at(rp["path"], s["ts_us"])})
    ex = Executor(sym, rules=None, client=None, lot_usd=lot_usd, q_max=10**9, out_dir=out_dir,
                  state_dir=out_dir / "state", dry_run=True)
    tot = ex._fill_totals(until_us=now_us() // DAY_US * DAY_US)
    exec_state = None
    try:
        exec_state = json.loads(ex.exec_state_path.read_text())
    except (OSError, ValueError):
        pass
    return {"symbol": sym, "fills": len(fills), "first_ts": first["ts_us"], "starts_flat": start_flat,
            "replay": rp, "implied": implied, "totals": tot, "exec_state": exec_state, "executor": ex}


def report(a: dict, lot_usd: float) -> None:
    sym, rp, tot = a["symbol"], a["replay"], a["totals"]
    mid = tot["mid"] or 0.0
    lots = (lambda p: p * mid / lot_usd) if mid else (lambda p: float("nan"))
    print(f"\n=== {sym}: {a['fills']} fills since {_ts(a['first_ts'])} UTC "
          f"({'starts flat' if a['starts_flat'] else 'first fill NOT from flat'})")
    if rp["resets"]:
        print("  restarts that reset the session's count:")
        for r in rp["resets"]:
            hid = r["ledger"] - r["restarted_at"]
            print(f"    {_ts(r['ts_us'])}  session held {r['session_had']:+.5f}, restarted at "
                  f"{r['restarted_at']:+.5f}, true ledger {r['ledger']:+.5f}  "
                  f"(hidden {hid:+.5f} = {hid * r['mid'] / lot_usd:+.1f} lots)")
    print(f"  clean ledger now: pos {tot['pos']:+.6f} ({lots(tot['pos']):+.1f} lots at {mid:g}), "
          f"cash {tot['cash']:.2f}, fees {tot['fees']:.2f}, pnl {tot['cash'] + tot['pos'] * mid - tot['fees']:.2f}")
    for i in a["implied"]:
        print(f"  balance check {_ts(i['ts_us'])}: free {i['base_free']:g}, ledger {i['ledger_pos']:+.6f} "
              f"-> starting balance {i['genesis_base']:.6f}")
    es = a["exec_state"]
    if es is not None:
        d = float(es["pos"]) - tot["pos"]
        tag = "matches" if abs(lots(d)) <= 1.0 else f"DIFFERS by {lots(d):+.1f} lots"
        print(f"  state file pos {float(es['pos']):+.6f}: {tag}")
    else:
        print("  state file: none")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="data/testnet")
    ap.add_argument("--symbols", default=None, help="comma list; default: every folder with fill files")
    ap.add_argument("--lot-usd", type=float, default=100.0)
    ap.add_argument("--base", action="append", default=[],
                    help="SYM=BALANCE starting base balance for the genesis (default 1.0, the testnet grant)")
    ap.add_argument("--write", action="store_true", help="write <SYM>/ledger_genesis.json if it does not exist")
    ap.add_argument("--write-exec", action="store_true", help="also rewrite state/<SYM>_exec.json (bots stopped!)")
    args = ap.parse_args()
    out = Path(args.out)
    syms = args.symbols.split(",") if args.symbols else sorted(
        p.name for p in out.iterdir() if p.is_dir() and any(p.glob("fills_*.jsonl")))
    base = {k: float(v) for k, v in (b.split("=", 1) for b in args.base)}
    for sym in syms:
        a = analyse(out, sym, args.lot_usd)
        if a is None:
            print(f"\n=== {sym}: no fills")
            continue
        report(a, args.lot_usd)
        if not args.write:
            continue
        ex: Executor = a["executor"]
        if ex.genesis_path.exists():
            print(f"  genesis exists, left as is: {ex.genesis_path}")
        else:
            g = {"ts_us": int(a["first_ts"]), "pos": 0.0, "cash": 0.0, "fees": 0.0,
                 "base_balance": base.get(sym, 1.0), "created_us": now_us(),
                 "note": "flat at the first recorded fill; position = genesis + all fills since"}
            ex.genesis_path.write_text(json.dumps(g, indent=1))
            print(f"  wrote {ex.genesis_path} (base_balance {g['base_balance']:g})")
        if args.write_exec:
            p = ex.exec_state_path
            if p.exists():
                bak = p.with_name(f"{p.name}.bak-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}")
                shutil.copy2(p, bak)
                print(f"  backup {bak}")
            old = a["exec_state"] or {}
            tot = ex._fill_totals(until_us=now_us() // DAY_US * DAY_US)
            ex.pos, ex.cash, ex.fees = tot["pos"], tot["cash"], tot["fees"]
            ex.day = now_us() // DAY_US
            same_day = old.get("day") == ex.day
            ex.day_start_pnl = float(old["day_start_pnl"]) if same_day and "day_start_pnl" in old \
                else tot["day_start_pnl"]
            ex.stopped = bool(old.get("stopped", False)) if same_day else False
            ex.save_exec_state()
            print(f"  wrote {p}: pos {ex.pos:+.6f}")


if __name__ == "__main__":
    main()
