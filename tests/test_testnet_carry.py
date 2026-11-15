"""Task L1b: the executor carries pos, cash, fees and the daily loss stop across restarts, and releases the
balance it reserves for an order when that order goes away (the leak found in L0)."""
import json

import pytest

from mm.testnet import Executor
from tests.test_testnet import FakeClient, K_ASK, K_BID, MID, RULES

DAY = 86_400_000_000
LOT = 100 / MID


def mk(tmp_path, **kw):
    c = FakeClient()
    args = dict(lot_usd=100.0, q_max=10, maker_fee_bps=0.0, max_daily_loss_usd=1e9, out_dir=tmp_path)
    args.update(kw)
    return c, Executor("BTCUSDT", RULES, c, **args)


def recs(tmp_path, kind="orders"):
    out = []
    for f in sorted((tmp_path / "BTCUSDT").glob(f"{kind}_*.jsonl")):
        out += [json.loads(x) for x in f.read_text().splitlines()]
    return out


def write_fills(tmp_path, fills):
    d = tmp_path / "BTCUSDT"
    d.mkdir(parents=True, exist_ok=True)
    (d / "fills_2026-11-12.jsonl").write_text("".join(json.dumps(f) + "\n" for f in fills))


def write_genesis(tmp_path, ts=0, pos=0.0, cash=0.0, fees=0.0, base_balance=None):
    d = tmp_path / "BTCUSDT"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ledger_genesis.json").write_text(json.dumps({"ts_us": ts, "pos": pos, "cash": cash, "fees": fees,
                                                       "base_balance": base_balance}))


def test_save_is_atomic_and_has_the_documented_keys(tmp_path):
    c, ex = mk(tmp_path)
    ex.pos, ex.cash, ex.fees = 0.5, -100.0, 0.1
    ex.step({1: None, -1: None}, MID, 5)
    ex.save_exec_state()
    p = tmp_path / "state" / "BTCUSDT_exec.json"
    d = json.loads(p.read_text())
    assert set(d) == {"pos", "cash", "fees", "day", "day_start_pnl", "stopped", "ts_us"}
    assert d["pos"] == 0.5 and d["day"] == 0
    assert not list((tmp_path / "state").glob("*.tmp"))


def test_restart_at_minus_9_lots_allows_one_more_sell_then_caps(tmp_path):
    c1, ex1 = mk(tmp_path)
    ex1.pos = -9 * LOT
    ex1.cash = 9 * 100.0
    ex1.step({1: None, -1: None}, MID, 1)
    ex1.save_exec_state()
    c2, ex2 = mk(tmp_path)                                   # the restart: a fresh process
    assert ex2.load_exec_state() == "loaded"
    assert ex2.lots(MID) == -9 and ex2.cash == pytest.approx(900.0)
    ex2.step({1: None, -1: K_ASK}, MID, 2)
    assert [x[1] for x in c2.calls if x[0] == "new"] == ["SELL"]
    c2.fill(ex2.orders[-1].order_id, LOT)
    ex2.step({1: None, -1: K_ASK}, MID, 3)                   # filled: now -10 lots, at the cap
    assert ex2.lots(MID) == -10 and ex2.orders[-1] is None
    n = len([x for x in c2.calls if x[0] == "new"])
    ex2.step({1: None, -1: K_ASK}, MID, 4)
    assert len([x for x in c2.calls if x[0] == "new"]) == n  # blocked by the real cap


def test_loss_stop_survives_a_restart_on_the_same_day_and_clears_next_day(tmp_path):
    c1, ex1 = mk(tmp_path, max_daily_loss_usd=1.0)
    ex1.step({1: K_BID, -1: K_ASK}, MID, 1)
    ex1.cash -= 5.0
    ex1.step({1: K_BID, -1: K_ASK}, MID, 2)
    assert ex1.stopped
    ex1.save_exec_state()
    c2, ex2 = mk(tmp_path, max_daily_loss_usd=1.0)
    ex2.load_exec_state()
    assert ex2.stopped
    ex2.step({1: K_BID, -1: K_ASK}, MID, 3)
    assert c2.calls == [] and ex2.orders == {1: None, -1: None}      # no orders after the restart
    ex2.step({1: K_BID, -1: K_ASK}, MID, DAY + 1)                    # a new UTC day
    assert not ex2.stopped and ex2.orders[1] is not None


