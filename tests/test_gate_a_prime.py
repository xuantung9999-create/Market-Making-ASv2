"""v2.1 Task 16: Gate A' = Gate A's five checks at 10 / 7.5 / 0 bp on >= 21 counted days per coin."""
import pandas as pd

from scripts.run_agent_walkforward import gate_a, gate_a_prime


def block(variant, queue, sym, nets, fee_shift=0.0, fills=50, counted=True):
    """One result row per day with the net P&L at each fee tier (each tier is 1 USD lower per day)."""
    out = []
    for i, x in enumerate(nets):
        out.append(dict(variant=variant, queue=queue, symbol=sym, day=f"d{i:02d}", fills=fills, counted=counted,
                        net_0bp=x + 2 * fee_shift, **{"net_7.5bp": x + fee_shift}, net_10bp=x))
    return out


def frame(agent_nets, days=21, stress=1.0, jt=-1.0):
    r = []
    for s in ("A", "B", "C"):
        nets = agent_nets[:days] if isinstance(agent_nets, list) else [agent_nets] * days
        r += block("agent", "headline", s, nets, fee_shift=1.0) + block("agent", "stress", s, [stress] * days, fee_shift=1.0)
        r += block("join_touch", "headline", s, [jt] * days, fee_shift=1.0)
    return pd.DataFrame(r)


def test_not_evaluated_until_every_coin_has_21_counted_days():
    g = gate_a_prime(frame(5.0, days=20))
    assert g["status"].startswith("not evaluated") and g["tiers"] == {} and g["min_days"] == 21
    assert gate_a_prime(frame(5.0, days=21))["status"] != g["status"]


def test_clear_edge_passes_at_all_three_tiers():
    g = gate_a_prime(frame([5.0, 6.0, 4.0] * 7))
    assert set(g["tiers"]) == {"10", "7.5", "0"}
    assert all(t["pass"] for t in g["tiers"].values()) and g["status"] == "pass"


def test_pass_at_zero_bp_only_is_edge_before_fees():
    # the agent loses money at 10 bp and 7.5 bp but earns before fees; join touch is worse everywhere
    g = gate_a_prime(frame([-1.2, -1.1, -1.3] * 7, jt=-3.0))
    t = g["tiers"]
    assert not t["10"]["pass"] and t["0"]["pass"] is True
    assert g["status"] == "edge before fees, not tradable at the base tier"


def test_ten_bp_tier_matches_gate_a():
    df = frame([5.0, 6.0, 4.0] * 7)
    assert gate_a_prime(df)["tiers"]["10"]["checks"] == gate_a(df)["checks"]


def test_book_state_walkforward_smoke_on_synthetic_days(tmp_path):
    """run_symbol(book_state=True) runs end to end: regime feed from the previous days, 4-wide table keys."""
    import numpy as np
    from scripts.run_agent_walkforward import run_symbol

    rng = np.random.default_rng(0)
    base = 1_700_000_000_000_000
    for d in range(5):
        n = 6000
        t = base + d * 86_400_000_000 + np.cumsum(rng.integers(20_000, 300_000, n))
        px = np.round(100 + np.cumsum(rng.choice([-0.01, 0.0, 0.01], n)), 2)
        pd.DataFrame({"ts_us": t, "price": px, "qty": rng.uniform(1, 30, n), "side": rng.choice([-1, 1], n)}) \
            .to_parquet(tmp_path / f"TESTUSDT_2024-01-{d + 1:02d}_trades.parquet", index=False)
    kept = []
    rows, agent = run_symbol("TESTUSDT", "headline", 1.0, warmup_days=2, data_dir=str(tmp_path), keep=kept, book_state=True)
    assert agent is not None and {r["variant"] for r in rows} == {"agent", "join_touch"}
    assert all(len(k) == 4 for k in agent.table._cells)
    assert agent.p_toxic_fn is not None                         # day 5 had >= 3 previous days
