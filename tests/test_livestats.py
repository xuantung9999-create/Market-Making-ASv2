"""Task L3: mm/livestats.py on synthetic fills and a synthetic feed."""
import numpy as np
import pandas as pd
import pytest

from mm import livestats as ls

S = 1_000_000
T0 = 1_794_600_000 * S


def feed(n=7200, mid0=100.0, tick=0.01, seed=0, hole=None, spike=None):
    """One book update a second. ``hole`` = (start_s, end_s) with no updates; ``spike`` = (second, factor)."""
    rng = np.random.default_rng(seed)
    t = np.arange(n) * S + T0
    mid = mid0 + np.cumsum(rng.integers(-1, 2, n)) * tick
    if spike:
        mid = mid.copy()
        mid[spike[0]] = mid[spike[0]] * spike[1]
    keep = np.ones(n, bool)
    if hole:
        keep[hole[0]:hole[1]] = False
    return pd.DataFrame({"recv_us": t[keep], "bid": (mid - tick)[keep], "ask": (mid + tick)[keep]})


def rows(times_s, sides, qty=1.0, book=None, off=0.01, fee_bps=10.0, extra=None):
    out = []
    b = book.set_index("recv_us")
    for ts, sd in zip(times_s, sides):
        t = T0 + int(ts * S)
        mid = float((b["bid"].asof(t) + b["ask"].asof(t)) / 2)
        r = {"ts_us": t, "side": sd, "price": mid - sd * off, "qty": qty, "mid": mid, "pos": 0.0, "pnl": 0.0,
             "how": "filled"}
        r.update(extra or {})
        out.append(r)
    return out


def test_two_restarts_make_one_continuous_curve():
    book = feed()
    p1 = rows([100, 200, 300], [1, 1, -1], book=book)
    p2 = rows([4000, 4100, 4200], [-1, -1, 1], book=book)
    for r in p2:                                  # the second process restarts its counters at zero
        r["pos"], r["pnl"] = 0.0, 0.0
    fl = ls.fills_frame(p1 + p2, fee_bps=10.0)
    an = ls.analyse(fl, book, fee_bps=10.0, lot_usd=100.0, q_max=10)
    side, px, qty = fl["side"].to_numpy(), fl["price"].to_numpy(), fl["qty"].to_numpy()
    mid_end = (book["bid"].iloc[-1] + book["ask"].iloc[-1]) / 2
    want = -(side * px * qty).sum() + (side * qty).sum() * mid_end - fl["fee"].sum()
    c = an["curve"]
    assert c["pnl"].iloc[-1] == pytest.approx(want, abs=1e-9)
    assert an["attribution"]["net"] == pytest.approx(want, abs=1e-9)
    assert np.abs(np.diff(c["pnl"].to_numpy())).max() < 1.0           # no sawtooth back to zero
    assert an["fills"]["pnl_after"].iloc[3] == pytest.approx(
        -(side[:4] * px[:4] * qty[:4]).sum() + (side[:4] * qty[:4]).sum() * an["fills"]["mid"].iloc[3] - fl["fee"].iloc[:4].sum())


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_attribution_terms_sum_to_net(seed):
    rng = np.random.default_rng(seed)
    book = feed(seed=seed, spike=(3000, 1.2))                         # one glitch up and back down
    times = np.sort(rng.integers(60, 7000, 60))
    sides = rng.choice([-1, 1], 60)
    fl = ls.fills_frame(rows(times, sides, qty=0.7, book=book, off=0.01) +
                        rows([2999.5], [-1], qty=1.0, book=book, off=30.0), fee_bps=10.0)
    an = ls.analyse(fl, book, fee_bps=10.0, lot_usd=100.0, q_max=10)
    a = an["attribution"]
    assert abs(a["edge"] + a["adverse"] + a["carry"] + a["fees"] + a["artifact"] - a["net"]) < 1e-6
    assert abs(a["identity_gap"]) < 1e-6
    assert a["fees"] == pytest.approx(-fl["fee"].sum())
    assert sum(r["net"] for r in an["by_day"]) == pytest.approx(a["net"], abs=1e-6)
    assert sum(r["net"] for r in an["by_hour"]) == pytest.approx(a["net"], abs=1e-6)
    assert an["counts"]["artifact_jumps"] >= 1


