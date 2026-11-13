"""v2.1 Task 12: the recorder writes a heartbeat file the dashboard and the audit can read."""
import json
import math

from mm.recorder import MultiRecorder

SEC = 1_000_000
HB_KEYS = {"bid", "ask", "bid_qty", "ask_qty", "last_book_utc", "last_trade_utc",
           "book_per_min", "trades_per_min", "last_trades"}


def book_msg(sym, u, b="0.010", a="0.011"):
    return json.dumps({"stream": f"{sym.lower()}@bookTicker",
                       "data": {"u": u, "s": sym, "b": b, "B": "1000", "a": a, "A": "2000"}})


def trade_msg(sym, p="0.0105", t=1_700_000_000_000, m=True):
    return json.dumps({"stream": f"{sym.lower()}@aggTrade",
                       "data": {"p": p, "q": "5", "T": t, "m": m, "s": sym}})


def _no_nan(o):
    if isinstance(o, float):
        assert math.isfinite(o)
    elif isinstance(o, dict):
        [_no_nan(v) for v in o.values()]
    elif isinstance(o, list):
        [_no_nan(v) for v in o]


def test_heartbeat_has_every_key_and_no_nan(tmp_path):
    rec = MultiRecorder(["ANKRUSDT", "BTCUSDT"], out=tmp_path)
    now = 1_700_000_100 * SEC
    rec.handle(book_msg("ANKRUSDT", 1), now - 5 * SEC)
    rec.handle(trade_msg("ANKRUSDT"), now - 4 * SEC)
    hb = rec.heartbeat(now_us=now)
    assert hb["schema"] == 1 and hb["ts_utc"].endswith("Z")
    assert set(hb["symbols"]) == {"ANKRUSDT", "BTCUSDT"}
    assert set(hb["symbols"]["ANKRUSDT"]) == HB_KEYS
    a = hb["symbols"]["ANKRUSDT"]
    assert (a["bid"], a["ask"], a["bid_qty"], a["ask_qty"]) == (0.010, 0.011, 1000.0, 2000.0)
    _no_nan(hb)


def test_symbol_with_no_messages_reports_nulls_not_zeros(tmp_path):
    rec = MultiRecorder(["ANKRUSDT"], out=tmp_path)
    s = rec.heartbeat(now_us=1_700_000_100 * SEC)["symbols"]["ANKRUSDT"]
    assert s["bid"] is None and s["last_book_utc"] is None and s["last_trades"] == []
    assert s["book_per_min"] == 0 and s["trades_per_min"] == 0


def test_per_minute_counts_only_the_last_60_seconds(tmp_path):
    rec = MultiRecorder(["ANKRUSDT"], out=tmp_path)
    now = 1_700_000_500 * SEC
    for i, age in enumerate([200, 90, 61, 59, 30, 1]):          # seconds ago
        rec.handle(book_msg("ANKRUSDT", i), now - age * SEC)
    s = rec.heartbeat(now_us=now)["symbols"]["ANKRUSDT"]
    assert s["book_per_min"] == 3


def test_last_trades_keeps_latest_30_newest_last(tmp_path):
    rec = MultiRecorder(["ANKRUSDT"], out=tmp_path)
    now = 1_700_000_500 * SEC
    for i in range(40):
        rec.handle(trade_msg("ANKRUSDT", p=f"{0.01 + i / 1e5:.5f}", t=1_700_000_000_000 + i), now - (40 - i) * SEC)
    lt = rec.heartbeat(now_us=now)["symbols"]["ANKRUSDT"]["last_trades"]
    assert len(lt) == 30 and lt[-1]["price"] == 0.01039 and lt[0]["price"] == 0.0101
    assert set(lt[0]) == {"t", "price", "qty", "side"}


def test_write_heartbeat_is_atomic_json(tmp_path):
    rec = MultiRecorder(["ANKRUSDT"], out=tmp_path)
    rec.handle(book_msg("ANKRUSDT", 1), 1_700_000_000 * SEC)
    path = rec.write_heartbeat(now_us=1_700_000_001 * SEC)
    assert path == tmp_path / "heartbeat.json"
    assert json.loads(path.read_text())["symbols"]["ANKRUSDT"]["bid"] == 0.010
    assert [p.name for p in tmp_path.iterdir() if p.is_file()] == ["heartbeat.json"]   # no temp file left


def test_heartbeat_does_not_change_what_is_recorded(tmp_path):
    rec = MultiRecorder(["ANKRUSDT"], out=tmp_path)
    rec.handle(book_msg("ANKRUSDT", 1), 10)
    rec.heartbeat(now_us=20)
    assert len(rec.recorders["ANKRUSDT"].book) == 1
