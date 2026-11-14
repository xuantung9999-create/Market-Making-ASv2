"""Task L4: scripts/build_session.py builds bundles, the session list and tape files, under dashboard/live only."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts import build_session as bs

S = 1_000_000
T0 = 1_794_600_000 * S
BUNDLE_KEYS = {"meta", "headline", "now", "curve", "markers", "states", "uptime", "attribution", "fills", "markout",
               "funnel", "incidents", "model", "takeaways"}


def write_jsonl(p: Path, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))


def make_base(tmp_path, glitch=True):
    base = tmp_path
    (base / "config").mkdir()
    (base / "config" / "live.json").write_text(json.dumps({
        "testnet": [{"name": "testnet-join", "symbols": ["BTCUSDT"], "policy": "join", "lot_usd": 100, "q_max": 10, "max_loss": 20}],
        "paper": {"name": "paper", "symbols": ["ANKRUSDT"]}}))
    n = 3600
    rng = np.random.default_rng(1)
    t = T0 + np.arange(n) * S
    mid = 67_500 + np.cumsum(rng.integers(-1, 2, n)) * 0.01
    bid, ask = mid - 0.01, mid + 0.01
    if glitch:                                              # a book glitch: bid and ask collapse for 4 s
        bid[1000:1004], ask[1000:1004] = 55_000.0, 57_882.59
    feed = base / "data/testnet/feed/BTCUSDT"
    (feed / "book").mkdir(parents=True)
    (feed / "trades").mkdir(parents=True)
    pd.DataFrame({"recv_us": t, "update_id": np.arange(n), "bid": bid, "bid_qty": 1.0, "ask": ask, "ask_qty": 1.0}
                 ).to_parquet(feed / "book" / f"BTCUSDT_book_{T0 // 1000}.parquet")
    pd.DataFrame({"recv_us": t[::5], "ts_us": t[::5], "price": mid[::5], "qty": 0.01, "side": 1}
                 ).to_parquet(feed / "trades" / f"BTCUSDT_trades_{T0 // 1000}.parquet")
    d = base / "data/testnet/BTCUSDT"
    fills = []
    for k, s in enumerate(range(100, 3000, 60)):
        sd = 1 if k % 3 else -1
        m = float(mid[s])
        fills.append({"ts_us": T0 + s * S + 300_000, "side": sd, "price": m - sd * 0.01, "qty": 0.0015,
                      "order_id": 100 + k, "mid": m, "pos": 0.0, "pnl": 0.0, "how": "filled"})
    if glitch:
        fills.append({"ts_us": T0 + 1002 * S, "side": -1, "price": 57_882.59, "qty": 0.00177, "order_id": 999,
                      "mid": 56_000.0, "pos": 0.0, "pnl": 0.0, "how": "filled"})
    write_jsonl(d / "fills_2026-11-14.jsonl", fills)
    orders = [{"ts_us": f["ts_us"] - 5 * S, "op": "place", "side": f["side"], "price": str(f["price"]), "qty": "0.0015",
               "order_id": f["order_id"], "action": "JOIN", "pred_bp": 1.0} for f in fills]
    orders += [{"ts_us": T0 + 500 * S, "op": "reject", "side": 1, "price": "1", "error": "HTTP 400 code -2010: Order would immediately match"},
               {"ts_us": T0 + 2000 * S, "op": "loss-stop", "pnl": -20.5}]
    write_jsonl(d / "orders_2026-11-14.jsonl", orders)
    write_jsonl(d / "state_2026-11-14.jsonl", [
        {"ts_us": T0 + k * 60 * S, "side": sd, "state": "QUOTING", "detail": None} for k in range(0, 50) for sd in (1, -1)])
    write_jsonl(d / "session.jsonl", [{"ts_us": T0, "op": "start", "pid": 1, "args": {}, "pos_at_start": 0.0}])
    (d / "status.json").write_text(json.dumps({"symbol": "BTCUSDT", "pos": -0.001, "lots": -1, "pnl": 0.0, "stopped": False,
                                               "open": {"bid": 67_500.0, "ask": None}, "policy": "join"}))
    return base


def load_bundle(base, sid):
    txt = (base / "dashboard/live" / f"session-{sid}.js").read_text()
    return json.loads(txt[txt.index('"] = ') + 5: txt.rindex(";")])


def test_bundle_has_every_key_and_no_nan(tmp_path):
    base = make_base(tmp_path)
    sessions = bs.build(base, now_us=T0 + 3600 * S)
    ids = [s["id"] for s in sessions]
    assert ids == ["testnet-BTCUSDT-join", "paper-ANKRUSDT-agent"]
    b = load_bundle(base, "testnet-BTCUSDT-join")
    assert BUNDLE_KEYS <= set(b)
    for k in ("id", "source", "symbol", "policy", "lot_usd", "q_max", "max_loss", "fee_bps", "built_ms", "thresholds"):
        assert k in b["meta"]
    for k in ("state", "lots", "pos_usd", "open", "last_fill_ms", "process"):
        assert k in b["now"]
    assert set(b["curve"]) == {"t", "pnl", "pnl_ex_artifact", "lots"}
    assert set(b["attribution"]["total"]) >= {"edge", "adverse", "carry", "fees", "artifact", "net"}
    assert {"placed", "cancelled", "rejected", "filled", "partial", "by_hour", "reject_reasons"} <= set(b["funnel"])
    assert {"arm_strip", "arms", "history", "calibration"} <= set(b["model"])
    text = (base / "dashboard/live/session-testnet-BTCUSDT-join.js").read_text()
    assert "NaN" not in text and "Infinity" not in text
    assert all(isinstance(v, str) and v for v in b["takeaways"].values()) and b["headline"]
    e = load_bundle(base, "paper-ANKRUSDT-agent")                 # empty session: still a full bundle, with sentences
    assert BUNDLE_KEYS <= set(e) and "no fills" in e["headline"].lower()


def test_glitch_fill_is_an_artifact_and_net_is_the_sum_of_five_terms(tmp_path):
    base = make_base(tmp_path)
    bs.build(base, now_us=T0 + 3600 * S)
    b = load_bundle(base, "testnet-BTCUSDT-join")
    a = b["attribution"]["total"]
    assert abs(sum(a[k] for k in ("edge", "adverse", "carry", "fees", "artifact")) - a["net"]) < 1e-6
    arts = [f for f in b["fills"] if f["artifact"]]
    # the glitch fill, plus the ordinary fill that happens to land inside the glitch window (its price is far from that mid)
    assert any(f["price"] == pytest.approx(57_882.59) for f in arts) and len(arts) == 2
    kinds = [i["kind"] for i in b["incidents"]]
    assert "artifact_fill" in kinds and "loss_stop" in kinds and "reject_burst" not in kinds
    assert any(m["kind"] == "loss_stop" for m in b["markers"])
    assert b["attribution"]["by_day"][0]["loss_stop"] is True


def test_state_log_feeds_uptime_and_now(tmp_path):
    base = make_base(tmp_path)
    bs.build(base, now_us=T0 + 3000 * S)
    b = load_bundle(base, "testnet-BTCUSDT-join")
    up = {(u["side"], u["state"]): u["share"] for u in b["uptime"]}
    assert up[("bid", "QUOTING")] == pytest.approx(1.0) and up[("ask", "QUOTING")] == pytest.approx(1.0)
    assert b["states"]["bid"][0]["state"] == "QUOTING"
    assert b["now"]["state"]["bid"]["state"] == "QUOTING"        # inferred from the resting bid: quoting
    assert b["now"]["state"]["ask"]["state"] in ("UNKNOWN", "INV_CAP", "QUOTING")


def test_sizes_are_under_the_limits_and_files_are_inside_dashboard_live(tmp_path):
    base = make_base(tmp_path)
    before = {p for p in base.rglob("*") if p.is_file() and "dashboard" not in p.parts}
    bs.build(base, now_us=T0 + 3600 * S)
    after = {p for p in base.rglob("*") if p.is_file() and "dashboard" not in p.parts}
    assert before == after                                        # nothing written outside dashboard/live
    files = list((base / "dashboard/live").glob("*.js"))
    assert files and all(f.stat().st_size < bs.MAX_BYTES for f in files)
    assert any(f.name.startswith("tape-testnet-BTCUSDT-join-2026-11-14") or f.name.startswith("tape-testnet-BTCUSDT-join-")
               for f in files)


def test_tape_has_touch_trades_orders_around_the_glitch_fill(tmp_path):
    base = make_base(tmp_path)
    bs.build(base, now_us=T0 + 3600 * S)
    tapes = list((base / "dashboard/live").glob("tape-*.js"))
    txt = tapes[0].read_text()
    t = json.loads(txt[txt.index('"] = ') + 5: txt.rindex(";")])
    w = t["windows"][0]
    assert w["touch"] and w["trades"] and w["orders"]
    assert w["t0"] <= (T0 + 1002 * S) // 1000 - 59_000 and w["t1"] >= (T0 + 1002 * S) // 1000 + 299_000
    assert {"side", "price", "t_place", "t_end", "end"} <= set(w["orders"][0])


def test_refuses_to_write_outside_the_output_folder(tmp_path):
    out = tmp_path / "dashboard" / "live"
    with pytest.raises(ValueError):
        bs._write(tmp_path / "elsewhere.js", "x", out)


def test_stale_session_files_are_removed(tmp_path):
    base = make_base(tmp_path)
    live = base / "dashboard/live"
    live.mkdir(parents=True)
    (live / "session-old-thing.js").write_text("x")
    (live / "status.js").write_text("window.LIVE={}")
    bs.build(base, now_us=T0 + 3600 * S)
    assert not (live / "session-old-thing.js").exists() and (live / "status.js").exists()


def test_size_guard_thins_a_large_bundle(tmp_path, monkeypatch):
    base = make_base(tmp_path)
    monkeypatch.setattr(bs, "MAX_BYTES", 60_000)
    bs.build(base, now_us=T0 + 3600 * S)
    b = load_bundle(base, "testnet-BTCUSDT-join")
    assert len(b["curve"]["t"]) < 1500