def test_fill_1430bp_from_mid_is_an_artifact_and_its_edge_lands_in_artifact():
    book = feed(n=900, mid0=67_542.74, tick=0.01)
    rec = rows([500], [-1], qty=0.00177, book=book, off=0.0)
    rec[0]["price"] = 57_882.59
    fl = ls.fills_frame(rec)
    an = ls.analyse(fl, book, fee_bps=10.0, lot_usd=100.0, q_max=10)
    f = an["fills"].iloc[0]
    assert f["artifact"] and "bp from mid" in f["reason"]
    mid = f["mid"]
    assert abs(57_882.59 - mid) / mid * 1e4 > 1400
    want = -(mid - 57_882.59) * 0.00177
    assert want == pytest.approx(-17.1, abs=0.2)
    a = an["attribution"]
    assert a["edge"] == 0.0 and a["artifact"] == pytest.approx(want, abs=1e-9)
    assert np.isnan(f["mk_60"]) and not np.isnan(f["edge_bp"])       # artifacts leave the markouts; edge is shown
    inc = ls.incidents(an, {"bid": [], "ask": []}, [], [], q_max=10, max_loss=20)
    af = [i for i in inc if i["kind"] == "artifact_fill"]
    assert len(af) == 1 and af[0]["severity"] == "high" and af[0]["cost_usd"] == pytest.approx(-want, abs=1e-6)
    assert "bp away" in af[0]["sentence"] and "17" in af[0]["sentence"]


def test_normal_fill_near_mid_is_not_an_artifact():
    book = feed()
    an = ls.analyse(ls.fills_frame(rows([300, 400], [1, -1], book=book)), book, lot_usd=100.0, q_max=10)
    assert not an["fills"]["artifact"].any() and an["attribution"]["artifact"] == 0.0


def test_feed_gap_drops_markouts_inside_it_and_makes_an_incident():
    book = feed(hole=(1000, 1180))                                    # 3 minutes without updates
    fl = ls.fills_frame(rows([990, 400], [1, 1], book=book))
    an = ls.analyse(fl, book, lot_usd=100.0, q_max=10)
    f = an["fills"].sort_values("t_us").reset_index(drop=True)
    inside, clear = f.iloc[1], f.iloc[0]                              # the fill at 990 s sits just before the hole
    assert np.isnan(inside["mk_60"]) and np.isnan(inside["mk_300"])
    assert not np.isnan(clear["mk_60"]) and not np.isnan(clear["mk_300"])
    assert an["counts"]["markout_dropped"][60] >= 1
    inc = ls.incidents(an, {"bid": [], "ask": []}, [], [], q_max=10, max_loss=20)
    gap = [i for i in inc if i["kind"] == "feed_gap"]
    assert len(gap) == 1 and gap[0]["severity"] == "medium" and "3 min" in gap[0]["sentence"]


def test_eleven_lots_with_q_max_ten_is_an_inventory_breach():
    book = feed(mid0=100.0)
    fl = ls.fills_frame(rows(np.arange(100, 100 + 11 * 20, 20), [1] * 11, qty=1.0, book=book))
    an = ls.analyse(fl, book, lot_usd=100.0, q_max=10)
    assert an["fills"]["lots_after"].abs().max() == 11
    inc = ls.incidents(an, {"bid": [], "ask": []}, [], [], q_max=10, max_loss=20)
    br = [i for i in inc if i["kind"] == "inventory_breach"]
    assert len(br) == 1 and br[0]["severity"] == "high" and "11 lots" in br[0]["sentence"]
    assert ls.incidents(ls.analyse(fl.iloc[:10], book, lot_usd=100.0, q_max=10), {"bid": [], "ask": []}, [], [],
                        q_max=10, max_loss=20) == [] or all(i["kind"] != "inventory_breach" for i in
                                                            ls.incidents(ls.analyse(fl.iloc[:10], book, lot_usd=100.0, q_max=10),
                                                                         {"bid": [], "ask": []}, [], [], q_max=10, max_loss=20))


def test_old_format_files_still_load():
    book = feed()
    old = [{"ts_us": T0 + 100 * S, "side": 1, "price": 99.99, "qty": 1.0, "order_id": 5, "mid": 100.0, "pos": 1.0,
            "pnl": -0.1, "how": "filled"}]
    fl = ls.fills_frame(old, fee_bps=10.0)
    assert fl["timing"].iloc[0] == "detected" and fl["t_us"].iloc[0] == fl["ts_us"].iloc[0]
    assert fl["fee"].iloc[0] == pytest.approx(99.99 * 1.0 * 10 / 1e4)
    an = ls.analyse(fl, book, lot_usd=100.0, q_max=10)
    assert np.isnan(an["fills"]["wait_s"].iloc[0]) and len(an["curve"]) > 1
    assert ls.fills_frame([]).empty and ls.analyse(ls.fills_frame([]), book)["attribution"]["net"] == 0.0


def test_new_format_fill_uses_exchange_time_and_queue_wait():
    book = feed()
    rec = rows([200], [1], book=book, extra={"fill_ts_us": T0 + 199 * S, "place_ts_us": T0 + 170 * S,
                                             "fee_est": 0.5})
    fl = ls.fills_frame(rec)
    assert fl["timing"].iloc[0] == "exchange" and fl["t_us"].iloc[0] == T0 + 199 * S and fl["fee"].iloc[0] == 0.5
    an = ls.analyse(fl, book, lot_usd=100.0, q_max=10)
    assert an["fills"]["wait_s"].iloc[0] == pytest.approx(29.0)


