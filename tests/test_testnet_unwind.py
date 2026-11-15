"""The loss stop works the position off instead of freezing it (and does not charge the price move of inventory carried in)."""
import json

import pytest

from mm.testnet import Executor
from tests.test_testnet import FakeClient, K_ASK, K_BID, MID, RULES

DAY = 86_400_000_000
LOT = 100.0 / MID


def mk(tmp_path, **kw):
    c = FakeClient()
    args = dict(lot_usd=100.0, q_max=10, maker_fee_bps=0.0, max_daily_loss_usd=1.0, out_dir=tmp_path)
    args.update(kw)
    return c, Executor("BTCUSDT", RULES, c, **args)


def stopped_long(tmp_path, lots=5, **kw):
    c, ex = mk(tmp_path, **kw)
    ex.step({1: K_BID, -1: K_ASK}, MID, 0)
    ex.pos, ex.cash = lots * LOT, -lots * 100.0
    ex.cash -= 5.0                                      # a 5 USDT trading loss: over the 1 USDT limit
    return c, ex


def test_a_stopped_long_keeps_only_its_ask_and_unwinds_to_flat(tmp_path):
    c, ex = stopped_long(tmp_path)
    ex.step({1: K_BID, -1: K_ASK}, MID, 1)
    assert ex.stopped
    assert ex.orders[1] is None and ex.orders[-1] is not None and ex.orders[-1].k == K_ASK
    for i in range(5):                                  # each fill of the ask takes one lot off
        c.fill(ex.orders[-1].order_id, LOT)
        ex.step({1: K_BID, -1: K_ASK}, MID, 2 + i)
    assert ex.lots(MID) == 0 and ex.orders == {1: None, -1: None}      # flat: nothing rests any more
    n = len([x for x in c.calls if x[0] == "new"])
    ex.step({1: K_BID, -1: K_ASK}, MID, 10)
    assert len([x for x in c.calls if x[0] == "new"]) == n and ex.stopped


def test_a_stopped_short_keeps_only_its_bid(tmp_path):
    c, ex = mk(tmp_path)
    ex.step({1: K_BID, -1: K_ASK}, MID, 0)
    ex.pos, ex.cash = -4 * LOT, 4 * 100.0 - 5.0
    ex.step({1: K_BID, -1: K_ASK}, MID, 1)
    assert ex.stopped and ex.orders[-1] is None and ex.orders[1] is not None


def test_when_the_policy_is_out_the_unwind_joins_the_best_price_of_its_side(tmp_path):
    c, ex = stopped_long(tmp_path)
    ex._info = {}
    ex.step({1: None, -1: None}, MID, 1, info={"book": (49_999.99, 50_000.01, 1.0, 1.0)})
    assert ex.stopped and ex.orders[-1] is not None and ex.orders[-1].k == K_ASK and ex.orders[1] is None


def test_an_unwinding_side_is_flagged_in_the_state_log(tmp_path):
    c, ex = stopped_long(tmp_path)
    ex.step({1: K_BID, -1: K_ASK}, MID, 1)
    snap = ex.state_log.snapshot()
    assert snap["ask"]["state"] == "LOSS_STOP" and snap["ask"]["detail"]["unwinding"] is True
    assert snap["bid"]["state"] == "LOSS_STOP" and snap["bid"]["detail"]["unwinding"] is False


def test_the_price_move_of_inventory_carried_into_the_day_is_not_a_loss(tmp_path):
    c, ex = mk(tmp_path, max_daily_loss_usd=5.0)
    ex.pos, ex.cash = 10 * LOT, -10 * 100.0             # long 10 lots overnight
    ex.step({1: None, -1: None}, MID, 0)
    ex.step({1: None, -1: None}, MID, DAY + 1)          # new UTC day: baseline taken
    assert ex.day_start_pos == pytest.approx(10 * LOT) and ex.day_start_mid == MID
    ex.step({1: None, -1: None}, MID * 0.95, DAY + 2)   # the price falls 5%: about 50 USDT on the position
    assert not ex.stopped and ex.day_pnl(MID * 0.95) == pytest.approx(0.0)
    ex.cash -= 6.0                                      # a real trading loss of 6 USDT does stop it
    ex.step({1: None, -1: None}, MID * 0.95, DAY + 3)
    assert ex.stopped


def test_the_day_baseline_survives_a_restart(tmp_path):
    c, ex = mk(tmp_path)
    ex.pos, ex.cash = 3 * LOT, -300.0
    ex.step({1: None, -1: None}, MID, 0)
    ex.step({1: None, -1: None}, MID, DAY + 1)
    ex.save_exec_state()
    d = json.loads((tmp_path / "state" / "BTCUSDT_exec.json").read_text())
    assert d["day_start_pos"] == pytest.approx(3 * LOT) and d["day_start_mid"] == MID
    c2, ex2 = mk(tmp_path)
    ex2.load_exec_state(now=DAY + 5)
    assert ex2.day_start_pos == pytest.approx(3 * LOT) and ex2.day_start_mid == MID