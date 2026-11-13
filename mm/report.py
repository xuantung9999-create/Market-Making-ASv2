"""Run bundles: the one format the trading dashboard reads.

Every number on the dashboard's Desk views is computed here, in Python, and written into a *run
bundle*: one JSON object per run (a backtest, a walk-forward test, a paper-trading session or, later,
a real account). The page only draws bundles, so a new data source needs no page change.

The contract is section 3 of ``docs/DASHBOARD_GUIDE.md``. In short:

    schema, run_id, kind, label, built_utc, config, days      required
    summary, curves, hourly, markouts, edge, calib, agent,    optional
    wait_hist, stress, screen, gates, health

Rules that keep the page honest:

- A key the producer cannot fill is LEFT OUT, never set to 0 or null. The page then shows
  "Not in this run" instead of a misleading zero.
- No NaN or Infinity anywhere (JSON has no such values and the page would draw nonsense).
- Only days with at least ``MIN_FILLS`` fills enter the statistics; thinner days still count in totals.
- No absolute file paths or account identifiers in a bundle.

Units: P&L in USD (USDT), markouts and edges in basis points of price, inventory in lots, times UTC.
"""
from __future__ import annotations

import json
import math
import re
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd

from mm.metrics import max_drawdown

SCHEMA = 1
KINDS = ("backtest", "walkforward", "paper", "live", "demo", "book")
REQUIRED = ("schema", "run_id", "kind", "label", "built_utc", "config", "days")
DAY_KEYS_REQUIRED = ("symbol", "date", "variant")
MIN_FILLS = 20              # a day needs this many fills to enter the statistics
MIN_DAYS_SHARPE = 5         # fewer counted days: no t-stat / Sharpe
MIN_DAYS_VAR = 20           # fewer counted days: no VaR / ES
MARKOUT_H = (1, 10, 60, 300)
RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
ABS_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/(?:home|Users|mnt|root|tmp|var|etc)/)")
JS_PREFIX = "window.RUNS = window.RUNS || {};"


# =============================================================================== helpers
def _finite(x) -> bool:
    return x is not None and isinstance(x, (int, float, np.floating, np.integer)) and math.isfinite(float(x))


def _put(d: dict, key: str, value) -> None:
    """Set ``d[key]`` only if ``value`` is a finite number (or a non-number that is not None)."""
    if value is None:
        return
    if isinstance(value, (float, np.floating)):
        if not math.isfinite(float(value)):
            return
        d[key] = float(value)
    elif isinstance(value, (np.integer,)):
        d[key] = int(value)
    elif isinstance(value, (np.bool_,)):
        d[key] = bool(value)
    else:
        d[key] = value


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")


def _iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%MZ")


def _day_start(date: str) -> datetime:
    return datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _minute_times(res, date: Optional[str]) -> list[datetime]:
    """UTC timestamps of a result's minute rows: from a ``ts_us`` column if the engine wrote one,
    else ``date`` midnight + ``t_s``."""
    m = res.minute
    if "ts_us" in m.columns:
        return [datetime.fromtimestamp(v / 1e6, tz=timezone.utc) for v in m["ts_us"].to_numpy()]
    if date is None:
        raise ValueError("result has no ts_us column: pass dates=[...] (one per result)")
    d0 = _day_start(date)
    return [d0 + timedelta(seconds=float(s)) for s in m["t_s"].to_numpy()]


def _fill_times(res, date: Optional[str]) -> list[datetime]:
    f = res.fills
    if len(f) == 0:
        return []
    if "ts_us" in f.columns:
        return [datetime.fromtimestamp(v / 1e6, tz=timezone.utc) for v in f["ts_us"].to_numpy()]
    if date is None:
        raise ValueError("result has no ts_us column: pass dates=[...] (one per result)")
    d0 = _day_start(date)
    return [d0 + timedelta(seconds=float(s)) for s in f["t_s"].to_numpy()]


# =============================================================================== day rows
def day_row(res, symbol: str, date: str, variant: str, extra: dict | None = None) -> dict:
    """One row of ``days`` from an engine result (``BTResult`` or ``QSResult``).

    ``net_edge_bp`` is the 60 s markout minus the maker fee: the same definition as
    ``mm.edge.net_edge_bp``, averaged over fills. Keys the result cannot provide are left out.
    """
    tot, f, m = res.totals, res.fills, res.minute
    d: dict = {"symbol": symbol, "date": date, "variant": variant}
    for k in ("pnl", "spread_capture", "inventory_pnl", "fees", "notional"):
        _put(d, k, tot.get(k))
    d["fills"] = int(len(f))
    if len(f) and "side" in f.columns:
        d["buy_fills"] = int((f["side"] > 0).sum())

    mk = getattr(res, "markouts", None)
    if mk is not None and len(mk):
        by_h = dict(zip(mk["h_s"].astype(float), mk["markout_bp"].astype(float)))
        for h in MARKOUT_H:
            _put(d, f"mk_{h}", by_h.get(float(h)))
        fee = getattr(res.cfg, "maker_fee_bps", None)
        if 60.0 in by_h and fee is not None:
            _put(d, "net_edge_bp", by_h[60.0] - float(fee))
    if len(f) and "net_edge_bp" in f.columns:          # per-fill net edge from the v2 engine wins
        _put(d, "net_edge_bp", float(np.nanmean(f["net_edge_bp"].to_numpy(float))))
    if len(f) and "wait_s" in f.columns:
        _put(d, "wait_s_med", float(np.nanmedian(f["wait_s"].to_numpy(float))))

    if len(m):
        q = m["q"].to_numpy(float)
        _put(d, "q_abs_max", float(np.abs(q).max()))
        if len(q) > 1:
            _put(d, "q_std", float(q.std(ddof=1)))
        _put(d, "max_dd", max_drawdown(m["pnl"].to_numpy(float)))
    if "uptime" in tot:
        u = tot["uptime"]
        _put(d, "uptime", float(np.mean(list(u.values()))) if isinstance(u, dict) else u)
    for k, v in (extra or {}).items():
        _put(d, k, v)
    return d


