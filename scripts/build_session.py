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
from mm.agent import MENU, START_ARM, AgentConfig
from mm.queue_sim import QSConfig

US = ls.US
MAX_BYTES = 1_500_000
HEAVY_EVERY_S = 300
DEFAULTS = {"lot_usd": 100.0, "q_max": 10, "max_loss": 20.0}
MARKOUT_GROUPS = ("all", "buy", "sell", "JOIN", "BACK")
# the range buttons of the page: key -> (hours, label that every sentence of that range carries)
RANGES = {"6h": (6, "the last 6 h"), "24h": (24, "the last 24 h"), "3d": (72, "the last 3 days"), "all": (None, "all time")}
OPEN_SEVERITIES = ("high", "medium")
REPLACE_MAX_GAP_S = 120.0       # a longer pause between two placements is a stop or a restart, not a replacement
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
        return "daily loss stop, holds until the next UTC day"
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


def state_reason(s: dict, q_max: int, lots, max_loss: float) -> Optional[str]:   # noqa: ARG001
    """Python's sentence for the detail of a quote state (the page shows it as written). Only states whose
    detail is easy to misread get one; the page formats the rest itself."""
    if s.get("state") != "LOSS_STOP":
        return None
    d = s.get("detail") if isinstance(s.get("detail"), dict) else {}
    since = f"fired at {hhmm(s['since_us'])}, " if s.get("since_us") else ""
    day = d.get("pnl_day")
    lim = d.get("max_loss", max_loss)
    if day is None:
        return f"daily loss stop ({since}holds until the next UTC day)"
    inside = "" if day < -lim else f", now inside the limit of -{lim:g}"
    return f"daily loss stop: the day's P&L is {day:+.2f} USDT{inside}; {since}holds until the next UTC day"


def last_state(intervals: dict, status_state: dict, stop_us: Optional[int] = None) -> dict:
    """Per side, the last logged interval when there is one; otherwise the status file's state, then inference.
    A loss stop is "since" the moment it fired (the latest loss-stop order of that UTC day), not since the last restart
    that cut the state log into two intervals."""
    out = {}
    for name in ("bid", "ask"):
        ivs = intervals.get(name) or []
        if ivs:
            iv = ivs[-1]
            since = int(iv["t0"])
            if iv["state"] == "LOSS_STOP" and stop_us and stop_us // ls.DAY_US == since // ls.DAY_US:
                since = min(since, int(stop_us))
            out[name] = {"state": iv["state"], "detail": iv.get("detail"), "since_us": since}
        elif (status_state or {}).get(name):
            out[name] = status_state[name]
    return out


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
    gaps = []                                               # time between two placements on the same side
    for side in (1, -1):
        t = sorted(o["ts_us"] for o in orders if o.get("op") == "place" and o.get("side") == side)
        gaps += [(b - a) / US for a, b in zip(t, t[1:]) if b - a <= REPLACE_MAX_GAP_S * US]
    return {"placed": ops.count("place"), "cancelled": ops.count("cancel"), "rejected": len(rej),
            "median_replace_s": float(np.median(gaps)) if len(gaps) >= 5 else None,
            "filled": int((fills["how"] != "partial").sum()) if len(fills) else 0,
            "partial": int((fills["how"] == "partial").sum()) if len(fills) else 0,
            "by_hour": [{"t": h * 3_600_000, **v} for h, v in sorted(by_hour.items())],
            "reject_reasons": [{"error": e, "n": n} for e, n in sorted(reasons.items(), key=lambda kv: -kv[1])]}


