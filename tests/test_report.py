"""Tests for mm/report.py: the run-bundle builder behind the trading dashboard."""
import json
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from mm.report import (build_bundle, curve, day_row, demo_bundle, hourly, markout_rows,
                       stress_rows, summary_rows, validate_bundle, write_bundle)

CFG = {"maker_fee_bps": 10.0, "latency_ms": 300, "queue_mult": 1.0, "lot_usd": 100.0,
       "q_max": 10, "decision_ms": 500}


def _days(pnls, fills=25, symbol="ANKRUSDT", variant="agent", notional=1000.0):
    return [{"symbol": symbol, "date": f"2026-11-{i + 1:02d}", "variant": variant, "pnl": float(p),
             "fills": fills, "notional": notional} for i, p in enumerate(pnls)]


def _row(rows, symbol="ANKRUSDT", variant="agent"):
    return next(r for r in rows if r["symbol"] == symbol and r["variant"] == variant)


# ----------------------------------------------------------------------------- summary_rows
def test_summary_rows_reference_numbers():
    r = _row(summary_rows(_days([10, -5, 20, 5, -10]), q_max=10, lot_usd=100))
    assert r["days"] == 5
    assert r["pnl_total"] == 20
    assert r["pnl_mean_day"] == 4
    assert r["pnl_std_day"] == pytest.approx(11.9373, abs=1e-3)
    assert r["t_stat"] == pytest.approx(0.7493, abs=1e-3)
    assert r["hit_rate"] == 0.6
    assert r["profit_factor"] == pytest.approx(35 / 15)
    assert r["max_dd"] == -10
    assert r["net_bp_per_usd"] == pytest.approx(40.0)
    assert r["turnover_day"] == 1.0
    assert "var95_day" not in r and "es95_day" not in r


def test_sharpe_and_its_standard_error():
    r = _row(summary_rows(_days([10, -5, 20, 5, -10]), q_max=10, lot_usd=100))
    s = 4 / np.std([10, -5, 20, 5, -10], ddof=1)
    assert r["sharpe_ann"] == pytest.approx(s * math.sqrt(365))
    assert r["sharpe_se"] == pytest.approx(math.sqrt((1 + 0.5 * s * s) / 5) * math.sqrt(365))


def test_thin_day_excluded_from_stats_but_counts_in_total():
    days = _days([10, -5, 20, 5, -10]) + [{"symbol": "ANKRUSDT", "date": "2026-11-06", "variant": "agent",
                                           "pnl": 100.0, "fills": 19, "notional": 1000.0}]
    r = _row(summary_rows(days, q_max=10, lot_usd=100))
    assert r["days"] == 5
    assert r["pnl_total"] == 120
    assert r["pnl_mean_day"] == 4


def test_four_days_has_no_t_stat_or_sharpe():
    r = _row(summary_rows(_days([1, 2, -1, 3]), q_max=10, lot_usd=100))
    for k in ("t_stat", "sharpe_ann", "sharpe_se"):
        assert k not in r
    assert r["days"] == 4


def test_no_losing_days_has_no_profit_factor():
    r = _row(summary_rows(_days([1, 2, 3, 4, 5]), q_max=10, lot_usd=100))
    assert "profit_factor" not in r


def test_var_and_es_with_twenty_days():
    pnls = list(range(-10, 10))        # 20 days
    r = _row(summary_rows(_days(pnls), q_max=10, lot_usd=100))
    v = np.percentile(pnls, 5)
    assert r["var95_day"] == pytest.approx(v)
    assert r["es95_day"] == pytest.approx(np.mean([p for p in pnls if p <= v]))


def test_pooled_row_per_variant():
    days = _days([1, 2, 3, 4, 5]) + _days([-1, -2, -3, -4, -5], symbol="SKLUSDT") \
        + _days([5, 5, 5, 5, -1], variant="join")
    rows = summary_rows(days, q_max=10, lot_usd=100)
    pooled = [r for r in rows if r["symbol"] == "ALL"]
    assert sorted(r["variant"] for r in pooled) == ["agent", "join"]
    a = _row(rows, "ALL", "agent")
    assert a["pnl_total"] == 0                     # 15 + (-15)
    assert a["days"] == 5                          # dates, not symbol-days
    assert rows[0]["symbol"] == "ALL"              # pooled rows come first


