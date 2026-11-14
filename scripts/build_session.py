"""Session bundles for the live dashboard (dashboard live spec, section 6.2).

    python -m scripts.build_session            # writes dashboard/live/sessions.js, session-<id>.js, tape-<id>-<date>.js

Reads data/testnet/**, data/paper/** and the recorded feed; writes ONLY under dashboard/live. Every number
and every sentence is computed here (mm/livestats.py); the page only formats and draws.

    dashboard/live/sessions.js            window.SESSIONS = [{id, source, symbol, policy, first_ms, last_ms, n_fills}]
    dashboard/live/session-<id>.js        window.SESSION_DATA["<id>"] = {bundle}       (under 1.5 MB)
    dashboard/live/tape-<id>-<date>.js    window.TAPES["<id>|<date>"] = {tape}         (under 1.5 MB)

The supervisor calls ``build_if_due`` on its minute loop; the heavy work runs at most every 5 minutes.
"""
from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from mm import livestats as ls
from mm.agent import MENU
from mm.queue_sim import QSConfig

US = ls.US
MAX_BYTES = 1_500_000
HEAVY_EVERY_S = 300
DEFAULTS = {"lot_usd": 100.0, "q_max": 10, "max_loss": 20.0}
MARKOUT_GROUPS = ("all", "buy", "sell", "JOIN", "BACK")
_PART_CACHE: dict = {}


@dataclass
class Spec:
    source: str           # "testnet" | "paper"
    symbol: str
    policy: str
    lot_usd: float
    q_max: int
    max_loss: float
    folder: Path
    feed: Path
    proc_name: str

    @property
    def id(self) -> str:
        return f"{self.source}-{self.symbol}-{self.policy}"


# ---------------------------------------------------------------------- discovery and loading
def _read_json(p: Path) -> Optional[dict]:
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def discover(base: Path, cfg: Optional[dict] = None) -> list[Spec]:
    cfg = cfg if cfg is not None else (_read_json(base / "config/live.json") or {})
    specs: list[Spec] = []
    t_cfg = {s: t for t in cfg.get("testnet") or [] for s in t.get("symbols", [])}
    root = base / "data" / "testnet"
    if root.is_dir():
        for d in sorted(root.iterdir()):
            if not d.is_dir() or d.name in ("feed", "state") or not re.fullmatch(r"[A-Z0-9]{2,20}", d.name):
                continue
            if not (list(d.glob("fills_*.jsonl")) or (d / "status.json").exists()):
                continue
            st = _read_json(d / "status.json") or {}
            c = t_cfg.get(d.name, {})
            specs.append(Spec("testnet", d.name, st.get("policy") or c.get("policy", "agent"),
                              float(c.get("lot_usd", DEFAULTS["lot_usd"])), int(c.get("q_max", DEFAULTS["q_max"])),
                              float(c.get("max_loss", DEFAULTS["max_loss"])), d, root / "feed" / d.name,
                              c.get("name", "testnet")))
    p_cfg = cfg.get("paper") or {}
    syms = list(p_cfg.get("symbols", []))
    proot = base / "data" / "paper"
    if proot.is_dir():
        for d in sorted(proot.iterdir()):
            if d.is_dir() and re.fullmatch(r"[A-Z0-9]{2,20}", d.name) and d.name not in syms and list(d.glob("fills_*.parquet")):
                syms.append(d.name)
    for s in syms:
        specs.append(Spec("paper", s, "agent", DEFAULTS["lot_usd"], DEFAULTS["q_max"], DEFAULTS["max_loss"],
                          proot / s, proot / "feed" / s, p_cfg.get("name", "paper")))
    return specs


def load_fill_rows(spec: Spec) -> list[dict]:
    if spec.source == "testnet":
        return ls.read_folder_jsonl(spec.folder, "fills")
    rows = []
    for f in sorted(spec.folder.glob("fills_*.parquet")):
        try:
            d = pd.read_parquet(f)
        except Exception:                                   # noqa: BLE001 - a half-written file: skip it this round
            continue
        for r in d.to_dict("records"):
            rows.append({"ts_us": int(r["ts_us"]), "side": int(r["side"]), "price": float(r["price"]),
                         "qty": float(r["qty"]), "mid": float(r.get("mid", r["price"])), "how": "sim"})
    return rows


