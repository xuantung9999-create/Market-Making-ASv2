"""Statistics for the live sessions (testnet and paper): continuous P&L across restarts, the five-term
attribution, artifact detection, markouts, queue wait, quote-state intervals and incidents.

Pure functions on data frames (dashboard live spec, sections 6.2 and 6.3). Times are microseconds since the
epoch inside this module; the bundle builder converts to milliseconds for the page.

Mid: the mid of the session's own recorded feed at or just before a timestamp. A mid from a book older than
``stale_s`` (5 s) is stale and per-fill statistics that use it are dropped (and counted).

Attribution (sums to ``net`` exactly): with the feed's mid path m_j and the position p_j held across update j,

    cash + pos_end * m_end  =  sum_f side*qty*mid_f  +  sum_j p_j * (m_j - m_{j-1})

so  net = edge + inventory pnl - fees. Inventory pnl is split into the artifact jumps (a mid that moves more
than ``jump_bp`` between two updates less than ``jump_gap_s`` apart), adverse selection (signed qty times the
change of the jump-free mid over ``adverse_s`` after each fill) and carry (the rest).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

US = 1_000_000
DAY_US = 86_400 * US
HOUR_US = 3_600 * US
HORIZONS = (1, 5, 30, 60, 300)
STATES = ("QUOTING", "WARMUP", "POLICY_OUT", "LOSS_STOP", "INV_CAP", "NO_BALANCE", "BELOW_MIN", "REJECTED",
          "STALE_FEED", "EXCHANGE_ERROR")


@dataclass(frozen=True)
class Thresholds:
    artifact_bp: float = 50.0          # a fill further than this from mid is an artifact ...
    artifact_spread_mult: float = 5.0  # ... or further than this many median spreads of the previous 5 min
    spread_window_s: float = 300.0
    jump_bp: float = 100.0             # an artifact jump: mid moves more than this ...
    jump_gap_s: float = 2.0            # ... between two updates less than this apart
    stale_s: float = 5.0               # a mid from a book older than this is stale
    feed_gap_s: float = 120.0          # no book update for this long is a feed gap
    adverse_s: float = 60.0
    idle_s: float = 300.0              # no side quoting for this long (and not by policy) is idle
    reject_burst_n: int = 5
    reject_burst_s: float = 60.0
    policy_out_s: float = 3600.0

    def to_dict(self) -> dict:
        return dict(self.__dict__)


# ---------------------------------------------------------------------- loading
def read_jsonl(path: str | Path) -> list[dict]:
    out = []
    try:
        text = Path(path).read_text()
    except OSError:
        return out
    for line in text.splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def read_folder_jsonl(folder: str | Path, kind: str) -> list[dict]:
    rows: list[dict] = []
    for f in sorted(Path(folder).glob(f"{kind}_*.jsonl")):
        rows += read_jsonl(f)
    return rows


def fills_frame(rows: list[dict], fee_bps: float = 10.0) -> pd.DataFrame:
    """One row per fill in time order. Old files lack ``fill_ts_us``, ``place_ts_us``, ``bid``, ``ask`` and
    ``fee_est``; those fills are placed in time by ``ts_us`` and flagged ``timing = "detected"``."""
    cols = ["ts_us", "t_us", "timing", "side", "price", "qty", "mid_det", "fee", "place_ts_us", "bid", "ask",
            "order_id", "how"]
    if not rows:
        return pd.DataFrame(columns=["i"] + cols)
    d = pd.DataFrame(rows)
    for c in ("fill_ts_us", "place_ts_us", "bid", "ask", "fee_est", "order_id", "how", "mid"):
        if c not in d:
            d[c] = np.nan if c != "how" else ""
    d["ts_us"] = d["ts_us"].astype("int64")
    have = d["fill_ts_us"].notna()
    d["t_us"] = np.where(have, d["fill_ts_us"].fillna(0), d["ts_us"]).astype("int64")
    d["timing"] = np.where(have, "exchange", "detected")
    d["side"] = d["side"].astype(int)
    d["price"], d["qty"] = d["price"].astype(float), d["qty"].astype(float)
    d["mid_det"] = d["mid"].astype(float)
    d["fee"] = np.where(d["fee_est"].notna(), d["fee_est"].astype(float), d["price"] * d["qty"] * fee_bps / 1e4)
    out = d.sort_values(["t_us", "ts_us"], kind="stable").reset_index(drop=True)[cols]
    out.insert(0, "i", np.arange(len(out)))
    return out


def book_arrays(book: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(t_us, mid, bid, ask) of the recorded book, sorted by time."""
    if book is None or len(book) == 0:
        z = np.empty(0)
        return z.astype("int64"), z, z, z
    tcol = "ts_us" if "ts_us" in book else "recv_us"
    b = book.sort_values(tcol, kind="stable")
    t = b[tcol].to_numpy("int64")
    bid, ask = b["bid"].to_numpy(float), b["ask"].to_numpy(float)
    return t, (bid + ask) / 2.0, bid, ask


def lookup(t_arr: np.ndarray, v_arr: np.ndarray, t) -> tuple[np.ndarray, np.ndarray]:
    """Value of a step series at times ``t`` (at or just before) and the age of that observation (s).
    Before the first observation the first value is returned with age = inf."""
    t = np.asarray(t, dtype="int64")
    if t_arr.size == 0:
        return np.full(t.shape, np.nan), np.full(t.shape, np.inf)
    idx = np.searchsorted(t_arr, t, side="right") - 1
    age = np.where(idx >= 0, (t - t_arr[np.clip(idx, 0, None)]) / US, np.inf)
    return v_arr[np.clip(idx, 0, None)], age


