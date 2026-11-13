"""Dashboard redesign R2: the verdict bundle and the bundle diet (docs/DASHBOARD_REDESIGN.md section 5)."""
import json
from pathlib import Path

import pytest

from mm import report as rep

RUNS = Path(__file__).resolve().parent.parent / "dashboard" / "runs"
EXAMPLE = [10, -5, 20, 5, -10]


def day(sym, date, variant, pnl, fees=2.0, notional=1000.0, fills=100, **kw):
    return {"symbol": sym, "date": date, "variant": variant, "pnl": pnl, "fees": fees,
            "notional": notional, "fills": fills, **kw}


def dates(n):
    return [f"2026-11-{i + 1:02d}" for i in range(n)]


def example_days(sym="A", variant="q1.0", pnl=EXAMPLE, **kw):
    return [day(sym, d, variant, p, **kw) for d, p in zip(dates(len(pnl)), pnl)]


def row_of(rows, sym, variant):
    (r,) = [r for r in rows if r["symbol"] == sym and r["variant"] == variant]
    return r


# ----------------------------------------------------------------------------- forest_rows
def test_forest_matches_the_hand_calculation():
    r = row_of(rep.forest_rows(example_days()), "A", "q1.0")
    assert r["net_bp"] == pytest.approx(40.0)
    assert r["net_se"] == pytest.approx(53.385, abs=1e-2)
    assert r["gross_bp"] == pytest.approx(60.0)            # fees were 2 per 1,000 traded
    assert r["gross_se"] == pytest.approx(53.385, abs=1e-2)
    assert r["t"] == pytest.approx(0.7493, abs=1e-3)
    assert r["hit_rate"] == 0.6 and r["n_days"] == 5 and r["days_total"] == 5 and r["fills"] == 500
    assert r["queue_mult"] == 1.0


def test_queue_multiplier_is_read_from_the_variant_name():
    rows = rep.forest_rows(example_days(variant="q0.5") + example_days(variant="q2.0")
                           + example_days(variant="bridge q0 lat100"))
    assert row_of(rows, "A", "q0.5")["queue_mult"] == 0.5
    assert row_of(rows, "A", "q2.0")["queue_mult"] == 2.0
    assert row_of(rows, "A", "bridge q0 lat100")["queue_mult"] == 0.0


def test_an_explicit_queue_multiplier_wins_for_strategy_variants():
    r = row_of(rep.forest_rows(example_days(variant="agent"), queue_mult=2.0), "A", "agent")
    assert r["queue_mult"] == 2.0


def test_pooled_row_sums_symbols_per_date():
    b = [day("B", d, "q1.0", p) for d, p in zip(dates(5), [0, 5, -20, 5, 10])]
    pooled = row_of(rep.forest_rows(example_days() + b), "ALL", "q1.0")
    assert pooled["n_days"] == 5 and pooled["fills"] == 1000    # five dates, not ten coin-days
    assert pooled["net_bp"] == pytest.approx(20.0)             # per-date sums 10, 0, 0, 10, 0 over 10,000 traded
    assert pooled["hit_rate"] == pytest.approx(0.4)


def test_a_variant_with_no_fills_has_a_row_but_no_numbers():
    days = [day("A", d, "agent", 0.0, fees=0.0, notional=0.0, fills=0) for d in dates(3)]
    r = row_of(rep.forest_rows(days), "A", "agent")
    assert r["fills"] == 0 and r["n_days"] == 0 and r["days_total"] == 3
    assert "net_bp" not in r and "t" not in r and "net_se" not in r


def test_a_day_with_19_fills_is_not_counted_but_its_fills_are():
    days = example_days() + [day("A", "2026-11-09", "q1.0", -1000.0, fills=19)]
    r = row_of(rep.forest_rows(days), "A", "q1.0")
    assert r["n_days"] == 5 and r["days_total"] == 6 and r["fills"] == 519
    assert r["net_bp"] == pytest.approx(40.0)


def test_t_needs_five_counted_days_and_se_needs_two():
    four = row_of(rep.forest_rows(example_days(pnl=EXAMPLE[:4])), "A", "q1.0")
    assert "t" not in four and "net_se" in four
    one = row_of(rep.forest_rows(example_days(pnl=EXAMPLE[:1])), "A", "q1.0")
    assert "net_se" not in one and "net_bp" in one


# ----------------------------------------------------------------------------- compare_rows
def test_compare_rows_totals_drawdown_and_fill_weighted_markout():
    days = [day("A", d, "q1.0", p, fills=f, mk_60=m) for d, p, f, m in
            zip(dates(5), EXAMPLE, [100, 100, 100, 100, 300], [1.0, 1.0, 1.0, 1.0, 5.0])]
    r = row_of(rep.compare_rows(days), "A", "q1.0")
    assert r["pnl_total"] == 20 and r["fills"] == 700 and r["max_dd"] == -10
    assert r["mk_60"] == pytest.approx((400 * 1.0 + 300 * 5.0) / 700)


