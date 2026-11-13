"""Two-state regime model (v2.1 Task 15), numpy only.

A Gaussian hidden Markov model with diagonal covariance on one-minute features:
    vol_bp     realised volatility: standard deviation of trade-to-trade price changes in the minute, bp
    abs_imb    absolute trade imbalance |buy qty - sell qty| / total qty
    n_trades   trade count
    mk10_bp    mean 10 s markout of shadow fills made in the minute (0 when none)
Fitted by EM on the previous days. The state with the worse mean markout is ``toxic`` (the more
volatile state when there is no markout column). Online use is the **forward filter only**: p_toxic at
minute t uses minutes up to t. The smoothed (forward-backward) path is used for fitting and nowhere else.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

MIN_US = 60 * 1_000_000
FEATURES = ["vol_bp", "abs_imb", "n_trades", "mk10_bp"]


def _recv(df: pd.DataFrame) -> pd.DataFrame:
    """The pipeline's trade frames call the time column ts_us, the recorder's recv_us; accept both."""
    return df if "recv_us" in df.columns or "ts_us" not in df.columns else df.rename(columns={"ts_us": "recv_us"})


def minute_features(trades: pd.DataFrame, fills: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per minute from the first trade's minute to the last (empty minutes: zeros, count 0).
    ``trades``: recv_us, price, qty, side. ``fills``: ts_us, mk10_bp (shadow fills with their 10 s markout)."""
    trades = _recv(trades)
    t = trades["recv_us"].to_numpy(np.int64)
    m = t // MIN_US
    first, last = int(m.min()), int(m.max())
    idx = np.arange(first, last + 1)
    px, qty, side = trades["price"].to_numpy(float), trades["qty"].to_numpy(float), trades["side"].to_numpy()
    ret = np.r_[0.0, np.diff(px)] / px * 1e4
    df = pd.DataFrame({"m": m, "ret": ret, "qty": qty, "signed": qty * side})
    # trade-to-trade changes that straddle two minutes are attributed to the later minute (past-only)
    g = df.groupby("m")
    out = pd.DataFrame({"vol_bp": g["ret"].std(ddof=0), "abs_imb": g["signed"].sum().abs() / g["qty"].sum(), "n_trades": g.size().astype(float)})
    out = out.reindex(idx)
    out["n_trades"] = out["n_trades"].fillna(0.0)
    out[["vol_bp", "abs_imb"]] = out[["vol_bp", "abs_imb"]].fillna(0.0)
    mk = pd.Series(0.0, index=idx)
    if fills is not None and len(fills):
        fm = fills["ts_us"].to_numpy(np.int64) // MIN_US
        agg = pd.Series(fills["mk10_bp"].to_numpy(float)).groupby(fm).mean()
        mk.loc[agg.index.intersection(idx)] = agg.loc[agg.index.intersection(idx)]
    out["mk10_bp"] = mk
    out.index = idx * MIN_US
    out.index.name = "minute_us"
    return out[FEATURES]


@dataclass
class RegimeModel:
    pi: np.ndarray
    A: np.ndarray
    means: np.ndarray            # in the original feature units
    vars: np.ndarray
    toxic: int
    mu: np.ndarray               # scaler fitted on the training minutes
    sd: np.ndarray

    def _logb(self, Z: np.ndarray) -> np.ndarray:
        zm = (self.means - self.mu) / self.sd
        zv = self.vars / self.sd ** 2
        return -0.5 * (((Z[:, None, :] - zm[None]) ** 2) / zv[None] + np.log(2 * np.pi * zv[None])).sum(2)

    def filter(self, X: np.ndarray) -> np.ndarray:
        """Forward filter: P(state_t | features up to t), shape (T, 2). Causal by construction."""
        Z = (np.asarray(X, float) - self.mu) / self.sd
        lb = self._logb(Z)
        out = np.empty((len(Z), 2))
        a = None
        for t in range(len(Z)):
            prior = self.pi if a is None else a @ self.A
            w = prior * np.exp(lb[t] - lb[t].max())
            a = w / w.sum()
            out[t] = a
        return out

    def p_toxic(self, X: np.ndarray) -> np.ndarray:
        return self.filter(X)[:, self.toxic]


