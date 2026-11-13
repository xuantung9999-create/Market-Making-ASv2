"""v2 Task 11: daily supervisor."""
import json

import numpy as np
import pandas as pd
import pytest

from scripts.daily_supervisor import gate_b, supervise, update_coin_state, z_score
from tests.test_paper import DAY0, S, cfgs, scripted, trained


def test_coin_state_rules():
    st = {}
    st = update_coin_state(st, -2.5)
    assert st["size_mult"] == 0.5 and st["enabled"] is True
    st = update_coin_state(st, -3.0)
    assert st["enabled"] is False                      # two bad days in a row
    st = update_coin_state(st, 0.1)
    st = update_coin_state(st, 0.2)
    assert st["enabled"] is False and st["size_mult"] == 0.5
    st = update_coin_state(st, -1.0)                   # still normal (z >= -2)
    assert st["enabled"] is True and st["size_mult"] == 1.0
    assert update_coin_state(st, float("nan")) == st   # a day with no fills tells us nothing


def test_z_score():
    f = pd.DataFrame({"net_edge_bp": [1.0, 3.0, 5.0, np.nan], "pred_edge_bp": [4.0, 4.0, 4.0, 4.0]})
    z = z_score(f)
    assert z == pytest.approx((3.0 - 4.0) / (2.0 / np.sqrt(3)))
    assert np.isnan(z_score(f.head(1)))
    assert np.isnan(z_score(pd.DataFrame(columns=["net_edge_bp", "pred_edge_bp"])))


def test_gate_b_numbers_only_after_14_days():
    rows = [{"symbol": "A", "date": f"d{i}", "pnl": 1.0 + i % 3, "fills": 30, "match": True} for i in range(13)]
    assert gate_b(rows) is None
    rows.append({"symbol": "A", "date": "d13", "pnl": -1.0, "fills": 30, "match": False})
    g = gate_b(rows)
    ids = [c["id"] for c in g["conditions"]]
    assert ids == ["B1", "B2", "B3", "B4"]
    assert g["conditions"][3]["value"] == pytest.approx(13 / 14)


def test_supervisor_replays_paper_day_exactly(tmp_path):
    from mm.paper import PaperSession
    acfg, qcfg = cfgs()
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "ANKRUSDT_table.json").write_text(json.dumps(trained().to_dict()))
    ps = PaperSession(["ANKRUSDT"], tmp_path / "state", tmp_path / "paper", acfg, qcfg, ticks={"ANKRUSDT": 1e-5})
    msgs = scripted(seed=2, n=1200, start=DAY0 + 22 * 3600 * S) + scripted(seed=3, n=200, start=DAY0 + 86_400 * S + 5 * S)
    for raw, t in msgs:
        ps.handle(raw, t)
    ps.checkpoint()
    rows = supervise(tmp_path / "paper", tmp_path / "state", tmp_path / "results", agent_cfg=acfg, write_bundle=False)
    assert len(rows) == 1 and rows[0]["match"] is True and rows[0]["fills"] > 0
    cs = json.loads((tmp_path / "paper" / "coin_state.json").read_text())
    assert "ANKRUSDT" in cs
    assert list((tmp_path / "results").glob("paper_report_*.md"))
    assert supervise(tmp_path / "paper", tmp_path / "state", tmp_path / "results", agent_cfg=acfg, write_bundle=False) == []