def load_feed(feed: Path, kind: str, since_us: Optional[int]) -> pd.DataFrame:
    """Part files of the recorded feed whose name timestamp is not before ``since_us`` (minus the last part)."""
    folder = feed / kind
    files = []
    for f in sorted(folder.glob("*.parquet")):
        m = re.search(r"_(\d{12,14})\.parquet$", f.name)
        files.append((int(m.group(1)) if m else 0, f))
    if since_us is not None:
        cut = since_us // 1000
        keep = [i for i, (t, _) in enumerate(files) if t >= cut]
        start = max(keep[0] - 1, 0) if keep else max(len(files) - 1, 0)
        files = files[start:]
    parts = []
    for _, f in files:
        try:
            st = f.stat()
            key = (str(f), st.st_size, st.st_mtime_ns)
            if key not in _PART_CACHE:                      # finished parts never change: read each once per process
                _PART_CACHE[key] = pd.read_parquet(f)
            parts.append(_PART_CACHE[key])
        except Exception:                                   # noqa: BLE001
            continue
    if len(_PART_CACHE) > 40000:
        _PART_CACHE.clear()
    if not parts:
        return pd.DataFrame(columns=["recv_us", "bid", "ask", "bid_qty", "ask_qty"] if kind == "book"
                            else ["recv_us", "price", "qty", "side"])
    d = pd.concat(parts, ignore_index=True)
    return d.sort_values("recv_us", kind="stable").drop_duplicates(subset=["recv_us", "update_id"] if "update_id" in d else None)


# ---------------------------------------------------------------------- small helpers
def clean(o, sig: int = 7):
    """JSON-safe: numpy to python, NaN/inf to None, floats to ``sig`` significant digits."""
    if isinstance(o, dict):
        return {str(k): clean(v, sig) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v, sig) for v in o]
    if isinstance(o, np.ndarray):
        return [clean(v, sig) for v in o.tolist()]
    if isinstance(o, (np.floating, float)):
        v = float(o)
        if not math.isfinite(v):
            return None
        return float(f"{v:.{sig}g}") if v else 0.0
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, pd.Timestamp):
        return o.isoformat()
    return o


def ms(us) -> int:
    return int(us) // 1000


def day_of(us: int) -> str:
    return datetime.fromtimestamp(us / US, tz=timezone.utc).strftime("%Y-%m-%d")


def hhmm(us: int) -> str:
    return datetime.fromtimestamp(us / US, tz=timezone.utc).strftime("%H:%M UTC")


def stamp(us: int) -> str:
    return datetime.fromtimestamp(us / US, tz=timezone.utc).strftime("%d %b %H:%M UTC")


def downsample(df: pd.DataFrame, n: int) -> pd.DataFrame:
    if len(df) <= n:
        return df
    idx = np.unique(np.linspace(0, len(df) - 1, n).astype(int))
    return df.iloc[idx]


# ---------------------------------------------------------------------- the bundle
def process_info(base: Path, spec: Spec, sessions: list[dict], now_s: float) -> dict:
    sup = _read_json(base / "data/live_status/supervisor.json") or {}
    proc = next((p for p in sup.get("processes", []) if p.get("name") == spec.proc_name
                 and (spec.source == "paper" or f"--symbols {spec.symbol}" in p.get("cmd", ""))), None)
    starts = sum(1 for s in sessions if s.get("op") == "start")
    if proc is None:
        return {"running": None, "uptime_s": None, "restarts": max(starts - 1, 0)}
    return {"running": bool(proc.get("running")), "uptime_s": proc.get("uptime_s"),
            "restarts": max(starts - 1, proc.get("restarts") or 0) if starts else proc.get("restarts") or 0}


def infer_state(status: dict, q_max: int) -> dict:
    """Best-effort quote state for a trader that does not log states yet (status.json without ``state``)."""
    out = {}
    lots = status.get("lots") or 0
    for side, name in ((1, "bid"), (-1, "ask")):
        resting = (status.get("open") or {}).get(name)
        if resting is not None:
            st = "QUOTING"
        elif status.get("stopped"):
            st = "LOSS_STOP"
        elif (lots >= q_max if side > 0 else lots <= -q_max):
            st = "INV_CAP"
        else:
            st = "UNKNOWN"
        out[name] = {"state": st, "detail": None if st != "UNKNOWN" else "not logged: the trader predates state logging",
                     "since_us": None}
    return out


def state_sentence(state: dict, q_max: int, lots) -> str:
    b, a = state.get("bid") or {}, state.get("ask") or {}
    sb, sa = b.get("state"), a.get("state")
    if sb == "QUOTING" and sa == "QUOTING":
        return "Quoting on both sides"
    if sb == "QUOTING" or sa == "QUOTING":
        which = "bid" if sb == "QUOTING" else "ask"
        other = a if sb == "QUOTING" else b
        return f"Quoting the {which} side only ({'ask' if which == 'bid' else 'bid'}: {_why(other, q_max, lots)})"
    since = min([x["since_us"] for x in (b, a) if x.get("since_us")] or [None], default=None)
    when = f" since {hhmm(since)}" if since else ""
    return f"Not quoting{when}: bid {_why(b, q_max, lots)}, ask {_why(a, q_max, lots)}"


