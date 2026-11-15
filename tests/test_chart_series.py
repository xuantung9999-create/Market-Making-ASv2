"""Task C2: mm/livestats.py::chart_series and the chart-<id>.js files written by scripts/build_session.py
(docs/DASHBOARD_SESSION_CHART_SPEC.md sections 7.2 to 7.4)."""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts import build_session as bs

S = 1_000_000
T0 = 1_794_600_000 * S          # an exact UTC hour
DAY = 86_400
CAP = 10
LOT = 100.0
RANGES = ("6h", "24h", "3d", "all")
CHART_KEYS = {"panels", "t", "mid", "bid_bp", "ask_bp", "lots", "max_abs_lots", "fills_cum", "buys_cum", "sells_cum",
              "width_bp", "pnl", "pnl_ex_artifact", "pnl_peak", "fill_ids", "axes", "off_scale", "titles", "events", "empty"}


def write_jsonl(p: Path, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))


def write_book(feed: Path, symbol: str, n: int, step_s: int, mid0: float):
    rng = np.random.default_rng(3)
    t = T0 + np.arange(n) * step_s * S
    mid = mid0 + np.cumsum(rng.integers(-1, 2, n)) * 0.01
    (feed / "book").mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"recv_us": t, "update_id": np.arange(n), "bid": mid - 0.01, "bid_qty": 1.0, "ask": mid + 0.01,
                  "ask_qty": 1.0}).to_parquet(feed / "book" / f"{symbol}_book_{T0 // 1000}.parquet")
    return t, mid


