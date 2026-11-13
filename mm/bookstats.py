"""Statistics from the recorded top of book (Dashboard Redesign R5).

Input frames come from ``mm.recorder.load_live``:
    book    recv_us, update_id, bid, bid_qty, ask, ask_qty
    trades  recv_us, ts_us, price, qty, side

Rules that hold for every function here:
  * Time is ``recv_us`` (the book has no other clock), UTC.
  * Past-only: the move after a sample at t is read from the book at or before t + h, never later,
    and a sample is dropped when t + h falls on the next UTC day or past the end of the data.
  * An hour is clean only if its first and last update are within 120 s of its edges and no gap
    inside it exceeds 120 s. Samples in other hours enter no statistic; ``coverage`` counts them.
  * No NaN leaves this module: missing values are ``None``.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd

from mm import report as rep
from mm.calibrate import infer_tick

SEC = 1_000_000
HOUR = 3_600 * SEC
DAY = 24 * HOUR
GAP_US = 120 * SEC
HORIZONS = (1, 5, 30)
BUCKETS = 10
MAX_SPREAD_TICKS = 10


def _f(x, nd: int = 6) -> Optional[float]:
    return None if x is None or not math.isfinite(float(x)) else round(float(x), nd)


def _iso(us: int, ms: bool = False) -> str:
    ts = pd.Timestamp(int(us), unit="us")
    return ts.strftime("%Y-%m-%dT%H:%M:%S" + (f".{ts.microsecond // 1000:03d}" if ms else "") + "Z")


def clean_hours(ts: np.ndarray) -> set[int]:
    """Epoch-hour indices that are fully covered (see the module docstring)."""
    ts = np.asarray(ts, np.int64)
    out: set[int] = set()
    if not len(ts):
        return out
    for h in range(int(ts[0] // HOUR), int(ts[-1] // HOUR) + 1):
        lo, hi = np.searchsorted(ts, [h * HOUR, (h + 1) * HOUR])
        if hi == lo:
            continue
        seg = ts[lo:hi]
        if seg[0] - h * HOUR > GAP_US or (h + 1) * HOUR - seg[-1] > GAP_US:
            continue
        if len(seg) > 1 and np.diff(seg).max() > GAP_US:
            continue
        out.add(h)
    return out


def _mask(hours_idx: np.ndarray, ok: set[int]) -> np.ndarray:
    return np.isin(hours_idx, np.fromiter(ok, np.int64, len(ok))) if ok else np.zeros(len(hours_idx), bool)


class _Grid:
    """The book sampled once per second (last known value), with a clean-hour flag per sample."""

    def __init__(self, book: pd.DataFrame, step_s: int = 1):
        ts = book["recv_us"].to_numpy(np.int64)
        self.ok = clean_hours(ts)
        if not len(ts):
            self.t = np.array([], np.int64)
            self.bid = self.ask = self.bq = self.aq = np.array([])
            self.clean = np.array([], bool)
            self.last = 0
            return
        step = step_s * SEC
        start = -(-int(ts[0]) // step) * step
        self.t = np.arange(start, int(ts[-1]) + 1, step, dtype=np.int64)
        idx = np.searchsorted(ts, self.t, side="right") - 1
        self.bid, self.ask = book["bid"].to_numpy(float)[idx], book["ask"].to_numpy(float)[idx]
        self.bq, self.aq = book["bid_qty"].to_numpy(float)[idx], book["ask_qty"].to_numpy(float)[idx]
        self.clean = _mask(self.t // HOUR, self.ok)
        self.last = int(ts[-1])

    @property
    def mid(self) -> np.ndarray:
        return (self.bid + self.ask) / 2


def coverage(book: pd.DataFrame, symbol: str) -> list[dict]:
    """One row per UTC date: clean hours and the total length of book gaps over 120 s."""
    ts = book["recv_us"].to_numpy(np.int64)
    if not len(ts):
        return []
    ok = clean_hours(ts)
    gaps = np.diff(ts)
    big = np.flatnonzero(gaps > GAP_US)
    rows = {}
    for d in range(int(ts[0] // DAY), int(ts[-1] // DAY) + 1):
        date = pd.Timestamp(d * DAY, unit="us").strftime("%Y-%m-%d")
        rows[d] = {"symbol": symbol, "date": date, "hours": sum(1 for h in ok if h // 24 == d), "gap_minutes": 0.0}
    for i in big:
        rows[int(ts[i] // DAY)]["gap_minutes"] += float(gaps[i]) / 60 / SEC
    return [dict(r, gap_minutes=round(r["gap_minutes"], 2)) for r in rows.values()]


def imb_curve(book: pd.DataFrame, symbol: str, horizons=HORIZONS, buckets: int = BUCKETS) -> list[dict]:
    """Mid move after h seconds by size imbalance at the touch, in ``buckets`` equal-count groups.

    imbalance = (bid_qty - ask_qty) / (bid_qty + ask_qty); move_bp = (mid(t+h) - mid(t)) / mid(t) * 1e4;
    se is the standard error of the bucket mean treating samples as independent (an understatement:
    neighbouring seconds overlap, so read the whisker as a lower bound)."""
    g = _Grid(book)
    n = len(g.t)
    out = []
    if not n:
        return out
    imb = (g.bq - g.aq) / (g.bq + g.aq)
    mid = g.mid
    for h in horizons:
        i = np.arange(n - h) if n > h else np.array([], int)
        j = i + h
        keep = g.clean[i] & g.clean[j] & (g.t[i] // DAY == g.t[j] // DAY) & (g.t[j] <= g.last)
        i, j = i[keep], j[keep]
        if len(i) < buckets:
            continue
        x, mv = imb[i], (mid[j] - mid[i]) / mid[i] * 1e4
        rank = np.empty(len(x), int)
        rank[np.argsort(x, kind="stable")] = np.arange(len(x))
        b = rank * buckets // len(x)
        for k in range(buckets):
            m = mv[b == k]
            out.append({"symbol": symbol, "h_s": int(h), "bucket": k, "imb_mid": _f(x[b == k].mean()),
                        "move_bp": _f(m.mean()), "se": _f(m.std(ddof=1) / math.sqrt(len(m))), "n": int(len(m))})
    return out


def _trades_in_clean(trades: pd.DataFrame, ok: set[int]) -> pd.DataFrame:
    if not len(trades):
        return trades
    return trades[_mask(trades["recv_us"].to_numpy(np.int64) // HOUR, ok)]


def profile(book: pd.DataFrame, trades: pd.DataFrame, symbol: str, tick: Optional[float] = None) -> dict:
    """One row per coin: how thick and how fast the touch is, in ticks, basis points and trades."""
    g = _Grid(book)
    ok = g.ok
    c = g.clean
    if tick is None:
        tick = infer_tick(np.r_[book["bid"].to_numpy(), book["ask"].to_numpy()])
    tr = _trades_in_clean(trades, ok)
    clean_minutes = len(ok) * 60
    spread_ticks = np.round((g.ask[c] - g.bid[c]) / tick) if c.any() else np.array([])
    touch = np.r_[g.bq[c], g.aq[c]]
    ts = book["recv_us"].to_numpy(np.int64)
    in_clean = _mask(ts // HOUR, ok)
    # how long a best price lasts: time between changes of the best bid or the best ask
    life = []
    for col in ("bid", "ask"):
        px = book[col].to_numpy(float)
        ch = np.flatnonzero(np.diff(px) != 0) + 1
        if len(ch) >= 2:
            a, b = ch[:-1], ch[1:]
            good = _mask(ts[a] // HOUR, ok) & _mask(ts[b] // HOUR, ok)
            life.append((ts[b] - ts[a])[good] / SEC)
    life = np.concatenate(life) if life else np.array([])
    touch_med = float(np.median(touch)) if len(touch) else None
    trade_med = float(tr["qty"].median()) if len(tr) else None
    return {
        "symbol": symbol,
        "tick_bp": _f(tick / float(np.median(g.mid[c])) * 1e4) if c.any() else None,
        "spread_ticks_med": _f(np.median(spread_ticks)) if len(spread_ticks) else None,
        "share_one_tick": _f((spread_ticks <= 1).mean()) if len(spread_ticks) else None,
        "touch_qty_med": _f(touch_med),
        "touch_in_trades": _f(touch_med / trade_med) if touch_med is not None and trade_med else None,
        "updates_per_min": _f(in_clean.sum() / clean_minutes) if clean_minutes else None,
        "trades_per_min": _f(len(tr) / clean_minutes) if clean_minutes else 0.0,
        "deplete_s_med": _f(np.median(life)) if len(life) else None,
    }


def spread_hist(book: pd.DataFrame, tick: float) -> dict:
    """Share of time at each spread, in ticks, capped at 10 (the last bin means 10 or more)."""
    g = _Grid(book)
    c = g.clean
    if not c.any():
        return {"ticks": [], "share": []}
    t = np.clip(np.round((g.ask[c] - g.bid[c]) / tick), 1, MAX_SPREAD_TICKS).astype(int)
    ticks, counts = np.unique(t, return_counts=True)
    return {"ticks": [int(x) for x in ticks], "share": [_f(x, 8) for x in counts / counts.sum()]}


def hourly(book: pd.DataFrame, trades: pd.DataFrame) -> dict:
    """By UTC hour of day: median spread (bp), median USD resting at the touch, mean trades per hour."""
    g = _Grid(book)
    c = g.clean
    hod = (g.t // HOUR) % 24
    spread_bp = (g.ask - g.bid) / g.mid * 1e4
    touch_usd = (g.bq * g.bid + g.aq * g.ask) / 2
    tr = _trades_in_clean(trades, g.ok)
    hours_seen = {}
    for h in g.ok:
        hours_seen.setdefault(h % 24, 0)
        hours_seen[h % 24] += 1
    tr_h = (tr["recv_us"].to_numpy(np.int64) // HOUR) % 24 if len(tr) else np.array([], int)
    out = {"spread_bp": [], "touch_usd": [], "trades": []}
    for h in range(24):
        m = c & (hod == h)
        out["spread_bp"].append(_f(np.median(spread_bp[m])) if m.any() else None)
        out["touch_usd"].append(_f(np.median(touch_usd[m]), 2) if m.any() else None)
        out["trades"].append(_f((tr_h == h).sum() / hours_seen[h], 2) if hours_seen.get(h) else None)
    return out


QTY_STEP = 0.10          # a size change under 10% of the last kept size is not worth a point
MAX_TOUCH_POINTS = 2500


def touch_samples(book: pd.DataFrame, hours: float = 6) -> dict:
    """The last ``hours`` of the touch at one-second resolution, thinned for the page: a point is kept
    when the best bid or ask changed, or a size moved more than 10% from the last kept point (plus the
    first and last point); beyond 2,500 points every k-th is kept. Prices are exact, so step lines are."""
    g = _Grid(book)
    n = int(hours * 3600)
    sl = slice(max(0, len(g.t) - n), len(g.t))
    bid, ask, bq, aq = g.bid[sl], g.ask[sl], g.bq[sl], g.aq[sl]
    if not len(bid):
        return {"t": [], "bid": [], "ask": [], "bid_qty": [], "ask_qty": []}
    keep = np.zeros(len(bid), bool)
    keep[0] = keep[-1] = True
    keep[1:] |= (bid[1:] != bid[:-1]) | (ask[1:] != ask[:-1])
    lb, la = bq[0], aq[0]
    for i in range(1, len(bid)):
        if keep[i] or abs(bq[i] - lb) > QTY_STEP * max(lb, 1e-12) or abs(aq[i] - la) > QTY_STEP * max(la, 1e-12):
            keep[i] = True
            lb, la = bq[i], aq[i]
    idx = np.flatnonzero(keep)
    if len(idx) > MAX_TOUCH_POINTS:
        idx = np.unique(np.r_[idx[:: -(-len(idx) // MAX_TOUCH_POINTS)], idx[-1]])
    return {"t": [_iso(x) for x in g.t[sl][idx]], "bid": [float(x) for x in bid[idx]], "ask": [float(x) for x in ask[idx]],
            "bid_qty": [float(f"{x:.4g}") for x in bq[idx]], "ask_qty": [float(f"{x:.4g}") for x in aq[idx]]}


def trades_sample(trades: pd.DataFrame, hours: float = 6, cap: int = 1500) -> dict:
    """Trades of the last ``hours``; over ``cap`` the largest are kept. Time-ordered."""
    empty = {"t": [], "price": [], "qty": [], "side": []}
    if not len(trades):
        return empty
    last = int(trades["recv_us"].max())
    t = trades[trades["recv_us"] >= last - int(hours * HOUR)]
    if len(t) > cap:
        t = t.nlargest(cap, "qty", keep="first")
    t = t.sort_values("recv_us", kind="stable")
    return {"t": [_iso(x, ms=True) for x in t["recv_us"]], "price": [float(x) for x in t["price"]],
            "qty": [float(x) for x in t["qty"]], "side": [int(x) for x in t["side"]]}


DEPTH_LEVELS = 10
HEAT_HOURS = 6


def _levels(df: pd.DataFrame, side: str) -> tuple[np.ndarray, np.ndarray]:
    k = "b" if side == "bid" else "a"
    px = df[[f"{k}p{i}" for i in range(DEPTH_LEVELS)]].to_numpy(float)
    qty = df[[f"{k}q{i}" for i in range(DEPTH_LEVELS)]].to_numpy(float)
    return px, qty


def depth_ladder(depth: pd.DataFrame) -> Optional[dict]:
    """The last recorded 10-level snapshot: per level price, size, cumulative size and distance from the mid (bp)."""
    if depth is None or not len(depth):
        return None
    last = depth.sort_values("recv_us").iloc[[-1]]
    bpx, bq = _levels(last, "bid")
    apx, aq = _levels(last, "ask")
    mid = float((bpx[0, 0] + apx[0, 0]) / 2)
    def side(px, q):
        out, cum = [], 0.0
        for p, x in zip(px[0], q[0]):
            if not (np.isfinite(p) and np.isfinite(x)):
                continue
            cum += float(x)
            out.append({"px": float(p), "qty": float(x), "cum": cum, "bp": round(float((p - mid) / mid * 1e4), 3)})
        return out
    return {"ts_us": int(last["recv_us"].iloc[0]), "mid": mid, "usd_per_unit": mid, "bids": side(bpx, bq), "asks": side(apx, aq)}


def depth_heatmap(depth: pd.DataFrame, bucket_min: int = 10, n_bins: int = 24) -> Optional[dict]:
    """Resting size (USD, both sides) by distance from the mid (bp) and time: the mean over each
    ``bucket_min`` window of the per-snapshot total in each distance bin. Last ``HEAT_HOURS`` hours."""
    if depth is None or not len(depth):
        return None
    d = depth.sort_values("recv_us")
    d = d[d["recv_us"] >= d["recv_us"].max() - HEAT_HOURS * 3_600_000_000]
    bpx, bq = _levels(d, "bid")
    apx, aq = _levels(d, "ask")
    mid = ((bpx[:, 0] + apx[:, 0]) / 2)[:, None]
    dist = np.hstack([(bpx - mid) / mid * 1e4, (apx - mid) / mid * 1e4])
    usd = np.hstack([bq * bpx, aq * apx])
    ok = np.isfinite(dist) & np.isfinite(usd)
    if not ok.any():
        return None
    R = float(np.ceil(np.nanpercentile(np.abs(dist[ok]), 95) * 10) / 10) or 1.0
    edges = np.linspace(-R, R, n_bins + 1)
    step = bucket_min * 60_000_000
    bk = (d["recv_us"].to_numpy(np.int64) // step)
    b0, nb = int(bk.min()), int(bk.max() - bk.min()) + 1
    tix = (bk - b0)
    yix = np.clip(np.digitize(dist, edges) - 1, 0, n_bins - 1)
    sums = np.zeros((n_bins, nb))
    rows = np.repeat(tix[:, None], dist.shape[1], axis=1)
    np.add.at(sums, (yix[ok], rows[ok]), usd[ok])
    cnt = np.bincount(tix, minlength=nb).astype(float)
    z = sums / np.where(cnt > 0, cnt, np.nan)
    t = [pd.Timestamp((b0 + i) * step, unit="us").strftime("%Y-%m-%dT%H:%M") for i in range(nb)]
    return {"t": t, "y": [round(float(v), 3) for v in (edges[:-1] + edges[1:]) / 2],
            "z": [[None if not np.isfinite(v) else round(float(v), 2) for v in row] for row in z], "bucket_min": bucket_min}


FILL_TOL, EDGE_TOL_BP = 0.30, 2.0          # the tape-validation rule (scripts/validate_tape.py)
_TV_KEYS = ("hours", "fills_real", "fills_inf", "net_edge_real", "net_edge_inf", "fill_ratio", "edge_diff_bp", "level_ratio")


def _fin(x):
    x = float(x)
    return x if np.isfinite(x) else None


def tape_validation(df: pd.DataFrame) -> Optional[dict]:
    """The Data tab's tape-validation card from results/tape_validation.csv: per coin-day rows and the pooled
    verdict (fills within 30% and fill-weighted net edge within 2 bp). None when there is nothing."""
    if df is None or not len(df):
        return None
    rows = [{"symbol": str(r["symbol"]), "date": str(r["date"]), **{k: _fin(r[k]) for k in _TV_KEYS}} for _, r in df.iterrows()]
    fr, fi = float(df["fills_real"].sum()), float(df["fills_inf"].sum())
    w = lambda e, f: float((df[e] * df[f]).sum() / df[f].sum()) if df[f].sum() else float("nan")
    er, ei = w("net_edge_real", "fills_real"), w("net_edge_inf", "fills_inf")
    ratio = fi / fr if fr else float("nan")
    ok = bool(np.isfinite(ratio) and np.isfinite(er) and np.isfinite(ei) and abs(ratio - 1) <= FILL_TOL and abs(ei - er) <= EDGE_TOL_BP)
    return {"rows": rows, "pooled": {"ok": ok, "fill_ratio": _fin(ratio), "net_edge_real": _fin(er), "net_edge_inf": _fin(ei),
                                     "edge_diff_bp": _fin(ei - er), "days": int(df["date"].nunique()),
                                     "level_ratio_median": _fin(df["level_ratio"].median())}}


def book_bundle(frames: dict, ticks: Optional[dict] = None, built_utc: Optional[str] = None,
                tape_validation: Optional[dict] = None, depth: Optional[dict] = None) -> dict:
    """The bundle behind the Market book tab: ``frames`` maps symbol -> (book, trades)."""
    ticks = ticks or {}
    syms = list(frames)
    touch, trades_, prof, imb, shist, hr, cov = {}, {}, [], [], {}, {}, []
    last_us = 0
    for s, (book, trades) in frames.items():
        tick = ticks.get(s) or infer_tick(np.r_[trades["price"].to_numpy(), book["bid"].to_numpy(), book["ask"].to_numpy()])
        touch[s] = touch_samples(book)
        trades_[s] = trades_sample(trades)
        prof.append(profile(book, trades, s, tick))
        imb += imb_curve(book, s)
        shist[s] = spread_hist(book, tick)
        hr[s] = hourly(book, trades)
        cov += coverage(book, s)
        last_us = max(last_us, int(book["recv_us"].max()))
    dsec = {sym: {"ladder": depth_ladder(df), "heat": depth_heatmap(df)} for sym, df in (depth or {}).items() if df is not None and len(df)}
    date = pd.Timestamp(last_us, unit="us").strftime("%Y-%m-%d")
    return rep.build_bundle(f"book-{date}", "book", f"Recorded order book, to {date}", {}, [], built_utc=built_utc,
                            symbols=syms, touch=touch, trades=trades_, profile=prof, imb_curve=imb,
                            spread_hist=shist, hourly=hr, coverage=cov, tape_validation=tape_validation, depth=dsec or None)
