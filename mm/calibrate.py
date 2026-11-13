"""Day 8: calibrate the A-S inputs for any coin from one day of trades.

Everything is measured in the coin's own price units AND in basis points, so a
70,000 USDT coin and a 0.01 USDT coin can be compared on one table.

  tick         smallest price step seen in the data
  spread       typical best-ask minus best-bid, estimated from trades: a buyer-initiated
               trade prints at the ask, a seller-initiated one at the bid, so when both
               sides trade within 1 s their price difference is a spread observation
  sigma        volatility of the mid, price units per sqrt(second) (and bp per sqrt(s))
  A, k         fill model lambda(delta) = A e^{-k delta}: how often a quote delta away
               from the mid gets traded through, fitted by regression of ln(lambda) on delta
  gamma        not measurable: chosen from a target skew, see ``gamma_from_skew``

``random_entry_markouts`` is a sanity check for the backtest's markout measure: entries at
random times should show markouts close to zero. If real fills show -1.5 bp while random
entries show ~0, the loss is adverse selection, not a measurement artefact.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from mm.data import trades_to_bars

TIERS = [(500e6, "large"), (50e6, "mid"), (5e6, "small"), (0.0, "micro")]   # USD volume per day


def tier_of(usd_volume: float) -> str:
    return next(name for floor, name in TIERS if usd_volume >= floor)


def infer_tick(prices: np.ndarray) -> float:
    """Smallest positive gap between distinct traded prices (rounded to remove float noise)."""
    u = np.unique(np.round(np.asarray(prices, float), 10))
    d = np.diff(u)
    d = d[d > 0]
    if d.size == 0:
        return float("nan")
    t = float(d.min())
    mag = 10 ** np.floor(np.log10(t))
    return float(np.round(t / mag) * mag)


def spread_estimate(trades: pd.DataFrame, max_gap_us: int = 1_000_000, min_obs: int = 100) -> np.ndarray:
    """Spread observations from ADJACENT opposite-side trades: buyer-aggressor price minus
    seller-aggressor price, when the two trades are at most ``max_gap_us`` apart (widened
    5x if that leaves fewer than ``min_obs`` pairs, for thin coins). Returns positive values.
    Pairing only adjacent trades matters: on a busy coin the price moves between
    non-adjacent trades, which would be mistaken for spread."""
    ts = trades["ts_us"].to_numpy()
    px = trades["price"].to_numpy(float)
    buy = trades["side"].to_numpy() > 0
    sw = np.nonzero(buy[1:] != buy[:-1])[0]
    gap = ts[sw + 1] - ts[sw]
    d = np.where(buy[sw + 1], px[sw + 1] - px[sw], px[sw] - px[sw + 1])
    for g in (max_gap_us, 5 * max_gap_us, 60 * max_gap_us):
        obs = d[(gap <= g) & (d > 0)]
        if obs.size >= min_obs:
            break
    return obs


def typical_spread(spreads: np.ndarray, tick: float) -> float:
    """Most common spread observation (in whole ticks), never below one tick."""
    if spreads.size == 0 or not np.isfinite(tick):
        return tick
    ticks = np.maximum(np.round(spreads / tick), 1).astype(int)
    return float(np.bincount(ticks).argmax() * tick)


def sigma_ewma(mid: pd.Series, bar_ms: int, halflife_s: float) -> pd.Series:
    """Past-only EWMA volatility of the mid, price units per sqrt(second)."""
    dt = bar_ms / 1000.0
    d2 = mid.diff().fillna(0.0) ** 2
    return np.sqrt(d2.ewm(halflife=max(halflife_s / dt, 1.0), adjust=True).mean() / dt)


def fill_curve(sec: pd.DataFrame, tick: float, fit_from: float | None = None, n: int = 60) -> dict:
    """P(a quote at previous-second mid +/- delta is traded through within 1 s) on a delta grid,
    the implied intensity lambda = -ln(1 - P) per second, and the fit ln(lambda) = ln(A) - k delta.

    The fit ignores the first few ticks: at the touch, fills come from ordinary queue
    turnover rather than from trades reaching out to a price, and they sit far above
    the exponential curve."""
    prev = sec["mid"].shift(1)
    reach = np.concatenate([(sec["buy_max"] - prev).to_numpy(), (prev - sec["sell_min"]).to_numpy()])
    reach = np.where(np.isnan(reach), -np.inf, reach)
    finite = reach[np.isfinite(reach) & (reach > 0)]
    d_max = max(float(np.percentile(finite, 99.5)) if finite.size else 0.0, 20 * tick)
    deltas = np.linspace(0, d_max, n)
    p = np.array([(reach >= d).mean() for d in deltas])
    lam = -np.log1p(-np.clip(p, 0, 0.999999))
    if fit_from is None:
        fit_from = max(5 * tick, 0.02 * d_max)
    m = (deltas >= fit_from) & (p > 0)
    k = A = r2 = float("nan")
    if m.sum() >= 5:
        y = np.log(lam[m])
        slope, icpt = np.polyfit(deltas[m], y, 1)
        pred = icpt + slope * deltas[m]
        ss_tot = ((y - y.mean()) ** 2).sum()
        k, A = -slope, float(np.exp(icpt))
        r2 = 1 - ((y - pred) ** 2).sum() / ss_tot if ss_tot > 0 else float("nan")
    return {"delta": deltas, "p": p, "lam": lam, "k": float(k), "A": float(A), "r2": float(r2),
            "fit_from": float(fit_from)}


def fit_two_part(fc: dict, min_pts: int = 4) -> dict:
    """Fit ln(lambda) with two straight lines (core near the mid, tail far out) and pick the
    breakpoint with the smallest total squared error. Many coins show a steep core (ordinary
    trades near the touch) and a flat tail (occasional large sweeps); one exponential fitted
    to both gets the core badly wrong, and the core is where a market maker's fills happen.
    Returns k and A for each part, the breakpoint, and the R^2 of one vs two lines."""
    d, lam = np.asarray(fc["delta"], float), np.asarray(fc["lam"], float)
    m = (d > 0) & (lam > 0)
    x, y = d[m], np.log(lam[m])
    out = {"k_core": float("nan"), "A_core": float("nan"), "k_tail": float("nan"), "A_tail": float("nan"),
           "break_delta": float("nan"), "r2_one": float("nan"), "r2_two": float("nan")}
    if len(x) < 2 * min_pts:
        return out
    sst = ((y - y.mean()) ** 2).sum()
    b1 = np.polyfit(x, y, 1)
    out["r2_one"] = float(1 - ((y - np.polyval(b1, x)) ** 2).sum() / sst) if sst > 0 else float("nan")
    best = None
    for j in range(min_pts - 1, len(x) - min_pts + 1):
        p1, p2 = np.polyfit(x[: j + 1], y[: j + 1], 1), np.polyfit(x[j:], y[j:], 1)
        sse = ((y[: j + 1] - np.polyval(p1, x[: j + 1])) ** 2).sum() + ((y[j + 1:] - np.polyval(p2, x[j + 1:])) ** 2).sum()
        if best is None or sse < best[0]:
            best = (sse, j, p1, p2)
    sse, j, p1, p2 = best
    out.update(k_core=float(-p1[0]), A_core=float(np.exp(p1[1])), k_tail=float(-p2[0]), A_tail=float(np.exp(p2[1])),
               break_delta=float(x[j]), r2_two=float(1 - sse / sst) if sst > 0 else float("nan"))
    return out


def gamma_from_skew(skew_bp: float, mid: float, sigma: float, q_max: float, horizon_s: float) -> float:
    """Pick gamma so that at full inventory (q = q_max lots) at the start of the horizon,
    the reservation price sits ``skew_bp`` away from the mid:
        q_max * gamma * sigma^2 * T = skew_bp * mid / 1e4
    This makes gamma comparable across coins with very different prices and volatilities."""
    return skew_bp * mid * 1e-4 / (q_max * sigma ** 2 * horizon_s)


def random_entry_markouts(bars: pd.DataFrame, bar_ms: int, horizons_s=(0, 1, 10, 60, 300),
                          n: int = 20_000, seed: int = 0) -> pd.DataFrame:
    """Markouts of random-side entries at the mid at random times (should be ~0 bp)."""
    rng = np.random.default_rng(seed)
    mid = bars["mid"].to_numpy(float)
    i = rng.integers(0, len(mid) - 1, n)
    side = rng.choice([-1, 1], n)
    out = []
    for h in horizons_s:
        j = np.minimum(i + int(round(h * 1000 / bar_ms)), len(mid) - 1)
        out.append((h, float(np.mean(side * (mid[j] - mid[i]) / mid[i] * 1e4))))
    return pd.DataFrame(out, columns=["h_s", "markout_bp"])


def calibrate(trades: pd.DataFrame, symbol: str = "", date: str = "") -> dict:
    """All calibration numbers for one coin-day, in price units and bp."""
    px = trades["price"].to_numpy(float)
    price = float(np.median(px))
    tick = infer_tick(px)
    spreads = spread_estimate(trades)
    spread = typical_spread(spreads, tick)
    sec = trades_to_bars(trades, 1000)
    dmid = sec["mid"].diff().dropna()
    sigma = float(dmid.std())
    fc = fill_curve(sec, tick)
    if not (np.isfinite(fc["k"]) and fc["k"] > 0):        # thin / tick-constrained coin: fit from 1 tick
        fc = fill_curve(sec, tick, fit_from=tick)
    two = fit_two_part(fc)
    t0, t1 = trades["ts_us"].iloc[[0, -1]]
    hours = max((t1 - t0) / 3.6e9, 1e-9)
    usd = float((trades["price"] * trades["qty"]).sum()) * 24 / hours
    bp = 1e4 / price
    return {
        "symbol": symbol, "date": date, "tier": tier_of(usd),
        "price": price, "tick": tick, "tick_bp": tick * bp,
        "spread": spread, "spread_ticks": spread / tick, "spread_bp": spread * bp,
        "usd_volume_day": usd, "trades": int(len(trades)), "trades_per_sec": len(trades) / (hours * 3600),
        "sigma": sigma, "sigma_bp": sigma * bp,
        "daily_vol_pct": float(np.log(sec["mid"]).diff().std() * np.sqrt(86_400) * 100),
        "k": fc["k"], "k_bp": fc["k"] / bp if np.isfinite(fc["k"]) else float("nan"),
        "A": fc["A"], "r2": fc["r2"], "half_spread_1_over_k_bp": (1 / fc["k"]) * bp if fc["k"] > 0 else float("nan"),
        "k_core": two["k_core"], "k_core_bp": two["k_core"] / bp, "k_tail_bp": two["k_tail"] / bp,
        "break_bp": two["break_delta"] * bp, "r2_one": two["r2_one"], "r2_two": two["r2_two"],
        "half_spread_core_bp": (1 / two["k_core"]) * bp if two["k_core"] > 0 else float("nan"),
        "fill_curve": fc,
    }
