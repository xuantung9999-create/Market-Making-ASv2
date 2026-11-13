"""v2.1 Task 12: audit what the recorder actually saved (synthetic feeds, no network)."""
import numpy as np
import pandas as pd
import pytest

from mm.recorder import BOOK_COLUMNS, LIVE_TRADE_COLUMNS, Recorder
from scripts.audit_recorder import audit_root, audit_symbol, passes

SEC = 1_000_000
DAY0 = 1_699_920_000                      # 2023-11-14 00:00:00 UTC


def make_book(start_s, n, step_s=2, bid=0.0100, ask=0.0101, bq=1000.0, aq=2000.0):
    ts = (start_s + np.arange(n) * step_s) * SEC
    return pd.DataFrame({"recv_us": ts.astype("int64"), "update_id": np.arange(1, n + 1),
                         "bid": bid, "bid_qty": bq, "ask": ask, "ask_qty": aq})[BOOK_COLUMNS]


def make_trades(times_s, prices, qty=5.0):
    ts = (np.asarray(times_s) * SEC).astype("int64")
    return pd.DataFrame({"recv_us": ts, "ts_us": ts, "price": prices, "qty": qty,
                         "side": np.where(np.arange(len(ts)) % 2 == 0, 1, -1).astype("int8")})[LIVE_TRADE_COLUMNS]


