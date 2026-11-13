"""Testnet executor against a fake exchange: placing, replacing, fill detection, caps, loss stop."""
import json

import pytest

from mm.testnet import BinanceError, Executor, Rules, TestnetClient, TestnetSession, load_env, targets_from_sim

RULES = Rules(tick=0.01, step=0.00001, min_qty=0.00001, min_notional=5.0, base="BTC", quote="USDT")
MID = 50_000.0
K_BID, K_ASK = 4_999_999, 5_000_001          # 49,999.99 / 50,000.01


class FakeClient:
    def __init__(self):
        self.book = {}          # order_id -> dict
        self.next_id = 1
        self.calls = []
        self.reject_next = False

    def new_order(self, symbol, side, price, qty, cid):
        self.calls.append(("new", side, price, qty))
        if self.reject_next:
            self.reject_next = False
            raise BinanceError(400, -2010, "Order would immediately match and take.")
        oid = self.next_id
        self.next_id += 1
        self.book[oid] = {"orderId": oid, "side": side, "price": price, "origQty": qty, "executedQty": "0",
                          "status": "NEW"}
        return dict(self.book[oid])

    def fill(self, oid, qty):
        o = self.book[oid]
        o["executedQty"] = str(float(o["executedQty"]) + qty)
        if float(o["executedQty"]) >= float(o["origQty"]) - 1e-12:
            o["status"] = "FILLED"

    def open_orders(self, symbol):
        return [dict(o) for o in self.book.values() if o["status"] in ("NEW", "PARTIALLY_FILLED")]

    def get_order(self, symbol, oid):
        return dict(self.book[oid])

    def cancel(self, symbol, oid):
        self.calls.append(("cancel", oid))
        o = self.book[oid]
        if o["status"] not in ("NEW", "PARTIALLY_FILLED"):
            raise BinanceError(400, -2011, "Unknown order sent.")
        o["status"] = "CANCELED"
        return dict(o)

    def cancel_all(self, symbol):
        out = []
        for o in self.book.values():
            if o["status"] in ("NEW", "PARTIALLY_FILLED"):
                o["status"] = "CANCELED"
                out.append(o)
        return out


def make(tmp_path, **kw):
    c = FakeClient()
    args = dict(lot_usd=100.0, q_max=2, maker_fee_bps=0.0, max_daily_loss_usd=1e9, out_dir=tmp_path)
    args.update(kw)
    return c, Executor("BTCUSDT", RULES, c, **args)


def test_rules_formatting():
    assert RULES.price_str(K_BID) == "49999.99"
    assert RULES.qty_str(100 / MID) == "0.00200"
    r = Rules.from_info({"baseAsset": "BTC", "quoteAsset": "USDT", "filters": [
        {"filterType": "PRICE_FILTER", "tickSize": "0.01000000"},
        {"filterType": "LOT_SIZE", "stepSize": "0.00001000", "minQty": "0.00001000"},
        {"filterType": "NOTIONAL", "minNotional": "5.00000000"}]})
    assert (r.tick, r.step, r.min_notional) == (0.01, 0.00001, 5.0)


def test_places_both_sides_then_holds(tmp_path):
    c, ex = make(tmp_path)
    ex.step({1: K_BID, -1: K_ASK}, MID, 0)
    assert [x[:3] for x in c.calls] == [("new", "BUY", "49999.99"), ("new", "SELL", "50000.01")]
    ex.step({1: K_BID, -1: K_ASK}, MID, 1)
    assert len(c.calls) == 2                       # same targets: nothing sent


def test_price_change_cancels_and_replaces(tmp_path):
    c, ex = make(tmp_path)
    ex.step({1: K_BID, -1: None}, MID, 0)
    ex.step({1: K_BID - 1, -1: None}, MID, 1)
    assert c.calls[1][0] == "cancel" and c.calls[2][:3] == ("new", "BUY", "49999.98")
    ex.step({1: None, -1: None}, MID, 2)
    assert c.calls[-1][0] == "cancel" and ex.orders[1] is None


def test_fill_detection_updates_position_and_pnl(tmp_path):
    c, ex = make(tmp_path)
    ex.step({1: K_BID, -1: None}, MID, 0)
    oid = ex.orders[1].order_id
    c.fill(oid, 0.001)                              # partial
    ex.step({1: K_BID, -1: None}, MID, 1)
    assert ex.pos == pytest.approx(0.001) and ex.orders[1] is not None
    c.fill(oid, 0.001)                              # rest of it
    ex.step({1: K_BID, -1: None}, MID, 2)
    assert ex.pos == pytest.approx(0.002)
    assert ex.n_fills == 2
    assert ex.pnl(MID) == pytest.approx(0.002 * 0.01)   # bought 1 cent under mid
    lines = (tmp_path / "BTCUSDT").glob("fills_*.jsonl")
    assert sum(len(f.read_text().splitlines()) for f in lines) == 2