def feed_gaps(t_arr: np.ndarray, gap_s: float, t_end: Optional[int] = None) -> list[tuple[int, int]]:
    """(start, end) of every stretch longer than ``gap_s`` without a book update."""
    if t_arr.size == 0:
        return []
    d = np.diff(t_arr)
    idx = np.nonzero(d > gap_s * US)[0]
    out = [(int(t_arr[i]), int(t_arr[i + 1])) for i in idx]
    if t_end is not None and t_end - int(t_arr[-1]) > gap_s * US:
        out.append((int(t_arr[-1]), int(t_end)))
    return out


def artifact_jumps(t_arr: np.ndarray, mid: np.ndarray, th: Thresholds) -> np.ndarray:
    """Boolean per book update: True where the mid jumped more than ``jump_bp`` since the previous update,
    less than ``jump_gap_s`` earlier."""
    j = np.zeros(t_arr.size, dtype=bool)
    if t_arr.size < 2:
        return j
    dm = np.abs(np.diff(mid)) / np.where(mid[:-1] > 0, mid[:-1], np.nan) * 1e4
    quick = np.diff(t_arr) < th.jump_gap_s * US
    j[1:] = (dm > th.jump_bp) & quick
    return j


# ---------------------------------------------------------------------- the core analysis
def analyse(fills: pd.DataFrame, book: pd.DataFrame, *, fee_bps: float = 10.0, lot_usd: float = 100.0,
            q_max: Optional[int] = None, thresholds: Thresholds = Thresholds(), horizons=HORIZONS,
            t_end: Optional[int] = None) -> dict:
    """Continuous P&L, attribution, artifacts, markouts, queue wait. See the module docstring."""
    th = thresholds
    t_b, mid_b, bid_b, ask_b = book_arrays(book)
    f = fills.copy().reset_index(drop=True)
    n = len(f)
    res: dict = {"thresholds": th.to_dict(), "n_fills": n}
    if n == 0:
        res.update(fills=f, curve=pd.DataFrame(columns=["t_us", "pnl", "pnl_ex_artifact", "lots"]),
                   jumps=pd.DataFrame(columns=["t_us", "dmid", "pos", "pnl"]), gaps=feed_gaps(t_b, th.feed_gap_s, t_end),
                   attribution=_zero_attr(), by_day=[], by_hour=[], counts={"stale_mid": 0, "artifact_fills": 0,
                   "artifact_jumps": 0, "markout_dropped": {}}, mid_end=None)
        return res
    tf, side, px, qty, fee = (f[c].to_numpy() for c in ("t_us", "side", "price", "qty", "fee"))
    tf = tf.astype("int64")
    sq = side * qty

    # mid at the fill (feed), fallback: first book mid for fills before the feed starts, else the recorded mid
    mid_f, age_f = lookup(t_b, mid_b, tf)
    if t_b.size:
        before = tf < t_b[0]
        mid_f = np.where(before, mid_b[0], mid_f)
    else:
        mid_f = f["mid_det"].to_numpy(float)
        age_f = np.full(n, np.inf)
    bad = ~np.isfinite(mid_f)
    mid_f = np.where(bad, f["mid_det"].to_numpy(float), mid_f)
    stale = np.asarray(age_f > th.stale_s) | bad

    # artifact fills: further from mid than max(artifact_bp, k * median spread of the previous window)
    if t_b.size:
        spread_bp = (ask_b - bid_b) / np.where(mid_b > 0, mid_b, np.nan) * 1e4
        lo = np.searchsorted(t_b, tf - int(th.spread_window_s * US), side="left")
        hi = np.searchsorted(t_b, tf, side="right")
        med = np.array([np.nanmedian(spread_bp[a:b]) if b > a else np.nan for a, b in zip(lo, hi)])
    else:
        med = np.full(n, np.nan)
    thr_bp = np.maximum(th.artifact_bp, th.artifact_spread_mult * np.nan_to_num(med, nan=0.0))
    dev_bp = np.abs(px - mid_f) / np.where(mid_f > 0, mid_f, np.nan) * 1e4
    artifact = np.nan_to_num(dev_bp, nan=0.0) > thr_bp

    # running position, cash, fees at each fill (ignores the per-process counters)
    pos = np.cumsum(sq)
    cash = -np.cumsum(sq * px)
    fees = np.cumsum(fee)
    lots = np.rint(pos * mid_f / lot_usd).astype(int) if lot_usd else np.zeros(n, int)
    f["pos_after"], f["lots_after"] = pos, lots
    f["pnl_after"] = cash + pos * mid_f - fees

    edge_f = side * (mid_f - px) * qty                        # USDT, against the feed mid at the fill
    f["mid"], f["mid_age_s"], f["stale"], f["artifact"] = mid_f, age_f, stale, artifact
    f["edge_usd"] = edge_f
    f["edge_bp"] = np.where(stale, np.nan, side * (mid_f - px) / px * 1e4)
    f["reason"] = np.where(artifact, "fill " + np.round(np.nan_to_num(dev_bp)).astype(int).astype(str) + " bp from mid", "")

    # inventory pnl along the feed's mid path
    jumps_mask = artifact_jumps(t_b, mid_b, th)
    if t_b.size:
        dmid = np.diff(mid_b, prepend=mid_b[0])
        k = np.searchsorted(tf, t_b, side="left")             # fills strictly before each update
        pos_exposed = np.concatenate([[0.0], pos])[k]
        inv_j = pos_exposed * dmid
        jump_pnl_j = np.where(jumps_mask, inv_j, 0.0)
        # jump-free mid path: remove the jump moves
        clean = mid_b - np.cumsum(np.where(jumps_mask, dmid, 0.0))
    else:
        dmid = inv_j = jump_pnl_j = np.empty(0)
        clean = np.empty(0)

    # adverse selection: change of the jump-free mid over adverse_s after each fill, times signed qty
    if t_b.size:
        c0, _ = lookup(t_b, clean, tf)
        c0 = np.where(tf < t_b[0], clean[0], c0)
        c1, _ = lookup(t_b, clean, tf + int(th.adverse_s * US))
        adverse_f = np.where(artifact, 0.0, sq * (c1 - c0))
    else:
        c0 = np.zeros(n)
        adverse_f = np.zeros(n)

    # markouts: past-only, on the jump-free mid, artifacts excluded
    gaps = feed_gaps(t_b, th.feed_gap_s, t_end)
    t_last = int(t_b[-1]) if t_b.size else None
    dropped = {}
    for h in horizons:
        col = f"mk_{h}"
        if not t_b.size:
            f[col] = np.nan
            continue
        th_t = tf + int(h * US)
        c1h, ageh = lookup(t_b, clean, th_t)
        mk = side * ((c1h - c0) + (mid_f - px)) / px * 1e4
        bad_h = stale | artifact | (th_t > t_last) | (ageh > th.stale_s)
        for g0, g1 in gaps:
            bad_h = bad_h | ((g0 < th_t) & (g1 > tf))
        f[col] = np.where(bad_h, np.nan, mk)
        dropped[h] = int((bad_h & ~artifact).sum())

    # queue wait
    f["wait_s"] = np.where(f["place_ts_us"].notna() & (f["timing"] == "exchange"),
                           (f["t_us"] - f["place_ts_us"]) / US, np.nan)

    # the five terms, per fill / per update, then totals and buckets
    edge_term = np.where(artifact, 0.0, edge_f)
    art_fill = np.where(artifact, edge_f, 0.0)
    fee_term = -fee
    inv_nonjump = np.where(jumps_mask, 0.0, inv_j) if t_b.size else np.empty(0)
    totals = {"edge": float(edge_term.sum()), "adverse": float(adverse_f.sum()),
              "carry": float(inv_nonjump.sum() - adverse_f.sum()), "fees": float(fee_term.sum()),
              "artifact": float(art_fill.sum() + jump_pnl_j.sum())}
    mid_end = float(mid_b[-1]) if t_b.size else float(mid_f[-1])
    net = float(cash[-1] + pos[-1] * mid_end - fees[-1])
    if not t_b.size:                                          # no feed at all: whatever is left is carry
        totals["carry"] = net - totals["edge"] - totals["adverse"] - totals["artifact"] - totals["fees"]
    totals["net"] = net
    notional = float((px * qty).sum())
    totals["notional"] = notional
    totals["bp"] = {k: (v / notional * 1e4 if notional > 0 else 0.0) for k, v in totals.items()
                    if k in ("edge", "adverse", "carry", "fees", "artifact", "net")}
    totals["identity_gap"] = float(totals["edge"] + totals["adverse"] + totals["carry"] + totals["fees"]
                                   + totals["artifact"] - net)

    # buckets (UTC day and hour of the event)
    ev_t = [tf]
    ev = {"edge": [edge_term], "adverse": [adverse_f], "fees": [fee_term], "artifact": [art_fill],
          "carry": [-adverse_f], "n": [np.ones(n)], "notional": [px * qty]}
    if t_b.size:
        ev_t.append(t_b)
        z = np.zeros(t_b.size)
        ev["edge"].append(z); ev["adverse"].append(z); ev["fees"].append(z)
        ev["artifact"].append(jump_pnl_j); ev["carry"].append(inv_nonjump); ev["n"].append(z); ev["notional"].append(z)
    T = np.concatenate(ev_t)
    E = {k: np.concatenate(v) for k, v in ev.items()}
    res["by_hour"] = _bucket(T, E, HOUR_US)
    res["by_day"] = _bucket(T, E, DAY_US)

    # continuous curve on a grid + every fill
    curve = finish_curve(_curve(t_b, mid_b, tf, pos, cash, fees, t_end, jumps_mask, jump_pnl_j, lot_usd), f)
    res.update(fills=f, curve=curve, gaps=gaps, attribution=totals, mid_end=mid_end,
               jumps=pd.DataFrame({"t_us": t_b[jumps_mask], "dmid": dmid[jumps_mask] if t_b.size else [],
                                   "pos": pos_exposed[jumps_mask] if t_b.size else [],
                                   "pnl": jump_pnl_j[jumps_mask] if t_b.size else []}),
               counts={"stale_mid": int(stale.sum()), "artifact_fills": int(artifact.sum()),
                       "artifact_jumps": int(jumps_mask.sum()), "markout_dropped": dropped},
               adverse_usd=adverse_f)
    f["adverse_usd"] = adverse_f
    return res


