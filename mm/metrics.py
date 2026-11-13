"""Day 7: summary statistics for a backtest run (``mm.backtest.BTResult``)."""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_PER_YEAR = 365 * 24 * 60


def max_drawdown(pnl: np.ndarray) -> float:
    """Largest peak-to-trough fall of the P&L curve (a negative number, or 0)."""
    if len(pnl) == 0:
        return 0.0
    peak = np.maximum.accumulate(np.concatenate([[0.0], pnl]))[1:]
    return float((pnl - peak).min())


def summarize(res, fee_bps_scenarios=(0.0, 2.0, 10.0)) -> dict:
    """One row of the results table.

    pnl_bps_of_volume  P&L per dollar traded: the market maker's real margin.
    edge_bp            average side * (mid at the end of the fill bar - fill price): what we earned at fill.
    markout_60s_bp     the same, 60 s later. edge - markout = adverse selection.
    markout_60s_tstat  markout_60s_bp / its standard error across fills: |t| < 2 means the
                       sign could be luck (thin coins with a few hundred fills).
    sharpe_ann         from 1-minute P&L changes, annualised (sqrt of minutes per year).
    net_<x>bp          P&L if every fill paid a maker fee of x bp (gross P&L - x bp * notional).
    """
    m, f, tot, cfg = res.minute, res.fills, res.totals, res.cfg
    hours = max((m["t_s"].iloc[-1] - m["t_s"].iloc[0]) / 3600.0, 1e-9) if len(m) > 1 else 1e-9
    dpnl = m["pnl"].diff().dropna().to_numpy()
    sharpe = float(dpnl.mean() / dpnl.std() * np.sqrt(MIN_PER_YEAR)) if len(dpnl) > 1 and dpnl.std() > 0 else np.nan
    mk = res.markouts.set_index("h_s")["markout_bp"] if len(res.markouts) else pd.Series(dtype=float)
    se = res.markouts.set_index("h_s")["se_bp"] if len(res.markouts) and "se_bp" in res.markouts else pd.Series(dtype=float)
    notional = tot["notional"]
    gross = tot["pnl"] + tot["fees"]
    out = {
        "strategy": res.name,
        "pnl": tot["pnl"],
        "spread_capture": tot["spread_capture"],
        "inventory_pnl": tot["inventory_pnl"],
        "fees": tot["fees"],
        "fills": int(len(f)),
        "fills_per_hour": len(f) / hours,
        "buy_fills": int((f["side"] > 0).sum()) if len(f) else 0,
        "notional_usdt": notional,
        "pnl_bps_of_volume": tot["pnl"] / notional * 1e4 if notional else np.nan,
        "edge_bp": float(mk.get(0, np.nan)),
        "markout_10s_bp": float(mk.get(10, np.nan)),
        "markout_60s_bp": float(mk.get(60, np.nan)),
        "markout_60s_tstat": float(mk.get(60, np.nan) / se.get(60, np.nan)) if len(se) and se.get(60, 0) else np.nan,
        "adverse_selection_bp": float(mk.get(0, np.nan) - mk.get(60, np.nan)) if len(mk) else np.nan,
        "sharpe_ann": sharpe,
        "max_drawdown": max_drawdown(m["pnl"].to_numpy()),
        "q_std": float(m["q"].std()),
        "q_max_abs": float(m["q"].abs().max()),
        "final_q": tot["final_q"],
    }
    for fb in fee_bps_scenarios:
        out[f"net_{fb:g}bp"] = gross - fb / 1e4 * notional
    return out
