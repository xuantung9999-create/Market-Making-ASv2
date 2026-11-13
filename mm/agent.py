"""v2 Task 6: the self-calibrating agent.

Three layers, all driven by the same market events and the same engine (``QueueSim``):

1. LEARN (shadow orders). Two make-believe quoters always rest at the best price (JOIN) and
   one tick behind it (BACK), with no inventory limit. Each of their fills is a free
   experiment: 60 s later we know its net edge (spread captured minus adverse selection minus
   fee), and the ``EdgeTable`` cell for that action and market state is updated. A fill is
   learned from only once its 60 s have actually passed, so nothing is ever learned from the
   future.

2. CHOOSE (a fixed menu of 12 settings). Each menu entry is an ``EdgePolicy`` with its own
   caution: a minimum edge, how many standard errors to subtract, and how strongly inventory
   pushes back. All 12 trade on paper side by side, with their own inventory. Every 30 min
   each one's P&L is scored, and the scores are averaged with a half-life of 48 intervals
   (one day). The LIVE track follows one entry and switches only when another has enough
   fills and beats it by a margin, so the agent does not chase noise.

3. GUARD. If the live track loses more than ``max_daily_loss_usd`` in a UTC day, it stops
   quoting until the day ends. Learning and scoring carry on.

What the agent may change: the table's numbers and which menu entry is live. It cannot
change the lot size, the inventory limit, the menu, the fee or the loss stop.
"""
from __future__ import annotations

from collections import deque

import numpy as np
from dataclasses import dataclass, replace
from typing import Optional

from mm.edge import EdgePolicy, EdgeTable, net_edge_bp
from mm.edge import book_state as book_state_fn
from mm.features import FeatureEngine
from mm.queue_sim import Action, Fixed, MarketState, QSConfig, QSResult, QueueSim, _drive


@dataclass(frozen=True)
class ArmSpec:
    e_min_bp: float
    z: float
    gamma_bp: float


MENU: tuple[ArmSpec, ...] = tuple(ArmSpec(e, z, g) for e in (0.0, 2.0, 5.0) for z in (0.0, 1.0) for g in (0.5, 2.0))
START_ARM = MENU.index(ArmSpec(5.0, 1.0, 2.0))       # the most conservative entry


@dataclass(frozen=True)
class AgentConfig:
    horizon_s: float = 60.0
    interval_s: float = 1800.0
    score_halflife_intervals: float = 48.0
    switch_margin_bp: float = 1.0
    min_arm_fills: float = 50.0
    max_daily_loss_usd: float = 20.0


class _LivePolicy:
    """Delegates to the live menu entry, unless the daily loss stop has fired."""
    name = "Agent (live)"

    def __init__(self, agent: "CalibrationAgent"):
        self.agent = agent

    def decide(self, st: MarketState, q: int) -> tuple[Action, Action]:
        a = self.agent
        if not a.stopped and a.live.pnl - a._day_start_pnl < -a.cfg.max_daily_loss_usd:
            a.stopped = True
        if a.stopped:
            return Action.OUT, Action.OUT
        acts = a.arms[a.live_arm].policy.decide(st, q)
        if isinstance(st.feat, dict):            # record the table's prediction with the order (dashboard calibration)
            for side, act, key in ((1, acts[0], "pred_bid"), (-1, acts[1], "pred_ask")):
                if act != Action.OUT:
                    st.feat[key] = a.table.estimate(act, a.table.bucket(st.feat, side))[0]
        return acts