def test_missing_file_starts_from_zero_and_logs(tmp_path):
    c, ex = mk(tmp_path)
    assert ex.load_exec_state() == "missing"
    assert ex.pos == 0 and ex.cash == 0 and not ex.stopped
    assert any(r["op"] == "exec-state-missing" for r in recs(tmp_path))


def test_corrupt_file_starts_from_zero_and_logs(tmp_path):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "BTCUSDT_exec.json").write_text("{not json")
    c, ex = mk(tmp_path)
    assert ex.load_exec_state() == "corrupt"
    assert ex.pos == 0 and not ex.stopped
    assert any(r["op"] == "exec-state-corrupt" for r in recs(tmp_path))


def test_mismatch_with_fill_files_is_logged_and_the_fill_sum_wins(tmp_path):
    fills = [{"ts_us": 1, "side": -1, "price": MID, "qty": LOT, "mid": MID} for _ in range(5)]
    write_fills(tmp_path, fills)                              # the files say -5 lots
    c1, ex1 = mk(tmp_path)
    ex1.pos = 0.0                                             # the state file says flat
    ex1.step({1: None, -1: None}, MID, 1)
    ex1.save_exec_state()
    c2, ex2 = mk(tmp_path)
    assert ex2.load_exec_state() == "mismatch"
    assert ex2.pos == pytest.approx(-5 * LOT)
    r = next(r for r in recs(tmp_path) if r["op"] == "state-mismatch")
    assert r["file_pos"] == 0.0 and r["fills_pos"] == pytest.approx(-5 * LOT)


def test_mismatch_rebases_the_loss_stop_on_the_fill_files(tmp_path):
    y = 100 * DAY
    write_fills(tmp_path, [{"ts_us": y - 10, "side": -1, "price": MID, "qty": LOT, "mid": MID - 100} for _ in range(5)])
    c1, ex1 = mk(tmp_path)
    ex1.step({1: None, -1: None}, MID, y + 1)                # same UTC day as the restart, file says flat
    ex1.day_start_pnl = 999.0
    ex1.save_exec_state()
    c2, ex2 = mk(tmp_path)
    assert ex2.load_exec_state(now=y + 5) == "mismatch"
    assert ex2.day_start_pnl == pytest.approx(5 * (100.0 - LOT * (MID - 100)))


def test_small_difference_is_not_a_mismatch(tmp_path):
    write_fills(tmp_path, [{"ts_us": 1, "side": 1, "price": MID, "qty": LOT, "mid": MID}])
    c1, ex1 = mk(tmp_path)
    ex1.pos, ex1.cash = 0.5 * LOT, 0.0                        # half a lot apart: within one lot
    ex1.step({1: None, -1: None}, MID, 1)
    ex1.save_exec_state()
    c2, ex2 = mk(tmp_path)
    assert ex2.load_exec_state() == "loaded"
    assert not any(r["op"] == "state-mismatch" for r in recs(tmp_path))


def test_first_start_with_fill_files_but_no_state_file_rebuilds_from_fills(tmp_path):
    fills = [{"ts_us": 1, "side": -1, "price": MID, "qty": LOT, "mid": MID} for _ in range(4)]
    write_fills(tmp_path, fills)
    c, ex = mk(tmp_path)
    assert ex.load_exec_state() == "rebuilt"
    assert ex.lots(MID) == -4 and ex.cash == pytest.approx(4 * 100.0)
    assert any(r["op"] == "state-rebuilt-from-fills" for r in recs(tmp_path))


def test_pre_carry_sessions_add_up_to_the_true_position(tmp_path):
    """BTC/ETH before 2026-11-14: each restart reset the session's count to 0 while the account kept its coins.
    Three sessions of -8 lots each are -24 lots of real inventory, and the rebuild must say so (and flag it)."""
    fills, n = [], 0
    for s in range(3):
        for i in range(8):                                  # each session recorded its own pos from 0
            fills.append({"ts_us": s * 1000 + i, "side": -1, "price": MID, "qty": LOT, "mid": MID,
                          "pos": -(i + 1) * LOT})
    write_fills(tmp_path, fills)
    c, ex = mk(tmp_path, q_max=10)
    assert ex.load_exec_state() == "rebuilt"
    assert ex.lots(MID) == -24
    assert next(r for r in recs(tmp_path) if r["op"] == "restore-over-cap")["lots"] == -24


