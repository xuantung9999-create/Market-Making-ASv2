"""SessionChart.frameIndex and SessionChart.check, run through node (no browser, no DOM)."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parent.parent / "dashboard" / "js" / "session_chart.js"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _node(expr: str, tz: str | None = None):
    code = f"const m = require({json.dumps(str(JS))}); console.log(JSON.stringify({expr}));"
    env = None
    if tz is not None:
        env = dict(os.environ, TZ=tz)
    out = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=30, env=env)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _model(n=6, kind="sim"):
    x = list(range(n))
    mid = [100.0 + i for i in x]
    return {
        "kind": kind, "xType": "linear", "x": x, "panels": ["price", "inventory", "pnl"],
        "mid": mid, "res": [m - 0.1 for m in mid],
        "band": {"bid": [m - 0.5 for m in mid], "ask": [m + 0.5 for m in mid]},
        "quotes": None, "fills": [], "inventory": [0] * n, "inventoryBench": [0] * n, "qMax": None,
        "pnl": [0.0] * n, "pnlPeak": [0.0] * n, "pnlAlt": None, "pnlBench": [0.0] * n,
        "tiles": {k: [0] * n for k in ("mid", "inventory", "pnl", "fills", "buys", "sells", "maxAbs", "spread")},
        "events": [],
    }


@pytest.mark.parametrize("n", [1, 2, 150, 201, 1500])
def test_frame_index_is_short_increasing_and_ends_at_the_last_point(n):
    idx = _node(f"m.frameIndex({n})")
    assert 1 <= len(idx) <= 200
    assert idx == sorted(set(idx))
    assert idx[-1] == n - 1
    if n >= 2:
        assert idx[0] >= 1


def test_check_accepts_a_valid_model():
    m = _model()
    assert _node(f"m.check({json.dumps(m)})") == []


def test_check_names_unequal_lengths():
    m = _model()
    m["inventory"] = m["inventory"][:-1]
    probs = _node(f"m.check({json.dumps(m)})")
    assert probs and any("inventory" in p for p in probs)


def test_check_flags_a_sim_point_where_bid_is_not_below_r():
    m = _model()
    m["band"]["bid"][3] = m["res"][3] + 0.2
    probs = _node(f"m.check({json.dumps(m)})")
    assert any("bid" in p for p in probs)
    # the same data is not a problem for a live model (rule D9)
    m["kind"] = "live"
    m["res"] = None
    assert not any("bid" in p and "res" in p for p in _node(f"m.check({json.dumps(m)})"))


def test_check_flags_non_increasing_x_and_more_than_three_events():
    m = _model()
    m["x"][2] = m["x"][1]
    assert any("x" in p for p in _node(f"m.check({json.dumps(m)})"))
    m = _model()
    m["events"] = [{"panel": "price", "x": 1, "y": 1, "text": "t"}] * 4
    assert any("event" in p for p in _node(f"m.check({json.dumps(m)})"))


# ---- plotX (docs/DASHBOARD_SESSION_CHART_UTC_SPEC.md task U1)

def test_plotx_gives_an_iso_utc_string_on_a_date_axis():
    assert _node('m.plotX("date", Date.UTC(2026, 10, 15, 0, 0))') == "2026-11-15T00:00:00.000Z"


def test_plotx_passes_numbers_through_on_a_linear_axis_and_nulls_bad_values():
    assert _node('m.plotX("linear", 0.42)') == 0.42
    assert _node('m.plotX("date", null)') is None
    assert _node('m.plotX("date", NaN)') is None


def test_plotx_does_not_depend_on_the_viewer_time_zone():
    expr = 'm.plotX("date", Date.UTC(2026, 10, 15, 7, 46))'
    bkk = _node(expr, tz="Asia/Bangkok")
    nyc = _node(expr, tz="America/New_York")
    assert bkk == nyc == "2026-11-15T07:46:00.000Z"
    # the subprocess really ran in two different zones
    assert _node("new Date(0).getTimezoneOffset()", tz="Asia/Bangkok") != _node("new Date(0).getTimezoneOffset()", tz="America/New_York")