def test_fill_found_when_cancel_misses(tmp_path):
    c, ex = make(tmp_path)
    ex.step({1: K_BID, -1: None}, MID, 0)
    oid = ex.orders[1].order_id
    c.fill(oid, 0.002)
    ex.sync = lambda mid: None                      # pretend the poll did not see it yet
    ex.step({1: K_BID - 1, -1: None}, MID, 1)       # cancel gets -2011 -> order queried
    assert ex.pos == pytest.approx(0.002)


def test_inventory_cap_uses_real_position(tmp_path):
    c, ex = make(tmp_path, q_max=2)
    ex.pos = 2 * 100 / MID                          # 2 lots long
    ex.step({1: K_BID, -1: K_ASK}, MID, 0)
    assert [x[1] for x in c.calls if x[0] == "new"] == ["SELL"]


def test_spot_balance_blocks_selling(tmp_path):
    c, ex = make(tmp_path, base_free=0.0)
    ex.step({1: None, -1: K_ASK}, MID, 0)
    assert c.calls == []


def test_post_only_reject_is_logged_and_retried(tmp_path):
    c, ex = make(tmp_path)
    c.reject_next = True
    ex.step({1: K_BID, -1: None}, MID, 0)
    assert ex.n_rejects == 1 and ex.orders[1] is None
    ex.step({1: K_BID, -1: None}, MID, 1)
    assert ex.orders[1] is not None


def test_loss_stop_cancels_and_resets_next_day(tmp_path):
    c, ex = make(tmp_path, max_daily_loss_usd=1.0)
    ex.step({1: K_BID, -1: K_ASK}, MID, 0)
    ex.cash -= 5.0                                  # lose 5 USDT
    ex.step({1: K_BID, -1: K_ASK}, MID, 1)
    assert ex.stopped and ex.orders == {1: None, -1: None}
    ex.step({1: K_BID, -1: K_ASK}, MID, 86_400_000_000 + 1)
    assert not ex.stopped and ex.orders[1] is not None


def test_dry_run_sends_nothing(tmp_path):
    c, ex = make(tmp_path, dry_run=True)
    ex.step({1: K_BID, -1: K_ASK}, MID, 0)
    ex.step({1: K_BID - 1, -1: None}, MID, 1)
    ex.cancel_all(MID)
    assert c.calls == []


def test_client_refuses_mainnet():
    with pytest.raises(ValueError):
        TestnetClient("k", "s", base="https://api.binance.com")


def test_load_env(tmp_path, monkeypatch):
    monkeypatch.delenv("BINANCE_TESTNET_API_KEY", raising=False)
    p = tmp_path / ".env"
    p.write_text("# comment\nBINANCE_TESTNET_API_KEY = 'abc'\n")
    load_env(p)
    import os
    assert os.environ["BINANCE_TESTNET_API_KEY"] == "abc"


def _feed(session, sym, t_s, bid, ask, trade=None):
    us = int(t_s * 1e6)
    session.handle(json.dumps({"stream": f"{sym.lower()}@bookTicker",
                               "data": {"u": 1, "s": sym, "b": str(bid), "B": "1", "a": str(ask), "A": "1"}}), us)
    if trade:
        session.handle(json.dumps({"stream": f"{sym.lower()}@aggTrade",
                                   "data": {"p": str(trade[0]), "q": "0.5", "T": us // 1000, "m": trade[1]}}), us)


def test_session_join_policy_quotes_and_sees_real_inventory(tmp_path):
    c = FakeClient()
    s = TestnetSession(["BTCUSDT"], c, {"BTCUSDT": RULES}, policy="join", warmup_s=5, lot_usd=100, q_max=2,
                       state_dir=tmp_path / "state", out_dir=tmp_path)
    s.execs["BTCUSDT"].maker_fee_bps = 0.0
    t0 = 1_700_000_000.0
    for i in range(10):
        _feed(s, "BTCUSDT", t0 + i, 49_999.99, 50_000.01, trade=(50_000.0, i % 2 == 0))
        s.tick(int((t0 + i) * 1e6))
        s.execute(int((t0 + i) * 1e6))
    tg = targets_from_sim(s.agents["BTCUSDT"].live)
    assert tg == {1: K_BID, -1: K_ASK}
    assert {x[1] for x in c.calls if x[0] == "new"} == {"BUY", "SELL"}
    # real inventory at the cap -> the policy's live track sees it and only the ask stays
    s.execs["BTCUSDT"].pos = 2 * 100 / 50_000.0
    s.tick(int((t0 + 11) * 1e6))
    s.execute(int((t0 + 11) * 1e6))
    assert s.agents["BTCUSDT"].live.q == 2
    assert s.execs["BTCUSDT"].orders[1] is None and s.execs["BTCUSDT"].orders[-1] is not None
    s.shutdown()
    assert not c.open_orders("BTCUSDT")