class CalibrationAgent:
    def __init__(self, cfg: AgentConfig, sim_cfg: QSConfig, tick: float, table: Optional[EdgeTable] = None,
                 book_state: bool = False, p_toxic_fn=None):
        """``book_state=True`` (v2.1 Task 16) adds the queue-ahead and regime features to every decision and
        uses the 18-cell book-state table; ``p_toxic_fn(ts_us) -> float`` is the causal regime feed."""
        self.cfg, self.sim_cfg, self.tick = cfg, sim_cfg, float(tick)
        self._book_state, self.p_toxic_fn = bool(book_state), p_toxic_fn
        self._typ: dict = {}                 # time-decayed typical displayed size per side
        self.table = table if table is not None else (EdgeTable(state_fn=book_state_fn) if book_state else EdgeTable())
        self.features = FeatureEngine(tick)
        shadow_cfg = replace(sim_cfg, q_max=None)
        extra = self._extra if book_state else None
        mk = lambda pol, c: QueueSim(pol, c, tick, self.features, feed_features=False, feat_extra=extra)
        self.shadows = [mk(Fixed(Action.JOIN, Action.JOIN, name="Shadow JOIN"), shadow_cfg),
                        mk(Fixed(Action.BACK, Action.BACK, name="Shadow BACK"), shadow_cfg)]
        self.arms = [mk(EdgePolicy(self.table, s.e_min_bp, s.z, s.gamma_bp,
                                   name=f"Arm {i} (e={s.e_min_bp:g}, z={s.z:g}, g={s.gamma_bp:g})"), sim_cfg)
                     for i, s in enumerate(MENU)]
        self.live = mk(_LivePolicy(self), sim_cfg)
        self._sims = self.shadows + self.arms + [self.live]
        self.live_arm = START_ARM
        self.stopped = False
        self.history: list[dict] = []
        n = len(MENU)
        self.score_mean = [0.0] * n          # decayed mean interval score, bp of q_max * lot_usd
        self.score_n = [0.0] * n             # decayed number of intervals scored
        self.fill_n = [0.0] * n              # decayed fill count
        self._decay = 0.5 ** (1.0 / cfg.score_halflife_intervals)
        self._learn: deque = deque()         # (due_us, action, bucket, side, price)
        self._mid: Optional[float] = None
        self._day_start_pnl = 0.0
        self._next_interval: Optional[int] = None
        self._arm_pnl0 = [0.0] * n
        self._arm_fills0 = [0] * n

    # ------------------------------------------------------------------ book-state features
    _TYP_HL_S = 1800.0

    def _track(self, ts: int, bid_qty: float, ask_qty: float) -> None:
        for key, q in (("bid", float(bid_qty)), ("ask", float(ask_qty))):
            m, last = self._typ.get(key, (q, ts))
            w = 1.0 - 0.5 ** (max(ts - last, 0) / 1e6 / self._TYP_HL_S)
            self._typ[key] = (m + w * (q - m), ts)

    def _extra(self, ts: int, bid_qty: float, ask_qty: float) -> dict:
        tb, ta = self._typ.get("bid", (0.0, 0))[0], self._typ.get("ask", (0.0, 0))[0]
        return {"qa_bid": bid_qty / tb if tb > 0 else 1.0, "qa_ask": ask_qty / ta if ta > 0 else 1.0,
                "p_toxic": float(self.p_toxic_fn(ts)) if self.p_toxic_fn is not None else 0.0}

    # ------------------------------------------------------------------ events
    def _pre(self, ts: int) -> None:
        """Learn from every shadow fill whose horizon has passed, using the mid known now."""
        while self._learn and self._learn[0][0] <= ts:
            _, action, bucket, side, price = self._learn.popleft()
            if self._mid is not None:
                self.table.update(action, bucket, net_edge_bp(side, price, self._mid, self.sim_cfg.maker_fee_bps))
        if self._next_interval is None:
            step = int(self.cfg.interval_s * 1e6)
            self._next_interval = (ts // step + 1) * step

    def on_book(self, ts_us, bid, ask, bid_qty, ask_qty) -> None:
        ts = int(ts_us)
        self._pre(ts)
        self.features.on_book(ts, bid, ask, bid_qty, ask_qty)
        if self._book_state:
            self._track(ts, bid_qty, ask_qty)
        self._mid = (bid + ask) / 2.0
        for s in self._sims:
            s.on_book(ts, bid, ask, bid_qty, ask_qty)

    def on_trade(self, ts_us, price, qty, side) -> list:
        ts = int(ts_us)
        self._pre(ts)
        self.features.on_trade(ts, price, qty, side)
        out = []
        horizon = int(self.cfg.horizon_s * 1e6)
        for s in self.shadows:
            for f in s.on_trade(ts, price, qty, side):
                feat = {k[2:]: v for k, v in f.items() if k.startswith("f_")}
                self._learn.append((f["ts_us"] + horizon, Action(f["action"]),
                                    self.table.bucket(feat, f["side"]), f["side"], f["price"]))
                out.append(f)
        for s in self.arms:
            s.on_trade(ts, price, qty, side)
        out.extend(self.live.on_trade(ts, price, qty, side))
        return out

    def on_timer(self, ts_us) -> None:
        ts = int(ts_us)
        self._pre(ts)
        if ts >= self._next_interval:
            self._end_interval(ts)
        for s in self._sims:
            s.on_timer(ts)

    # ------------------------------------------------------------------ scoring / switching
    def _end_interval(self, ts: int) -> None:
        step = int(self.cfg.interval_s * 1e6)
        self._next_interval = (ts // step + 1) * step
        unit = (self.sim_cfg.q_max or 10) * self.sim_cfg.lot_usd
        d = self._decay
        for i, arm in enumerate(self.arms):
            pnl, nf = arm.pnl, len(arm._fills)
            x = (pnl - self._arm_pnl0[i]) / unit * 1e4
            self.score_n[i] = self.score_n[i] * d + 1.0
            self.score_mean[i] += (x - self.score_mean[i]) / self.score_n[i]
            self.fill_n[i] = self.fill_n[i] * d + (nf - self._arm_fills0[i])
            self._arm_pnl0[i], self._arm_fills0[i] = pnl, nf
        switched = self._maybe_switch()
        self.history.append({"ts_us": ts, "live_arm": self.live_arm, "switched": switched,
                             "scores": list(self.score_mean), "fills": list(self.fill_n)})

    def _maybe_switch(self) -> bool:
        ok = [i for i in range(len(MENU)) if self.fill_n[i] >= self.cfg.min_arm_fills]
        if not ok:
            return False
        best = max(ok, key=lambda i: (self.score_mean[i], -i))
        if best != self.live_arm and self.score_mean[best] > self.score_mean[self.live_arm] + self.cfg.switch_margin_bp:
            self.live_arm = best
            return True
        return False

    # ------------------------------------------------------------------ persistence
    def state_dict(self) -> dict:
        """What the agent has chosen and scored (the table is saved separately with to_dict)."""
        return {"live_arm": self.live_arm, "score_mean": list(self.score_mean), "score_n": list(self.score_n),
                "fill_n": list(self.fill_n)}

    def load_state(self, d: dict) -> None:
        n = len(MENU)
        self.live_arm = int(d.get("live_arm", START_ARM))
        for k in ("score_mean", "score_n", "fill_n"):
            v = d.get(k)
            if v is not None and len(v) == n:
                setattr(self, k, [float(x) for x in v])

    # ------------------------------------------------------------------ day / results
    def end_day(self) -> None:
        """Flatten every simulator; learned table, scores and live arm carry over."""
        self._learn.clear()                  # fills without a full horizon are never learned from
        for s in self._sims:
            s.end_day()
        self._mid = None
        self.stopped = False
        self._day_start_pnl = self.live.pnl

    def result(self, day: Optional[int] = None) -> QSResult:
        """The live track; fills carry ``pred_edge_bp``, the edge the table predicted for them."""
        res = self.live.result(day=day)
        f = res.fills
        if len(f) and ("f_pred_bid" in f.columns or "f_pred_ask" in f.columns):
            pb = f["f_pred_bid"] if "f_pred_bid" in f.columns else np.nan
            pa = f["f_pred_ask"] if "f_pred_ask" in f.columns else np.nan
            f["pred_edge_bp"] = np.where(f["side"] > 0, pb, pa)
        return res


def run_agent(tape, trades, agent: CalibrationAgent, decision_ms: int) -> None:
    """Feed one day of events (the caller calls ``agent.end_day()`` afterwards)."""
    _drive(agent, tape, trades, decision_ms)
