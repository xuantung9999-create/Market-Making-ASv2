"""R8: the book bundle carries the tape-validation result (inferred vs recorded book) for the Data tab."""
import json
import math

import numpy as np
import pandas as pd

from mm import bookstats
from scripts.validate_tape import verdict


def frame(ratio=1.0, edge_gap=0.5):
    return pd.DataFrame({
        "symbol": ["A", "A", "B"], "date": ["d1", "d2", "d1"], "hours": [20, 22, 18],
        "fills_real": [100, 120, 80], "fills_inf": [100 * ratio, 120 * ratio, 80 * ratio],
        "net_edge_real": [-3.0, -3.0, -4.0], "net_edge_inf": [-3.0 + edge_gap] * 3,
        "wait_med_real": [5.0, 6.0, 7.0], "wait_med_inf": [4.0, 5.0, 6.0],
        "fill_ratio": [ratio] * 3, "edge_diff_bp": [edge_gap] * 3, "level_ratio": [0.8, 0.9, 1.0]})


def test_section_has_rows_and_the_pooled_verdict_matching_validate_tape():
    df = frame()
    sec = bookstats.tape_validation(df)
    assert len(sec["rows"]) == 3 and sec["rows"][0]["symbol"] == "A"
    ok, nums = verdict(df)
    assert sec["pooled"]["ok"] is ok is True
    assert math.isclose(sec["pooled"]["fill_ratio"], nums["fill_ratio"])
    assert sec["pooled"]["days"] == 2 and math.isclose(sec["pooled"]["level_ratio_median"], 0.9)


def test_section_flags_a_bad_inferred_tape_and_is_json_clean():
    sec = bookstats.tape_validation(frame(ratio=2.0))
    assert sec["pooled"]["ok"] is False
    df = frame(); df.loc[0, "net_edge_inf"] = np.nan
    json.dumps(bookstats.tape_validation(df), allow_nan=False)            # no NaN reaches the page
    assert bookstats.tape_validation(pd.DataFrame()) is None


def test_book_bundle_includes_it_only_when_given():
    from tests.test_bookstats import make_book, make_trades                 # the existing synthetic recorder frames
    book = make_book()
    f = {"TESTUSDT": (book, make_trades(book))}
    assert "tape_validation" not in bookstats.book_bundle(f, ticks={"TESTUSDT": 0.01})
    b = bookstats.book_bundle(f, ticks={"TESTUSDT": 0.01}, tape_validation=bookstats.tape_validation(frame()))
    assert b["tape_validation"]["pooled"]["ok"] is True