# =============================================================================== summary
def _stats(pnl_all: np.ndarray, notional_all: np.ndarray, counted: np.ndarray,
           notional_counted: np.ndarray, q_max: int, lot_usd: float) -> dict:
    out: dict = {}
    n = int(len(counted))
    out["days"] = n
    out["pnl_total"] = float(pnl_all.sum())
    notional_total = float(notional_all.sum())
    if notional_total > 0:
        out["net_bp_per_usd"] = out["pnl_total"] / notional_total * 1e4
    if n == 0:
        return out
    mean = float(counted.mean())
    out["pnl_mean_day"] = mean
    out["hit_rate"] = float((counted > 0).mean())
    out["max_dd"] = max_drawdown(np.cumsum(counted))
    if len(notional_counted) and q_max and lot_usd:
        out["turnover_day"] = float(np.mean(notional_counted / (q_max * lot_usd)))
    neg = counted[counted < 0].sum()
    if neg < 0:
        out["profit_factor"] = float(counted[counted > 0].sum() / abs(neg))
    if n >= 2:
        std = float(counted.std(ddof=1))
        out["pnl_std_day"] = std
        if n >= MIN_DAYS_SHARPE and std > 0:
            s = mean / std
            out["t_stat"] = mean / (std / math.sqrt(n))
            out["sharpe_ann"] = s * math.sqrt(365)
            out["sharpe_se"] = math.sqrt((1 + 0.5 * s * s) / n) * math.sqrt(365)
    if n >= MIN_DAYS_VAR:
        v = float(np.percentile(counted, 5))
        out["var95_day"] = v
        out["es95_day"] = float(counted[counted <= v].mean())
    return out


def _fill_weighted(rows: list[dict], per_date: Optional[int] = None) -> dict:
    """Display columns for the blotter: ``fills_day`` (mean fills per day, or per date for the
    pooled row) and fill-weighted means of ``net_edge_bp`` and ``mk_60`` over all days."""
    out: dict = {}
    n_days = per_date if per_date is not None else len(rows)
    total_fills = sum(r.get("fills", 0) for r in rows)
    if n_days:
        out["fills_day"] = total_fills / n_days
    for k in ("net_edge_bp", "mk_60"):
        w = [(r[k], r.get("fills", 0)) for r in rows if k in r and r.get("fills", 0) > 0]
        wsum = sum(f for _, f in w)
        if wsum:
            out[k] = sum(v * f for v, f in w) / wsum
    return out


def summary_rows(days: list[dict], q_max: int, lot_usd: float) -> list[dict]:
    """Statistics per symbol|variant plus one pooled row per variant (``symbol == "ALL"``, the
    portfolio: daily P&L summed across symbols per date). Pooled rows come first.

    A day counts in the statistics if it has ``fills >= MIN_FILLS``. Every day counts in
    ``pnl_total`` and ``net_bp_per_usd``.
    """
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for d in days:
        if "pnl" in d:
            groups[(d["symbol"], d["variant"])].append(d)

    def counted(rows):
        c = [r for r in rows if r.get("fills", 0) >= MIN_FILLS]
        return (np.array([r["pnl"] for r in c], float),
                np.array([r.get("notional", 0.0) for r in c], float))

    per_symbol = []
    for (sym, var), rows in sorted(groups.items()):
        rows = sorted(rows, key=lambda r: r["date"])
        cp, cn = counted(rows)
        row = {"symbol": sym, "variant": var}
        row.update(_stats(np.array([r["pnl"] for r in rows], float),
                          np.array([r.get("notional", 0.0) for r in rows], float), cp, cn, q_max, lot_usd))
        row.update(_fill_weighted(rows))
        per_symbol.append(row)

    pooled = []
    for var in sorted({v for _, v in groups}):
        by_date: dict[str, dict] = defaultdict(lambda: {"pnl": 0.0, "fills": 0, "notional": 0.0})
        for (sym, v), rows in groups.items():
            if v != var:
                continue
            for r in rows:
                agg = by_date[r["date"]]
                agg["pnl"] += r["pnl"]; agg["fills"] += r.get("fills", 0); agg["notional"] += r.get("notional", 0.0)
        rows = [by_date[k] for k in sorted(by_date)]
        cp, cn = counted(rows)
        n_sym = len({s for s, v in groups if v == var})
        row = {"symbol": "ALL", "variant": var}
        row.update(_stats(np.array([r["pnl"] for r in rows], float),
                          np.array([r["notional"] for r in rows], float), cp, cn,
                          q_max * n_sym, lot_usd))
        row.update(_fill_weighted([r for (_, v), rs in groups.items() if v == var for r in rs], per_date=len(rows)))
        pooled.append(row)
    return pooled + per_symbol


# =============================================================================== curves
def curve(results: list, every_min: int = 5, dates: Optional[list[str]] = None) -> dict:
    """``{t, pnl, q, mid}`` sampled every ``every_min`` minutes, P&L cumulative across the list
    (each result is one UTC day; its P&L restarts at 0, so earlier days' totals are added)."""
    t, pnl, q, mid = [], [], [], []
    offset = 0.0
    step = every_min * 60
    for i, res in enumerate(results):
        m = res.minute
        if len(m) == 0:
            continue
        times = _minute_times(res, dates[i] if dates else None)
        secs = m["t_s"].to_numpy(float) if "t_s" in m.columns else np.array(
            [(x - times[0]).total_seconds() for x in times])
        bucket = np.floor((secs - 1e-9) / step).astype(int)
        last = np.r_[bucket[1:] != bucket[:-1], True]           # last row of each bucket
        p, qq, mm_ = m["pnl"].to_numpy(float), m["q"].to_numpy(float), m["mid"].to_numpy(float)
        for j in np.flatnonzero(last):
            t.append(_iso(times[j])); pnl.append(round(offset + p[j], 6))
            q.append(float(qq[j])); mid.append(float(mm_[j]))
        offset += float(p[-1])
    return {"t": t, "pnl": pnl, "q": q, "mid": mid}


def hourly(results: list, dates: Optional[list[str]] = None) -> dict:
    """P&L, fills and (when per-fill net edge exists) mean net edge by UTC hour of day."""
    pnl = np.zeros(24); fills = np.zeros(24, int)
    edge_sum = np.zeros(24); edge_n = np.zeros(24, int)
    for i, res in enumerate(results):
        date = dates[i] if dates else None
        m = res.minute
        if len(m):
            times = _minute_times(res, date)
            p = m["pnl"].to_numpy(float)
            dp = np.diff(np.r_[0.0, p])
            if "ts_us" in m.columns:
                starts = [times[0] - timedelta(minutes=1)] + times[:-1]
            else:
                d0 = _day_start(date)
                starts = [d0] + times[:-1]
            for st, x in zip(starts, dp):
                pnl[st.hour] += x
        f = res.fills
        if len(f):
            ft = _fill_times(res, date)
            has_edge = "net_edge_bp" in f.columns
            e = f["net_edge_bp"].to_numpy(float) if has_edge else None
            for j, ts in enumerate(ft):
                fills[ts.hour] += 1
                if has_edge and math.isfinite(e[j]):
                    edge_sum[ts.hour] += e[j]; edge_n[ts.hour] += 1
    out = {"pnl": [round(float(x), 6) for x in pnl], "fills": [int(x) for x in fills]}
    if edge_n.sum():
        # hours with no fills get the overall mean so the array stays numeric (no NaN in JSON)
        overall = float(edge_sum.sum() / edge_n.sum())
        out["net_edge_bp"] = [float(edge_sum[h] / edge_n[h]) if edge_n[h] else overall for h in range(24)]
    return out