def _zero_attr() -> dict:
    z = {"edge": 0.0, "adverse": 0.0, "carry": 0.0, "fees": 0.0, "artifact": 0.0, "net": 0.0, "notional": 0.0,
         "identity_gap": 0.0}
    z["bp"] = {k: 0.0 for k in ("edge", "adverse", "carry", "fees", "artifact", "net")}
    return z


def _bucket(T: np.ndarray, E: dict, width_us: int) -> list[dict]:
    key = T // width_us
    out = []
    for k in np.unique(key):
        m = key == k
        row = {t: float(E[t][m].sum()) for t in ("edge", "adverse", "carry", "fees", "artifact")}
        row["net"] = row["edge"] + row["adverse"] + row["carry"] + row["fees"] + row["artifact"]
        row["fills"] = int(E["n"][m].sum())
        row["notional"] = float(E["notional"][m].sum())
        row["t0_us"] = int(k * width_us)
        out.append(row)
    return out


def _curve(t_b, mid_b, tf, pos, cash, fees, t_end, jumps_mask, jump_pnl_j, lot_usd, step_s: float = 60.0,
           max_points: int = 4000) -> pd.DataFrame:
    """Cumulative pnl on a time grid (and at every fill): cash + pos*mid - fees, plus the same without the
    artifact amounts (jump pnl accumulated at each jump)."""
    if t_b.size == 0:
        return pd.DataFrame({"t_us": tf, "pnl": cash - fees, "lots": np.zeros(len(tf), int)})
    t0, t1 = int(tf[0]), int(max(t_b[-1], tf[-1], t_end or 0))
    span = max(t1 - t0, 1)
    step = max(step_s, span / US / max_points) * US
    grid = np.unique(np.concatenate([np.arange(t0, t1, int(step)), tf, [t1]])).astype("int64")
    k = np.searchsorted(tf, grid, side="right")
    p = np.concatenate([[0.0], pos])[k]
    c = np.concatenate([[0.0], cash])[k]
    fe = np.concatenate([[0.0], fees])[k]
    m, _ = lookup(t_b, mid_b, grid)
    pnl = c + p * m - fe
    cum_jump = np.concatenate([[0.0], np.cumsum(jump_pnl_j)])[np.searchsorted(t_b, grid, side="right")]
    # artifact fills' edge is also an artifact amount; add it at the fill time
    return pd.DataFrame({"t_us": grid, "pnl": pnl, "cum_jump": cum_jump,
                         "lots": np.rint(p * m / lot_usd).astype(int) if lot_usd else 0})


