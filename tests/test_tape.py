"""v2 Task 3: book tapes and the merged event stream."""
import pandas as pd

from mm.tape import (BOOK_TAPE_COLUMNS, book_from_recorder, book_from_trades, default_level_qty,
                     merge_events, typical_level_qty)


def trades(rows):
    return pd.DataFrame(rows, columns=["ts_us", "price", "qty", "side"])


def test_inferred_book_rule():
    t = trades([(1, 100.0, 1.0, 1), (2, 99.0, 1.0, -1), (3, 100.0, 1.0, -1), (4, 100.0, 1.0, 1)])
    b = book_from_trades(t, tick=1.0, level_qty=50.0)
    assert list(b.columns) == BOOK_TAPE_COLUMNS
    assert b[["ts_us", "bid", "ask"]].values.tolist() == [[2, 99, 100], [3, 100, 101], [4, 99, 100]]
    assert (b["bid_qty"] == 50).all() and (b["ask_qty"] == 50).all()


def test_one_sided_trades_give_empty_tape():
    b = book_from_trades(trades([(1, 100.0, 1.0, 1), (2, 101.0, 1.0, 1)]), tick=1.0, level_qty=50.0)
    assert len(b) == 0 and list(b.columns) == BOOK_TAPE_COLUMNS


def test_no_row_when_nothing_changes():
    t = trades([(1, 100.0, 1.0, 1), (2, 99.0, 1.0, -1), (3, 99.0, 2.0, -1), (4, 100.0, 1.0, 1)])
    assert len(book_from_trades(t, tick=1.0, level_qty=5.0)) == 1


def test_small_tick_prices_compared_as_integer_ticks():
    tick = 1e-5
    t = trades([(1, 0.00376, 1e6, 1), (2, 0.00375, 1e6, -1), (3, 0.00376, 1e6, -1)])
    b = book_from_trades(t, tick=tick, level_qty=1.0)
    assert round(b["bid"].iloc[-1] / tick) == 376 and round(b["ask"].iloc[-1] / tick) == 377


def test_recorder_book_and_level_sizes():
    rec = pd.DataFrame({"recv_us": [5, 3], "update_id": [2, 1], "bid": [1.0, 1.0], "bid_qty": [10.0, 30.0],
                        "ask": [1.1, 1.1], "ask_qty": [20.0, 40.0]})
    b = book_from_recorder(rec)
    assert list(b.columns) == BOOK_TAPE_COLUMNS and b["ts_us"].tolist() == [3, 5]
    assert typical_level_qty(b) == 25.0                     # median of 10, 30, 20, 40
    assert default_level_qty(trades([(1, 1.0, 2.0, 1), (2, 1.0, 4.0, -1), (3, 1.0, 9.0, 1)])) == 80.0


def test_merge_order_at_equal_timestamps():
    tape = pd.DataFrame([(1_000_000, 99.0, 100.0, 1.0, 1.0)], columns=BOOK_TAPE_COLUMNS)
    tr = trades([(1_000_000, 99.0, 1.0, -1)])
    kinds = [(k, (x if k == "timer" else x[0])) for k, x in merge_events(tape, tr, decision_ms=1000)]
    assert kinds == [("book", 1_000_000), ("trade", 1_000_000), ("timer", 1_000_000)]


def test_merge_timer_grid_and_sorting():
    tape = pd.DataFrame([(2_500_000, 99.0, 100.0, 1.0, 1.0), (500_000, 99.0, 100.0, 1.0, 1.0)],
                        columns=BOOK_TAPE_COLUMNS)
    tr = trades([(1_200_000, 99.0, 1.0, -1)])
    ev = list(merge_events(tape, tr, decision_ms=1000))
    ts = [x if k == "timer" else x[0] for k, x in ev]
    assert ts == sorted(ts)
    assert [x for k, x in ev if k == "timer"] == [1_000_000, 2_000_000]
