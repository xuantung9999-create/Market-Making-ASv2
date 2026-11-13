"""v2 Task 1: one websocket, several symbols. Offline tests (no network)."""
import json

from mm.recorder import BOOK_COLUMNS, LIVE_TRADE_COLUMNS, MultiRecorder, combined_url, load_live


def book_msg(sym, u=1, b="0.010", a="0.011"):
    return json.dumps({"stream": f"{sym.lower()}@bookTicker",
                       "data": {"u": u, "s": sym.upper(), "b": b, "B": "1000", "a": a, "A": "2000"}})


def trade_msg(sym, p="65000.5", q="0.01", t=1_700_000_000_000, m=True):
    return json.dumps({"stream": f"{sym.lower()}@aggTrade",
                       "data": {"p": p, "q": q, "T": t, "m": m, "s": sym.upper()}})


def test_book_goes_to_its_symbol_only(tmp_path):
    rec = MultiRecorder(["ANKRUSDT", "BTCUSDT"], out=tmp_path)
    rec.handle(book_msg("ANKRUSDT"), 123)
    assert len(rec.recorders["ANKRUSDT"].book) == 1
    assert rec.recorders["ANKRUSDT"].book[0][0] == 123
    assert rec.recorders["BTCUSDT"].book == []


def test_trade_goes_to_its_symbol_only(tmp_path):
    rec = MultiRecorder(["ANKRUSDT", "BTCUSDT"], out=tmp_path)
    rec.handle(trade_msg("btcusdt"), 5)
    assert len(rec.recorders["BTCUSDT"].trades) == 1
    assert rec.recorders["BTCUSDT"].trades[0][4] == -1   # buyer is maker -> seller aggressor
    assert rec.recorders["ANKRUSDT"].trades == []


def test_flush_writes_one_file_per_symbol_per_kind_and_load_live_reads_back(tmp_path):
    rec = MultiRecorder(["ANKRUSDT", "BTCUSDT"], out=tmp_path)
    rec.handle(book_msg("ANKRUSDT", u=1), 10)
    rec.handle(book_msg("ANKRUSDT", u=2), 20)
    rec.handle(trade_msg("ANKRUSDT", p="0.0105"), 15)
    rec.handle(book_msg("BTCUSDT", b="65000", a="65000.1"), 11)
    rec.handle(trade_msg("BTCUSDT"), 12)
    rec.flush()
    for sym in ("ANKRUSDT", "BTCUSDT"):
        for kind in ("book", "trades"):
            assert len(list((tmp_path / sym / kind).glob("*.parquet"))) == 1
    book = load_live(tmp_path / "ANKRUSDT" / "book")
    assert list(book.columns) == BOOK_COLUMNS and len(book) == 2
    trades = load_live(tmp_path / "BTCUSDT" / "trades")
    assert list(trades.columns) == LIVE_TRADE_COLUMNS and len(trades) == 1


def test_unknown_stream_is_ignored(tmp_path):
    rec = MultiRecorder(["ANKRUSDT"], out=tmp_path)
    rec.handle(book_msg("SOLUSDT"), 1)                                    # symbol not recorded
    rec.handle(json.dumps({"stream": "ankrusdt@depth5", "data": {}}), 2)   # kind not recorded
    rec.handle(json.dumps({"result": None, "id": 1}), 3)                   # control message
    assert rec.recorders["ANKRUSDT"].book == [] and rec.recorders["ANKRUSDT"].trades == []


def test_combined_url_lists_every_stream():
    url = combined_url(["ANKRUSDT", "btcusdt"])
    assert url.startswith("wss://stream.binance.com:9443/stream?streams=")
    for s in ("ankrusdt@bookTicker", "ankrusdt@aggTrade", "btcusdt@bookTicker", "btcusdt@aggTrade"):
        assert s in url