def test_genesis_sets_where_the_ledger_starts(tmp_path):
    # flat-ledger history before ts 500 is superseded by a genesis holding -1 lot; +1 since -> 0
    write_genesis(tmp_path, ts=500, pos=-1 * LOT, cash=100.0)
    write_fills(tmp_path, [{"ts_us": 100 + i, "side": -1, "price": MID, "qty": LOT, "mid": MID} for i in range(6)]
                + [{"ts_us": 600, "side": 1, "price": MID, "qty": LOT, "mid": MID}])
    c, ex = mk(tmp_path)
    assert ex.load_exec_state() == "rebuilt"
    assert ex.lots(MID) == 0 and ex.cash == pytest.approx(0.0)
    assert next(r for r in recs(tmp_path) if r["op"] == "state-rebuilt-from-fills")["ignored"] == 6


def test_start_record_logs_the_state_it_started_from(tmp_path):
    c, ex = mk(tmp_path)
    ex.pos, ex.cash, ex.fees, ex.day, ex.day_start_pnl = -2 * LOT, 200.0, 0.3, 7, -4.0
    ex.log_session("start", {})
    r = json.loads((tmp_path / "BTCUSDT" / "session.jsonl").read_text().splitlines()[-1])
    assert r["pos_at_start"] == pytest.approx(-2 * LOT) and r["cash_at_start"] == 200.0
    assert r["fees_at_start"] == 0.3 and r["day"] == 7 and r["day_start_pnl_at_start"] == -4.0


# ---- reconciliation with the exchange balance
def test_balance_matching_the_ledger_is_not_a_mismatch(tmp_path):
    write_genesis(tmp_path, base_balance=1.0)
    write_fills(tmp_path, [{"ts_us": 1 + i, "side": 1, "price": MID, "qty": LOT, "mid": MID} for i in range(5)])
    c, ex = mk(tmp_path)
    ex.load_exec_state()
    r = ex.reconcile_balance(1.0 + 5 * LOT)
    assert r["lots_apart"] == pytest.approx(0.0, abs=1e-9)
    assert not any(x["op"] == "balance-mismatch" for x in recs(tmp_path))


def test_missed_fills_show_up_as_a_balance_mismatch_and_pos_is_kept(tmp_path):
    # the BTC case: the account holds ~3 lots more than the ledger (orders that filled while the bot was down)
    write_genesis(tmp_path, base_balance=1.0)
    write_fills(tmp_path, [{"ts_us": 1 + i, "side": -1, "price": MID, "qty": LOT, "mid": MID} for i in range(5)])
    c, ex = mk(tmp_path)
    ex.load_exec_state()
    ex.reconcile_balance(1.0 - 2 * LOT)
    r = next(x for x in recs(tmp_path) if x["op"] == "balance-mismatch")
    assert r["lots_apart"] == pytest.approx(3.0)
    assert ex.lots(MID) == -5                                 # reported, not silently "fixed"


def test_no_genesis_balance_means_no_reconciliation(tmp_path):
    write_fills(tmp_path, [{"ts_us": 1, "side": -1, "price": MID, "qty": LOT, "mid": MID}])
    c, ex = mk(tmp_path)
    ex.load_exec_state()
    assert ex.reconcile_balance(0.5) is None
    assert not any(x["op"].startswith("balance-") for x in recs(tmp_path))