def finish_curve(curve: pd.DataFrame, fills: pd.DataFrame) -> pd.DataFrame:
    """Add ``pnl_ex_artifact`` = pnl minus the artifact amounts accumulated so far (artifact fills' edge at
    their fill time, plus the jump pnl)."""
    c = curve.copy()
    if "cum_jump" not in c:
        c["cum_jump"] = 0.0
    art = fills[fills["artifact"]] if len(fills) else fills
    cum_fill = np.zeros(len(c))
    if len(art):
        tt = art["t_us"].to_numpy("int64")
        ee = np.cumsum(art["edge_usd"].to_numpy(float))
        k = np.searchsorted(tt, c["t_us"].to_numpy("int64"), side="right")
        cum_fill = np.concatenate([[0.0], ee])[k]
    c["pnl_ex_artifact"] = c["pnl"] - c["cum_jump"] - cum_fill
    return c.drop(columns=["cum_jump"])


# ---------------------------------------------------------------------- quote-state intervals
def state_intervals(rows: list[dict], t_end: Optional[int] = None, repeat_us: int = 60 * US,
                    max_gap_us: int = 150 * US) -> dict:
    """Merge the state log (a line on change, plus one per side every 60 s) into intervals per side.
    An interval ends at the next different state, or one repeat after the last line when the log goes quiet
    for longer than ``max_gap_us`` (the process was down)."""
    out = {"bid": [], "ask": []}
    for side, name in ((1, "bid"), (-1, "ask")):
        rs = sorted((r for r in rows if r.get("side") == side), key=lambda r: r["ts_us"])
        cur = None
        last_ts = None
        for r in rs:
            ts = int(r["ts_us"])
            if cur is not None and ts - last_ts > max_gap_us:
                cur["t1"] = last_ts + repeat_us
                out[name].append(cur)
                cur = None
            if cur is None or cur["state"] != r["state"]:
                if cur is not None:
                    cur["t1"] = ts
                    out[name].append(cur)
                cur = {"t0": ts, "t1": ts, "state": r["state"], "detail": r.get("detail")}
            else:
                cur["detail"] = r.get("detail")
            last_ts = ts
        if cur is not None:
            end = t_end if t_end is not None and t_end - last_ts <= max_gap_us else last_ts + repeat_us
            cur["t1"] = max(end, cur["t0"])
            out[name].append(cur)
    return out


def uptime(intervals: dict, t0: Optional[int] = None, t1: Optional[int] = None) -> list[dict]:
    """Seconds and share of the observed time spent in each state, per side."""
    rows = []
    for name in ("bid", "ask"):
        acc: dict = {}
        for iv in intervals.get(name, []):
            a, b = iv["t0"], iv["t1"]
            if t0 is not None:
                a = max(a, t0)
            if t1 is not None:
                b = min(b, t1)
            if b > a:
                acc[iv["state"]] = acc.get(iv["state"], 0.0) + (b - a) / US
        tot = sum(acc.values())
        for st, s in sorted(acc.items(), key=lambda kv: -kv[1]):
            rows.append({"side": name, "state": st, "seconds": s, "share": s / tot if tot else 0.0})
    return rows


# ---------------------------------------------------------------------- incidents
def _fmt_ts(us: int) -> str:
    return pd.Timestamp(int(us), unit="us", tz="UTC").strftime("%d %b %H:%M:%S UTC")


def _dur(s: float) -> str:
    return f"{s:.0f} s" if s < 90 else f"{s / 60:.0f} min" if s < 5400 else f"{s / 3600:.1f} h"


def day_pnl_at(state_rows: Optional[list[dict]], ts_us: int, window_s: float = 5.0) -> Optional[float]:
    """The day's P&L the trader itself logged in its LOSS_STOP state line closest to ``ts_us`` (within ``window_s``)."""
    best = None
    for r in state_rows or []:
        d = r.get("detail")
        if r.get("state") == "LOSS_STOP" and isinstance(d, dict) and d.get("pnl_day") is not None:
            gap = abs(int(r["ts_us"]) - int(ts_us))
            if gap <= window_s * US and (best is None or gap < best[0]):
                best = (gap, float(d["pnl_day"]))
    return None if best is None else best[1]


