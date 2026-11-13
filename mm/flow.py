"""Day 9: reading the order flow, so informed traders hurt less.

Informed traders do not announce themselves, but their trading leaves traces a market
maker can measure from past data only:

  imbalance   (buy volume - sell volume) / total over the last 5 s and 60 s.
              Persistent one-sided aggression tends to come before the price moves.
  momentum    mid change over the last 5 s and 60 s, in bp.
  vol ratio   short-term volatility (10 s) / normal volatility (30 min). Above ~3 the
              market is in a news or liquidation burst, when quotes get picked off.
  sweep       a trade reaching far beyond the previous mid within one bar: someone paid
              to take liquidity across several levels. They usually know something.

``fit_alpha`` regresses the next 10 s mid move on these features (calibration days only,
non-overlapping samples) and ``predict_alpha`` applies the coefficients to a new day.
Every feature at bar i uses bars <= i only.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

FEATURES = ["imb_5s", "imb_60s", "ret_5s", "ret_60s"]


def flow_features(bars: pd.DataFrame, bar_ms: int = 100) -> pd.DataFrame:
    """Past-only features on the bar grid built by mm.data.trades_to_bars."""
    n5, n10, n60 = (int(s * 1000 / bar_ms) for s in (5, 10, 60))
    n30m = int(1800 * 1000 / bar_ms)
    mid = bars["mid"]
    out = pd.DataFrame(index=bars.index)
    for name, w in (("5s", n5), ("60s", n60)):
        b = bars["buy_vol"].rolling(w, min_periods=1).sum()
        s = bars["sell_vol"].rolling(w, min_periods=1).sum()
        out[f"imb_{name}"] = ((b - s) / (b + s)).where(b + s > 0, 0.0)
        out[f"ret_{name}"] = ((mid - mid.shift(w)) / mid * 1e4).fillna(0.0)
    d2 = mid.diff().fillna(0.0) ** 2
    vol_s = np.sqrt(d2.rolling(n10, min_periods=1).mean())
    vol_l = np.sqrt(d2.rolling(n30m, min_periods=n10).mean())
    out["vol_ratio"] = (vol_s / vol_l).replace([np.inf, -np.inf], np.nan).fillna(1.0)
    prev = mid.shift(1)
    reach = np.fmax((bars["buy_max"] - prev).to_numpy(), (prev - bars["sell_min"]).to_numpy())
    with np.errstate(divide="ignore", invalid="ignore"):
        z = reach / vol_l.to_numpy()                                      # in units of a normal bar move
    out["sweep_z"] = np.nan_to_num(z, nan=0.0, posinf=0.0, neginf=0.0)
    return out


def forward_return_bp(bars: pd.DataFrame, horizon_s: float = 10, bar_ms: int = 100) -> pd.Series:
    h = int(horizon_s * 1000 / bar_ms)
    mid = bars["mid"]
    return (mid.shift(-h) - mid) / mid * 1e4


@dataclass
class AlphaModel:
    coef: np.ndarray          # intercept first, then FEATURES
    tstat: np.ndarray
    r2: float
    n: int
    horizon_s: float
    cap_bp: float

    def as_dict(self) -> dict:
        names = ["const"] + FEATURES
        return {"coef": dict(zip(names, map(float, self.coef))), "tstat": dict(zip(names, map(float, self.tstat))),
                "r2": float(self.r2), "n": int(self.n), "horizon_s": self.horizon_s, "cap_bp": self.cap_bp}


def _design(feat: pd.DataFrame) -> np.ndarray:
    return np.column_stack([np.ones(len(feat))] + [feat[c].to_numpy(float) for c in FEATURES])


def fit_alpha(feat_list, fwd_list, horizon_s: float = 10, bar_ms: int = 100, cap_bp: float = 20.0) -> AlphaModel:
    """OLS of the forward mid move (bp) on the flow features, pooled over calibration days.
    Samples are taken every ``horizon_s`` so targets do not overlap (honest t-stats)."""
    step = int(horizon_s * 1000 / bar_ms)
    X, y = [], []
    for f, r in zip(feat_list, fwd_list):
        idx = np.arange(int(1800 * 1000 / bar_ms), len(f), step)     # skip the 30-min warm-up
        Xi, yi = _design(f.iloc[idx]), r.iloc[idx].to_numpy(float)
        ok = np.isfinite(yi) & np.isfinite(Xi).all(axis=1)
        X.append(Xi[ok]); y.append(yi[ok])
    X, y = np.vstack(X), np.concatenate(y)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    dof = max(len(y) - X.shape[1], 1)
    s2 = resid @ resid / dof
    cov = s2 * np.linalg.pinv(X.T @ X)
    t = beta / np.sqrt(np.maximum(np.diag(cov), 1e-300))
    r2 = 1 - resid @ resid / ((y - y.mean()) @ (y - y.mean())) if len(y) > 1 else float("nan")
    return AlphaModel(beta, t, r2, len(y), horizon_s, cap_bp)


def predict_alpha(model: AlphaModel, feat: pd.DataFrame) -> np.ndarray:
    """Predicted mid move over the model horizon, in bp, clipped to +/- cap_bp."""
    return np.clip(_design(feat) @ model.coef, -model.cap_bp, model.cap_bp)


def out_of_sample_r2(pred: np.ndarray, fwd: pd.Series, horizon_s: float = 10, bar_ms: int = 100) -> dict:
    """How well the day-ahead predictions did on the test day (non-overlapping samples)."""
    step = int(horizon_s * 1000 / bar_ms)
    idx = np.arange(int(1800 * 1000 / bar_ms), len(pred), step)
    p, y = pred[idx], fwd.to_numpy(float)[idx]
    ok = np.isfinite(p) & np.isfinite(y)
    p, y = p[ok], y[ok]
    if len(y) < 10:
        return {"r2_oos": float("nan"), "corr": float("nan"), "hit_rate": float("nan"), "n": int(len(y))}
    r2 = 1 - ((y - p) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    nz = (np.abs(p) > 1e-9) & (np.abs(y) > 1e-9)
    return {"r2_oos": float(r2), "corr": float(np.corrcoef(p, y)[0, 1]) if p.std() > 0 else float("nan"),
            "hit_rate": float((np.sign(p[nz]) == np.sign(y[nz])).mean()) if nz.any() else float("nan"), "n": int(len(y))}
