"""Dashboard redesign R5: statistics from the recorded top of book (mm/bookstats.py)."""
import numpy as np
import pandas as pd
import pytest

from mm import bookstats as bs

SEC = 1_000_000
HOUR = 3_600 * SEC
DAY0 = 20_000 * 24 * HOUR           # an exact UTC midnight in microseconds


def make_book(n_s=7200, start=DAY0, tick=0.01, spread_ticks=1, imb=None, mid=None, q=1000.0):
    """One update per second. imb in [-1, 1] sets the size split at the touch; mid is the mid price."""
    t = start + np.arange(n_s) * SEC
    imb = np.zeros(n_s) if imb is None else np.asarray(imb, float)
    mid = np.full(n_s, 100.0) if mid is None else np.asarray(mid, float)
    half = spread_ticks * tick / 2
    return pd.DataFrame({"recv_us": t, "update_id": np.arange(n_s), "bid": mid - half, "bid_qty": q * (1 + imb) / 2,
                         "ask": mid + half, "ask_qty": q * (1 - imb) / 2})


def make_trades(book, every_s=10, qty=5.0):
    t = book["recv_us"].to_numpy()[::every_s]
    return pd.DataFrame({"recv_us": t, "ts_us": t, "price": 100.0, "qty": qty, "side": 1})


def info_driven_book(n_s=7200, k=0.002, seed=3):
    """Imbalance cycles through 10 levels in shuffled order; the mid's next step is proportional to it."""
    rng = np.random.default_rng(seed)
    levels = np.linspace(-0.9, 0.9, 10)
    imb = rng.permutation(np.resize(levels, n_s))
    mid = 100.0 + np.r_[0.0, np.cumsum(k * imb[:-1])]
    return make_book(n_s=n_s, imb=imb, mid=mid)


# ------------------------------------------------------------------ imbalance curve
def test_imbalance_curve_rises_when_the_mid_follows_imbalance():
    rows = bs.imb_curve(info_driven_book(), "TEST", horizons=(1,))
    r = sorted((x for x in rows if x["h_s"] == 1), key=lambda x: x["bucket"])
    assert [x["bucket"] for x in r] == list(range(10))
    moves = [x["move_bp"] for x in r]
    assert all(b > a for a, b in zip(moves, moves[1:]))
    assert all(a["imb_mid"] < b["imb_mid"] for a, b in zip(r, r[1:]))
    assert r[0]["move_bp"] < 0 < r[-1]["move_bp"]
    assert all(x["n"] > 500 and x["se"] > 0 for x in r)


def test_horizon_move_uses_the_book_at_or_before_t_plus_h_and_drops_the_tail():
    book = info_driven_book(n_s=7200)
    rows = bs.imb_curve(book, "TEST", horizons=(30,))
    # 7200 one-second samples, the last 30 have no t+30 inside the data: dropped; never padded
    assert sum(x["n"] for x in rows) == 7200 - 30


def test_samples_are_dropped_when_the_day_ends_before_the_horizon():
    book = make_book(n_s=3600, start=DAY0 + 23 * HOUR + 0)       # the hour 23:00 to 24:00
    book2 = pd.concat([book, make_book(n_s=3600, start=DAY0 + 24 * HOUR)], ignore_index=True)
    rows = bs.imb_curve(book2, "TEST", horizons=(5,))
    n_total = sum(x["n"] for x in rows)
    assert n_total == 7200 - 5 - 5                  # last 5 s of each day lost; the 5 s at midnight do not bridge


def test_an_hour_with_a_gap_over_120_s_enters_no_statistic():
    book = info_driven_book(n_s=7200)
    gap = (book["recv_us"] > DAY0 + 600 * SEC) & (book["recv_us"] < DAY0 + 780 * SEC)     # 3 minutes, hour 0
    gappy = book[~gap].reset_index(drop=True)
    rows = bs.imb_curve(gappy, "TEST", horizons=(1,))
    assert sum(x["n"] for x in rows) <= 3600 - 1               # only the second hour is clean
    cov = bs.coverage(gappy, "TEST")
    assert cov[0]["hours"] == 1 and cov[0]["gap_minutes"] == pytest.approx(3.0, abs=0.1)
    assert cov[0]["date"] == pd.Timestamp(DAY0 * 1000, unit="ns").strftime("%Y-%m-%d")


# ------------------------------------------------------------------ profile
def test_share_one_tick_is_one_when_the_spread_never_widens():
    book = make_book()
    p = bs.profile(book, make_trades(book), "TEST", tick=0.01)
    assert p["share_one_tick"] == 1.0 and p["spread_ticks_med"] == 1.0
    assert p["tick_bp"] == pytest.approx(0.01 / 100.0 * 1e4)


def test_share_one_tick_falls_when_the_spread_widens_half_the_time():
    book = make_book()
    wide = np.arange(len(book)) % 2 == 1
    book.loc[wide, "ask"] += 0.01
    p = bs.profile(book, make_trades(book), "TEST", tick=0.01)
    assert p["share_one_tick"] == pytest.approx(0.5, abs=0.01)


def test_touch_size_in_trades_and_rates():
    book = make_book(q=1000.0)
    p = bs.profile(book, make_trades(book, every_s=10, qty=5.0), "TEST", tick=0.01)
    assert p["touch_qty_med"] == pytest.approx(500.0)
    assert p["touch_in_trades"] == pytest.approx(100.0)
    assert p["updates_per_min"] == pytest.approx(60.0, rel=0.02)
    assert p["trades_per_min"] == pytest.approx(6.0, rel=0.02)