# ---- scripts/rebuild_ledger.py
def test_replay_finds_the_resets_and_the_hidden_inventory(tmp_path):
    from scripts.rebuild_ledger import analyse
    fills = [{"ts_us": 1, "side": -1, "price": MID, "qty": LOT, "mid": MID, "pos": -LOT},
             {"ts_us": 2, "side": -1, "price": MID, "qty": LOT, "mid": MID, "pos": -2 * LOT},
             {"ts_us": 10, "side": -1, "price": MID, "qty": LOT, "mid": MID, "pos": -LOT}]   # restart: counted from 0
    write_fills(tmp_path, fills)
    (tmp_path / "BTCUSDT" / "session.jsonl").write_text(json.dumps(
        {"ts_us": 5, "op": "start", "base_free": 1.0 - 2 * LOT}) + "\n")
    a = analyse(tmp_path, "BTCUSDT", 100.0)
    assert a["starts_flat"] and a["replay"]["pos"] == pytest.approx(-3 * LOT)
    (rs,) = a["replay"]["resets"]
    assert rs["session_had"] == pytest.approx(-2 * LOT) and rs["restarted_at"] == pytest.approx(0.0)
    assert a["implied"][0]["genesis_base"] == pytest.approx(1.0)      # balance agrees with a 1.0 start


def test_restored_position_beyond_q_max_is_flagged(tmp_path):
    write_fills(tmp_path, [{"ts_us": 1 + i, "side": -1, "price": MID, "qty": LOT, "mid": MID} for i in range(12)])
    c, ex = mk(tmp_path, q_max=10)
    ex.load_exec_state()
    r = next(r for r in recs(tmp_path) if r["op"] == "restore-over-cap")
    assert r["lots"] == -12 and r["q_max"] == 10


def test_restored_position_within_q_max_is_not_flagged(tmp_path):
    write_fills(tmp_path, [{"ts_us": 1 + i, "side": -1, "price": MID, "qty": LOT, "mid": MID} for i in range(10)])
    c, ex = mk(tmp_path, q_max=10)
    ex.load_exec_state()
    assert not any(r["op"] == "restore-over-cap" for r in recs(tmp_path))


def test_rebuilt_state_derives_the_day_start_for_the_loss_stop(tmp_path):
    # yesterday: sold 1 lot at MID. Today: nothing yet. Day start pnl must be yesterday's closing pnl.
    y = 100 * DAY
    write_fills(tmp_path, [{"ts_us": y - 10, "side": -1, "price": MID, "qty": LOT, "mid": MID - 100}])
    c, ex = mk(tmp_path)
    ex.load_exec_state(now=y + 5)
    assert ex.day == (y + 5) // DAY
    # continuous pnl at that fill: cash + pos*mid = 100 - LOT*(MID-100) = 0.2 (sold 100 above its mid)
    assert ex.day_start_pnl == pytest.approx(100.0 - LOT * (MID - 100))


# ---- balance reservation (L0 finding)
def test_cancel_returns_the_reserved_balance(tmp_path):
    c, ex = mk(tmp_path, base_free=1.0, quote_free=1000.0)
    for i in range(50):                                        # re-quote 50 times at changing prices
        ex.step({1: K_BID - i, -1: K_ASK + i}, MID, i)
    ex.step({1: None, -1: None}, MID, 100)                     # cancel everything
    assert ex.quote_free == pytest.approx(1000.0) and ex.base_free == pytest.approx(1.0)


def test_partial_fill_then_cancel_keeps_only_what_was_traded(tmp_path):
    c, ex = mk(tmp_path, base_free=1.0, quote_free=1000.0)
    ex.step({1: K_BID, -1: None}, MID, 0)
    o = ex.orders[1]
    c.fill(o.order_id, LOT / 2)
    ex.step({1: None, -1: None}, MID, 1)
    spent = (LOT / 2) * o.price
    assert ex.quote_free == pytest.approx(1000.0 - spent)
    assert ex.base_free == pytest.approx(1.0 + LOT / 2)


def test_full_fill_does_not_release_anything(tmp_path):
    c, ex = mk(tmp_path, base_free=1.0, quote_free=1000.0)
    ex.step({1: K_BID, -1: None}, MID, 0)
    o = ex.orders[1]
    c.fill(o.order_id, o.qty)
    ex.step({1: None, -1: None}, MID, 1)
    assert ex.quote_free == pytest.approx(1000.0 - o.qty * o.price)


def test_reject_does_not_reserve(tmp_path):
    c, ex = mk(tmp_path, base_free=1.0, quote_free=1000.0)
    c.reject_next = True
    ex.step({1: K_BID, -1: None}, MID, 0)
    assert ex.quote_free == 1000.0