def six_hours():
    book = make_book(DAY0, 6 * 3600 // 2)
    tt = DAY0 + 100 + np.arange(40) * 300
    trades = make_trades(tt, np.where(np.arange(40) % 2 == 0, 0.0101, 0.0100))
    return book, trades


def test_clean_day_counts_hours_and_has_no_faults():
    book, trades = six_hours()
    (row,) = audit_symbol("ANKRUSDT", book, trades)
    assert row["date"] == "2023-11-14" and row["clean_hours"] == 6
    assert row["book_updates"] == 10_800 and row["trades"] == 40
    assert row["gaps_over_5s"] == 0 and row["crossed_or_locked"] == 0
    assert row["bad_sizes"] == 0 and row["id_backwards"] == 0 and row["out_of_book_share"] == 0.0


def test_a_five_minute_hole_spoils_that_hour_and_is_counted():
    book = make_book(DAY0, 3 * 3600 // 2)
    t = book["recv_us"] / SEC - DAY0
    book = book[~((t > 4200) & (t < 4500))].reset_index(drop=True)      # 01:10:00 to 01:15:00
    (row,) = audit_symbol("ANKRUSDT", book, make_trades([DAY0 + 10], [0.0100]))
    assert row["clean_hours"] == 2
    assert row["gaps_over_5s"] == 1 and row["gap_seconds"] == pytest.approx(300.0)
    assert row["max_gap_s"] == pytest.approx(300.0)


def test_a_book_that_stops_early_is_not_a_clean_hour():
    book = make_book(DAY0, 3000)                                         # ends 01:39:58
    (row,) = audit_symbol("ANKRUSDT", book, make_trades([DAY0 + 10], [0.0100]))
    assert row["clean_hours"] == 1


def test_crossed_and_locked_books_are_counted():
    book, trades = six_hours()
    book.loc[10, ["bid", "ask"]] = [0.0102, 0.0101]                      # crossed
    book.loc[11, ["bid", "ask"]] = [0.0102, 0.0102]                      # locked
    book.loc[12, ["bid", "ask"]] = [0.0105, 0.0101]                      # crossed
    assert audit_symbol("ANKRUSDT", book, trades)[0]["crossed_or_locked"] == 3


def test_non_positive_sizes_are_counted():
    book, trades = six_hours()
    book.loc[5, "bid_qty"] = 0.0
    book.loc[6, "ask_qty"] = -1.0
    assert audit_symbol("ANKRUSDT", book, trades)[0]["bad_sizes"] == 2


def test_update_id_going_backwards_is_counted():
    book, trades = six_hours()
    book.loc[100, "update_id"] = 3
    assert audit_symbol("ANKRUSDT", book, trades)[0]["id_backwards"] == 1


def test_trades_outside_the_book_just_before_them_are_counted():
    book = make_book(DAY0, 3600 // 2)
    inside = make_trades(DAY0 + 10 + np.arange(10), [0.0100, 0.0101] * 5)
    outside = make_trades(DAY0 + 100 + np.arange(5), [0.0105] * 5)
    trades = pd.concat([inside, outside], ignore_index=True)
    (row,) = audit_symbol("ANKRUSDT", book, trades)
    assert row["out_of_book_share"] == pytest.approx(5 / 15)


def test_trade_before_any_book_update_is_not_judged():
    book = make_book(DAY0 + 50, 100)
    trades = make_trades([DAY0 + 10, DAY0 + 60], [0.0500, 0.0100])
    (row,) = audit_symbol("ANKRUSDT", book, trades)
    assert row["out_of_book_share"] == 0.0


def test_spread_in_ticks_and_queue_in_trades():
    book, trades = six_hours()
    (row,) = audit_symbol("ANKRUSDT", book, trades)
    assert row["tick"] == pytest.approx(0.0001)
    assert row["spread_ticks_med"] == pytest.approx(1.0)
    assert row["touch_in_trades"] == pytest.approx(300.0)               # 1500 resting / 5 per trade


def test_days_are_split_at_utc_midnight():
    book = pd.concat([make_book(DAY0 + 86_400 - 20, 10), make_book(DAY0 + 86_400, 10)], ignore_index=True)
    book["update_id"] = np.arange(1, 21)
    rows = audit_symbol("ANKRUSDT", book, make_trades([DAY0 + 86_401], [0.0100]))
    assert [r["date"] for r in rows] == ["2023-11-14", "2023-11-15"]


def _day(**kw):
    base = dict(clean_hours=22, crossed_or_locked=0, out_of_book_share=0.0)
    return {**base, **kw}


def test_pass_rule_needs_seven_good_days():
    assert passes([_day() for _ in range(7)])
    assert not passes([_day() for _ in range(6)])


def test_pass_rule_ignores_days_that_fail_any_condition():
    good = [_day() for _ in range(6)]
    for bad in (_day(clean_hours=19), _day(crossed_or_locked=1),
                _day(out_of_book_share=0.02), _day(out_of_book_share=0.05)):
        assert not passes(good + [bad])
    assert passes(good + [_day(clean_hours=20, out_of_book_share=0.0199)])


def test_audit_root_reads_the_recorder_layout_and_flags_missing_coins(tmp_path):
    rec = Recorder("ANKRUSDT", out=tmp_path)
    book, trades = six_hours()
    rec.book = list(book.itertuples(index=False, name=None))
    rec.trades = list(trades.itertuples(index=False, name=None))
    rec.flush()
    table = audit_root(tmp_path, ["ANKRUSDT", "SKLUSDT"])
    ank = table[table.symbol == "ANKRUSDT"].iloc[0]
    assert ank["clean_hours"] == 6 and ank["book_updates"] == 10_800
    skl = table[table.symbol == "SKLUSDT"].iloc[0]
    assert skl["note"] == "no recorded files"


def test_cli_fails_cleanly_when_a_required_coin_has_no_files(tmp_path, capsys):
    from scripts.audit_recorder import main
    rec = Recorder("ANKRUSDT", out=tmp_path)
    book, trades = six_hours()
    rec.book = list(book.itertuples(index=False, name=None))
    rec.trades = list(trades.itertuples(index=False, name=None))
    rec.flush()
    rc = main(["--root", str(tmp_path), "--symbols", "ANKRUSDT,SKLUSDT", "--out", str(tmp_path / "a.csv")])
    out = capsys.readouterr().out
    assert rc == 0 and "TASK 12 FAIL" in out
    assert "FAIL  SKLUSDT: 0 recorded days" in out and "FAIL  ANKRUSDT: 1 recorded days" in out