def test_depletion_time_is_how_long_a_best_price_lasts():
    mid = 100.0 + 0.01 * (np.arange(7200) // 20)             # the best price moves every 20 s
    p = bs.profile(make_book(mid=mid), make_trades(make_book(mid=mid)), "TEST", tick=0.01)
    assert p["deplete_s_med"] == pytest.approx(20.0, abs=1.0)


def test_profile_is_none_safe_without_trades():
    p = bs.profile(make_book(), make_trades(make_book()).iloc[0:0], "TEST", tick=0.01)
    assert p["touch_in_trades"] is None and p["trades_per_min"] == 0.0


# ------------------------------------------------------------------ histograms, hours, touch
def test_spread_hist_shares_sum_to_one_and_cap_at_ten_ticks():
    book = make_book()
    book.loc[::3, "ask"] += 0.30
    h = bs.spread_hist(book, tick=0.01)
    assert sum(h["share"]) == pytest.approx(1.0) and h["ticks"][-1] <= 10
    assert h["ticks"][0] == 1


def test_hourly_has_24_entries_each():
    book = make_book()
    h = bs.hourly(book, make_trades(book))
    assert all(len(h[k]) == 24 for k in ("spread_bp", "touch_usd", "trades"))
    assert h["spread_bp"][0] == pytest.approx(0.01 / 100 * 1e4)
    assert h["trades"][5] is None                            # no data in hour 5 of this tape


def test_touch_samples_keep_every_price_change_and_the_last_six_hours():
    mid = 100.0 + 0.01 * (np.arange(10 * 3600) // 60)            # the best price steps once a minute
    book = make_book(n_s=10 * 3600, mid=mid)
    s = bs.touch_samples(book, hours=6)
    assert set(s) == {"t", "bid", "ask", "bid_qty", "ask_qty"} and s["t"][-1].endswith("Z")
    assert len(s["t"]) == 6 * 60 + 1 or len(s["t"]) == 6 * 60 + 2     # one point per step, plus the ends
    assert len(set(s["bid"])) == len({round(100.0 + 0.01 * (k // 60) - 0.005, 6) for k in range(4 * 3600, 10 * 3600)}) \
        or len(set(s["bid"])) >= 6 * 60


def test_touch_samples_keep_big_size_moves_and_drop_small_ones():
    n = 3600
    imb = np.where(np.arange(n) % 600 < 300, 0.0, 0.5)           # size jumps every 5 minutes
    imb = imb + 0.001 * np.sin(np.arange(n))                      # wobble far under 10%
    s = bs.touch_samples(make_book(n_s=n, imb=imb), hours=6)
    assert 10 <= len(s["t"]) <= 16


def test_touch_samples_are_capped():
    n = 6 * 3600
    rng = np.random.default_rng(0)
    s = bs.touch_samples(make_book(n_s=n, mid=100 + rng.normal(0, 1, n)), hours=6)
    assert len(s["t"]) <= bs.MAX_TOUCH_POINTS + 1 and s["t"][-1] > s["t"][0]


def test_touch_samples_of_a_quiet_book_are_just_its_two_ends():
    s = bs.touch_samples(make_book(n_s=10 * 3600), hours=6)
    assert len(s["t"]) == 2 and s["t"][0] < s["t"][1]


def test_trades_sample_keeps_the_largest_when_capped():
    book = make_book(n_s=3600)
    tr = make_trades(book, every_s=1)
    tr["qty"] = np.arange(len(tr), dtype=float)
    out = bs.trades_sample(tr, hours=6, cap=100)
    assert len(out["t"]) == 100 and min(out["qty"]) >= len(tr) - 100
    assert out["t"] == sorted(out["t"])


# ------------------------------------------------------------------ bundle
def test_book_bundle_validates_and_is_json_clean():
    from mm import report as rep
    book = info_driven_book()
    b = bs.book_bundle({"TESTUSDT": (book, make_trades(book))}, ticks={"TESTUSDT": 0.01}, built_utc="2026-11-13 10:00")
    assert b["kind"] == "book" and b["symbols"] == ["TESTUSDT"]
    for k in ("touch", "trades", "profile", "imb_curve", "spread_hist", "hourly", "coverage"):
        assert k in b, k
    assert rep.validate_bundle(b) == []


def test_build_book_bundle_cli_writes_a_loadable_file_and_fails_clearly_without_data(tmp_path, capsys):
    from scripts import build_book_bundle as cli
    assert cli.main(["--root", str(tmp_path / "none"), "--out", str(tmp_path / "out")]) == 1
    for kind, df in (("book", info_driven_book(n_s=3600)), ("trades", make_trades(info_driven_book(n_s=3600)))):
        d = tmp_path / "live" / "TESTUSDT" / kind
        d.mkdir(parents=True)
        df.to_parquet(d / f"TESTUSDT_{kind}_1.parquet")
    assert cli.main(["--root", str(tmp_path / "live"), "--out", str(tmp_path / "out")]) == 0
    files = list((tmp_path / "out").glob("book-*.js"))
    assert len(files) == 1 and "TESTUSDT" in files[0].read_text(encoding="utf-8")
    assert "book-" in (tmp_path / "out" / "index.js").read_text(encoding="utf-8")