def test_markout_matches_its_definition():
    book = feed()
    fl = ls.fills_frame(rows([300], [1], book=book))
    an = ls.analyse(fl, book, lot_usd=100.0, q_max=10)
    f = an["fills"].iloc[0]
    t = int(f["t_us"]) + 60 * S
    b = book.set_index("recv_us")
    m = float((b["bid"].asof(t) + b["ask"].asof(t)) / 2)
    assert f["mk_60"] == pytest.approx(1 * (m - f["price"]) / f["price"] * 1e4, abs=1e-6)


def test_state_intervals_uptime_and_idle_incident():
    rows_ = []
    for k in range(0, 11):                                            # 10 minutes: bid no balance, ask at the cap
        rows_.append({"ts_us": T0 + k * 60 * S, "side": 1, "state": "NO_BALANCE", "detail": {"free": 1}})
        rows_.append({"ts_us": T0 + k * 60 * S, "side": -1, "state": "INV_CAP", "detail": {"lots": -11}})
    iv = ls.state_intervals(rows_, t_end=T0 + 10 * 60 * S)
    assert [x["state"] for x in iv["bid"]] == ["NO_BALANCE"] and iv["bid"][0]["t1"] - iv["bid"][0]["t0"] == 600 * S
    up = ls.uptime(iv)
    assert {(u["side"], u["state"]): round(u["share"], 6) for u in up} == {("bid", "NO_BALANCE"): 1.0, ("ask", "INV_CAP"): 1.0}
    book = feed()
    an = ls.analyse(ls.fills_frame([]), book)
    inc = ls.incidents(an, iv, [], [], q_max=10, max_loss=20)
    idle = [i for i in inc if i["kind"] == "idle"]
    assert len(idle) == 1 and idle[0]["severity"] == "high" and "NO_BALANCE" in idle[0]["sentence"]


def test_policy_out_is_not_idle_and_long_policy_out_is_info():
    rows_ = []
    for k in range(0, 121):
        for s in (1, -1):
            rows_.append({"ts_us": T0 + k * 60 * S, "side": s, "state": "POLICY_OUT", "detail": {"live_arm": 3}})
    iv = ls.state_intervals(rows_, t_end=T0 + 120 * 60 * S)
    inc = ls.incidents(ls.analyse(ls.fills_frame([]), feed()), iv, [], [], q_max=10, max_loss=20)
    assert [i["kind"] for i in inc] == ["policy_out"] and inc[0]["severity"] == "info"


def test_quiet_log_means_the_process_was_down():
    rows_ = [{"ts_us": T0, "side": 1, "state": "QUOTING", "detail": None},
             {"ts_us": T0 + 60 * S, "side": 1, "state": "QUOTING", "detail": None},
             {"ts_us": T0 + 3600 * S, "side": 1, "state": "QUOTING", "detail": None}]
    iv = ls.state_intervals(rows_, t_end=T0 + 3660 * S)
    assert len(iv["bid"]) == 2 and iv["bid"][0]["t1"] == T0 + 120 * S      # ends one repeat after the last line


def test_restart_reject_burst_loss_stop_incidents():
    an = ls.analyse(ls.fills_frame([]), feed())
    orders = [{"ts_us": T0 + k * 5 * S, "op": "reject", "error": "x"} for k in range(6)] + \
             [{"ts_us": T0 + 900 * S, "op": "loss-stop", "pnl": -20.5}]
    sess = [{"ts_us": T0, "op": "start", "pos_at_start": 0.0}, {"ts_us": T0 + 100 * S, "op": "stop"},
            {"ts_us": T0 + 200 * S, "op": "start", "pos_at_start": 0.0},
            {"ts_us": T0 + 300 * S, "op": "start", "pos_at_start": -0.017}]
    inc = ls.incidents(an, {"bid": [], "ask": []}, orders, sess, q_max=10, max_loss=20)
    kinds = sorted(i["kind"] for i in inc)
    assert kinds == ["loss_stop", "reject_burst", "restart"]
    assert next(i for i in inc if i["kind"] == "restart")["severity"] == "medium"
    assert next(i for i in inc if i["kind"] == "loss_stop")["severity"] == "high"
    assert [i["t0"] for i in inc] == sorted((i["t0"] for i in inc), reverse=True)


def test_tape_windows_merge():
    w = ls.tape_windows([1000 * S, 1100 * S, 5000 * S])
    assert w == [(940 * S, 1400 * S), (4940 * S, 5300 * S)]
