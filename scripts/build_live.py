"""Live status for the dashboard: what the 24/7 PC is doing right now.

    python -m scripts.build_live            # writes dashboard/live/status.js once

The supervisor (scripts/supervise_live.py) calls ``build()`` every minute. The dashboard's Live tab
re-reads dashboard/live/status.js every 30 s, so opening dashboard/index.html on the PC shows a
live view without a server. dashboard/live/ is git-ignored: live numbers never go to GitHub.

Reads (all optional; missing parts show as "no data yet"):
  data/live_status/supervisor.json        process states and restarts (written by the supervisor)
  data/testnet/<SYM>/status.json          testnet position, P&L, open orders (every minute)
  data/testnet/<SYM>/fills_<date>.jsonl   real testnet fills
  data/testnet/<SYM>/orders_<date>.jsonl  places, cancels, rejects
  data/live/<SYM>/book|trades/*.parquet   recorder part files (only file names, plus the newest file)
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

PART_RE = re.compile(r"_(\d{12,14})\.parquet$")
DAY_S = 86_400


def _read_json(p: Path) -> Optional[dict]:
    try:
        return json.loads(p.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _jsonl(paths, since_us: int) -> list[dict]:
    out = []
    for p in paths:
        try:
            for line in p.read_text().splitlines():
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("ts_us", 0) >= since_us:
                    out.append(r)
        except OSError:
            continue
    out.sort(key=lambda r: r.get("ts_us", 0))
    return out


def _recent_days(now: datetime, n: int) -> list[str]:
    return [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n - 1, -1, -1)]


def testnet_section(root: Path, now: datetime, days: int = 7) -> list[dict]:
    """One entry per traded symbol: status, fill curve, last fills, order counts per hour."""
    out = []
    if not root.is_dir():
        return out
    now_us = int(now.timestamp() * 1e6)
    since = now_us - days * DAY_S * 1_000_000
    since24 = now_us - DAY_S * 1_000_000
    dates = _recent_days(now, days)
    for d in sorted(p for p in root.iterdir() if p.is_dir() and p.name not in ("feed", "state")):
        status = _read_json(d / "status.json")
        fills = _jsonl([d / f"fills_{x}.jsonl" for x in dates], since)
        orders = _jsonl([d / f"orders_{x}.jsonl" for x in dates[-2:]], since24)
        if not (status or fills or orders):
            continue
        hours: dict[int, dict] = {}
        for o in orders:
            h = o["ts_us"] // 3_600_000_000 * 3600
            c = hours.setdefault(h, {"place": 0, "cancel": 0, "reject": 0, "fill": 0})
            op = o.get("op", "")
            if op in ("place", "cancel", "reject"):
                c[op] += 1
        for f in fills:
            if f["ts_us"] >= since24:
                h = f["ts_us"] // 3_600_000_000 * 3600
                hours.setdefault(h, {"place": 0, "cancel": 0, "reject": 0, "fill": 0})["fill"] += 1
        events = [{"t": o["ts_us"] // 1000, "op": o.get("op"), "side": o.get("side"),
                   "price": o.get("price"), "error": o.get("error")} for o in orders[-40:]]
        out.append({
            "symbol": d.name,
            "status": status,
            "curve": {"t": [f["ts_us"] // 1000 for f in fills], "pnl": [f.get("pnl") for f in fills],
                      "pos": [f.get("pos") for f in fills]},
            "fills": [{"t": f["ts_us"] // 1000, "side": f.get("side"), "price": f.get("price"), "qty": f.get("qty"),
                       "mid": f.get("mid"), "pnl": f.get("pnl"), "how": f.get("how")} for f in fills[-50:]][::-1],
            "fills_24h": sum(1 for f in fills if f["ts_us"] >= since24),
            "hours": [{"t": h * 1000, **c} for h, c in sorted(hours.items())],
            "events": events[::-1],
        })
    return out


def _parts(folder: Path) -> list[int]:
    if not folder.is_dir():
        return []
    ms = []
    for p in folder.glob("*.parquet"):
        m = PART_RE.search(p.name)
        if m:
            ms.append(int(m.group(1)))
    return sorted(ms)


def _rows(path: Path) -> Optional[int]:
    try:
        import pyarrow.parquet as pq
        return int(pq.ParquetFile(path).metadata.num_rows)
    except Exception:                              # noqa: BLE001 - unreadable part file: just skip the count
        return None


def recorder_section(root: Path, now: datetime, gap_s: float = 180.0) -> list[dict]:
    """Per symbol: newest part file age, part files and gaps over 24 h, rows in the newest part."""
    out = []
    if not root.is_dir():
        return out
    now_ms = int(now.timestamp() * 1000)
    since = now_ms - DAY_S * 1000
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        row = {"symbol": d.name}
        for kind in ("book", "trades"):
            ms = _parts(d / kind)
            recent = [m for m in ms if m >= since]
            gaps = [(b - a) / 1000 for a, b in zip(recent, recent[1:]) if (b - a) / 1000 > gap_s]
            newest = ms[-1] if ms else None
            row[kind] = {
                "last_ms": newest,
                "age_s": (now_ms - newest) / 1000 if newest else None,
                "parts_24h": len(recent),
                "gaps_24h": len(gaps),
                "gap_minutes_24h": round(sum(gaps) / 60, 1),
                "rows_last_part": _rows(d / kind / f"{d.name}_{kind}_{newest}.parquet") if newest else None,
                "total_parts": len(ms),
            }
        out.append(row)
    return out


def build(base: str | Path = ".", out: str | Path = "dashboard/live/status.js", now: Optional[datetime] = None) -> dict:
    base = Path(base)
    now = now or datetime.now(timezone.utc)
    live = {
        "built_ms": int(now.timestamp() * 1000),
        "supervisor": _read_json(base / "data/live_status/supervisor.json"),
        "testnet": testnet_section(base / "data/testnet", now),
        "recorder": recorder_section(base / "data/live", now),
    }
    p = base / out
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text("window.LIVE = " + json.dumps(live, separators=(",", ":"), default=str) + ";\n")
    tmp.replace(p)
    return live


if __name__ == "__main__":
    t = time.time()
    live = build()
    print(f"dashboard/live/status.js: {len(live['testnet'])} testnet symbols, "
          f"{len(live['recorder'])} recorded symbols ({time.time() - t:.2f}s)")