def incidents(an: dict, intervals: dict, orders: list[dict], sessions: list[dict], *, q_max: int,
              max_loss: float, thresholds: Thresholds = Thresholds(), t_end: Optional[int] = None,
              state_rows: Optional[list[dict]] = None) -> list[dict]:
    """Rule-based incidents, each with a sentence that includes its numbers (spec 6.3). Newest first.
    ``cost_usd`` is always a cost: positive means money lost, 0 when the event was in our favour."""
    th = thresholds
    out: list[dict] = []
    f = an["fills"]

    def add(kind, severity, t0, t1, sentence, fills=(), cost=None):
        out.append({"id": f"{kind}-{int(t0)}", "kind": kind, "severity": severity, "t0": int(t0), "t1": int(t1),
                    "sentence": sentence, "fills": [int(i) for i in fills], "cost_usd": None if cost is None else float(cost)})

    # loss stops. The order log's ``pnl`` is the cumulative P&L; the limit is on the day's P&L, so print both.
    for r in orders:
        if r.get("op") == "loss-stop":
            day = day_pnl_at(state_rows, r["ts_us"])
            cum = f"cumulative P&L at that moment was {r.get('pnl', 0):.2f} USDT"
            head = (f"the day's P&L was {day:.2f} USDT against a limit of -{max_loss:g} USDT" if day is not None
                    else f"the day's loss passed the limit of {max_loss:g} USDT")
            add("loss_stop", "high", r["ts_us"], r["ts_us"],
                f"Daily loss stop fired at {_fmt_ts(r['ts_us'])}: {head}; {cum}. "
                f"It holds until the next UTC day, even if the day's P&L recovers.", cost=max_loss)
    # artifact fills: a glitch that paid us is information, not an incident to act on
    for _, r in (f[f["artifact"]].iterrows() if len(f) else []):
        gain = r["edge_usd"]
        what = (f"{'Sell' if r['side'] < 0 else 'Buy'} of {r['qty']:g} at {r['price']:g} when the mid was {r['mid']:g} "
                f"({abs(r['price'] - r['mid']) / r['mid'] * 1e4:.0f} bp away), a book glitch ")
        if gain > 0:
            add("artifact_fill", "info", r["t_us"], r["t_us"],
                what + f"worth {gain:+.2f} USDT in our favour at the fill's own mid.", fills=[r["i"]], cost=0.0)
        else:
            add("artifact_fill", "high", r["t_us"], r["t_us"],
                what + f"costing {-gain:.2f} USDT at the fill's own mid.", fills=[r["i"]], cost=-gain)
    # inventory breach: contiguous runs of abs(lots) > q_max, judged after each fill
    if len(f):
        br = (f["lots_after"].abs() > q_max).to_numpy()
        i = 0
        while i < len(f):
            if br[i]:
                j = i
                while j + 1 < len(f) and br[j + 1]:
                    j += 1
                worst = int(f["lots_after"].iloc[i:j + 1].abs().max())
                t1 = int(f["t_us"].iloc[j + 1]) if j + 1 < len(f) else int(t_end or f["t_us"].iloc[j])
                add("inventory_breach", "high", f["t_us"].iloc[i], t1,
                    f"Inventory reached {worst} lots against a cap of {q_max} at {_fmt_ts(f['t_us'].iloc[i])}.",
                    fills=f["i"].iloc[i:j + 1].tolist())
                i = j + 1
            else:
                i += 1
    # idle: no side QUOTING for > idle_s, not by policy / warm-up / loss stop / stale feed
    ok_idle = {"POLICY_OUT", "WARMUP", "LOSS_STOP", "STALE_FEED"}
    edges = sorted({iv[k] for s in intervals.values() for iv in s for k in ("t0", "t1")})
    run = None
    for a, b in zip(edges, edges[1:]):
        st = {}
        for name in ("bid", "ask"):
            for iv in intervals.get(name, []):
                if iv["t0"] <= a < iv["t1"]:
                    st[name] = iv["state"]
        idle_now = len(st) == 2 and "QUOTING" not in st.values() and not (set(st.values()) & ok_idle)
        if idle_now:
            run = (run[0], b, run[2]) if run else (a, b, dict(st))
        else:
            if run and run[1] - run[0] > th.idle_s * US:
                _idle(add, run)
            run = None
    if run and run[1] - run[0] > th.idle_s * US:
        _idle(add, run)
    # restart: a start with no clean stop before it
    last = None
    for r in sorted(sessions, key=lambda r: r["ts_us"]):
        if r.get("op") == "start" and last is not None and last.get("op") != "stop":
            add("restart", "medium", r["ts_us"], r["ts_us"],
                f"Trader restarted at {_fmt_ts(r['ts_us'])} without a clean stop before it; it began with "
                f"{r.get('pos_at_start', 0):g} in position.")
        last = r
    # reject burst
    rj = sorted(r["ts_us"] for r in orders if r.get("op") == "reject")
    i = 0
    while i < len(rj):
        j = i
        while j + 1 < len(rj) and rj[j + 1] - rj[i] <= th.reject_burst_s * US:
            j += 1
        if j - i + 1 >= th.reject_burst_n:
            add("reject_burst", "medium", rj[i], rj[j],
                f"{j - i + 1} orders rejected within {(rj[j] - rj[i]) / US:.0f} s from {_fmt_ts(rj[i])}.")
            i = j + 1
        else:
            i += 1
    # feed gaps
    for g0, g1 in an["gaps"]:
        add("feed_gap", "medium", g0, g1, f"No book update for {_dur((g1 - g0) / US)} from {_fmt_ts(g0)}.")
    # exchange errors and long policy-out
    for name in ("bid", "ask"):
        for iv in intervals.get(name, []):
            if iv["state"] == "EXCHANGE_ERROR":
                add("exchange_error", "low", iv["t0"], iv["t1"],
                    f"Exchange error on the {name} side at {_fmt_ts(iv['t0'])}: {str(iv.get('detail'))[:80]}.")
    for iv in _both(intervals, "POLICY_OUT"):
        if iv[1] - iv[0] > th.policy_out_s * US:
            add("policy_out", "info", iv[0], iv[1],
                f"The policy chose to stay out on both sides for {_dur((iv[1] - iv[0]) / US)} from {_fmt_ts(iv[0])}.")
    out.sort(key=lambda r: -r["t0"])
    return out


def _idle(add, run) -> None:
    a, b, st = run
    why = ", ".join(f"{k} {v}" for k, v in st.items())
    add("idle", "high", a, b, f"Not quoting since {_fmt_ts(a)}: {why} ({_dur((b - a) / US)}).")