# ----------------------------------------------------------------------------- stress_rows
def test_stress_rows():
    days = _days([1, 2, 3])
    for d, q in zip(days, (3, 7, 5)):
        d["q_abs_max"] = q
    rows = stress_rows(days, q_max=10, lot_usd=100)
    r10 = next(r for r in rows if r["shock_pct"] == 10)
    assert r10["loss_at_cap_usd"] == 100
    assert r10["loss_at_max_seen_usd"] == pytest.approx(70)
    assert sorted(r["shock_pct"] for r in rows) == [5, 10, 20]


# ----------------------------------------------------------------------------- from results
def _fake_result():
    t = np.arange(1, 121) * 60.0                    # two hours of minute rows
    pnl = np.cumsum(np.full(120, 0.01))
    minute = pd.DataFrame({"t_s": t, "mid": 100 + 0 * t, "pnl": pnl, "q": np.r_[np.zeros(60), np.full(60, 2)],
                           "spread_capture": pnl * 2, "inventory_pnl": -pnl * 0.5, "fees": pnl * 0.5})
    fills = pd.DataFrame({"bar": np.arange(30), "side": np.tile([1, -1], 15), "price": np.full(30, 100.0),
                          "t_s": np.linspace(10, 7000, 30)})
    mk = pd.DataFrame({"h_s": [0, 1, 10, 60, 300], "markout_bp": [5, 4, 3, 2, 1], "se_bp": [.5] * 5})
    totals = {"pnl": 1.2, "spread_capture": 2.4, "inventory_pnl": -0.6, "fees": 0.6, "final_q": 2, "notional": 3000.0}
    return SimpleNamespace(minute=minute, fills=fills, totals=totals, markouts=mk,
                           cfg=SimpleNamespace(maker_fee_bps=10.0))


def test_day_row_from_result():
    d = day_row(_fake_result(), "ANKRUSDT", "2026-11-10", "join", extra={"live_arm": 3})
    assert d["pnl"] == 1.2 and d["fills"] == 30 and d["buy_fills"] == 15
    assert d["mk_60"] == 2 and d["mk_300"] == 1
    assert d["net_edge_bp"] == pytest.approx(2 - 10.0)
    assert d["q_abs_max"] == 2 and d["live_arm"] == 3
    assert "wait_s_med" not in d                     # no wait_s column: left out, not 0
    assert "uptime" not in d


def test_curve_hourly_and_markouts():
    r = _fake_result()
    c = curve([r, r], every_min=5, dates=["2026-11-09", "2026-11-10"])
    assert len(c["t"]) == len(c["pnl"]) == len(c["q"]) == len(c["mid"]) == 48
    assert c["pnl"][-1] == pytest.approx(2 * 1.2)   # cumulative across days
    assert c["t"][0].startswith("2026-11-09T00:05")
    h = hourly([r], dates=["2026-11-10"])
    assert len(h["pnl"]) == 24 and sum(h["fills"]) == 30
    assert h["pnl"][0] == pytest.approx(0.6) and h["pnl"][1] == pytest.approx(0.6)
    rows = markout_rows(r, "ANKRUSDT", "join")
    assert [x["h_s"] for x in rows] == [1, 10, 60, 300] and rows[0]["n"] == 30


# ----------------------------------------------------------------------------- validate_bundle
def _demo():
    return demo_bundle(seed=1)


def test_demo_bundle_is_valid_and_complete():
    b = _demo()
    assert validate_bundle(b) == []
    assert b["kind"] == "demo"
    assert len({d["symbol"] for d in b["days"]}) == 3
    assert len({d["date"] for d in b["days"]}) == 30
    for s in ("curves", "hourly", "markouts", "edge", "calib", "agent", "wait_hist",
              "stress", "screen", "gates", "health", "summary"):
        assert b.get(s), s


