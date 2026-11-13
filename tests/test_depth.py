"""R9: partial-depth recording (opt-in) and the ladder / heatmap statistics."""
import json

import numpy as np
import pandas as pd
import pytest

from mm import bookstats as bs
from mm import recorder as rc

SEC = 1_000_000


def payload(mid=100.0, levels=10, tick=0.01, qty=10.0, uid=160):
    return {"lastUpdateId": uid,
            "bids": [[f"{mid - tick * (i + 1) / 2:.4f}", str(qty * (i + 1))] for i in range(levels)],
            "asks": [[f"{mid + tick * (i + 1) / 2:.4f}", str(qty * (i + 1))] for i in range(levels)]}


def test_parse_depth_flattens_ten_levels_per_side():
    row = rc.parse_depth(payload(), 123)
    assert len(row) == len(rc.DEPTH_COLUMNS) and row[0] == 123 and row[1] == 160
    d = dict(zip(rc.DEPTH_COLUMNS, row))
    assert d["bp0"] == pytest.approx(99.995) and d["bq0"] == 10.0 and d["ap9"] == pytest.approx(100.05) and d["aq9"] == 100.0


def test_short_ladders_are_padded_with_nan():
    p = payload(levels=3)
    d = dict(zip(rc.DEPTH_COLUMNS, rc.parse_depth(p, 1)))
    assert np.isnan(d["bp5"]) and np.isnan(d["aq9"]) and d["bq2"] == 30.0


def test_depth_is_off_by_default_and_the_url_only_changes_when_asked():
    assert "depth" not in rc.combined_url(["ANKRUSDT"])
    assert "ankrusdt@depth10@1000ms" in rc.combined_url(["ANKRUSDT"], depth=True)
    assert rc.combined_url(["ANKRUSDT"]).startswith("wss://stream.binance.com:9443/stream?streams=ankrusdt@bookTicker")


def test_multirecorder_routes_and_writes_depth_files(tmp_path):
    rec = rc.MultiRecorder(["ANKRUSDT"], out=tmp_path, depth=True)
    rec.handle(json.dumps({"stream": "ankrusdt@depth10@1000ms", "data": payload()}), 5 * SEC)
    rec.handle(json.dumps({"stream": "ankrusdt@depth10@1000ms", "data": payload(uid=161)}), 6 * SEC)
    rec.flush()
    df = rc.load_live(tmp_path / "ANKRUSDT" / "depth")
    assert len(df) == 2 and list(df.columns) == rc.DEPTH_COLUMNS and list(df["update_id"]) == [160, 161]
    off = rc.MultiRecorder(["ANKRUSDT"], out=tmp_path / "off")
    off.handle(json.dumps({"stream": "ankrusdt@depth10@1000ms", "data": payload()}), 1)
    off.flush()
    assert not (tmp_path / "off" / "ANKRUSDT" / "depth").exists()


def depth_frame(minutes=60, mid=100.0, bid_heavy=False):
    t = np.arange(minutes * 60) * SEC
    rows = []
    for ts in t:
        p = payload(mid=mid, qty=10.0)
        if bid_heavy:
            p["bids"] = [[b[0], str(float(b[1]) * 4)] for b in p["bids"]]
        rows.append(rc.parse_depth(p, int(ts)))
    return pd.DataFrame(rows, columns=rc.DEPTH_COLUMNS)


def test_ladder_has_cumulative_sizes_and_distance_from_mid_in_bp():
    lad = bs.depth_ladder(depth_frame(minutes=2))
    assert len(lad["bids"]) == 10 and len(lad["asks"]) == 10
    b0, b9 = lad["bids"][0], lad["bids"][9]
    assert b0["cum"] == pytest.approx(10.0) and b9["cum"] == pytest.approx(sum(10.0 * (i + 1) for i in range(10)))
    assert b0["bp"] < 0 < lad["asks"][0]["bp"] and b9["bp"] < b0["bp"]
    assert lad["mid"] == pytest.approx(100.0, abs=0.01) and lad["usd_per_unit"] == pytest.approx(lad["mid"])


def test_heatmap_is_time_by_distance_with_bounded_size():
    h = bs.depth_heatmap(depth_frame(minutes=60), bucket_min=10, n_bins=12)
    assert len(h["t"]) == 6 and len(h["y"]) == 12 and len(h["z"]) == 12 and len(h["z"][0]) == 6
    assert h["y"] == sorted(h["y"]) and h["y"][0] < 0 < h["y"][-1]
    assert np.nanmax(np.array(h["z"], float)) > 0
    json.dumps(h, allow_nan=False)                                     # None, never NaN


def test_book_bundle_carries_depth_only_when_given():
    from tests.test_bookstats import make_book, make_trades
    book = make_book()
    f = {"TESTUSDT": (book, make_trades(book))}
    assert "depth" not in bs.book_bundle(f, ticks={"TESTUSDT": 0.01})
    b = bs.book_bundle(f, ticks={"TESTUSDT": 0.01}, depth={"TESTUSDT": depth_frame(minutes=30)})
    d = b["depth"]["TESTUSDT"]
    assert set(d) == {"ladder", "heat"} and d["ladder"]["bids"][0]["cum"] > 0