def markout_rows(res, symbol: str, variant: str) -> list[dict]:
    """Markout rows for the Execution view. Engines with per-fill ``action`` and ``f_mk_<h>``
    columns get one row per action and side; otherwise one pooled row (action ALL, side both)."""
    f = res.fills
    rows = []
    per_fill = len(f) and "action" in f.columns and all(f"mk_{h}" in f.columns for h in MARKOUT_H)
    if per_fill:
        for (act, side), g in f.groupby(["action", "side"]):
            for h in MARKOUT_H:
                x = g[f"mk_{h}"].to_numpy(float); x = x[np.isfinite(x)]
                if len(x) < 2:
                    continue
                rows.append({"symbol": symbol, "variant": variant, "action": _ACTION_NAMES.get(act, str(act)),
                             "side": "buy" if side > 0 else "sell", "h_s": h, "bp": float(x.mean()),
                             "se": float(x.std(ddof=1) / math.sqrt(len(x))), "n": int(len(x))})
        return rows
    mk = getattr(res, "markouts", None)
    if mk is None or not len(mk):
        return rows
    for _, r in mk.iterrows():
        h = float(r["h_s"])
        if h not in MARKOUT_H:
            continue
        row = {"symbol": symbol, "variant": variant, "action": "ALL", "side": "both", "h_s": int(h),
               "bp": float(r["markout_bp"]), "n": int(len(f))}
        _put(row, "se", r.get("se_bp"))
        rows.append(row)
    return rows


_ACTION_NAMES = {0: "OUT", 1: "JOIN", 2: "BACK"}
WAIT_EDGES = [0, 2, 5, 10, 20, 40, 80, 160, 320, 640, 1280, 3600, 86400]


def edge_rows(table, symbol: str) -> list[dict]:
    """The ``edge`` section from a v2 ``EdgeTable``: shrunk mean and standard error per action and
    (imbalance, volatility) bucket. Actions without enough pooled fills to estimate are left out."""
    rows = []
    for act, name in ((1, "JOIN"), (2, "BACK")):
        for imb in range(3):
            for vol in range(3):
                mean, se = table.estimate(act, (imb, vol))
                if mean <= -1e8:
                    continue
                n = table.cell(act, (imb, vol))[0]
                rows.append({"symbol": symbol, "action": name, "imb": imb, "vol": vol,
                             "n": round(float(n), 2), "mean": float(mean), "se": float(se)})
    return rows


def agent_rows(history: list[dict], symbol: str) -> list[dict]:
    """The ``agent`` section from ``CalibrationAgent.history``."""
    return [{"symbol": symbol, "ts": _iso(datetime.fromtimestamp(h["ts_us"] / 1e6, tz=timezone.utc)),
             "live_arm": int(h["live_arm"]), "switched": bool(h["switched"]),
             "scores": [round(float(x), 4) for x in h["scores"]]} for h in history]


def calib_rows(fills: pd.DataFrame, symbol: str, bins: int = 5) -> list[dict]:
    """5 equal-count bins of the table's predicted net edge against the realised net edge."""
    if not {"pred_edge_bp", "net_edge_bp"} <= set(fills.columns):
        return []
    f = fills[["pred_edge_bp", "net_edge_bp"]].astype(float)
    f = f[np.isfinite(f["pred_edge_bp"]) & np.isfinite(f["net_edge_bp"])].sort_values("pred_edge_bp", kind="stable")
    if len(f) < 2 * bins:
        return []
    rows = []
    for g in np.array_split(np.arange(len(f)), bins):
        part = f.iloc[g]
        real = part["net_edge_bp"].to_numpy()
        row = {"symbol": symbol, "pred_mean": float(part["pred_edge_bp"].mean()), "real_mean": float(real.mean()),
               "n": int(len(part))}
        if len(real) > 1:
            row["se"] = float(real.std(ddof=1) / math.sqrt(len(real)))
        rows.append(row)
    return rows


def wait_hist_of(fills: pd.DataFrame, edges=WAIT_EDGES) -> dict:
    """Histogram of queue waits (seconds from order activation to fill)."""
    w = fills["wait_s"].to_numpy(float) if len(fills) and "wait_s" in fills.columns else np.array([])
    w = w[np.isfinite(w)]
    count, _ = np.histogram(np.clip(w, edges[0], edges[-1] - 1e-9), bins=edges)
    return {"edges": list(edges), "count": [int(c) for c in count]}


def screen_rows(screen: pd.DataFrame) -> list[dict]:
    """The ``screen`` section from results/screen.csv (Build Guide Task 2)."""
    out = []
    for _, r in screen.iterrows():
        row = {"symbol": str(r["symbol"]), "constrained": bool(r["constrained"])}
        for src, dst in (("tick_bp_med", "tick_bp"), ("spread_ticks_med", "spread_ticks"),
                         ("usd_volume_med", "usd_volume_day"), ("trades_per_sec_med", "trades_per_s"), ("days", "days")):
            if src in r:
                _put(row, dst, float(r[src]))
        out.append(row)
    return out