def _why(s: dict, q_max: int, lots) -> str:
    st, d = s.get("state"), s.get("detail")
    if st == "INV_CAP":
        return f"at inventory cap ({lots} of {q_max} lots)" if lots is not None else "at inventory cap"
    if st == "NO_BALANCE" and isinstance(d, dict):
        return f"blocked by balance (need {d.get('need', 0):.4g}, free {d.get('free', 0):.4g} {d.get('asset', '')})"
    if st == "LOSS_STOP":
        return "daily loss stop"
    if st == "POLICY_OUT":
        arm = d.get("live_arm") if isinstance(d, dict) else None
        return "policy stays out" + (f" (arm {arm})" if arm is not None else "")
    if st == "WARMUP":
        return "warming up"
    if st == "STALE_FEED":
        return "no recent book update"
    if st == "REJECTED":
        return f"last order rejected ({str(d)[:40]})"
    if st == "EXCHANGE_ERROR":
        return "exchange error"
    if st == "UNKNOWN" or st is None:
        return "reason not recorded yet"
    return str(st).lower().replace("_", " ")


def markout_table(f: pd.DataFrame, actions: dict, fee_bps: float) -> list[dict]:
    rows = []
    if f.empty:
        return rows
    g = f[~f["artifact"]].copy()
    g["action"] = g["order_id"].map(actions)
    groups = {"all": g, "buy": g[g["side"] > 0], "sell": g[g["side"] < 0],
              "JOIN": g[g["action"] == "JOIN"], "BACK": g[g["action"] == "BACK"]}
    for name in MARKOUT_GROUPS:
        sub = groups[name]
        for h in ls.HORIZONS:
            v = sub[f"mk_{h}"].dropna().to_numpy(float)
            if len(v) == 0:
                continue
            se = float(v.std(ddof=1) / math.sqrt(len(v))) if len(v) > 1 else None
            rows.append({"group": name, "h_s": h, "bp": float(v.mean()), "se": se, "n": int(len(v))})
    return rows


def fill_caption(r) -> str:
    """One sentence for the tape panel (Python writes every finding)."""
    dev = (r.price - r.mid) / r.mid * 1e4 if r.mid else float("nan")
    where = f"{abs(dev):.1f} bp {'above' if dev > 0 else 'below'} the mid {r.mid:g}" if np.isfinite(dev) else "no mid"
    s = f"{'Sold' if r.side < 0 else 'Bought'} {r.qty:g} at {r.price:g}, {where}."
    if r.artifact:
        s += f" Flagged as a book glitch ({r.reason}); it is kept out of the strategy numbers."
    elif r.mk_60 == r.mk_60:
        s += f" 60 s later the mid had moved {r.mk_60 - (r.edge_bp if r.edge_bp == r.edge_bp else 0):+.1f} bp, a markout of {r.mk_60:+.1f} bp before fees."
    if r.wait_s == r.wait_s:
        s += f" The order waited {r.wait_s:.1f} s in the queue."
    return s


def wait_terciles(f: pd.DataFrame) -> list[dict]:
    """Markout at 60 s by tercile of queue wait."""
    if f.empty:
        return []
    g = f[~f["artifact"] & f["wait_s"].notna() & f["mk_60"].notna()].copy()
    if len(g) < 9:
        return []
    g["tercile"] = pd.qcut(g["wait_s"].rank(method="first"), 3, labels=False)
    out = []
    for t, s in g.groupby("tercile"):
        v = s["mk_60"]
        out.append({"tercile": int(t), "wait_lo": float(s["wait_s"].min()), "wait_hi": float(s["wait_s"].max()),
                    "mk_60": float(v.mean()), "se": float(v.std(ddof=1) / math.sqrt(len(v))) if len(v) > 1 else None,
                    "n": int(len(v))})
    return out