def _both(intervals: dict, state: str) -> list[tuple[int, int]]:
    """Stretches where both sides were in ``state``."""
    bid = [(iv["t0"], iv["t1"]) for iv in intervals.get("bid", []) if iv["state"] == state]
    ask = [(iv["t0"], iv["t1"]) for iv in intervals.get("ask", []) if iv["state"] == state]
    out = []
    for a0, a1 in bid:
        for b0, b1 in ask:
            lo, hi = max(a0, b0), min(a1, b1)
            if hi > lo:
                out.append((lo, hi))
    return out


# ---------------------------------------------------------------------- tape (drill-down) windows
def tape_windows(times_us: list[int], before_s: float = 60.0, after_s: float = 300.0) -> list[tuple[int, int]]:
    """Merged windows from ``before_s`` before to ``after_s`` after each time."""
    w = sorted((int(t - before_s * US), int(t + after_s * US)) for t in times_us)
    out: list[list[int]] = []
    for a, b in w:
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


# ---------------------------------------------------------------------- the session chart (dashboard chart spec, 7.2 to 7.4)
CHART_MAX_FILLS = 1500


def _px(x: float) -> str:
    """A price as the page prints it: thousands separated from 1,000 up, five significant digits below."""
    return f"{x:,.0f}" if abs(x) >= 1000 else f"{float(f'{x:.5g}'):g}"


def _in(label: str) -> str:
    return ("over " if label.startswith("all") else "in ") + label


def _sl(v) -> str:
    v = int(v)
    return ("−" if v < 0 else "+") + str(abs(v))


def order_intervals(orders: list[dict], fills: pd.DataFrame, t_end: int) -> dict:
    """Where our orders rested: {side: (start_us, end_us, price)} as arrays. An order opens at its ``place`` and
    closes at the first of its cancel (or cancel-miss), its full fill, the next placement on the same side (the
    trader keeps one order per side) and ``t_end``."""
    ends: dict = {}
    for o in orders:
        if o.get("op") in ("cancel", "cancel-miss") and o.get("order_id") is not None:
            ts = int(o["ts_us"])
            ends[o["order_id"]] = min(ends.get(o["order_id"], ts), ts)
    if len(fills) and "order_id" in fills:
        for oid, t, how in zip(fills["order_id"], fills["t_us"], fills["how"]):
            if oid == oid and oid is not None and how != "partial":
                ends[oid] = min(ends.get(oid, int(t)), int(t))
    out = {}
    for side in (1, -1):
        pl = sorted((int(o["ts_us"]), float(o["price"]), o.get("order_id")) for o in orders
                    if o.get("op") == "place" and o.get("order_id") is not None and int(o["side"]) == side)
        a = np.array([p[0] for p in pl], dtype="int64")
        p = np.array([p[1] for p in pl], dtype=float)
        nxt = np.append(a[1:], t_end) if len(a) else a
        e = np.array([min(ends.get(pl[i][2], t_end), int(nxt[i]), t_end) for i in range(len(pl))], dtype="int64")
        keep = e > a
        out[side] = (a[keep], e[keep], p[keep])
    return out