def caught_section(spec: Spec, inc: list[dict], fun: dict, an: dict, intervals: dict, att: dict) -> list[dict]:
    """What the execution test caught (showcase spec section 7). Only testnet sessions have one, and every row cites a
    count or an incident that is in this bundle: a finding with nothing to cite is left out, never invented.
    ``n`` and ``unit`` are the cited count; ``cites`` names the incident ids or the counter the row rests on."""
    if spec.source != "testnet":
        return []
    rows = []
    restarts = [i for i in inc if i["kind"] == "restart"]
    if restarts:
        rows.append({"id": "carry_state", "finding": "Position and the daily loss stop were not carried across restarts",
                     "status": "fixed", "task": "live spec L1b", "n": len(restarts), "unit": "restarts",
                     "evidence": restarts[0]["sentence"], "cites": {"kind": "incident", "ids": [restarts[0]["id"]]}})
    nb = [iv for name in ("bid", "ask") for iv in intervals.get(name, []) if iv["state"] == "NO_BALANCE"]
    if nb:
        rows.append({"id": "no_balance", "finding": "The trader returned silently when the balance check failed",
                     "status": "fixed", "task": "live spec L1 (NO_BALANCE)", "n": len(nb), "unit": "NO_BALANCE intervals",
                     "evidence": f"{len(nb)} intervals are now logged as NO_BALANCE instead of a silent return",
                     "cites": {"kind": "count", "key": "states.NO_BALANCE"}})
    post = sum(r["n"] for r in fun.get("reject_reasons", []) if "immediately match" in r["error"])
    if post:
        attempts = fun["placed"] + fun["rejected"]
        rows.append({"id": "post_only", "finding": "Post-only orders were rejected with \"would immediately match and take\"",
                     "status": "by design", "task": "a post-only order never takes liquidity", "n": post, "unit": "rejected orders",
                     "evidence": f"{post:,} of {attempts:,} order attempts were rejected this way; they are counted as rejects, never as fills",
                     "cites": {"kind": "count", "key": "funnel.reject_reasons"}})
    if restarts:
        rows.append({"id": "unclean_restart", "finding": "The trader restarted without a clean stop", "status": "open", "task": None,
                     "n": len(restarts), "unit": "restarts without a clean stop",
                     "evidence": f"{len(restarts)} restart{'s' if len(restarts) != 1 else ''} logged as incidents",
                     "cites": {"kind": "incident", "ids": [i["id"] for i in restarts]}})
    n_art = int(an["counts"].get("artifact_fills", 0))
    if n_art:
        usd = float(att["artifact"])
        rows.append({"id": "book_glitch", "finding": "The testnet book printed fills far from the mid", "status": "by design",
                     "task": "a thin testnet book; kept out of the strategy numbers", "n": n_art, "unit": "book-glitch fills", "usd": usd,
                     "evidence": f"{n_art} fill{'s' if n_art != 1 else ''} at prices far from the mid, {usd:+.2f} USDT in total, excluded from the strategy numbers",
                     "cites": {"kind": "count", "key": "attribution.counts.artifact_fills"}})
    return rows


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
    min_fills = AgentConfig().min_arm_fills
    eligible = [a["arm"] for a in arms if a["fills"] is not None and a["fills"] >= min_fills]
    return {"fixed": spec.policy == "join", "live_arm": live_arm, "arm_strip": strip, "arms": arms, "history": hist,
            "calibration": calib, "policy_out_share": (tot_out / tot) if tot else None,
            "best_score_bp": max(scores) if scores else None, "entry_threshold_bp": 0.0,
            "min_arm_fills": min_fills, "eligible_arms": eligible, "start_arm": START_ARM,
            "switches": sum(1 for h in history if h.get("switched"))}


def why_out_sentence(mo: dict) -> str:
    """Why the agent is (or is not) quoting, in three cases: no arm is eligible yet, every eligible arm scores
    below zero, or an eligible arm is positive. The switch rule is ``AgentConfig.min_arm_fills`` shadow fills."""
    arms = [a for a in mo["arms"] if a.get("score_bp") is not None]
    if not arms:
        return "No arm scores recorded yet."
    seen = [a for a in arms if (a.get("fills") or 0) > 0]
    share = mo.get("policy_out_share")
    stayed = f"; it stayed out {share:.0%} of the logged time" if share is not None else ""
    need = mo["min_arm_fills"]
    elig = [a for a in arms if a["arm"] in mo["eligible_arms"]]
    if not elig:
        best = max(seen, key=lambda a: a["score_bp"]) if seen else None
        live = mo["live_arm"]
        where = (f"its most conservative setting, arm {live}" if live == mo["start_arm"]
                 else f"its current setting, arm {live}")
        so_far = (f"best so far: arm {best['arm']}, {best['score_bp']:+.2f} bp on {best['fills']:.1f} fills" if best
                  else "none has a shadow fill yet")
        return f"No setting has the {need:g} shadow fills needed to be chosen ({so_far}), so the agent stays on {where}{stayed}."
    best = max(elig, key=lambda a: a["score_bp"])
    if best["score_bp"] < mo["entry_threshold_bp"]:
        return (f"Every eligible arm scores below 0 bp (best: arm {best['arm']}, {best['score_bp']:+.2f} bp on "
                f"{best['fills']:.1f} fills), so the agent quotes nothing{stayed}.")
    return (f"The best eligible arm, {best['arm']}, scores {best['score_bp']:+.2f} bp on {best['fills']:.1f} fills against "
            f"an entry threshold of {mo['entry_threshold_bp']:g} bp; the live arm is {mo['live_arm']}{stayed}.")