def funnel(orders: list[dict], fills: pd.DataFrame) -> dict:
    ops = [o.get("op") for o in orders]
    rej = [o for o in orders if o.get("op") == "reject"]
    by_hour: dict = {}
    for o in orders:
        if o.get("op") in ("place", "cancel", "reject"):
            h = int(o["ts_us"] // ls.HOUR_US)
            by_hour.setdefault(h, {"placed": 0, "cancelled": 0, "rejected": 0})
            key = {"place": "placed", "cancel": "cancelled", "reject": "rejected"}[o["op"]]
            by_hour[h][key] += 1
    reasons: dict = {}
    for o in rej:
        e = re.sub(r"\d+(\.\d+)?", "#", str(o.get("error", "")))[:100]
        reasons[e] = reasons.get(e, 0) + 1
    return {"placed": ops.count("place"), "cancelled": ops.count("cancel"), "rejected": len(rej),
            "filled": int((fills["how"] != "partial").sum()) if len(fills) else 0,
            "partial": int((fills["how"] == "partial").sum()) if len(fills) else 0,
            "by_hour": [{"t": h * 3_600_000, **v} for h, v in sorted(by_hour.items())],
            "reject_reasons": [{"error": e, "n": n} for e, n in sorted(reasons.items(), key=lambda kv: -kv[1])]}


def model_section(spec: Spec, history: list[dict], agent_state: Optional[dict], f: pd.DataFrame, orders: list[dict],
                  intervals: dict, fee_bps: float, t_end: int) -> dict:
    live_arm = (agent_state or {}).get("live_arm")
    strip, prev = [], None
    for h in history:
        arm = h.get("live_arm")
        if prev is None or arm != prev[1]:
            if prev is not None:
                strip[-1]["t1"] = ms(h["ts_us"])
            strip.append({"t0": ms(h["ts_us"]), "t1": ms(t_end), "arm": arm})
            prev = (h["ts_us"], arm)
    sm = (agent_state or {}).get("score_mean") or []
    fn = (agent_state or {}).get("fill_n") or []
    arms = [{"arm": i, "e_min_bp": s.e_min_bp, "z": s.z, "gamma_bp": s.gamma_bp,
             "score_bp": sm[i] if i < len(sm) else None, "fills": fn[i] if i < len(fn) else None,
             "live": i == live_arm} for i, s in enumerate(MENU)]
    hist = [{"t": ms(h["ts_us"]), "scores": h.get("scores"), "fills": h.get("fills"), "live_arm": h.get("live_arm"),
             "switched": bool(h.get("switched"))} for h in history]
    if len(hist) > 600:
        hist = hist[::math.ceil(len(hist) / 600)]
    # predicted against realised: bucket the place records' pred_bp, join to fills by order id
    pred = {o["order_id"]: o["pred_bp"] for o in orders if o.get("op") == "place" and o.get("pred_bp") is not None
            and o.get("order_id") is not None}
    calib = []
    if len(f) and pred:
        g = f[~f["artifact"]].copy()
        g["pred"] = g["order_id"].map(pred)
        g = g.dropna(subset=["pred", "mk_60"])
        if len(g) >= 3:
            q = min(5, max(1, len(g) // 3))
            g["bucket"] = pd.qcut(g["pred"].rank(method="first"), q, labels=False)
            for b, s in g.groupby("bucket"):
                real = s["mk_60"] - fee_bps
                calib.append({"pred_bucket": int(b), "pred_bp": float(s["pred"].mean()), "real_bp": float(real.mean()),
                              "se": float(real.std(ddof=1) / math.sqrt(len(real))) if len(real) > 1 else None,
                              "n": int(len(s))})
    tot_out = sum(iv["t1"] - iv["t0"] for n in ("bid", "ask") for iv in intervals.get(n, []) if iv["state"] == "POLICY_OUT")
    tot = sum(iv["t1"] - iv["t0"] for n in ("bid", "ask") for iv in intervals.get(n, []))
    scores = [a["score_bp"] for a in arms if a["score_bp"] is not None]
    return {"fixed": spec.policy == "join", "live_arm": live_arm, "arm_strip": strip, "arms": arms, "history": hist,
            "calibration": calib, "policy_out_share": (tot_out / tot) if tot else None,
            "best_score_bp": max(scores) if scores else None, "entry_threshold_bp": 0.0,
            "switches": sum(1 for h in history if h.get("switched"))}


def build_bundle(base: Path, spec: Spec, now_us: int, tapes_out: Optional[dict] = None) -> dict:
    fee_bps = QSConfig().maker_fee_bps
    th = ls.Thresholds()
    rows = load_fill_rows(spec)
    fills = ls.fills_frame(rows, fee_bps)
    since = int(fills["t_us"].min()) - 400 * US if len(fills) else None
    book = load_feed(spec.feed, "book", since)
    t_b = ls.book_arrays(book)[0]
    t_end = int(t_b[-1]) if t_b.size else (int(fills["t_us"].max()) if len(fills) else now_us)
    an = ls.analyse(fills, book, fee_bps=fee_bps, lot_usd=spec.lot_usd, q_max=spec.q_max, thresholds=th, t_end=t_end)
    orders = ls.read_folder_jsonl(spec.folder, "orders")
    sessions = ls.read_jsonl(spec.folder / "session.jsonl")
    states = ls.read_folder_jsonl(spec.folder, "state")
    history = ls.read_folder_jsonl(spec.folder, "history")
    agent_state = _read_json(base / "data" / spec.source / "state" / f"{spec.symbol}_agent.json")
    status = _read_json(spec.folder / "status.json") or {}
    intervals = ls.state_intervals(states, t_end=min(now_us, t_end) if t_end else None)
    inc = ls.incidents(an, intervals, orders, sessions, q_max=spec.q_max, max_loss=spec.max_loss, thresholds=th, t_end=t_end)
    f = an["fills"]
    first_us = int(f["t_us"].min()) if len(f) else None
    last_us = int(f["t_us"].max()) if len(f) else None
    att = an["attribution"]

    # now
    st_now = status.get("state") or (infer_state(status, spec.q_max) if status else {})
    mid_now = an["mid_end"] or (status.get("pos") and 0) or 0
    lots_now = status.get("lots") if status.get("lots") is not None else (int(f["lots_after"].iloc[-1]) if len(f) else 0)
    since24 = now_us - 24 * 3600 * US
    open_inc = [i for i in inc if i["severity"] in ("high", "medium") and i["t1"] >= since24]
    now = {"state": st_now, "lots": lots_now, "pos_usd": (status.get("pos", 0) or 0) * (mid_now or 0),
           "open": {"bid": (status.get("open") or {}).get("bid"), "ask": (status.get("open") or {}).get("ask")},
           "last_fill_ms": ms(last_us) if last_us else None, "process": process_info(base, spec, sessions, time.time()),
           "state_logged": bool(status.get("state")), "open_incidents": len(open_inc), "mid": mid_now or None}

    # markers
    markers = []
    for r in sorted(sessions, key=lambda r: r["ts_us"]):
        if r.get("op") == "start":
            markers.append({"t": ms(r["ts_us"]), "kind": "restart", "ref": r["ts_us"]})
    for r in orders:
        if r.get("op") == "loss-stop":
            markers.append({"t": ms(r["ts_us"]), "kind": "loss_stop", "ref": r["ts_us"]})
    for i in inc:
        if i["severity"] == "high" and i["kind"] not in ("loss_stop",):
            markers.append({"t": ms(i["t0"]), "kind": "incident", "ref": i["id"]})
    if first_us:
        d = (first_us // ls.DAY_US + 1) * ls.DAY_US
        while d < t_end:
            markers.append({"t": ms(d), "kind": "day", "ref": day_of(d)})
            d += ls.DAY_US
    markers.sort(key=lambda m: m["t"])

    # curve, columnar
    c = downsample(an["curve"], 1500)
    curve = {"t": [ms(t) for t in c["t_us"]], "pnl": c["pnl"].tolist(), "pnl_ex_artifact": c["pnl_ex_artifact"].tolist(),
             "lots": c["lots"].tolist()}

    # attribution with day labels and the loss-stop flag
    stop_days = {day_of(r["ts_us"]) for r in orders if r.get("op") == "loss-stop"}
    by_day = [{**r, "date": day_of(r["t0_us"]), "loss_stop": day_of(r["t0_us"]) in stop_days} for r in an["by_day"]]
    by_hour = [{**r, "t": ms(r["t0_us"])} for r in an["by_hour"]]
    for r in by_day + by_hour:
        r.pop("t0_us", None)

    # fills table
    keep = ["i", "t_us", "side", "price", "qty", "mid", "edge_bp", "mk_1", "mk_5", "mk_30", "mk_60", "mk_300", "wait_s",
            "pnl_after", "lots_after", "artifact", "reason", "timing"]
    ft = f[keep].copy() if len(f) else pd.DataFrame(columns=keep)
    ft["t"] = (ft["t_us"] // 1000).astype("int64")
    ft["caption"] = [fill_caption(r) for r in ft.itertuples()]
    ft = ft.drop(columns=["t_us"])
    fills_out = ft.to_dict("records")

    actions = {o["order_id"]: o["action"] for o in orders if o.get("op") == "place" and o.get("action") and o.get("order_id")}
    markout = markout_table(f, actions, fee_bps)
    fun = funnel(orders, f)
    model = model_section(spec, history, agent_state, f, orders, intervals, fee_bps, t_end)

    bundle = {
        "meta": {"id": spec.id, "source": spec.source, "symbol": spec.symbol, "policy": spec.policy,
                 "lot_usd": spec.lot_usd, "q_max": spec.q_max, "max_loss": spec.max_loss, "fee_bps": fee_bps,
                 "built_ms": ms(now_us), "thresholds": th.to_dict(), "first_ms": ms(first_us) if first_us else None,
                 "last_ms": ms(t_end) if t_end else None,
                 "label": ("TESTNET: execution test, not a result" if spec.source == "testnet"
                           else "PAPER: real market data, simulated fills")},
        "now": now, "curve": curve, "markers": markers,
        "states": {n: [{"t0": ms(iv["t0"]), "t1": ms(iv["t1"]), "state": iv["state"], "detail": iv.get("detail")}
                       for iv in intervals[n]] for n in ("bid", "ask")},
        "uptime": ls.uptime(intervals), "uptime_24h": ls.uptime(intervals, t0=now_us - 24 * 3600 * US, t1=now_us),
        "attribution": {"total": att, "by_day": by_day, "by_hour": by_hour,
                        "counts": an["counts"], "thresholds": th.to_dict()},
        "fills": fills_out, "markout": markout, "funnel": fun, "wait_terciles": wait_terciles(f),
        "incidents": [{**i, "t0": ms(i["t0"]), "t1": ms(i["t1"]), "id": i["id"]} for i in inc],
        "model": model,
    }
    bundle["takeaways"], bundle["headline"] = takeaways(spec, bundle, an, f, intervals, status, now_us)
    attribution_raw = bundle["attribution"]
    bundle = clean(bundle)
    bundle["attribution"] = clean(attribution_raw, 12)       # the five terms must still sum to net to 1e-6
    # size guard: thin the curve and the fills table until it fits
    for _ in range(4):
        if len(json.dumps(bundle, separators=(",", ":"))) <= MAX_BYTES:
            break
        for k in bundle["curve"]:
            bundle["curve"][k] = bundle["curve"][k][::2]
        bundle["model"]["history"] = bundle["model"]["history"][::2]
        bundle["fills"] = [{k: v for k, v in r.items() if k not in ("mk_1", "mk_5", "reason", "caption")} for r in bundle["fills"]]
    if tapes_out is not None:
        tapes_out.update(build_tapes(spec, fills, an, inc, orders, now_us, book))
    return bundle


# ---------------------------------------------------------------------- sentences (Python writes every finding)
def takeaways(spec: Spec, b: dict, an: dict, f: pd.DataFrame, intervals: dict, status: dict, now_us: int):
    att = an["attribution"]
    q_max = spec.q_max
    n = len(f)
    tk: dict = {}
    nruns = max(1, sum(1 for m in b["markers"] if m["kind"] == "restart"))
    rest = att["net"] - att["fees"] - att["artifact"]
    net_ex = att["net"] - att["artifact"]
    if n == 0:
        tk["cum_pnl"] = "No fills in this session yet, so there is no P&L to show."
    else:
        tk["cum_pnl"] = (f"Net {att['net']:+.2f} USDT over {n} fills ({net_ex:+.2f} without artifacts), kept as one "
                         f"curve across {nruns} run{'s' if nruns != 1 else ''}; fees are estimated.")
    tk["waterfall"] = (f"Of the {att['net']:+.2f} USDT net, fees are {att['fees']:+.2f}, artifacts {att['artifact']:+.2f}, "
                       f"and everything else {rest:+.2f} (edge {att['edge']:+.2f}, adverse selection {att['adverse']:+.2f}, "
                       f"carry {att['carry']:+.2f}).") if n else "Nothing to attribute yet: no fills."
    worst = f.loc[(f["edge_usd"]).idxmin()] if n else None
    cost_inc = [i for i in b["incidents"] if i.get("cost_usd")]
    if cost_inc:
        top = max(cost_inc, key=lambda i: i["cost_usd"])
        tk["worst_fills"] = f"The costliest single event: {top['sentence']}"
    elif worst is not None:
        tk["worst_fills"] = (f"The worst fill cost {-worst['edge_usd']:.2f} USDT against its own mid "
                             f"({worst['edge_bp']:.1f} bp); no fill looks like an artifact.")
    else:
        tk["worst_fills"] = "No fills yet, so there is no worst fill."
    tk["attr_time"] = ("Each bar is one UTC hour of signed edge, adverse selection, carry, fees and artifacts; the line is their sum."
                       if n else "No fills yet.")
    tk["day_table"] = (f"{len(b['attribution']['by_day'])} UTC day(s); a day with 'loss stop: yes' hit the "
                       f"{spec.max_loss:g} USDT daily limit.") if n else "No fills yet."
    now = b["now"]
    if not now["state_logged"] and not b["states"]["bid"]:
        tk["state_strip"] = ("The quote-state log starts at the next trader restart; until then the state shown is inferred "
                             "from the status file, and reasons for idle time are not recorded.")
    else:
        up = {(u["side"], u["state"]): u["share"] for u in b["uptime"]}
        tk["state_strip"] = ("Share of observed time quoting: bid {:.0%}, ask {:.0%}.".format(
            up.get(("bid", "QUOTING"), 0.0), up.get(("ask", "QUOTING"), 0.0)))
    m60 = [r for r in b["markout"] if r["group"] == "all" and r["h_s"] == 60]
    if m60:
        r = m60[0]
        tk["markout"] = (f"60 s after a typical fill the mid sits {r['bp']:+.2f} bp from the fill price (n = {r['n']}), "
                         f"against a maker fee of {spec.lot_usd and b['meta']['fee_bps']:g} bp; "
                         f"{an['counts']['artifact_fills']} artifact fill(s) are left out.")
    else:
        tk["markout"] = "No markouts yet: no fill has a clean 60 s window in the recorded feed."
    eb = f.loc[~f["artifact"], "edge_bp"].dropna() if n else pd.Series(dtype=float)
    tk["edge_hist"] = (f"Median edge at fill {eb.median():+.2f} bp over {len(eb)} fills; "
                       f"{an['counts']['artifact_fills']} artifact(s) are off scale.") if len(eb) else "No edge statistics yet."
    w = f["wait_s"].dropna() if n else pd.Series(dtype=float)
    tk["queue_wait"] = (f"Median queue wait {w.median():.1f} s over {len(w)} fills with exchange timing.") if len(w) else (
        "Queue wait needs exchange fill times, which the trader logs from its next restart.")
    fu = b["funnel"]
    tk["funnel"] = (f"{fu['placed']} orders placed, {fu['cancelled']} cancelled, {fu['rejected']} rejected, "
                    f"{fu['filled']} filled.")
    tk["fills_table"] = "Click a fill to open the tape around it." if n else "No fills yet."
    mo = b["model"]
    if spec.policy == "join":
        tk["arm_strip"] = tk["arm_scores"] = tk["calibration"] = tk["why_out"] = "Fixed policy: always join the best price. No model decisions."
    else:
        sw = mo["switches"]
        tk["arm_strip"] = f"Live arm {mo['live_arm']}, {sw} switch{'es' if sw != 1 else ''} in the recorded history."
        tk["arm_scores"] = "Each line is one arm's decayed interval score in bp; the zero line is break-even."
        tk["calibration"] = ("Predicted edge against the realised 60 s markout net of fee, bucketed." if mo["calibration"]
                             else "No fills carry a prediction yet, so predicted and realised edge cannot be compared.")
        best = mo["best_score_bp"]
        share = mo["policy_out_share"]
        if best is not None and best < 0:
            tk["why_out"] = (f"Every arm scores below 0 bp (best {best:+.2f} bp), so the agent quotes nothing"
                             + (f"; it stayed out {share:.0%} of the logged time." if share is not None else "."))
        elif best is not None:
            tk["why_out"] = f"The best arm scores {best:+.2f} bp against an entry threshold of 0 bp."
        else:
            tk["why_out"] = "No arm scores recorded yet."
    # headline
    lots = now["lots"]
    ss = state_sentence(now["state"], q_max, lots) if now["state"] else "no state recorded"
    label = f"{spec.source} {spec.symbol} {spec.policy}"
    if n:
        head = (f"{label}: net {att['net']:+.2f} USDT ({net_ex:+.2f} without artifacts) on {n} fills. {ss}. "
                f"{now['open_incidents']} open incident{'s' if now['open_incidents'] != 1 else ''}.")
    else:
        head = f"{label}: no fills yet. {ss}."
    return tk, head


# ---------------------------------------------------------------------- tape files
def build_tapes(spec: Spec, fills: pd.DataFrame, an: dict, inc: list[dict], orders: list[dict], now_us: int,
                book: Optional[pd.DataFrame] = None) -> dict:
    """One tape per UTC day: the touch, trades and our own orders around each fill and incident."""
    f = an["fills"]
    trades = load_feed(spec.feed, "trades", int(f["t_us"].min()) - 400 * US if len(f) else None)
    pts = [(int(r["t_us"]), r["i"], abs(r["edge_usd"])) for _, r in f.iterrows()] if len(f) else []
    inc_t = [(i["t0"], None) for i in inc]
    days = sorted({day_of(t) for t, *_ in pts} | {day_of(i["t0"]) for i in inc})
    out = {}
    for day in days:
        d0 = int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * US)
        d1 = d0 + ls.DAY_US
        day_pts = [p for p in pts if d0 <= p[0] < d1]
        day_inc = [i for i in inc if d0 <= i["t0"] < d1]
        note = None
        for attempt in range(2):
            times = [p[0] for p in day_pts] + [i["t0"] for i in day_inc]
            wins = [w for w in ls.tape_windows(times)]
            tape = _tape(spec, wins, orders, f, book, trades)
            tape.update(id=spec.id, date=day, note=note)
            tape = clean(tape)
            if len(json.dumps(tape, separators=(",", ":"))) <= MAX_BYTES or attempt == 1:
                break
            top = sorted(day_pts, key=lambda p: -p[2])[:200]
            day_pts = top
            day_inc = [i for i in day_inc if i["severity"] == "high"]
            note = "Tape thinned to the high-severity incidents and the 200 fills with the largest absolute edge (size limit)."
        out[day] = tape
    return out


def _tape(spec: Spec, wins: list[tuple[int, int]], orders: list[dict], f: pd.DataFrame, book: pd.DataFrame,
          trades: pd.DataFrame) -> dict:
    if not wins:
        return {"windows": []}
    out = []
    for a, b in wins:
        bk = book[(book["recv_us"] >= a) & (book["recv_us"] <= b)] if len(book) else book
        touch = []
        if len(bk):
            sec = bk.assign(s=bk["recv_us"] // US).groupby("s").tail(1)
            last = None
            for r in sec.itertuples():
                cur = (r.bid, r.ask, r.bid_qty, r.ask_qty)
                if cur != last:
                    touch.append([ms(r.recv_us), *cur])
                    last = cur
        tr = trades[(trades["recv_us"] >= a) & (trades["recv_us"] <= b)] if len(trades) else trades
        trd = [[ms(r.recv_us), r.price, r.qty, int(r.side)] for r in tr.itertuples()][:600]
        out.append({"t0": ms(a), "t1": ms(b), "touch": touch, "trades": trd, "orders": _order_segments(orders, f, a, b)})
    return {"windows": out}


def _order_segments(orders: list[dict], f: pd.DataFrame, a: int, b: int) -> list[dict]:
    """Our own orders as {side, price, t_place, t_end, end} where they overlap [a, b]."""
    ends = {}
    for o in orders:
        if o.get("op") in ("cancel", "cancel-miss") and o.get("order_id") is not None:
            ends[o["order_id"]] = (o["ts_us"], "cancel")
    if len(f):
        for _, r in f.iterrows():
            if r.get("order_id") == r.get("order_id") and r["order_id"] is not None and r["how"] != "partial":
                ends[r["order_id"]] = (int(r["t_us"]), "fill")
    segs = []
    for o in orders:
        if o.get("op") != "place" or o.get("order_id") is None:
            continue
        t_end, end = ends.get(o["order_id"], (b, "open"))
        if t_end < a or o["ts_us"] > b:
            continue
        segs.append({"side": o["side"], "price": float(o["price"]), "t_place": ms(o["ts_us"]), "t_end": ms(t_end), "end": end})
    for o in orders:
        if o.get("op") == "reject" and a <= o["ts_us"] <= b:
            segs.append({"side": o["side"], "price": float(o["price"]), "t_place": ms(o["ts_us"]),
                         "t_end": ms(o["ts_us"]), "end": "reject"})
    return segs[:400]


# ---------------------------------------------------------------------- writing
def _write(path: Path, text: str, out_root: Path) -> None:
    path = path.resolve()
    if out_root.resolve() not in path.parents:
        raise ValueError(f"refusing to write outside {out_root}: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def build(base: Path = Path("."), now_us: Optional[int] = None, cfg: Optional[dict] = None) -> list[dict]:
    """Build every session bundle, the session list and the tape files. Returns the session list."""
    base = Path(base)
    out = base / "dashboard" / "live"
    now_us = now_us or int(time.time() * US)
    sessions = []
    wanted = {"sessions.js"}
    for spec in discover(base, cfg):
        tapes: dict = {}
        try:
            b = build_bundle(base, spec, now_us, tapes)
        except Exception as e:                              # noqa: BLE001 - one bad session must not hide the others
            print(f"session {spec.id}: build failed: {e!r}", flush=True)
            continue
        js = f'window.SESSION_DATA = window.SESSION_DATA || {{}};\nwindow.SESSION_DATA["{spec.id}"] = {json.dumps(b, separators=(",", ":"))};\n'
        name = f"session-{spec.id}.js"
        _write(out / name, js, out)
        wanted.add(name)
        for day, t in tapes.items():
            tn = f"tape-{spec.id}-{day}.js"
            _write(out / tn, f'window.TAPES = window.TAPES || {{}};\nwindow.TAPES["{spec.id}|{day}"] = {json.dumps(t, separators=(",", ":"))};\n', out)
            wanted.add(tn)
        m = b["meta"]
        sessions.append({"id": spec.id, "source": spec.source, "symbol": spec.symbol, "policy": spec.policy,
                         "first_ms": m["first_ms"], "last_ms": m["last_ms"], "n_fills": len(b["fills"])})
    _write(out / "sessions.js", "window.SESSIONS = " + json.dumps(sessions, separators=(",", ":")) + ";\n", out)
    for f in list(out.glob("session-*.js")) + list(out.glob("tape-*.js")):   # drop files of sessions that are gone
        if f.name not in wanted:
            f.unlink()
    return sessions


_last_build = 0.0


def build_if_due(base: Path = Path("."), every_s: float = HEAVY_EVERY_S) -> bool:
    """For the supervisor's minute loop: heavy work at most every ``every_s``."""
    global _last_build
    now = time.time()
    if now - _last_build < every_s:
        return False
    _last_build = now
    build(base)
    return True


if __name__ == "__main__":
    t = time.time()
    s = build(Path("."))
    print(f"{len(s)} session(s) in {time.time() - t:.1f} s: " + ", ".join(f"{x['id']} ({x['n_fills']} fills)" for x in s))
