"""Offline tests for the downloader and recorder: fake Binance files, no network."""
import hashlib
import io
import json
import zipfile

import numpy as np
import pandas as pd
import pytest

import mm.data as data
from mm.recorder import Recorder, load_live, parse_book, parse_trade

# Spot format: no header, microsecond timestamps
SPOT_CSV = (
    "1,100000.00,0.5,1,1,1762732800000000,False,True\n"     # buyer aggressor
    "2,99999.99,0.2,2,3,1762732800050000,True,True\n"        # seller aggressor
    "3,100000.01,0.1,4,4,1762732800120000,False,True\n"
    "4,99999.98,0.3,5,5,1762732801500000,True,True\n"
)
# Futures format: header, millisecond timestamps
FUT_CSV = (
    "agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker\n"
    "1,100000.0,0.5,1,1,1762732800000,false\n"
    "2,99999.9,0.2,2,3,1762732800050,true\n"
)


def test_parse_spot_file():
    t = data.parse_aggtrades(io.StringIO(SPOT_CSV))
    assert list(t.columns) == data.TRADE_COLUMNS
    assert t.ts_us.iloc[0] == 1762732800000000
    assert list(t.side) == [1, -1, 1, -1]          # buyer-maker -> seller aggressor -> -1
    assert t.qty.sum() == pytest.approx(1.1)


def test_parse_futures_file_converts_ms_to_us():
    t = data.parse_aggtrades(io.StringIO(FUT_CSV))
    assert len(t) == 2
    assert t.ts_us.iloc[1] == 1762732800050 * 1000
    assert list(t.side) == [1, -1]


def test_bars_aggregate_correctly_and_keep_empty_bars():
    t = data.parse_aggtrades(io.StringIO(SPOT_CSV))
    bars = data.trades_to_bars(t, freq_ms=100)
    assert np.all(np.diff(bars.ts_us) == 100_000)               # regular grid
    assert len(bars) == 16                                      # 0.0s .. 1.5s
    b0 = bars.iloc[0]                                           # trades 1 and 2
    assert b0.buy_max == 100000.00 and b0.sell_min == 99999.99
    assert b0.mid == pytest.approx(99999.995)
    assert bars.iloc[5].n_trades == 0 and np.isnan(bars.iloc[5].buy_max)
    assert bars.iloc[5].mid == bars.iloc[1].mid                 # carried forward
    assert bars.n_trades.sum() == 4


def test_bars_have_no_look_ahead():
    """A bar's values only change when trades inside it change."""
    t = data.parse_aggtrades(io.StringIO(SPOT_CSV))
    full = data.trades_to_bars(t, 100)
    early = data.trades_to_bars(t[t.ts_us < 1762732801000000], 100)
    pd.testing.assert_frame_equal(full.iloc[: len(early)].reset_index(drop=True), early)


def test_summary_sigma_units():
    rng = np.random.default_rng(0)
    n = 3600
    ts = 1762732800_000000 + np.arange(n) * 1_000_000
    mid = 100_000 + np.cumsum(rng.choice([-1.0, 1.0], n) * 5.0)   # 5 USDT per second steps
    trades = pd.DataFrame({
        "ts_us": np.repeat(ts, 2) + np.tile([0, 1], n),
        "price": np.ravel(np.column_stack([mid + 0.005, mid - 0.005])),
        "qty": 0.01, "side": np.tile(np.array([1, -1], dtype="int8"), n),
    })
    s = data.summarize(trades)
    assert s["sigma_usdt_per_sqrt_s"] == pytest.approx(5.0, rel=0.02)
    assert s["n_trades"] == 2 * n and s["buy_share"] == pytest.approx(0.5)


def _fake_zip(csv: str, name="BTCUSDT-aggTrades-2026-11-10.csv") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, csv)
    return buf.getvalue()


def test_download_day_end_to_end(tmp_path, monkeypatch):
    raw = _fake_zip(SPOT_CSV)
    good = f"{hashlib.sha256(raw).hexdigest()}  BTCUSDT-aggTrades-2026-11-10.zip".encode()
    seen = []

    def fake_fetch(url, timeout=0):
        seen.append(url)
        return good if url.endswith(".CHECKSUM") else raw

    monkeypatch.setattr(data, "_fetch", fake_fetch)
    out = data.download_day("btcusdt", "2026-11-10", out_dir=tmp_path)
    assert seen[0] == ("https://data.binance.vision/data/spot/daily/aggTrades/"
                       "BTCUSDT/BTCUSDT-aggTrades-2026-11-10.zip")
    assert out.name == "BTCUSDT_2026-11-10_trades.parquet"
    assert len(data.load_trades(out)) == 4


def test_download_rejects_bad_checksum(tmp_path, monkeypatch):
    raw = _fake_zip(SPOT_CSV)
    monkeypatch.setattr(data, "_fetch",
                        lambda url, timeout=0: b"deadbeef  x.zip" if url.endswith(".CHECKSUM") else raw)
    with pytest.raises(IOError, match="checksum"):
        data.download_day("BTCUSDT", "2026-11-10", out_dir=tmp_path)


def test_recorder_parsers_and_flush(tmp_path):
    book = {"u": 400900217, "s": "BTCUSDT", "b": "100000.00", "B": "1.5", "a": "100000.01", "A": "0.7"}
    trade = {"e": "aggTrade", "E": 1, "s": "BTCUSDT", "a": 5, "p": "100000.01", "q": "0.02",
             "f": 1, "l": 1, "T": 1762732800123, "m": False, "M": True}
    assert parse_book(book, 7) == (7, 400900217, 100000.0, 1.5, 100000.01, 0.7)
    assert parse_trade(trade, 9) == (9, 1762732800123000, 100000.01, 0.02, 1)

    rec = Recorder("btcusdt", out=tmp_path, flush_s=9999)
    rec.handle(json.dumps({"stream": "btcusdt@bookTicker", "data": book}), 1)
    rec.handle(json.dumps({"stream": "btcusdt@aggTrade", "data": {**trade, "m": True}}), 2)
    rec.flush()
    b = load_live(tmp_path / "BTCUSDT" / "book")
    t = load_live(tmp_path / "BTCUSDT" / "trades")
    assert b.ask.iloc[0] == 100000.01 and len(b) == 1
    assert t.side.iloc[0] == -1 and t.ts_us.iloc[0] == 1762732800123000