def test_compare_pnl_total_includes_days_below_the_fill_threshold():
    days = example_days() + [day("A", "2026-11-09", "q1.0", -50.0, fills=3)]
    assert row_of(rep.compare_rows(days), "A", "q1.0")["pnl_total"] == -30


# ----------------------------------------------------------------------------- thinning
def curve(dates_, per_day=288):
    t, pnl = [], []
    for di, d in enumerate(dates_):
        for k in range(per_day):
            t.append(f"{d}T{k * 5 // 60:02d}:{k * 5 % 60:02d}Z")
            pnl.append(float(di * 1000 + k))
    return {"t": t, "pnl": pnl, "q": [1.0] * len(t), "mid": [0.5] * len(t)}


def test_thin_curves_keeps_the_last_point_of_every_old_day_and_everything_in_the_last_three():
    ds = dates(10)
    out = rep.thin_curves({"A|q1.0": curve(ds)}, keep_days=3)["A|q1.0"]
    assert len(out["t"]) == 7 * 1 + 3 * 288
    assert out["t"][:7] == [f"{d}T23:55Z" for d in ds[:7]]
    assert out["t"][-1] == "2026-11-10T23:55Z" and out["pnl"][-1] == 9 * 1000 + 287
    assert all(len(out[k]) == len(out["t"]) for k in ("pnl", "q", "mid"))


def test_thin_curves_with_zero_keep_days_is_daily_only():
    out = rep.thin_curves({"A|q1.0": curve(dates(4))}, keep_days=0)["A|q1.0"]
    assert out["t"] == [f"{d}T23:55Z" for d in dates(4)]


def test_thin_curves_is_idempotent_and_does_not_touch_its_input():
    src = {"A|q1.0": curve(dates(6))}
    once = rep.thin_curves(src, keep_days=3)
    assert len(src["A|q1.0"]["t"]) == 6 * 288
    assert rep.thin_curves(once, keep_days=3) == once


def test_thin_agent_keeps_switches_and_the_last_row_of_each_symbol_day():
    rows = [{"symbol": "A", "ts": f"2026-11-01T{h:02d}:30Z", "live_arm": 1, "switched": h == 5, "scores": [0.0]}
            for h in range(24)] + [{"symbol": "A", "ts": f"2026-11-02T{h:02d}:30Z", "live_arm": 1,
                                    "switched": False, "scores": [0.0]} for h in range(24)]
    out = rep.thin_agent(rows)
    assert [r["ts"] for r in out] == ["2026-11-01T05:30Z", "2026-11-01T23:30Z", "2026-11-02T23:30Z"]


# ----------------------------------------------------------------------------- slim_bundle
def bundle_with_curves(variant="q1.0"):
    days = example_days(variant=variant)
    return rep.build_bundle("qb-test", "backtest", "test", {"q_max": 10, "lot_usd": 100.0}, days,
                            curves={f"A|{variant}": curve(dates(10))})


def test_slim_keeps_final_values_and_records_time_at_each_inventory_level_first():
    b = bundle_with_curves()
    before_last = b["curves"]["A|q1.0"]["pnl"][-1]
    for c in b["curves"].values():
        c["q"] = [float(i % 3 - 1) for i in range(len(c["q"]))]       # -1, 0, 1 cycling
    out = rep.slim_bundle(b)
    assert out["curves"]["A|q1.0"]["pnl"][-1] == before_last
    h = out["q_hist"]["A|q1.0"]
    assert h["levels"] == [-1, 0, 1] and sum(h["share"]) == pytest.approx(1.0)
    assert h["share"][0] == pytest.approx(1 / 3, abs=1e-3)
    assert rep.validate_bundle(out) == []


def test_slim_is_idempotent():
    once = rep.slim_bundle(bundle_with_curves())
    assert rep.slim_bundle(once) == once


# ----------------------------------------------------------------------------- verdict_bundle
def qb_bundle(net_per_day=-1.82):
    days = []
    for var, k in (("q0.5", 0.9), ("q1.0", 1.0), ("q2.0", 1.1), ("bridge q0 lat100", 0.6)):
        for sym in ("A", "B"):
            for i, d in enumerate(dates(10)):
                days.append(day(sym, d, var, net_per_day * k + (0.3 if i % 2 else -0.3), fees=1.0))
    curves = {f"{s}|{v}": curve(dates(10), per_day=4) for s in ("A", "B")
              for v in ("q0.5", "q1.0", "q2.0", "bridge q0 lat100")}
    return rep.build_bundle("qb-test", "backtest", "Queue baseline", {"q_max": 10, "lot_usd": 100.0, "queue_mult": 1.0},
                            days, curves=curves, built_utc="2026-11-12 11:50")


