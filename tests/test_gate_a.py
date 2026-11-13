"""v2 Task 8: Gate A arithmetic on a synthetic results table."""
import pandas as pd

from scripts.run_agent_walkforward import gate_a


def rows(variant, queue, sym, nets, fills=50, counted=True):
    return [dict(variant=variant, queue=queue, symbol=sym, day=f"d{i}", net_10bp=x, fills=fills, counted=counted)
            for i, x in enumerate(nets)]


def test_gate_passes_on_clear_edge():
    nets = [5.0, 6.0, 4.0, 5.5, 4.5, 6.5, 5.0, 4.0]
    r = []
    for s in ("A", "B", "C"):
        r += rows("agent", "headline", s, nets) + rows("agent", "stress", s, [1.0] * 8)
        r += rows("join_touch", "headline", s, [-1.0] * 8)
    g = gate_a(pd.DataFrame(r))
    assert g["pass"] is True and g["coin_days"] == 24


def test_gate_filters_and_each_check():
    r = rows("agent", "headline", "A", [5.0] * 8) + rows("agent", "headline", "B", [5.0] * 8)
    r += rows("agent", "headline", "C", [100.0] * 3, fills=5)          # < 20 fills: ignored
    r += rows("agent", "headline", "D", [100.0] * 3, counted=False)    # warm-up: ignored
    r += rows("agent", "stress", "A", [-1.0] * 8)
    r += rows("join_touch", "headline", "A", [50.0] * 8)
    g = gate_a(pd.DataFrame(r))
    c = g["checks"]
    assert g["coin_days"] == 16
    assert c["2_three_symbols_positive"]["pass"] is False             # only A and B
    assert c["4_stress_queue_mean_pos"]["pass"] is False
    assert c["5_agent_beats_join_touch"]["pass"] is False             # 80 < 400
    assert g["pass"] is False


def test_gate_with_no_counted_days():
    g = gate_a(pd.DataFrame(rows("agent", "headline", "A", [1.0], counted=False)))
    assert g["pass"] is False and g["coin_days"] == 0


def test_gate_has_scoreboard_conditions():
    g = gate_a(pd.DataFrame(rows("agent", "headline", "A", [1.0] * 6)))
    conds = g["conditions"]
    assert [c["id"] for c in conds] == ["A1", "A2", "A3", "A4", "A5"]
    assert all(set(c) == {"id", "text", "value", "pass"} for c in conds)