def fit(X: np.ndarray, n_iter: int = 60, markout_col: int | None = 3, tol: float = 1e-6) -> RegimeModel:
    """EM (Baum-Welch with scaling) for a two-state diagonal Gaussian HMM. Deterministic: the start splits
    the minutes at the median of the first feature (volatility)."""
    X = np.asarray(X, float)
    mu, sd = X.mean(0), X.std(0)
    sd = np.where(sd > 0, sd, 1.0)
    Z = (X - mu) / sd
    T, d = Z.shape
    r = (Z[:, 0] > np.median(Z[:, 0])).astype(float)
    gamma = np.c_[1 - r, r]
    A = np.array([[0.95, 0.05], [0.05, 0.95]])
    pi = np.array([0.5, 0.5])
    zm = np.zeros((2, d))
    zv = np.ones((2, d))

    def mstep(gamma, xi_sum):
        for k in range(2):
            w = gamma[:, k]
            zm[k] = (w[:, None] * Z).sum(0) / w.sum()
            zv[k] = np.maximum((w[:, None] * (Z - zm[k]) ** 2).sum(0) / w.sum(), 1e-3)

    mstep(gamma, None)
    last = -np.inf
    for _ in range(n_iter):
        lb = -0.5 * (((Z[:, None, :] - zm[None]) ** 2) / zv[None] + np.log(2 * np.pi * zv[None])).sum(2)
        b = np.exp(lb - lb.max(1, keepdims=True))
        alpha, c = np.empty((T, 2)), np.empty(T)
        a0 = pi * b[0]
        c[0] = a0.sum(); alpha[0] = a0 / c[0]
        for t in range(1, T):
            at = (alpha[t - 1] @ A) * b[t]
            c[t] = at.sum(); alpha[t] = at / c[t]
        beta = np.ones((T, 2))
        for t in range(T - 2, -1, -1):
            beta[t] = (A @ (b[t + 1] * beta[t + 1])) / c[t + 1]
        gamma = alpha * beta
        gamma /= gamma.sum(1, keepdims=True)
        xi = (alpha[:-1, :, None] * A[None] * (b[1:] * beta[1:])[:, None, :] / c[1:, None, None]).sum(0)
        A = xi / xi.sum(1, keepdims=True)
        pi = gamma[0]
        mstep(gamma, xi)
        ll = float(np.log(c).sum() + lb.max(1).sum())
        if abs(ll - last) < tol * abs(ll):
            break
        last = ll
    means, variances = zm * sd + mu, zv * sd ** 2
    toxic = int(np.argmin(means[:, markout_col])) if markout_col is not None else int(np.argmax(means[:, 0]))
    return RegimeModel(pi=pi, A=A, means=means, vars=variances, toxic=toxic, mu=mu, sd=sd)


def markout_gap(p_toxic: np.ndarray, markout_bp: np.ndarray, threshold: float = 0.7) -> dict:
    """Task 15 pass statistic: mean 60 s markout of shadow fills in minutes with p_toxic above ``threshold``
    minus the mean in the other minutes (bp, negative = worse), Welch t-statistic, and the group sizes."""
    p, y = np.asarray(p_toxic, float), np.asarray(markout_bp, float)
    tox, rest = y[p > threshold], y[p <= threshold]
    out = {"n_toxic": int(len(tox)), "n_rest": int(len(rest)), "gap_bp": None, "t": None}
    if len(tox) > 1 and len(rest) > 1:
        gap = float(tox.mean() - rest.mean())
        se = float(np.sqrt(tox.var(ddof=1) / len(tox) + rest.var(ddof=1) / len(rest)))
        out["gap_bp"], out["t"] = gap, gap / se if se > 0 else None
    return out


def causal_p_toxic(train_trades: list, test_trades: pd.DataFrame) -> pd.Series:
    """Causal regime feed for one test day: fit on the minute features of ``train_trades`` (a list of the
    previous days' trade frames; no markout column, so the more volatile state is toxic) and run the
    forward filter over the test day. The value at minute m uses minutes up to m only. Indexed by the
    minute's start (us)."""
    X = np.vstack([minute_features(t)[FEATURES[:3]].to_numpy() for t in train_trades])
    model = fit(X, markout_col=None)
    f = minute_features(test_trades)
    return pd.Series(model.p_toxic(f[FEATURES[:3]].to_numpy()), index=f.index, name="p_toxic")


def lookup(p: pd.Series, ts_us: int) -> float:
    """p_toxic known at ``ts_us``: the filter of the last *completed* minute (the current one is unfinished)."""
    m = (int(ts_us) // MIN_US - 1) * MIN_US
    if len(p) == 0 or m < int(p.index[0]):
        return 0.0
    return float(p.iloc[min((m - int(p.index[0])) // MIN_US, len(p) - 1)])