def wf_bundle(queue_mult, fills=0):
    days = [day(s, d, "agent", 0.0, fees=0.0, notional=0.0, fills=fills) for s in ("A", "B") for d in dates(10)]
    days += [day(s, d, "join_touch", -2.0) for s in ("A", "B") for d in dates(10)]
    cfg = {"q_max": 10, "lot_usd": 100.0, "queue_mult": queue_mult}
    gates = {"A": {"conditions": [{"id": "A1", "text": "x", "value": None, "pass": False},
                                  {"id": "A2", "text": "y", "value": 0, "pass": False}], "pass": False}}
    curves = {f"{s}|{v}": curve(dates(10), per_day=4) for s in ("A", "B") for v in ("agent", "join_touch")}
    return rep.build_bundle(f"wf-test-q{queue_mult:g}", "walkforward", f"wf q{queue_mult}", cfg, days,
                            curves=curves, gates=gates, built_utc="2026-11-12 12:31")


def make_verdict():
    return rep.verdict_bundle([qb_bundle(), wf_bundle(0.5), wf_bundle(1.0), wf_bundle(2.0)])


def test_verdict_bundle_is_valid_and_has_its_sections():
    v = make_verdict()
    assert rep.validate_bundle(v) == []
    assert v["run_id"] == "pub-verdict" and v["kind"] == "walkforward"
    for k in ("forest", "compare", "curves", "gross_curves", "gates", "takeaways"):
        assert k in v, k
    assert "headline" in v["takeaways"]


def test_forest_has_join_touch_at_every_queue_and_the_agent_only_at_the_headline_queue():
    f = make_verdict()["forest"]
    jt = [r for r in f if r["symbol"] == "ALL" and r["variant"] == "join_touch"]
    assert sorted(r["queue_mult"] for r in jt) == [0.0, 0.5, 1.0, 2.0]
    assert all(r["scenario"] for r in jt)
    ag = [r for r in f if r["symbol"] == "ALL" and r["variant"] == "agent"]
    assert [r["queue_mult"] for r in ag] == [1.0] and ag[0]["fills"] == 0 and "net_bp" not in ag[0]


def test_curves_are_pooled_and_daily_and_the_agent_comes_from_the_headline_run_only():
    v = make_verdict()
    assert sorted(v["curves"]) == ["ALL|agent", "ALL|bridge q0 lat100", "ALL|q0.5", "ALL|q1.0", "ALL|q2.0"]
    assert all(len(c["t"]) == 10 for c in v["curves"].values())
    assert sorted(v["gross_curves"]) == sorted(v["curves"])


def test_gross_curve_sits_above_net_by_cumulative_fees():
    v = make_verdict()
    net, gross = v["curves"]["ALL|q1.0"], v["gross_curves"]["ALL|q1.0"]
    assert gross["t"] == net["t"]
    # two coins pay 1.0 of fees per day each: 2.0 per date, accumulating
    assert [g - n for g, n in zip(gross["pnl"], net["pnl"])] == pytest.approx([2.0 * (i + 1) for i in range(10)])


def test_gates_come_from_the_headline_walkforward_run():
    assert make_verdict()["gates"]["A"]["conditions"][0]["id"] == "A1"


def test_takeaway_headline_states_the_numbers_it_was_built_from():
    v = make_verdict()
    (r,) = [r for r in v["forest"] if r["symbol"] == "ALL" and r["variant"] == "join_touch" and r["queue_mult"] == 1.0]
    h = v["takeaways"]["headline"]
    assert f"lost {abs(r['net_bp']):.1f} bp per dollar traded after fees" in h
    assert f"t = {r['t']:.1f}" in h and "10 days" in h and "2 coins" in h
    assert "made no fills in 10 days" in h


def test_takeaway_headline_switches_wording_when_the_agent_does_trade():
    v = rep.verdict_bundle([qb_bundle(), wf_bundle(1.0, fills=50)])
    assert "made no fills" not in v["takeaways"]["headline"]


def test_every_chart_takeaway_is_rebuilt_from_the_bundle_not_stored_text():
    a, b = make_verdict(), rep.verdict_bundle([qb_bundle(net_per_day=+1.0), wf_bundle(1.0)])
    assert a["takeaways"] != b["takeaways"]
    assert "made" in b["takeaways"]["headline"]


# ----------------------------------------------------------------------------- the committed runs
def _load(path):
    s = path.read_text(encoding="utf-8")
    return json.loads(s[s.index("= {") + 2: s.rstrip().rstrip(";").rindex("}") + 1])


def test_every_committed_run_file_is_under_3_mb():
    files = sorted(RUNS.glob("*.js"))
    assert files
    big = [(p.name, p.stat().st_size) for p in files if p.stat().st_size > 3_000_000]
    assert big == []


def test_the_committed_verdict_file_is_small_and_valid_and_says_what_the_readme_says():
    p = RUNS / "pub-verdict.js"
    assert p.exists() and p.stat().st_size < 300_000
    v = _load(p)
    assert rep.validate_bundle(v) == []
    q1 = [r for r in v["forest"] if r["symbol"] == "ALL" and r["variant"] == "join_touch" and r["queue_mult"] == 1.0][0]
    assert q1["net_bp"] == pytest.approx(-18.24, abs=0.01) and q1["gross_bp"] == pytest.approx(-8.24, abs=0.01)
    assert q1["n_days"] == 60