def make_base(tmp_path: Path):
    """Three days of BTC testnet (one fill per 20 min, one cap breach, one artifact fill, no orders on day 2 from
    10:00 to 14:00), a paper session with fills, and a paper session with a feed but no fills and no orders."""
    base = tmp_path
    (base / "config").mkdir()
    (base / "config" / "live.json").write_text(json.dumps({
        "testnet": [{"name": "testnet-join", "symbols": ["BTCUSDT"], "policy": "join", "lot_usd": LOT, "q_max": CAP, "max_loss": 20}],
        "paper": {"name": "paper", "symbols": ["SKLUSDT", "COTIUSDT"]}}))
    n = 3 * 1440
    t, mid = write_book(base / "data/testnet/feed/BTCUSDT", "BTCUSDT", n, 60, 67_500.0)
    d = base / "data/testnet/BTCUSDT"
    fills, k = [], 0
    for s in range(1200, 3 * DAY - 600, 1200):
        if 100 <= k < 112:
            sd = 1                                          # twelve buys in a row: 12 lots, past the cap of 10
        elif 112 <= k < 124:
            sd = -1                                         # and twelve sells back
        else:
            sd = 1 if k % 2 == 0 else -1
        m = float(mid[s // 60])
        fills.append({"ts_us": T0 + s * S + 300_000, "side": sd, "price": m - sd * 0.01, "qty": 0.0015, "order_id": 5000 + k,
                      "mid": m, "pos": 0.0, "pnl": 0.0, "how": "filled"})
        k += 1
    art_s = DAY + 12 * 3600 + 30                            # day 2, 12:00:30
    fills.append({"ts_us": T0 + art_s * S, "side": -1, "price": 57_882.59, "qty": 0.0015, "order_id": 9999,
                  "mid": 67_500.0, "pos": 0.0, "pnl": 0.0, "how": "filled"})
    write_jsonl(d / "fills_2026-11-14.jsonl", fills)
    orders = []
    gap = (DAY + 10 * 3600, DAY + 14 * 3600)
    for m in range(0, 3 * DAY, 600):
        if gap[0] <= m < gap[1] or m >= 3 * DAY - 600:
            continue
        mm = float(mid[m // 60])
        for sd, off, oid in ((1, -0.5, 100_000 + 2 * m), (-1, 0.5, 100_001 + 2 * m)):
            orders.append({"ts_us": T0 + m * S, "op": "place", "side": sd, "price": str(mm + off), "qty": "0.0015", "order_id": oid})
            orders.append({"ts_us": T0 + (m + 540) * S, "op": "cancel", "order_id": oid})
    write_jsonl(d / "orders_2026-11-14.jsonl", orders)
    write_jsonl(d / "session.jsonl", [{"ts_us": T0, "op": "start", "pid": 1, "args": {}, "pos_at_start": 0.0}])
    (d / "status.json").write_text(json.dumps({"symbol": "BTCUSDT", "pos": 0.0, "lots": 0, "pnl": 0.0, "stopped": False,
                                               "open": {"bid": None, "ask": None}, "policy": "join"}))
    # paper: SKLUSDT has fills, COTIUSDT only a feed
    tp, mp = write_book(base / "data/paper/feed/SKLUSDT", "SKLUSDT", n, 60, 0.5)
    pf = base / "data/paper/SKLUSDT"
    pf.mkdir(parents=True)
    rows = [{"ts_us": int(T0 + s * S), "side": 1 if i % 2 == 0 else -1, "price": float(mp[s // 60]), "qty": 400.0,
             "mid": float(mp[s // 60])} for i, s in enumerate(range(3600, 3 * DAY - 600, 7200))]
    pd.DataFrame(rows).to_parquet(pf / "fills_2026-11-14.parquet")
    write_book(base / "data/paper/feed/COTIUSDT", "COTIUSDT", n, 60, 0.2)
    return base, art_s, gap


def _load(base, name, prefix):
    txt = (base / "dashboard/live" / name).read_text()
    return json.loads(txt[txt.index('"] = ') + 5: txt.rindex(";")])


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    base, art_s, gap = make_base(tmp_path_factory.mktemp("c2"))
    bs.build(base, now_us=T0 + 3 * DAY * S)
    return {"base": base, "art_s": art_s, "gap": gap,
            "bundle": _load(base, "session-testnet-BTCUSDT-join.js", "session"),
            "chart": _load(base, "chart-testnet-BTCUSDT-join.js", "chart"),
            "pbundle": _load(base, "session-paper-SKLUSDT-agent.js", "session"),
            "pchart": _load(base, "chart-paper-SKLUSDT-agent.js", "chart"),
            "echart": _load(base, "chart-paper-COTIUSDT-agent.js", "chart")}


def _series(c):
    return [k for k in ("t", "mid", "bid_bp", "ask_bp", "lots", "max_abs_lots", "fills_cum", "buys_cum", "sells_cum", "width_bp",
                        "pnl", "pnl_ex_artifact", "pnl_peak") if c.get(k) is not None]


def _window_fills(b, r):
    end = b["meta"]["last_ms"]
    hours = {"6h": 6, "24h": 24, "3d": 72, "all": None}[r]
    w0 = None if hours is None else end - hours * 3_600_000
    return [f for f in b["fills"] if f["t"] <= end and (w0 is None or f["t"] >= w0)], w0


def test_file_shape_and_keys(built):
    c = built["chart"]
    assert c["id"] == "testnet-BTCUSDT-join" and c["built_ms"] and set(c["by_range"]) == set(RANGES)
    for r in RANGES:
        assert CHART_KEYS - {"pnl", "pnl_ex_artifact", "pnl_peak"} <= set(c["by_range"][r]), r


def test_every_array_has_one_length_at_most_500_and_t_increases(built):
    for key in ("chart", "pchart"):
        for r in RANGES:
            cr = built[key]["by_range"][r]
            lens = {len(cr[k]) for k in _series(cr)}
            assert len(lens) == 1 and 1 <= lens.pop() <= 500, (key, r)
            assert all(a < b for a, b in zip(cr["t"], cr["t"][1:])), (key, r)


def test_fill_counts_match_the_session_bundle(built):
    b, c = built["bundle"], built["chart"]["by_range"]
    for r in RANGES:
        cr = c[r]
        n = cr["fills_cum"][-1]
        assert n == cr["buys_cum"][-1] + cr["sells_cum"][-1]
        if r in ("3d", "all"):                              # the window covers the whole session: the tile counts the same fills
            assert n == b["by_range"][r]["counts"]["fills"] == len(b["fills"])
        else:                                               # the tile counts whole UTC hours; the chart counts the exact window
            assert n == len(_window_fills(b, r)[0])
    assert all(a <= b2 for a, b2 in zip(c["all"]["fills_cum"], c["all"]["fills_cum"][1:]))


def test_lots_and_max_abs_lots_follow_the_fills(built):
    b, c = built["bundle"], built["chart"]["by_range"]
    for r in RANGES:
        fw, _ = _window_fills(b, r)
        cr = c[r]
        assert cr["lots"][-1] == fw[-1]["lots_after"]
        m = cr["max_abs_lots"]
        assert all(x <= y for x, y in zip(m, m[1:]))
        assert m[-1] == max(abs(f["lots_after"]) for f in fw)
    assert c["all"]["max_abs_lots"][-1] > CAP


def _resting(built, side):
    """The intervals (ms) in which the synthetic trader had an order of this side resting."""
    out = []
    for m in range(0, 3 * DAY, 600):
        if built["gap"][0] <= m < built["gap"][1] or m >= 3 * DAY - 600:
            continue
        out.append(((T0 // 1000) + m * 1000, (T0 // 1000) + (m + 540) * 1000))
    return out


def test_quote_distance_is_null_exactly_where_no_order_rested(built):
    cr = built["chart"]["by_range"]["all"]
    t = cr["t"]
    width = (t[1] - t[0])
    iv = _resting(built, 1)
    for i, te in enumerate(t):
        t0 = te - width
        rested = any(a < te and b > t0 for a, b in iv)
        assert (cr["bid_bp"][i] is not None) == rested, i
        assert (cr["ask_bp"][i] is not None) == rested, i
    bid = [v for v in cr["bid_bp"] if v is not None]
    ask = [v for v in cr["ask_bp"] if v is not None]
    assert bid and ask and max(bid) < 0 < min(ask)           # bid below the mid is negative
    assert any(v is None for v in cr["bid_bp"]) and any(v is not None for v in cr["bid_bp"])   # the gap is there


def test_width_is_ask_minus_bid(built):
    cr = built["chart"]["by_range"]["all"]
    for w, a, b in zip(cr["width_bp"], cr["ask_bp"], cr["bid_bp"]):
        if a is None or b is None:
            assert w is None
        else:
            assert w == pytest.approx(a - b, abs=1e-9)


def test_testnet_has_no_pnl_and_paper_has_it(built):
    for r in RANGES:
        cr = built["chart"]["by_range"][r]
        assert not {"pnl", "pnl_ex_artifact", "pnl_peak"} & set(cr) and "pnl" not in cr["panels"] and "pnl" not in cr["titles"]
    pc = built["pchart"]["by_range"]["all"]
    assert "pnl" in pc["panels"] and {"pnl", "pnl_ex_artifact", "pnl_peak"} <= set(pc)
    assert all(p >= v - 1e-9 for p, v in zip(pc["pnl_peak"], pc["pnl"]))
    assert pc["titles"]["pnl"] == built["pbundle"]["by_range"]["all"]["takeaways"]["cum_pnl"]
    assert "quotes" not in pc["panels"]                       # a paper session records no orders


def test_titles_say_what_the_series_say(built):
    cr = built["chart"]["by_range"]["all"]
    label = built["bundle"]["by_range"]["all"]["label"]
    tp = cr["titles"]["price"]
    mids = [v for v in cr["mid"] if v is not None]
    n, art = cr["fills_cum"][-1], sum(1 for f in built["bundle"]["fills"] if f["artifact"])
    glitch = "1 of them a book glitch" if art == 1 else f"{art} of them book glitches"
    assert f"{n} fills" in tp and glitch in tp and label in tp
    assert f"{mids[0]:,.0f}" in tp and f"{mids[-1]:,.0f}" in tp
    tq = cr["titles"]["quotes"]
    share = sum(1 for w in cr["width_bp"] if w is not None) / len(cr["width_bp"])
    med = float(np.median([w for w in cr["width_bp"] if w is not None]))
    assert f"{share:.0%}" in tq and f"{med:.1f} bp" in tq and label in tq
    ti = cr["titles"]["inventory"]
    assert f"±{CAP}-lot cap" in ti and "once" in ti
    peak = max(cr["lots"], key=abs)
    assert str(abs(peak)) in ti or str(cr["max_abs_lots"][-1]) in ti
    assert cr["titles"]["card"] and cr["titles"]["sub"] and label in cr["titles"]["sub"]


def test_events_name_the_cap_breach_and_the_glitch(built):
    c = built["chart"]["by_range"]
    ev = c["all"]["events"]
    assert 1 <= len(ev) <= 3
    inv = [e for e in ev if e["panel"] == "inventory"]
    assert inv and "past the cap" in inv[0]["text"] and f"±{CAP}" in inv[0]["text"]
    fe = [e for e in ev if e["panel"] == "price"]
    assert fe and "book glitch" in fe[0]["text"] and "bp under the mid" in fe[0]["text"]
    lo, hi = c["all"]["axes"]["price"]
    assert lo <= fe[0]["y"] <= hi                           # the note sits on the edge, where the hollow marker is
    assert "book glitch" not in " ".join(e["text"] for e in c["24h"]["events"])      # day 3 holds no glitch fill


def test_off_scale_and_fill_distance(built):
    b, cr = built["bundle"], built["chart"]["by_range"]["all"]
    assert cr["off_scale"] and re.fullmatch(r"\d+ fills? off scale", cr["off_scale"])
    assert all("dist_bp" in f for f in b["fills"])
    art = [f for f in b["fills"] if f["artifact"]]
    assert art and art[0]["dist_bp"] < -1000                  # the glitch fill sold far below the mid
    assert built["chart"]["by_range"]["24h"]["off_scale"] is None
    lo, hi = cr["axes"]["bp"]
    assert lo < 0 < hi


def test_paper_with_a_feed_but_nothing_else_is_an_empty_state(built):
    for r in RANGES:
        e = built["echart"]["by_range"][r]
        assert e["empty"] and e["panels"] == ["price"], r
        assert "No orders" in e["empty"] and e["titles"]["card"]
    s = built["pchart"]["by_range"]["all"]
    assert s["empty"] is None


def test_files_have_no_nan_and_are_small(built):
    d = built["base"] / "dashboard/live"
    for f in d.glob("chart-*.js"):
        txt = f.read_text()
        assert "NaN" not in txt and "Infinity" not in txt
        assert f.stat().st_size < bs.MAX_BYTES, f.name
    assert len(list(d.glob("chart-*.js"))) == 3


def test_a_window_with_1600_fills_keeps_the_artifact_and_1500_ids(tmp_path):
    base = tmp_path
    (base / "config").mkdir()
    (base / "config" / "live.json").write_text(json.dumps({
        "testnet": [{"name": "t", "symbols": ["BTCUSDT"], "policy": "join", "lot_usd": LOT, "q_max": CAP, "max_loss": 20}]}))
    t, mid = write_book(base / "data/testnet/feed/BTCUSDT", "BTCUSDT", 4000, 1, 67_500.0)
    d = base / "data/testnet/BTCUSDT"
    fills = []
    for k in range(1600):
        sd = 1 if k % 2 == 0 else -1
        m = float(mid[10 + 2 * k])
        fills.append({"ts_us": T0 + (10 + 2 * k) * S + 300_000, "side": sd, "price": m - sd * (0.01 + 0.001 * (k % 7)),
                      "qty": 0.0015, "order_id": k, "mid": m, "pos": 0.0, "pnl": 0.0, "how": "filled"})
    fills[800]["price"] = 57_882.59
    fills[800]["side"] = -1
    write_jsonl(d / "fills_2026-11-14.jsonl", fills)
    write_jsonl(d / "session.jsonl", [{"ts_us": T0, "op": "start", "pid": 1, "args": {}, "pos_at_start": 0.0}])
    (d / "status.json").write_text(json.dumps({"symbol": "BTCUSDT", "pos": 0.0, "lots": 0, "pnl": 0.0, "stopped": False,
                                               "open": {}, "policy": "join"}))
    bs.build(base, now_us=T0 + 4000 * S)
    b = _load(base, "session-testnet-BTCUSDT-join.js", "session")
    cr = _load(base, "chart-testnet-BTCUSDT-join.js", "chart")["by_range"]["6h"]
    ids = cr["fill_ids"]
    assert len(ids) == 1500 and len(set(ids)) == 1500
    art = [f["i"] for f in b["fills"] if f["artifact"]]
    assert art and set(art) <= set(ids)
    assert "showing the 1,500 largest of 1,600" in cr["titles"]["price"]
    assert cr["fills_cum"][-1] == 1600                        # the counts still cover every fill