def public_bundle(b: dict, every_min: int = 30, agent_every: int = 4) -> dict:
    """A copy fit for publishing (Dashboard Guide D12): run id ``pub-<run_id>``, curves thinned to
    one point every ``every_min`` minutes (the last point of each bucket, so totals stay exact),
    agent history thinned to every ``agent_every``-th row plus every switch. Demo runs are refused."""
    if b.get("kind") == "demo":
        raise ValueError("refusing to publish a demo bundle")
    out = json.loads(json.dumps(b))
    out["run_id"] = b["run_id"] if b["run_id"].startswith("pub-") else f"pub-{b['run_id']}"
    for key, c in (out.get("curves") or {}).items():
        t = c.get("t") or []
        if not t:
            continue
        stamps = [datetime.fromisoformat(x.replace("Z", "+00:00")) for x in t]
        bucket = [int(s.timestamp() // (every_min * 60)) for s in stamps]
        keep = [i for i in range(len(t)) if i == len(t) - 1 or bucket[i + 1] != bucket[i]]
        for k, v in list(c.items()):
            if isinstance(v, list) and len(v) == len(t):
                c[k] = [v[i] for i in keep]
    if out.get("agent"):
        by_sym: dict = defaultdict(list)
        for r in out["agent"]:
            by_sym[r["symbol"]].append(r)
        out["agent"] = [r for rows in by_sym.values() for i, r in enumerate(rows)
                        if r["switched"] or i % agent_every == 0 or i == len(rows) - 1]
    return out


def stress_rows(days: list[dict], q_max: int, lot_usd: float, shocks=(5, 10, 20)) -> list[dict]:
    """Loss in USD if the price gaps ``shock_pct`` against a full position: at the cap
    (``q_max`` lots of ``lot_usd``) and at the largest inventory actually seen."""
    max_seen: dict[str, float] = {}
    syms = []
    for d in days:
        s = d["symbol"]
        if s not in syms:
            syms.append(s)
        if "q_abs_max" in d:
            max_seen[s] = max(max_seen.get(s, 0.0), float(d["q_abs_max"]))
    rows = []
    for s in syms:
        for sh in shocks:
            r = {"symbol": s, "shock_pct": sh, "loss_at_cap_usd": q_max * lot_usd * sh / 100}
            if s in max_seen:
                r["loss_at_max_seen_usd"] = max_seen[s] * lot_usd * sh / 100
            rows.append(r)
    return rows


# =============================================================================== bundles
def build_bundle(run_id: str, kind: str, label: str, config: dict, days: list[dict],
                 built_utc: Optional[str] = None, **sections) -> dict:
    """Assemble a bundle. ``summary`` is computed from ``days`` unless passed in; ``stress`` too
    when ``config`` has ``q_max`` and ``lot_usd``. Sections passed as None are left out."""
    b = {"schema": SCHEMA, "run_id": run_id, "kind": kind, "label": label,
         "built_utc": built_utc or _now_utc(), "config": dict(config), "days": list(days)}
    q_max, lot = config.get("q_max"), config.get("lot_usd")
    if "summary" not in sections and q_max and lot:
        b["summary"] = summary_rows(days, q_max, lot)
    if "stress" not in sections and q_max and lot and days:
        b["stress"] = stress_rows(days, q_max, lot)
    for k, v in sections.items():
        if v is not None:
            b[k] = v
    if b.get("curves"):
        b["curves"].update(pooled_curves(b["curves"]))
    return b


def pooled_curves(curves: dict) -> dict:
    """``ALL|<variant>`` curves: cumulative P&L and inventory summed across symbols on the union of
    their timestamps (each symbol's last value carried forward; 0 before its first point)."""
    out = {}
    by_var: dict[str, list[dict]] = defaultdict(list)
    for key, c in curves.items():
        sym, _, var = key.partition("|")
        if sym != "ALL" and c.get("t"):
            by_var[var].append(c)
    for var, cs in by_var.items():
        if len(cs) < 2:
            continue
        ts = sorted({t for c in cs for t in c["t"]})
        pnl = np.zeros(len(ts)); q = np.zeros(len(ts))
        pos = {t: i for i, t in enumerate(ts)}
        for c in cs:
            idx = np.array([pos[t] for t in c["t"]])
            for arr, vals in ((pnl, c["pnl"]), (q, c["q"])):
                filled = np.full(len(ts), np.nan); filled[idx] = vals
                filled = pd.Series(filled).ffill().fillna(0.0).to_numpy()
                arr += filled
        out[f"ALL|{var}"] = {"t": ts, "pnl": [round(float(x), 6) for x in pnl], "q": [float(x) for x in q]}
    return out


def _walk_nonfinite(x, path, out):
    if isinstance(x, dict):
        for k, v in x.items():
            _walk_nonfinite(v, f"{path}.{k}", out)
    elif isinstance(x, (list, tuple)):
        for i, v in enumerate(x):
            _walk_nonfinite(v, f"{path}[{i}]", out)
    elif isinstance(x, (float, np.floating)) and not math.isfinite(float(x)):
        out.append(f"non-finite number (NaN or Infinity) at {path}: not allowed, leave the key out")
    elif isinstance(x, str) and ABS_PATH_RE.match(x):
        out.append(f"absolute file path at {path}: bundles must not contain local paths")


def validate_bundle(b: dict) -> list[str]:
    """Problems with a bundle, one message each. An empty list means valid."""
    msgs: list[str] = []
    for k in REQUIRED:
        if k not in b:
            msgs.append(f"missing required key: {k}")
    if "schema" in b and b["schema"] != SCHEMA:
        msgs.append(f"schema must be {SCHEMA}, got {b['schema']!r}")
    if "kind" in b and b["kind"] not in KINDS:
        msgs.append(f"kind must be one of {KINDS}, got {b['kind']!r}")
    if "run_id" in b and not (isinstance(b["run_id"], str) and RUN_ID_RE.match(b["run_id"])):
        msgs.append(f"run_id must be a lowercase slug, got {b['run_id']!r}")
    if "days" in b:
        if not isinstance(b["days"], list):
            msgs.append("days must be a list")
        else:
            for i, d in enumerate(b["days"]):
                miss = [k for k in DAY_KEYS_REQUIRED if k not in d]
                if miss:
                    msgs.append(f"days[{i}] missing {', '.join(miss)}")
    for key, c in (b.get("curves") or {}).items():
        lens = {k: len(c.get(k, [])) for k in ("t", "pnl", "q", "mid") if k in c}
        if "t" not in c or len(set(lens.values())) > 1:
            msgs.append(f"curves[{key}] arrays differ in length: {lens}")
    for key, h in (b.get("hourly") or {}).items():
        bad = [k for k, v in h.items() if len(v) != 24]
        if bad:
            msgs.append(f"hourly[{key}] arrays must have length 24: {bad}")
    _walk_nonfinite(b, "bundle", msgs)
    return msgs


def _dumps(b: dict) -> str:
    return json.dumps(b, allow_nan=False, separators=(",", ":"), ensure_ascii=False)


def _index_entry(b: dict) -> dict:
    syms = []
    for d in b["days"] or b.get("forest") or []:
        if d["symbol"] not in syms and d["symbol"] != "ALL":
            syms.append(d["symbol"])
    syms = syms or list(b.get("symbols") or [])
    n_days = len({d["date"] for d in b["days"]}) if b["days"] else max(
        [r.get("days_total", 0) for r in b.get("forest") or []] + [len({c["date"] for c in b.get("coverage") or []})] or [0])
    return {"run_id": b["run_id"], "kind": b["kind"], "label": b["label"], "built_utc": b["built_utc"],
            "symbols": syms, "n_days": n_days}


def read_index(out_dir: str | Path = "dashboard/runs") -> list[dict]:
    p = Path(out_dir) / "index.js"
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8").strip()
    return json.loads(text[text.index("=") + 1:].strip().rstrip(";"))


def write_bundle(b: dict, out_dir: str | Path = "dashboard/runs", slim: bool = True) -> Path:
    """Write ``<run_id>.js`` (loadable with a plain ``<script>`` tag, so the page works from a file)
    and rewrite ``index.js``, newest first. Raises ``ValueError`` and writes nothing if invalid.
    ``slim`` applies the bundle diet (``slim_bundle``) so a committed run stays under 3 MB."""
    if slim:
        b = slim_bundle(b)
    problems = validate_bundle(b)
    if problems:
        raise ValueError("invalid bundle:\n  " + "\n  ".join(problems))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rid = b["run_id"]
    path = out / f"{rid}.js"
    path.write_text(f'{JS_PREFIX}\nwindow.RUNS["{rid}"] = {_dumps(b)};\n', encoding="utf-8")
    idx = [e for e in read_index(out) if e["run_id"] != rid] + [_index_entry(b)]
    idx.sort(key=lambda e: e["built_utc"], reverse=True)
    (out / "index.js").write_text("window.RUN_INDEX = " + json.dumps(idx, indent=1, ensure_ascii=False) + ";\n",
                                  encoding="utf-8")
    return path


# =============================================================================== verdict + diet
# docs/DASHBOARD_REDESIGN.md section 5: a small bundle the Verdict tab loads first, and the thinning
# that keeps every run file under 3 MB.
HEADLINE_QUEUE = 1.0
KEEP_DAYS = 3                      # days of 5-minute points kept in a slimmed run
VERDICT_ID = "pub-verdict"
_QUEUE_RE = re.compile(r"\bq(\d+(?:\.\d+)?)")


def _queue_of(variant: str, default: Optional[float] = None) -> Optional[float]:
    m = _QUEUE_RE.search(variant)
    return float(m.group(1)) if m else default


def _scenario(variant: str, queue_mult: Optional[float]) -> str:
    if variant.startswith("bridge"):
        return "front of queue, 100 ms (v1 assumption)"
    if queue_mult is None:
        return variant
    tag = {0.5: " (optimistic)", 1.0: " (headline)", 2.0: " (stress)"}.get(queue_mult, "")
    return (f"queue {queue_mult:g}x{tag}" if variant.startswith("q") else f"{variant}, queue {queue_mult:g}x{tag}")


def _by_date(rows: list[dict]) -> list[dict]:
    """One row per date, P&L, fees, notional and fills summed across symbols (the portfolio day)."""
    agg: dict[str, dict] = {}
    for r in rows:
        a = agg.setdefault(r["date"], {"date": r["date"], "pnl": 0.0, "fees": 0.0, "notional": 0.0, "fills": 0})
        a["pnl"] += r.get("pnl", 0.0); a["fees"] += r.get("fees", 0.0)
        a["notional"] += r.get("notional", 0.0); a["fills"] += r.get("fills", 0)
    return [agg[d] for d in sorted(agg)]


def _ratio_stats(rows: list[dict]) -> dict:
    """Net and gross edge in bp per dollar traded with standard errors, over counted days.

    ``net_bp = sum(pnl) / sum(notional)``. Its standard error treats days as the independent unit
    (delta method on the ratio): ``sqrt(D / (D - 1) * sum((p_i - r * n_i)^2)) / sum(n)``.
    ``t`` is the t-statistic of daily P&L, as in ``summary_rows``. Days below ``MIN_FILLS`` fills do
    not enter the statistics but their fills still count in ``fills``."""
    counted = [r for r in rows if r.get("fills", 0) >= MIN_FILLS and r.get("notional", 0.0) > 0]
    out: dict = {"days_total": len(rows), "n_days": len(counted), "fills": int(sum(r.get("fills", 0) for r in rows))}
    if not counted:
        return out
    p = np.array([r["pnl"] for r in counted], float)
    n = np.array([r["notional"] for r in counted], float)
    g = p + np.array([r.get("fees", 0.0) for r in counted], float)
    total_n, d = float(n.sum()), len(counted)
    out["net_bp"] = float(p.sum() / total_n * 1e4)
    out["gross_bp"] = float(g.sum() / total_n * 1e4)
    out["hit_rate"] = float((p > 0).mean())
    if d >= 2:
        for key, x in (("net", p), ("gross", g)):
            r = x.sum() / total_n
            out[f"{key}_se"] = float(math.sqrt(d / (d - 1) * float(((x - r * n) ** 2).sum())) / total_n * 1e4)
        std = float(p.std(ddof=1))
        if d >= MIN_DAYS_SHARPE and std > 0:
            out["t"] = float(p.mean() / (std / math.sqrt(d)))
    return out


def _group_days(days: list[dict]) -> tuple[dict, dict]:
    per_sym: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for d in days:
        if "pnl" in d:
            per_sym[(d["symbol"], d["variant"])].append(d)
    per_var: dict[str, list[dict]] = defaultdict(list)
    for (_, var), rows in per_sym.items():
        per_var[var] += rows
    return per_sym, per_var


def _labelled(sym: str, var: str, queue_mult: Optional[float]) -> dict:
    qm = _queue_of(var, queue_mult)
    row = {"symbol": sym, "variant": var}
    if qm is not None:
        row["queue_mult"] = qm
    row["scenario"] = _scenario(var, qm)
    return row


def forest_rows(days: list[dict], queue_mult: Optional[float] = None) -> list[dict]:
    """One row per variant for the pooled portfolio (``symbol == "ALL"``, first) and one per
    symbol|variant: net and gross bp per dollar traded with standard errors, t, hit rate."""
    per_sym, per_var = _group_days(days)
    pooled = [{**_labelled("ALL", v, queue_mult), **_ratio_stats(_by_date(rows))} for v, rows in sorted(per_var.items())]
    single = [{**_labelled(s, v, queue_mult), **_ratio_stats(sorted(rows, key=lambda r: r["date"]))}
              for (s, v), rows in sorted(per_sym.items())]
    return pooled + single


def _compare_row(rows: list[dict], daily: list[dict]) -> dict:
    out = {"fills": int(sum(r.get("fills", 0) for r in rows)), "pnl_total": float(sum(r.get("pnl", 0.0) for r in rows))}
    st = _ratio_stats(daily)
    if "net_bp" in st:
        out["net_bp"] = st["net_bp"]
    w = [(r["mk_60"], r["fills"]) for r in rows if r.get("fills", 0) > 0 and _finite(r.get("mk_60"))]
    if sum(f for _, f in w):
        out["mk_60"] = float(sum(v * f for v, f in w) / sum(f for _, f in w))
    if daily:
        out["max_dd"] = float(max_drawdown(np.cumsum([r["pnl"] for r in daily])))
    return out


def compare_rows(days: list[dict], queue_mult: Optional[float] = None) -> list[dict]:
    """Totals per symbol|variant and pooled: fills, P&L over every day, net bp, fill-weighted 60 s
    markout and maximum drawdown of cumulative daily P&L."""
    per_sym, per_var = _group_days(days)
    pooled = [{**_labelled("ALL", v, queue_mult), **_compare_row(rows, _by_date(rows))} for v, rows in sorted(per_var.items())]
    single = [{**_labelled(s, v, queue_mult), **_compare_row(rows, sorted(rows, key=lambda r: r["date"]))}
              for (s, v), rows in sorted(per_sym.items())]
    return pooled + single


def thin_curves(curves: dict, keep_days: int = KEEP_DAYS) -> dict:
    """Every point of the last ``keep_days`` UTC days, and only the last point of each earlier day
    (so the final cumulative value of every day is exact). ``keep_days=0`` gives daily points only.
    Returns new curves; the input is not modified and thinning twice changes nothing."""
    out = {}
    for key, c in curves.items():
        t = c.get("t") or []
        if not t:
            out[key] = {k: (list(v) if isinstance(v, list) else v) for k, v in c.items()}
            continue
        day = [x[:10] for x in t]
        cutoff = ((datetime.fromisoformat(day[-1]) - timedelta(days=keep_days - 1)).strftime("%Y-%m-%d")
                  if keep_days > 0 else "9999-99-99")
        keep = [i for i in range(len(t)) if day[i] >= cutoff or i == len(t) - 1 or day[i + 1] != day[i]]
        out[key] = {k: ([v[i] for i in keep] if isinstance(v, list) and len(v) == len(t) else v) for k, v in c.items()}
    return out


def thin_agent(rows: list[dict]) -> list[dict]:
    """Every switch of live setting plus the last row of each symbol and day."""
    last: dict[tuple[str, str], int] = {}
    for i, r in enumerate(rows):
        last[(r["symbol"], r["ts"][:10])] = i
    keep = set(last.values()) | {i for i, r in enumerate(rows) if r.get("switched")}
    return [rows[i] for i in sorted(keep)]


def q_hist_of(curves: dict) -> dict:
    """Share of the run's 5-minute points spent at each whole-lot inventory level, per symbol|variant.
    Computed before thinning: end-of-day inventory alone would misstate how long a limit was hit."""
    out = {}
    for key, c in curves.items():
        if key.startswith("ALL|") or not c.get("q"):
            continue
        levels, counts = np.unique(np.round(np.asarray(c["q"], float)).astype(int), return_counts=True)
        out[key] = {"levels": [int(x) for x in levels], "share": [round(float(x), 8) for x in counts / counts.sum()]}
    return out


def slim_bundle(b: dict, keep_days: int = KEEP_DAYS) -> dict:
    """The diet every producer script applies before writing: 5-minute curves only for the last
    ``keep_days`` days, thinned agent history, and ``q_hist`` so the Risk tab keeps its inventory
    distribution. Idempotent."""
    out = dict(b)
    if b.get("curves"):
        if "q_hist" not in b:
            out["q_hist"] = q_hist_of(b["curves"])
        out["curves"] = thin_curves(b["curves"], keep_days)
    if b.get("agent"):
        out["agent"] = thin_agent(b["agent"])
    return out


def _gross_curve(net: dict, days: list[dict]) -> dict:
    """Net curve plus cumulative fees through each point's date: the same curve before fees."""
    fees: dict[str, float] = defaultdict(float)
    for d in days:
        fees[d["date"]] += d.get("fees", 0.0)
    dates_, cum, run = sorted(fees), [], 0.0
    for d in dates_:
        run += fees[d]
        cum.append(run)
    pnl = []
    for t, v in zip(net["t"], net["pnl"]):
        i = bisect_right(dates_, t[:10])
        pnl.append(round(v + (cum[i - 1] if i else 0.0), 6))
    return {"t": list(net["t"]), "pnl": pnl}


def verdict_bundle(runs: list[dict], run_id: str = VERDICT_ID) -> dict:
    """The small bundle behind the Verdict tab, from the queue-baseline (``backtest``) runs and the
    agent walk-forward (``walkforward``) runs. Join-touch comes from the baseline at every queue
    assumption; the agent comes from the walk-forward at each of its queue assumptions; the curves
    and the gate scoreboard come from the headline queue."""
    qb = [r for r in runs if r["kind"] == "backtest"]
    wf = [r for r in runs if r["kind"] == "walkforward"]
    if not qb:
        raise ValueError("verdict_bundle needs at least one backtest (queue baseline) run")
    forest, compare, curves, gross, gates = [], [], {}, {}, None

    def add_curves(run, variants, days):
        pooled = {k: v for k, v in (run.get("curves") or {}).items() if k.startswith("ALL|")}
        pooled = pooled or pooled_curves(run.get("curves") or {})
        for key, c in thin_curves(pooled, keep_days=0).items():
            if key.partition("|")[2] in variants:
                curves[key] = {"t": c["t"], "pnl": c["pnl"]}
                var = key.partition("|")[2]
                gross[key] = _gross_curve(curves[key], [d for d in days if d["variant"] == var])

    def as_join_touch(rows):
        # the queue baseline always quotes the best price: its variants are join-touch at each queue assumption
        out = []
        for x in rows:
            qm = _queue_of(x["variant"], 0.0 if x["variant"].startswith("bridge") else None)
            out.append({**x, "variant": "join_touch", "queue_mult": qm, "scenario": _scenario(x["variant"], qm),
                        "series": x["variant"]})
        return out

    for r in qb:
        forest += as_join_touch(forest_rows(r["days"])); compare += as_join_touch(compare_rows(r["days"]))
        add_curves(r, {d["variant"] for d in r["days"]}, r["days"])
    for r in wf:
        if r["config"].get("queue_mult") != HEADLINE_QUEUE:
            continue
        agent_days = [d for d in r["days"] if d["variant"] == "agent"]
        forest += forest_rows(agent_days, queue_mult=HEADLINE_QUEUE)
        compare += compare_rows(agent_days, queue_mult=HEADLINE_QUEUE)
        gates = r.get("gates") or gates
        add_curves(r, {"agent"}, agent_days)
    dates_ = {d["date"] for r in qb for d in r["days"]}
    coins = sorted({d["symbol"] for r in qb for d in r["days"]})
    b = build_bundle(run_id, "walkforward", f"Verdict: {len(dates_)}-day queue-aware test, {len(coins)} coins",
                     dict(qb[0]["config"]), [], built_utc=max(r["built_utc"] for r in runs),
                     forest=forest, compare=compare, curves=curves, gross_curves=gross, gates=gates)
    b["takeaways"] = takeaways(b)
    return b


def takeaways(b: dict) -> dict:
    """One plain sentence per chart, written from the bundle's own numbers so it cannot go stale.
    The page prints these and never composes a finding itself."""
    out: dict = {}
    forest = b.get("forest") or []
    jt = [r for r in forest if r["symbol"] == "ALL" and r["variant"] == "join_touch" and "net_bp" in r]
    if jt:
        base = next((r for r in jt if r.get("queue_mult") == HEADLINE_QUEUE), jt[0])
        coins = len({r["symbol"] for r in forest if r["variant"] == base["variant"] and r["symbol"] != "ALL"})
        ts = f"t = {base['t']:.1f}, " if "t" in base else ""
        text = (f"Always quoting the best price {'lost' if base['net_bp'] < 0 else 'made'} {abs(base['net_bp']):.1f} bp "
                f"per dollar traded after fees ({ts}{base['n_days']} days, {coins} coins)")
        ag = next((r for r in forest if r["symbol"] == "ALL" and r["variant"] == "agent"
                   and r.get("queue_mult") == HEADLINE_QUEUE), None)
        if ag is not None:
            if ag["fills"] == 0:
                text += f"; the self-calibrating agent made no fills in {ag['days_total']} days"
            else:
                text += f"; the self-calibrating agent made {ag['fills']:,} fills"
                if "net_bp" in ag:
                    text += f" and earned {ag['net_bp']:+.1f} bp"
        out["headline"] = text + "."
        lo, hi = min(jt, key=lambda r: r["net_bp"]), max(jt, key=lambda r: r["net_bp"])
        if hi["net_bp"] < 0:
            out["ov-forest"] = (f"Every assumption loses money after fees, from {hi['net_bp']:.1f} bp ({hi['scenario']}) "
                                f"to {lo['net_bp']:.1f} bp ({lo['scenario']}); before fees the best case is "
                                f"{max(r['gross_bp'] for r in jt):.1f} bp.")
        else:
            out["ov-forest"] = (f"{hi['scenario']} makes {hi['net_bp']:.1f} bp after fees; "
                                f"{lo['scenario']} makes {lo['net_bp']:.1f} bp. Check the intervals before trusting either.")
    cmp_ = next((r for r in (b.get("compare") or []) if r["symbol"] == "ALL" and r["variant"] == "join_touch"
                 and r.get("queue_mult") == HEADLINE_QUEUE), None)
    if cmp_ is not None and jt:
        coins = len({r["symbol"] for r in forest if r["variant"] == "join_touch" and r["symbol"] != "ALL"})
        out["ov-cum"] = (f"At queue {HEADLINE_QUEUE:g}x the {coins} coins together {'lost' if cmp_['pnl_total'] < 0 else 'made'} "
                         f"{abs(cmp_['pnl_total']):,.0f} USD on 100 USD lots.")
    gate = ((b.get("gates") or {}).get("A") or {}).get("conditions")
    if gate:
        met = sum(1 for c in gate if c.get("pass"))
        out["ov-gates"] = (f"Gate A: {'pass' if ((b['gates']['A']).get('pass')) else 'fail'}; "
                           f"{met} of {len(gate)} conditions met.")
    return out


# =============================================================================== demo bundle
DEMO_COINS = [  # symbol, price, tick, base fills/day, true net edge bp for agent / join-touch
    ("ANKRUSDT", 0.0038, 0.00001, 260, 1.6, -0.8),
    ("SKLUSDT", 0.0231, 0.00001, 180, 0.9, -1.5),
    ("ARBUSDT", 0.3120, 0.0001, 420, -0.6, -3.2),
]
DEMO_ARMS = 12


def demo_bundle(seed: int = 0) -> dict:
    """A complete synthetic bundle (kind ``demo``): 3 symbols x 30 days x 2 variants, every
    section filled. For building and checking the page only; it is NOT a result and the page labels
    it "Demo data, not results". Curves use 30-minute points to keep the file small."""
    rng = np.random.default_rng(seed)
    cfg = {"maker_fee_bps": 10.0, "latency_ms": 300, "queue_mult": 1.0, "lot_usd": 100.0,
           "q_max": 10, "decision_ms": 500}
    fee, lot, q_max = cfg["maker_fee_bps"], cfg["lot_usd"], cfg["q_max"]
    end = datetime(2026, 11, 11, tzinfo=timezone.utc)
    dates = [(end - timedelta(days=29 - i)).strftime("%Y-%m-%d") for i in range(30)]
    variants = (("agent", 4), ("join_touch", 5))

    days, curves, hourly_, markouts, edge, calib, agent, wait_hist, screen = [], {}, {}, [], [], [], [], {}, []
    for sym, px0, tick, base_fills, e_agent, e_join in DEMO_COINS:
        tick_bp = tick / px0 * 1e4
        half_bp = min(tick_bp / 2, 13.0)
        mids = px0 * np.exp(np.cumsum(rng.normal(0, 0.035, 30)))
        for var, idx in variants:
            true_e = e_agent if var == "agent" else e_join
            t_all, p_all, q_all, m_all = [], [], [], []
            offset = 0.0
            hp = np.zeros(24); hf = np.zeros(24, int); he = np.zeros(24)
            for di, date in enumerate(dates):
                fills = int(rng.poisson(base_fills * (0.75 if var == "agent" else 1.0)))
                if di == 6 and sym == "SKLUSDT":
                    fills = 14                       # one thin day: shows the >= 20 fills rule
                notional = fills * lot
                day_e = true_e + rng.normal(0, 3.5)
                pnl = notional * day_e / 1e4
                fees_ = notional * fee / 1e4
                sc = notional * half_bp / 1e4 * rng.uniform(0.9, 1.1)
                inv = pnl - sc + fees_
                mk60 = day_e + fee
                buy = int(rng.binomial(fills, 0.5))
                n_pts = 48
                steps = rng.normal(0, 1, n_pts)
                path = np.cumsum(steps); path = path - np.linspace(0, 1, n_pts) * path[-1]
                path = path * abs(pnl) * 0.15 + np.linspace(pnl / n_pts, pnl, n_pts)
                qpath = np.clip(np.round(np.cumsum(rng.normal(0, 1.4, n_pts))), -q_max, q_max)
                mpath = mids[di] * np.exp(np.cumsum(rng.normal(0, 0.003, n_pts)))
                d0 = _day_start(date)
                for j in range(n_pts):
                    t_all.append(_iso(d0 + timedelta(minutes=30 * (j + 1))))
                    p_all.append(round(offset + float(path[j]), 4)); q_all.append(float(qpath[j]))
                    m_all.append(float(f"{mpath[j]:.6g}"))
                offset += pnl
                w = 1 + 0.6 * np.sin(np.arange(24) / 24 * 2 * np.pi - 1.2)
                w = w / w.sum()
                hp += pnl * w + rng.normal(0, abs(pnl) * 0.02 + 0.01, 24)
                hfill = rng.multinomial(fills, w); hf += hfill
                he += (day_e + rng.normal(0, 2, 24)) * hfill
                row = {"symbol": sym, "date": date, "variant": var, "pnl": round(pnl, 4),
                       "spread_capture": round(sc, 4), "inventory_pnl": round(inv, 4), "fees": round(fees_, 4),
                       "fills": fills, "buy_fills": buy, "notional": round(notional, 2),
                       "mk_1": round(mk60 + 2.6 + rng.normal(0, .3), 3), "mk_10": round(mk60 + 1.2 + rng.normal(0, .3), 3),
                       "mk_60": round(mk60, 3), "mk_300": round(mk60 - 0.7 + rng.normal(0, .5), 3),
                       "net_edge_bp": round(day_e, 3), "wait_s_med": round(float(rng.lognormal(3.2, .3)), 1),
                       "q_abs_max": float(np.abs(qpath).max()), "q_std": round(float(qpath.std(ddof=1)), 3),
                       "max_dd": round(float(min(0.0, (path - np.maximum.accumulate(np.r_[0, path])[1:]).min())), 4),
                       "uptime": round(float(rng.uniform(0.82, 0.99)), 3)}
                if var == "agent":
                    row["switches"] = int(rng.poisson(0.6))
                    row["loss_stop"] = bool(pnl < -2.5)
                    row["live_arm"] = int(idx + (di // 10))
                days.append(row)
            key = f"{sym}|{var}"
            curves[key] = {"t": t_all, "pnl": p_all, "q": q_all, "mid": m_all}
            hourly_[key] = {"pnl": [round(float(x), 4) for x in hp], "fills": [int(x) for x in hf],
                            "net_edge_bp": [round(float(he[h] / hf[h]), 3) if hf[h] else round(true_e, 3) for h in range(24)]}
            n_tot = int(hf.sum())
            for act, shift in (("JOIN", 0.0), ("BACK", 1.8)):
                for side in ("buy", "sell"):
                    n = n_tot // 4
                    for h, extra in zip(MARKOUT_H, (2.6, 1.2, 0.0, -0.7)):
                        markouts.append({"symbol": sym, "variant": var, "action": act, "side": side, "h_s": h,
                                         "bp": round(true_e + fee + extra + shift + rng.normal(0, 0.4), 3),
                                         "se": round(11.0 / math.sqrt(max(n, 1)) * (1 + h / 300), 3), "n": n})
        for act, shift in (("JOIN", 0.0), ("BACK", 1.5)):
            for imb in range(3):
                for vol in range(3):
                    n = int(rng.integers(8, 900))
                    edge.append({"symbol": sym, "action": act, "imb": imb, "vol": vol, "n": n,
                                 "mean": round(e_agent + shift + (imb - 1) * 4.0 - vol * 1.5 + rng.normal(0, 1), 3),
                                 "se": round(12 / math.sqrt(n), 3)})
        for b_ in range(5):
            pred = -4 + 3 * b_ + rng.normal(0, .3)
            calib.append({"symbol": sym, "pred_mean": round(pred, 3), "real_mean": round(0.75 * pred - 0.5 + rng.normal(0, .6), 3),
                          "se": round(float(rng.uniform(0.6, 1.4)), 3), "n": int(rng.integers(150, 400))})
        arm = 4
        for i in range(120):
            ts = _iso(_day_start(dates[0]) + timedelta(hours=6 * (i + 1)))
            scores = [round(float(e_agent - abs(a - 6) * 0.4 + rng.normal(0, .8)), 3) for a in range(DEMO_ARMS)]
            best = int(np.argmax(scores))
            switched = best != arm and scores[best] - scores[arm] > 1.2
            arm = best if switched else arm
            agent.append({"symbol": sym, "ts": ts, "live_arm": arm, "switched": bool(switched), "scores": scores})
        edges = [0, 2, 5, 10, 20, 40, 80, 160, 320, 640]
        wait_hist[sym] = {"edges": edges, "count": [int(x) for x in rng.multinomial(4000, [.04, .07, .12, .2, .24, .18, .1, .04, .01])]}
        screen.append({"symbol": sym, "tick_bp": round(tick_bp, 3), "spread_ticks": round(float(rng.uniform(1.0, 1.3)), 2),
                       "usd_volume_day": round(float(rng.uniform(0.3e6, 4e6)), 0), "trades_per_s": round(float(rng.uniform(0.2, 3)), 2),
                       "sigma_bp": round(float(rng.uniform(20, 60)), 1), "price": float(f"{mids[-1]:.6g}"),
                       "constrained": bool(tick_bp > 5)})
    screen.append({"symbol": "BTCUSDT", "tick_bp": 0.001, "spread_ticks": 1.0, "usd_volume_day": 1.2e9,
                   "trades_per_s": 38.0, "sigma_bp": 9.0, "price": 101250.5, "constrained": False})

    gates = {
        "A": {"pass": False, "conditions": [
            {"id": "A1", "text": "Agent net bp per $ > 0 on pooled walk-forward days", "value": 0.42, "pass": True},
            {"id": "A2", "text": "t-statistic of pooled daily P&L > 2", "value": 1.31, "pass": False},
            {"id": "A3", "text": "Positive at queue_mult 2.0 (stress)", "value": -0.9, "pass": False},
            {"id": "A4", "text": "Max drawdown < 20% of capital at cap", "value": 0.07, "pass": True},
            {"id": "A5", "text": "Agent total net P&L >= Join touch total", "value": 1.0, "pass": True}]},
        "B": {"pass": False, "conditions": [
            {"id": "B1", "text": "Paper fills within +/-30% of simulator", "value": 0.18, "pass": True},
            {"id": "B2", "text": "Paper net edge within 2 bp of simulator", "value": 2.7, "pass": False}]},
    }
    health = {"recorder": [], "tests_passed": 93}
    for sym, *_ in DEMO_COINS:
        for date in dates[-7:]:
            hrs = float(rng.choice([24.0, 24.0, 24.0, 23.5, 18.2, 0.0], p=[.5, .2, .1, .1, .07, .03]))
            health["recorder"].append({"symbol": sym, "date": date, "hours": hrs,
                                       "gap_minutes": round((24 - hrs) * 60, 1), "delay_ms_med": round(float(rng.uniform(240, 330)), 0)})

    b = build_bundle("demo", "demo", "Demo data (synthetic)", cfg, days, built_utc=_now_utc(),
                     curves=curves, hourly=hourly_, markouts=markouts, edge=edge, calib=calib, agent=agent,
                     wait_hist=wait_hist, screen=screen, gates=gates, health=health)
    return b


if __name__ == "__main__":     # python -m mm.report  -> writes the demo bundle
    print(write_bundle(demo_bundle()))