def build_bundle(base: Path, spec: Spec, now_us: int, tapes_out: Optional[dict] = None,
                 chart_out: Optional[dict] = None) -> dict:
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
    inc = ls.incidents(an, intervals, orders, sessions, q_max=spec.q_max, max_loss=spec.max_loss, thresholds=th, t_end=t_end,
                       state_rows=states)
    f = an["fills"]
    first_us = int(f["t_us"].min()) if len(f) else None
    last_us = int(f["t_us"].max()) if len(f) else None
    att = an["attribution"]

    # now
    st_fallback = status.get("state") or (infer_state(status, spec.q_max) if status else {})
    st_now = {**st_fallback, **last_state(intervals, status.get("state") or {}, max((int(r["ts_us"]) for r in orders if r.get("op") == "loss-stop"), default=None))}      # a logged interval wins (B8)
    mid_now = an["mid_end"] or (status.get("pos") and 0) or 0
    lots_now = status.get("lots") if status.get("lots") is not None else (int(f["lots_after"].iloc[-1]) if len(f) else 0)
    for name in ("bid", "ask"):                              # Python writes the loss-stop wording (B9)
        if name in st_now:
            rs = state_reason(st_now[name], spec.q_max, lots_now, spec.max_loss)
            if rs:
                st_now[name] = {**st_now[name], "reason": rs}
    now = {"state": st_now, "lots": lots_now, "pos_usd": (status.get("pos", 0) or 0) * (mid_now or 0),
           "open": {"bid": (status.get("open") or {}).get("bid"), "ask": (status.get("open") or {}).get("ask")},
           "last_fill_ms": ms(last_us) if last_us else None, "process": process_info(base, spec, sessions, time.time()),
           "state_logged": bool(status.get("state")) or bool(intervals["bid"] or intervals["ask"]),
           "open_incidents": 0, "mid": mid_now or None}      # open_incidents is filled from by_range["24h"] below

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
    ft["dist_bp"] = (ft["price"] - ft["mid"]) / ft["mid"].where(ft["mid"] > 0) * 1e4     # signed in price terms: a sell under the mid is negative
    ft["caption"] = [fill_caption(r) for r in ft.itertuples()]
    ft = ft.drop(columns=["t_us"])
    fills_out = ft.to_dict("records")

    actions = {o["order_id"]: o["action"] for o in orders if o.get("op") == "place" and o.get("action") and o.get("order_id")}
    markout = markout_table(f, actions, fee_bps)
    fun = funnel(orders, f)
    model = model_section(spec, history, agent_state, f, orders, intervals, fee_bps, t_end)
    caught = caught_section(spec, inc, fun, an, intervals, att)

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
        "model": model, "caught": caught,
    }
    bundle["by_range"] = build_by_range(spec, bundle, an, f, intervals, t_end)
    bundle["now"]["open_incidents"] = bundle["by_range"]["24h"]["counts"]["open_incidents"]
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
    if chart_out is not None:
        chart_out.update(fills=f, book=book, orders=orders, curve=an["curve"], t_end=t_end,
                         ranges={k: (RANGES[k][0], v["label"]) for k, v in bundle["by_range"].items()},
                         pnl_sentences={k: v["takeaways"]["cum_pnl"] for k, v in bundle["by_range"].items()})
    return bundle


# ---------------------------------------------------------------------- sentences (Python writes every finding)
def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _window_sums(b: dict, an: dict, w0: Optional[int], end_ms: int, n: int) -> dict:
    """Attribution terms of a range, summed from the hourly buckets with the rule the page used to apply itself
    (an hour counts when it ends after the window starts). The whole session uses the exact totals."""
    keys = ("edge", "adverse", "carry", "fees", "artifact", "net", "fills", "notional")
    if w0 is None:
        a = an["attribution"]
        return {**{k: float(a[k]) for k in keys if k in a}, "fills": n}
    s = dict.fromkeys(keys, 0.0)
    for r in b["attribution"]["by_hour"]:
        if r["t"] + 3_600_000 > w0 and r["t"] <= end_ms:
            for k in keys:
                s[k] += r.get(k) or 0.0
    s["fills"] = int(s["fills"])
    return s