def _quote_means(iv: tuple, edges: np.ndarray, t_b: np.ndarray, mid_b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Time-weighted mean distance (bp, signed in price terms) of resting orders from the mid, per bucket, and the
    resting time per bucket (us). With G(t) the integral of 1/mid, the integral of (p/mid - 1) over [a, b] is
    p * (G(b) - G(a)) - (b - a), so no per-update loop is needed."""
    nb = len(edges) - 1
    a, b, p = iv
    zero = np.zeros(nb)
    if not len(a) or not t_b.size:
        return np.full(nb, np.nan), zero
    inv = 1.0 / mid_b
    gk = np.concatenate([[0.0], np.cumsum(np.diff(t_b).astype(float) * inv[:-1])])

    def G(t):
        i = np.clip(np.searchsorted(t_b, t, side="right") - 1, 0, None)
        return gk[i] + (t - t_b[i]) * inv[i]

    a = np.maximum(a, max(int(edges[0]), int(t_b[0])))
    b = np.minimum(b, int(edges[-1]))
    ok = b > a
    a, b, p = a[ok], b[ok], p[ok]
    if not len(a):
        return np.full(nb, np.nan), zero
    ia = np.clip(np.searchsorted(edges, a, side="right") - 1, 0, nb - 1)
    ib = np.clip(np.searchsorted(edges, b, side="left") - 1, 0, nb - 1)
    cnt = ib - ia + 1
    idx = np.repeat(np.arange(len(a)), cnt)
    within = np.arange(int(cnt.sum())) - np.repeat(np.cumsum(cnt) - cnt, cnt)
    bk = ia[idx] + within
    lo = np.maximum(a[idx], edges[bk])
    hi = np.minimum(b[idx], edges[bk + 1])
    g = hi > lo
    idx, bk, lo, hi = idx[g], bk[g], lo[g], hi[g]
    integ = 1e4 * (p[idx] * (G(hi) - G(lo)) - (hi - lo).astype(float))
    s_i = np.bincount(bk, weights=integ, minlength=nb)
    s_l = np.bincount(bk, weights=(hi - lo).astype(float), minlength=nb)
    mean = np.where(s_l > 0, s_i / np.where(s_l > 0, s_l, 1.0), np.nan)
    return mean, s_l


def _axis_range(vals, lo_q: float = 1.0, hi_q: float = 99.0, pad: float = 0.10) -> Optional[list]:
    v = np.asarray([x for x in vals if x is not None and np.isfinite(x)], dtype=float)
    if not v.size:
        return None
    lo, hi = float(np.percentile(v, lo_q)), float(np.percentile(v, hi_q))
    if hi - lo < 1e-9:
        d = max(abs(lo) * 1e-4, 1.0 if abs(lo) < 1 else 1e-6)
        lo, hi = lo - d, hi + d
    p = (hi - lo) * pad
    return [lo - p, hi + p]


def chart_series(fills: pd.DataFrame, book: pd.DataFrame, orders: list[dict], curve: pd.DataFrame, *, t_end: int,
                 q_max: int, source: str, symbol: str, policy: str, ranges: dict, thresholds: Thresholds = Thresholds(),
                 pnl_sentences: Optional[dict] = None, max_buckets: int = 500) -> dict:
    """Everything the session chart draws, per range button. ``ranges`` maps key -> (hours or None, label). Every
    number and every sentence is written here; the page prints them. ``pnl_sentences`` maps key -> the
    ``cum_pnl`` sentence (paper sessions only). P&L is the curve as it is: cumulative since the session began."""
    th = thresholds
    t_b, mid_b, _bid, _ask = book_arrays(book)
    f = fills.reset_index(drop=True)
    ft = f["t_us"].to_numpy("int64") if len(f) else np.empty(0, "int64")
    lots_all = f["lots_after"].to_numpy(int) if len(f) else np.empty(0, int)
    side_all = f["side"].to_numpy(int) if len(f) else np.empty(0, int)
    art_all = f["artifact"].to_numpy(bool) if len(f) else np.empty(0, bool)
    edge_all = f["edge_usd"].to_numpy(float) if len(f) else np.empty(0)
    mid_f = f["mid"].to_numpy(float) if len(f) else np.empty(0)
    px_f = f["price"].to_numpy(float) if len(f) else np.empty(0)
    dist_all = (px_f - mid_f) / np.where(mid_f > 0, mid_f, np.nan) * 1e4 if len(f) else np.empty(0)
    iv = order_intervals(orders, f, t_end)
    paper = source == "paper"
    ct = curve["t_us"].to_numpy("int64") if len(curve) else np.empty(0, "int64")
    starts = [int(t_b[0])] if t_b.size else []
    starts += [int(ft[0])] if len(ft) else []
    starts += [int(iv[s][0].min()) for s in (1, -1) if len(iv[s][0])]
    data_start = min(starts) if starts else t_end
    out = {}
    for key, (hours, label) in ranges.items():
        w0 = data_start if hours is None else max(t_end - int(hours * 3_600 * US), data_start)
        w0 = min(w0, t_end - US)
        span = t_end - w0
        nb = int(min(max_buckets, max(2, span // 1000)))
        edges = np.linspace(w0, t_end, nb + 1).round().astype("int64")
        edges[-1] = t_end
        ends = edges[1:]
        t_ms = [int(e) // 1000 for e in ends]
        i0 = int(np.searchsorted(ft, w0, side="left"))
        i1 = int(np.searchsorted(ft, t_end, side="right"))
        nwin = i1 - i0
        mean_b, rest_b = _quote_means(iv[1], edges, t_b, mid_b)
        mean_a, rest_a = _quote_means(iv[-1], edges, t_b, mid_b)
        has_orders = bool((rest_b > 0).any() or (rest_a > 0).any())
        mid_e, age = lookup(t_b, mid_b, ends)
        mid_s = np.where(np.isfinite(age) & (age <= th.feed_gap_s), mid_e, np.nan) if t_b.size else np.full(nb, np.nan)
        titles = {"card": f"{symbol} {policy}: the session, replayed"}
        base = {"t": t_ms, "mid": mid_s, "axes": {"price": _axis_range(mid_s), "bp": None}, "off_scale": None,
                "events": [], "fill_ids": None, "empty": None}
        if not np.isfinite(mid_s).any():
            titles["sub"] = f"Nothing to replay {_in(label)}."
            titles["price"] = f"No book was recorded {_in(label)}."
            out[key] = {**base, "t": [], "mid": [], "axes": {"price": None, "bp": None}, "panels": ["price"], "titles": titles,
                        "empty": f"No book data {_in(label)}, so there is no price series."}
            continue
        if not nwin and not has_orders:
            titles["sub"] = f"Price {_in(label)}; the {policy} trader placed no orders."
            titles["price"] = _price_title(mid_s, 0, 0, label, None)
            out[key] = {**base, "panels": ["price"], "titles": titles,
                        "empty": f"No orders {_in(label)}: the {policy} trader stayed out."}
            continue
        panels = ["price"] + (["quotes"] if has_orders else []) + ["inventory"] + (["pnl"] if paper and nwin else [])
        # inventory and counts
        k = np.searchsorted(ft, ends, side="right")
        lots_arr = np.concatenate([[0], lots_all])
        lots = lots_arr[k]
        start_lots = int(lots_arr[i0])
        run = np.maximum.accumulate(np.concatenate([[abs(start_lots)], np.abs(lots_all[i0:i1])])) if nwin else np.array([abs(start_lots)])
        kk = np.clip(k - i0, 0, nwin)
        max_abs = run[kk]
        buys = np.concatenate([[0], np.cumsum(side_all[i0:i1] > 0)])[kk]
        sells = np.concatenate([[0], np.cumsum(side_all[i0:i1] < 0)])[kk]
        # fills drawn
        win_idx = np.arange(i0, i1)
        n_art = int(art_all[i0:i1].sum())
        ids = None
        if nwin > CHART_MAX_FILLS:
            art = win_idx[art_all[i0:i1]]
            rest = win_idx[~art_all[i0:i1]]
            rest = rest[np.argsort(-np.abs(edge_all[rest]), kind="stable")][:max(CHART_MAX_FILLS - len(art), 0)]
            drawn = np.sort(np.concatenate([art, rest]))
            ids = [int(f["i"].iloc[j]) for j in drawn]
        else:
            drawn = win_idx
        width = mean_a - mean_b
        # axes and off-scale
        price_ax = _axis_range(mid_s)
        bp_vals = list(mean_b[np.isfinite(mean_b)]) + list(mean_a[np.isfinite(mean_a)])
        bp_vals += [v for v in dist_all[drawn][~art_all[drawn]] if np.isfinite(v)] if has_orders else []
        bp_ax = _axis_range(bp_vals) if has_orders else None
        off = 0
        for j in drawn:
            o = (price_ax and not (price_ax[0] <= px_f[j] <= price_ax[1])) or \
                (bp_ax and np.isfinite(dist_all[j]) and not (bp_ax[0] <= dist_all[j] <= bp_ax[1]))
            off += bool(o)
        # titles
        titles["sub"] = (f"Price with our quotes and fills, inventory{' and P&L' if 'pnl' in panels else ''} {_in(label)}. "
                         f"Press Play or drag the slider.")
        shown = (nwin, len(drawn)) if ids is not None else None
        titles["price"] = _price_title(mid_s, nwin, n_art, label, shown)
        if has_orders:
            both = np.isfinite(width)
            share = float(both.mean())
            titles["quotes"] = (f"Both sides quoted {share:.0%} of {label}; median quote width {float(np.median(width[both])):.1f} bp"
                                if both.any() else f"Orders rested on one side only {_in(label)}; no bucket had both sides quoted.")
        # cap excursions
        seq = np.concatenate([[start_lots], lots_all[i0:i1]]) if nwin else np.array([start_lots])
        over = np.abs(seq) > q_max
        entries = int((over[1:] & ~over[:-1]).sum() + (1 if over[0] else 0)) if len(over) else 0
        peak_j = int(np.argmax(np.abs(seq)))
        peak = int(seq[peak_j])
        if entries:
            titles["inventory"] = (f"Inventory went past the ±{q_max}-lot cap {'once' if entries == 1 else f'{entries} times'}, "
                                   f"to {_sl(peak)} lots {_in(label)}")
        else:
            titles["inventory"] = f"Inventory stayed inside the ±{q_max}-lot cap {_in(label)}"
        events = []
        # inventory event
        if nwin:
            wl = lots_all[i0:i1]
            first_over = np.nonzero(np.abs(wl) > q_max)[0]
            if len(first_over):
                j = i0 + int(first_over[0])
                events.append({"panel": "inventory", "t": int(ft[j]) // 1000, "y": int(lots_all[j]),
                               "text": f"past the cap: {_sl(lots_all[j])} of ±{q_max} lots"})
            elif np.abs(wl).max() > 0:
                j = i0 + int(np.argmax(np.abs(wl)))
                events.append({"panel": "inventory", "t": int(ft[j]) // 1000, "y": int(lots_all[j]),
                               "text": f"peak: {_sl(lots_all[j])} lots"})
        # fill event: the costliest fill by edge in USDT
        if len(drawn) and edge_all[drawn].min() < 0:
            j = int(drawn[int(np.argmin(edge_all[drawn]))])
            sold = side_all[j] < 0
            d = abs(dist_all[j])
            where = "under" if px_f[j] < mid_f[j] else "over"
            if art_all[j]:
                text = f"book glitch: {'sold' if sold else 'bought'} {d:,.0f} bp {where} the mid"
            else:
                text = f"costliest fill: {'sold' if sold else 'bought'} {d:.1f} bp {where} the mid ({edge_all[j]:+.2f} USDT)"
            y = px_f[j] if not price_ax else min(max(px_f[j], price_ax[0]), price_ax[1])
            events.append({"panel": "price", "t": int(ft[j]) // 1000, "y": float(y), "text": text})
        base.update(axes={"price": price_ax, "bp": bp_ax}, fill_ids=ids,
                    off_scale=(f"{off} fill{'s' if off != 1 else ''} off scale" if off else None))
        res = {**base, "panels": panels, "titles": titles, "mid": mid_s,
               "bid_bp": mean_b if has_orders else None, "ask_bp": mean_a if has_orders else None,
               "width_bp": width if has_orders else None,
               "lots": lots, "max_abs_lots": max_abs, "fills_cum": buys + sells, "buys_cum": buys, "sells_cum": sells}
        if "pnl" in panels and len(ct):
            def at(col):
                v = curve[col].to_numpy(float)
                kc = np.searchsorted(ct, ends, side="right")
                return np.where(kc > 0, v[np.clip(kc - 1, 0, None)], 0.0), v, kc
            pnl, vfull, _ = at("pnl")
            pnl_ex, _, _ = at("pnl_ex_artifact")
            k0 = int(np.searchsorted(ct, w0, side="right"))
            p0 = float(vfull[k0 - 1]) if k0 > 0 else 0.0
            peak_p = np.maximum.accumulate(np.concatenate([[p0], pnl]))[1:]
            res.update(pnl=pnl, pnl_ex_artifact=pnl_ex, pnl_peak=peak_p)
            titles["pnl"] = (pnl_sentences or {}).get(key) or f"Cumulative P&L since the session began, shown for {label}."
            dd = peak_p - pnl
            if dd.max() > 1e-9:
                j = int(np.argmax(dd))
                events.append({"panel": "pnl", "t": t_ms[j], "y": float(pnl[j]), "text": f"drawdown −{dd[j]:.2f} USDT"})
        res["events"] = events[:3]
        out[key] = res
    return out


def _price_title(mid_s: np.ndarray, n_fills: int, n_art: int, label: str, shown: Optional[tuple]) -> str:
    v = mid_s[np.isfinite(mid_s)]
    a, b = float(v[0]), float(v[-1])
    if abs(b - a) <= abs(a) * 1e-6:
        move = f"Mid stayed at {_px(a)}"
    else:
        move = f"Mid {'fell' if b < a else 'rose'} from {_px(a)} to {_px(b)}"
    if not n_fills:
        fl = "no fills"
    else:
        gl = ("none of them book glitches" if not n_art else "1 of them a book glitch" if n_art == 1
              else f"{n_art} of them book glitches")
        fl = f"{n_fills:,} fill{'s' if n_fills != 1 else ''}, {gl}"
    s = f"{move} {_in(label)}; {fl}"
    if shown:
        s += f"; showing the {shown[1]:,} largest of {shown[0]:,}"
    return s