@pytest.mark.parametrize("mutate,needle", [
    (lambda b: b.pop("kind"), "kind"),
    (lambda b: b.__setitem__("kind", "foo"), "kind"),
    (lambda b: b["days"][0].pop("symbol"), "symbol"),
    (lambda b: next(iter(b["curves"].values()))["pnl"].pop(), "length"),
    (lambda b: b["days"][3].__setitem__("pnl", float("nan")), "finite"),
    (lambda b: b["summary"][0].__setitem__("pnl_total", float("inf")), "finite"),
])
def test_validate_reports_exactly_one_problem(mutate, needle):
    b = _demo()
    mutate(b)
    msgs = validate_bundle(b)
    assert len(msgs) == 1, msgs
    assert needle in msgs[0]


def test_validate_rejects_absolute_paths():
    b = _demo()
    b["label"] = r"C:\Users\someone\run"
    assert len(validate_bundle(b)) == 1


# ----------------------------------------------------------------------------- write_bundle
def _parse_run_js(text):
    prefix = "window.RUNS = window.RUNS || {};"
    assert text.startswith(prefix)
    body = text[len(prefix):].strip()
    head = body[:body.index("=") + 1]
    assert head.startswith("window.RUNS[")
    return json.loads(body[len(head):].strip().rstrip(";"))


def _parse_index(text):
    prefix = "window.RUN_INDEX ="
    assert text.startswith(prefix)
    return json.loads(text[len(prefix):].strip().rstrip(";"))


def test_write_bundle_round_trip_and_index(tmp_path):
    a = build_bundle("bt-a", "backtest", "A", CFG, _days([1, 2, 3, 4, 5]), built_utc="2026-11-10 08:00")
    b = build_bundle("bt-b", "backtest", "B", CFG, _days([1, 2, 3, 4, 5]), built_utc="2026-11-11 08:00")
    p = write_bundle(a, tmp_path)
    assert _parse_run_js(p.read_text(encoding="utf-8"))["run_id"] == "bt-a"
    write_bundle(b, tmp_path)
    idx = _parse_index((tmp_path / "index.js").read_text(encoding="utf-8"))
    assert [r["run_id"] for r in idx] == ["bt-b", "bt-a"]
    assert idx[0]["n_days"] == 5 and idx[0]["symbols"] == ["ANKRUSDT"]
    a2 = build_bundle("bt-a", "backtest", "A again", CFG, _days([1, 2]), built_utc="2026-11-12 08:00")
    write_bundle(a2, tmp_path)
    idx = _parse_index((tmp_path / "index.js").read_text(encoding="utf-8"))
    assert [r["run_id"] for r in idx] == ["bt-a", "bt-b"]
    assert idx[0]["label"] == "A again"


def test_write_invalid_bundle_raises_and_writes_nothing(tmp_path):
    b = build_bundle("bt-x", "backtest", "X", CFG, _days([1, 2, 3]))
    b["kind"] = "foo"
    with pytest.raises(ValueError):
        write_bundle(b, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_build_bundle_fills_summary_and_header():
    b = build_bundle("bt-a", "backtest", "A", CFG, _days([1, 2, 3, 4, 5]))
    assert b["schema"] == 1 and b["summary"] and validate_bundle(b) == []
    assert len(b["built_utc"]) == 16


def test_blotter_columns_are_fill_weighted():
    days = _days([1, 2, 3])
    days[0].update(fills=30, net_edge_bp=2.0, mk_60=12.0)
    days[1].update(fills=10, net_edge_bp=-2.0, mk_60=8.0)
    r = _row(summary_rows(days, q_max=10, lot_usd=100))
    assert r["fills_day"] == pytest.approx((30 + 10 + 25) / 3)
    assert r["net_edge_bp"] == pytest.approx((30 * 2 - 10 * 2) / 40)
    assert r["mk_60"] == pytest.approx((30 * 12 + 10 * 8) / 40)


def test_pooled_curve_sums_symbols_with_carry_forward():
    curves = {"A|agent": {"t": ["t1", "t2", "t3"], "pnl": [1, 2, 3], "q": [1, 1, 1], "mid": [1, 1, 1]},
              "B|agent": {"t": ["t2", "t3"], "pnl": [10, 20], "q": [-1, 0], "mid": [5, 5]}}
    b = build_bundle("bt-c", "backtest", "C", CFG, _days([1]), curves=curves)
    allc = b["curves"]["ALL|agent"]
    assert allc["t"] == ["t1", "t2", "t3"] and allc["pnl"] == [1, 12, 23] and allc["q"] == [1, 0, 1]
    assert validate_bundle(b) == []