def _in_window(t_ms: pd.Series, w0: Optional[int], end_ms: int) -> pd.Series:
    return (t_ms <= end_ms) & ((t_ms >= w0) if w0 is not None else True)


def _worst_fill_sentence(f: pd.DataFrame, w0: Optional[int], end_ms: int, label: str) -> str:
    """About fills only: the fill with the lowest edge at fill plus 60 s markout in the range (what the table sorts by)."""
    if not len(f):
        return "No fills yet, so there is no worst fill."
    g = f[_in_window(f["t_us"] // 1000, w0, end_ms) & f["edge_bp"].notna()].copy()
    if g.empty:
        return f"No fill in {label} has a markout, so there is no worst fill."
    g["score"] = g["edge_bp"] + g["mk_60"].fillna(0.0)
    r = g.loc[g["score"].idxmin()]
    mk = (f" and {r['mk_60']:+.1f} bp 60 s later" if r["mk_60"] == r["mk_60"] else ", with no 60 s markout")
    glitch = " It is a book glitch fill." if r["artifact"] else ""
    return (f"The worst fill in {label}: {'sold' if r['side'] < 0 else 'bought'} {r['qty']:g} at {r['price']:g}, "
            f"{r['edge_bp']:+.1f} bp against its mid{mk} (edge plus 60 s: {r['score']:+.1f} bp).{glitch}")


def build_by_range(spec: Spec, b: dict, an: dict, f: pd.DataFrame, intervals: dict, t_end: int) -> dict:
    """Everything that depends on the range buttons, built once per range (spec section 9, rules 1 and 2).
    The page reads ``by_range[range]`` and never recomputes these numbers. The window ends at ``meta.last_ms``."""
    n = len(f)
    end_ms = ms(t_end)
    first_us = int(f["t_us"].min()) if n else None
    t_ms = f["t_us"] // 1000 if n else pd.Series(dtype="int64")
    out = {}
    for key, (hours, label) in RANGES.items():
        w0 = end_ms - hours * 3_600_000 if hours else None
        if hours is None and first_us:
            label = f"all time since {datetime.fromtimestamp(first_us / US, tz=timezone.utc).strftime('%d %b')}"
        s = _window_sums(b, an, w0, end_ms, n)
        net_ex = s["net"] - s["artifact"]
        inc = [i for i in b["incidents"] if (w0 is None or i["t0"] >= w0) and i["t0"] <= end_ms]
        n_open = sum(1 for i in inc if i["severity"] in OPEN_SEVERITIES)
        up = ls.uptime(intervals, t0=None if hours is None else t_end - hours * 3_600_000_000,
                       t1=None if hours is None else t_end)
        rows_q = [u for u in up if u["state"] == "QUOTING"]
        quoting = (sum(u["share"] for u in rows_q) / 2.0) if up else None
        shares = {u["side"]: u["share"] for u in rows_q}
        inw = _in_window(t_ms, w0, end_ms) if n else pd.Series(dtype=bool)
        n_art = int((inw & f["artifact"]).sum()) if n else 0
        tiles = {"net": s["net"], "net_ex_artifacts": net_ex, "edge": s["edge"], "adverse": s["adverse"], "carry": s["carry"],
                 "artifact": s["artifact"], "fees": s["fees"], "fills": s["fills"], "notional": s["notional"],
                 "quoting_share": quoting}
        counts = {"fills": s["fills"], "incidents": len(inc), "open_incidents": n_open, "artifact_fills": n_art}
        tk: dict = {}
        if n == 0:
            tk["cum_pnl"] = "No fills in this session yet, so there is no P&L to show."
            tk["waterfall"] = "Nothing to attribute yet: no fills."
        else:
            nruns = max(1, sum(1 for m in b["markers"] if m["kind"] == "restart" and (w0 is None or m["t"] >= w0)))
            if s["fills"] == 0:                          # no trades, but the position held still moves with the price
                tk["cum_pnl"] = (f"No fills in {label}; the net {s['net']:+.2f} USDT is the position already held moving with "
                                 f"the price. The curve is cumulative since the session began.")
            else:
                tk["cum_pnl"] = (f"In {label}: net {s['net']:+.2f} USDT over {s['fills']} fills ({net_ex:+.2f} without artifacts), "
                                 f"{nruns} run{'s' if nruns != 1 else ''}; fees are estimated. The curve is cumulative since "
                                 f"the session began.")
            rest = s["net"] - s["fees"] - s["artifact"]
            tk["waterfall"] = (f"Of the {s['net']:+.2f} USDT net in {label}, fees are {s['fees']:+.2f}, artifacts "
                               f"{s['artifact']:+.2f}, and everything else {rest:+.2f} (edge {s['edge']:+.2f}, adverse "
                               f"selection {s['adverse']:+.2f}, carry {s['carry']:+.2f}).")
        tk["worst_fills"] = _worst_fill_sentence(f, w0, end_ms, label)
        tk["pnl_summary"] = (f"Net {s['net']:+.2f} USDT in {label}, of which fees {s['fees']:+.2f} and book glitches "
                             f"{s['artifact']:+.2f}. Not a strategy result." if spec.source == "testnet" else
                             f"Net {s['net']:+.2f} USDT in {label}, of which fees {s['fees']:+.2f}.")
        eb = f.loc[inw & ~f["artifact"], "edge_bp"].dropna() if n else pd.Series(dtype=float)
        tk["edge_hist"] = (f"Median edge at fill {eb.median():+.2f} bp over {len(eb)} fills in {label}; "
                           f"{_plural(n_art, 'artifact')} off scale.") if len(eb) else f"No edge statistics for {label}."
        wv = f.loc[inw & ~f["artifact"], "wait_s"].dropna() if n else pd.Series(dtype=float)
        wv = wv[wv > 0]
        rep = b["funnel"].get("median_replace_s")
        if len(wv):
            tk["queue_wait"] = (f"Median order age at fill {wv.median():.1f} s over {len(wv)} fills in {label}: the time since "
                                f"the filled order was last placed"
                                + (f"; the trader replaces each order about every {rep:.0f} s, so this is not time in the queue."
                                   if rep else "; this is not time in the queue."))
        else:
            tk["queue_wait"] = f"No fill in {label} carries an exchange time, which the trader logs from its next restart."
        if not b["now"]["state_logged"] and not b["states"]["bid"]:
            tk["state_strip"] = ("The quote-state log starts at the next trader restart; until then the state shown is inferred "
                                 "from the status file, and reasons for idle time are not recorded.")
        elif up:
            tk["state_strip"] = (f"Share of observed time quoting in {label}: bid {shares.get('bid', 0.0):.0%}, "
                                 f"ask {shares.get('ask', 0.0):.0%}.")
        else:
            tk["state_strip"] = f"No quote state was recorded in {label}."
        ss = state_sentence(b["now"]["state"], spec.q_max, b["now"]["lots"]) if b["now"]["state"] else "no state recorded"
        src = f"{spec.source} {spec.symbol} {spec.policy}"
        if n == 0:
            head = f"{src}: no fills yet. {ss}. {_plural(n_open, 'open incident')} in {label}."
        else:
            head = (f"{src} ({label}): net {s['net']:+.2f} USDT ({net_ex:+.2f} without artifacts) on {s['fills']} fills. "
                    f"{ss}. {_plural(n_open, 'open incident')}.")
        out[key] = {"label": label, "tiles": tiles, "counts": counts, "takeaways": tk, "headline": head, "uptime": up}
    return out


def takeaways(spec: Spec, b: dict, an: dict, f: pd.DataFrame, intervals: dict, status: dict, now_us: int):
    """Sentences that do not depend on the range, plus the whole-session version of those that do (``by_range`` holds
    one set per range; the page prefers it)."""
    n = len(f)
    tk: dict = dict(b["by_range"]["all"]["takeaways"])
    tk["attr_time"] = ("Each bar is one UTC hour of signed edge, adverse selection, carry, fees and artifacts; the line is their sum."
                       if n else "No fills yet.")
    tk["day_table"] = (f"{len(b['attribution']['by_day'])} UTC day(s); a day with 'loss stop: yes' hit the "
                       f"{spec.max_loss:g} USDT daily limit.") if n else "No fills yet."
    m60 = [r for r in b["markout"] if r["group"] == "all" and r["h_s"] == 60]
    if m60:
        r = m60[0]
        tk["markout"] = (f"Over all time, 60 s after a typical fill the mid sits {r['bp']:+.2f} bp from the fill price (n = {r['n']}), "
                         f"against a maker fee of {b['meta']['fee_bps']:g} bp; "
                         f"{an['counts']['artifact_fills']} artifact fill(s) are left out.")
    else:
        tk["markout"] = "No markouts yet: no fill has a clean 60 s window in the recorded feed."
    fu = b["funnel"]
    tk["funnel"] = (f"Over all time: {fu['placed']} orders placed, {fu['cancelled']} cancelled, {fu['rejected']} rejected, "
                    f"{fu['filled']} filled.")
    tk["fills_table"] = "Click a fill to open the tape around it." if n else "No fills yet."
    nc = len(b.get("caught") or [])
    tk["caught"] = (f"{nc} finding{'s' if nc != 1 else ''} from this session, each with the count or incident it rests on." if nc
                    else "Nothing is recorded as caught for this session yet.")
    mo = b["model"]
    if spec.policy == "join":
        tk["arm_strip"] = tk["arm_scores"] = tk["calibration"] = tk["why_out"] = "Fixed policy: always join the best price. No model decisions."
    else:
        sw = mo["switches"]
        tk["arm_strip"] = f"Live arm {mo['live_arm']}, {sw} switch{'es' if sw != 1 else ''} in the recorded history."
        tk["arm_scores"] = "Each line is one arm's decayed interval score in bp; the zero line is break-even."
        tk["calibration"] = ("Predicted edge against the realised 60 s markout net of fee, bucketed." if mo["calibration"]
                             else "No fills carry a prediction yet, so predicted and realised edge cannot be compared.")
        tk["why_out"] = why_out_sentence(mo)
    return tk, b["by_range"]["all"]["headline"]


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


# ---------------------------------------------------------------------- the session chart file
def build_chart_file(spec: Spec, args: dict, now_us: int) -> str:
    """``window.SESSION_CHART["<id>"] = {...}`` (dashboard chart spec 7.2). Thinned to fewer buckets until it fits the
    size limit; numbers keep 12 significant digits so the width of a quote stays ask minus bid."""
    for nb in (500, 250, 125, 60):
        by_range = ls.chart_series(args["fills"], args["book"], args["orders"], args["curve"], t_end=args["t_end"],
                                   q_max=spec.q_max, source=spec.source, symbol=spec.symbol, policy=spec.policy,
                                   ranges=args["ranges"], pnl_sentences=args["pnl_sentences"] if spec.source == "paper" else None,
                                   max_buckets=nb)
        text = json.dumps(clean({"id": spec.id, "built_ms": ms(now_us), "by_range": by_range}, 12), separators=(",", ":"))
        if len(text) <= MAX_BYTES:
            break
    return f'window.SESSION_CHART = window.SESSION_CHART || {{}};\nwindow.SESSION_CHART["{spec.id}"] = {text};\n'


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
        chart_in: dict = {}
        try:
            b = build_bundle(base, spec, now_us, tapes, chart_in)
            chart_js = build_chart_file(spec, chart_in, now_us)
        except Exception as e:                              # noqa: BLE001 - one bad session must not hide the others
            print(f"session {spec.id}: build failed: {e!r}", flush=True)
            continue
        js = f'window.SESSION_DATA = window.SESSION_DATA || {{}};\nwindow.SESSION_DATA["{spec.id}"] = {json.dumps(b, separators=(",", ":"))};\n'
        name = f"session-{spec.id}.js"
        _write(out / name, js, out)
        wanted.add(name)
        _write(out / f"chart-{spec.id}.js", chart_js, out)
        wanted.add(f"chart-{spec.id}.js")
        for day, t in tapes.items():
            tn = f"tape-{spec.id}-{day}.js"
            _write(out / tn, f'window.TAPES = window.TAPES || {{}};\nwindow.TAPES["{spec.id}|{day}"] = {json.dumps(t, separators=(",", ":"))};\n', out)
            wanted.add(tn)
        m = b["meta"]
        sessions.append({"id": spec.id, "source": spec.source, "symbol": spec.symbol, "policy": spec.policy,
                         "first_ms": m["first_ms"], "last_ms": m["last_ms"], "n_fills": len(b["fills"])})
    _write(out / "sessions.js", "window.SESSIONS = " + json.dumps(sessions, separators=(",", ":")) + ";\n", out)
    for f in list(out.glob("session-*.js")) + list(out.glob("tape-*.js")) + list(out.glob("chart-*.js")):   # drop files of sessions that are gone
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
