"""Build a publishable copy of the dashboard (Dashboard Guide D12, --public step).

    python -m scripts.publish_dashboard                       # every non-demo run in dashboard/runs
    python -m scripts.publish_dashboard --runs qb-2026-11-12,wf-2026-11-12-q1
    python -m scripts.publish_dashboard --live-snapshot       # also a frozen, sanitised copy of the live sessions

Showcase spec section 8: without --live-snapshot nothing live is published. With it, dashboard_public/snapshot/ holds the
session bundles and session chart files (through allow-lists of keys), the sessions list and only the tape files the page opens (the curated
example and the days that have an incident). The Operations pages and their scripts, dashboard/live/status.js, .env and
data/ are never published. Every file written is scanned and the publish fails if it holds a path, a private address, the
host name, a process id field or a credential word.

Writes dashboard_public/: the page, its scripts, data.js, and pub-<run_id>.js copies of the chosen
runs (by default every non-demo run, pub-verdict, and the newest recorded-book bundle) with curves thinned to 30-minute points (demo runs are refused). The live strip never appears
on a published copy because it only runs when the page is served by the local server.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import socket
from datetime import datetime, timezone
from pathlib import Path

from mm.report import JS_PREFIX, public_bundle, validate_bundle

DASH = Path("dashboard")
TAPE_MAX_BYTES = 1_500_000
# Operations (live spec L10) is the owner's view of the PC: host, processes, command lines. Not in the public copy at all.
OPERATIONS_SCRIPTS = ("js/live.js", "js/views/pcstatus.js", "js/views/lv_health.js", "js/views/live.js")

# Allow-list of the keys a published session bundle may keep (live spec 6.2 plus the showcase additions). None = any value.
_FILL = {k: None for k in ("i", "t", "side", "price", "qty", "mid", "edge_bp", "mk_1", "mk_5", "mk_30", "mk_60", "mk_300", "wait_s",
                           "pnl_after", "lots_after", "artifact", "reason", "timing", "caption", "dist_bp")}
_STATES = [{k: None for k in ("t0", "t1", "state", "detail")}]
SESSION_ALLOW = {
    "meta": {k: None for k in ("id", "source", "symbol", "policy", "lot_usd", "q_max", "max_loss", "fee_bps", "built_ms", "thresholds",
                               "first_ms", "last_ms", "label")},
    "now": {"state": None, "lots": None, "pos_usd": None, "open": None, "last_fill_ms": None, "state_logged": None,
            "open_incidents": None, "mid": None, "process": {"running": None, "uptime_s": None, "restarts": None}},
    "curve": {k: None for k in ("t", "pnl", "pnl_ex_artifact", "lots")},
    "markers": [{"t": None, "kind": None, "ref": None}],
    "states": {"bid": _STATES, "ask": _STATES},
    "uptime": [{k: None for k in ("side", "state", "seconds", "share")}],
    "uptime_24h": [{k: None for k in ("side", "state", "seconds", "share")}],
    "attribution": {"total": None, "by_day": None, "by_hour": None, "counts": None, "thresholds": None},
    "fills": [_FILL],
    "markout": [{k: None for k in ("group", "h_s", "bp", "se", "n")}],
    "funnel": {k: None for k in ("placed", "cancelled", "rejected", "median_replace_s", "filled", "partial", "by_hour", "reject_reasons")},
    "wait_terciles": None,
    "incidents": [{k: None for k in ("id", "kind", "severity", "t0", "t1", "sentence", "fills", "cost_usd")}],
    "model": {k: None for k in ("fixed", "live_arm", "arm_strip", "arms", "history", "calibration", "policy_out_share", "best_score_bp",
                                "entry_threshold_bp", "min_arm_fills", "eligible_arms", "start_arm", "switches")},
    "caught": [{k: None for k in ("id", "finding", "status", "task", "n", "unit", "usd", "evidence", "cites")}],
    "by_range": None, "takeaways": None, "headline": None,
}
SESSION_LIST_ALLOW = [{k: None for k in ("id", "source", "symbol", "policy", "first_ms", "last_ms", "n_fills")}]
# The session chart file (dashboard chart spec 7.2 and 8): exactly these keys, per range. Published only with --live-snapshot.
_CHART_RANGE = {k: None for k in ("panels", "t", "mid", "bid_bp", "ask_bp", "lots", "max_abs_lots", "fills_cum", "buys_cum", "sells_cum",
                                  "width_bp", "pnl", "pnl_ex_artifact", "pnl_peak", "fill_ids", "off_scale", "empty")}
_CHART_RANGE.update(axes={"price": None, "bp": None},
                    titles={k: None for k in ("card", "sub", "price", "quotes", "inventory", "pnl")},
                    events=[{k: None for k in ("panel", "t", "y", "text")}])
CHART_ALLOW = {"id": None, "built_ms": None, "by_range": {r: _CHART_RANGE for r in ("6h", "24h", "3d", "all")}}
TAPE_ALLOW = {"windows": [{"t0": None, "t1": None, "touch": None, "trades": None, "orders": None}], "id": None, "date": None, "note": None}


def allow(obj, spec):
    """``obj`` reduced to the keys ``spec`` names (a dict of sub-specs, a one-item list for a list of records, None for a leaf)."""
    if spec is None:
        return obj
    if isinstance(spec, list):
        return [allow(x, spec[0]) for x in obj] if isinstance(obj, list) else obj
    if isinstance(obj, dict):
        return {k: allow(obj[k], s) for k, s in spec.items() if k in obj}
    return obj


# What must never reach a published file (showcase spec section 8).
_PATTERNS = {
    "a Windows path": re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:(?:\\{1,4}|/)[A-Za-z0-9_.$ -]"),
    "a Unix path": re.compile(r"(?<![\w.:/-])/(?:home|Users|usr|var|etc|opt|root|mnt|tmp|srv|private)/[\w.-]"),
    "a private IP address": re.compile(r"(?<![\d.])(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|"
                                       r"172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(?![\d])"),
    "a process id field": re.compile(r'"(?:pid|ppid|process_id)"\s*:'),
    "a credential word": re.compile(r"apikey|api_key|secret|signature", re.I),
}


def host_names() -> list[str]:
    names = {socket.gethostname(), platform.node(), os.environ.get("COMPUTERNAME", ""), os.environ.get("HOSTNAME", "")}
    return sorted(n for n in names if n and len(n) >= 4)


def scan_for_leaks(root: Path, hosts: list[str] | None = None) -> list[str]:
    """Every problem found in the files under ``root``, as 'file: what'. Empty when the copy is clean."""
    hosts = host_names() if hosts is None else hosts
    host_re = re.compile("|".join(re.escape(h) for h in hosts), re.I) if hosts else None
    out = []
    for f in sorted(p for p in root.rglob("*") if p.is_file()):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for what, rx in _PATTERNS.items():
            m = rx.search(text)
            if m:
                out.append(f"{f.relative_to(root).as_posix()}: {what} ('{text[max(0, m.start() - 20):m.end() + 20]}')".replace("\n", " "))
        if host_re and (m := host_re.search(text)):
            out.append(f"{f.relative_to(root).as_posix()}: the host name '{m.group(0)}'")
    return out


def strip_operations(html: str) -> str:
    """The public page without the Operations tab, views and scripts."""
    a = html.index('  <div class="tab-wrap" data-tab="l-health">')
    b = html.index('  <div class="tab-wrap" data-tab="book">')
    html = html[:a] + html[b:]
    html = re.sub(r"[ \t]*<a href=\"#l-health\"[^>]*>Operations</a>\r?\n", "", html)
    for s in OPERATIONS_SCRIPTS:
        html = html.replace(f'<script src="{s}"></script>\n', "").replace(f'<script src="{s}"></script>', "")
    return html


def load_js_object(path: Path):
    s = path.read_text(encoding="utf-8")
    return json.loads(s[s.index("= {") + 2: s.rstrip().rstrip(";").rindex("}") + 1])


def write_snapshot(out: Path) -> str:
    """Write out/snapshot/ from dashboard/live through the allow-lists. Returns the 'YYYY-MM-DD HH:MM' the snapshot was built."""
    live, snap = DASH / "live", out / "snapshot"
    txt = (live / "sessions.js").read_text(encoding="utf-8")
    listed = json.loads(txt[txt.index("["): txt.rindex("]") + 1])
    snap.mkdir(parents=True)
    kept, built, incident_days = [], [], {}
    for entry in listed:
        sid = entry["id"]
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", sid):
            raise SystemExit(f"snapshot: refusing the session id {sid!r}")
        b = allow(load_js_object(live / f"session-{sid}.js"), SESSION_ALLOW)
        (snap / f"session-{sid}.js").write_text(
            f'window.SESSION_DATA = window.SESSION_DATA || {{}};\nwindow.SESSION_DATA["{sid}"] = {json.dumps(b, separators=(",", ":"))};\n', encoding="utf-8")
        chart = live / f"chart-{sid}.js"
        if chart.exists():                                                  # the session chart, through its own allow-list
            c = allow(load_js_object(chart), CHART_ALLOW)
            (snap / chart.name).write_text(
                f'window.SESSION_CHART = window.SESSION_CHART || {{}};\nwindow.SESSION_CHART["{sid}"] = {json.dumps(c, separators=(",", ":"))};\n', encoding="utf-8")
        kept.append(allow(entry, SESSION_LIST_ALLOW[0]))
        built.append((b.get("meta") or {}).get("built_ms") or 0)
        if (b.get("meta") or {}).get("source") == "testnet":
            incident_days[sid] = {datetime.fromtimestamp(i["t0"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d") for i in b.get("incidents", [])}
    (snap / "sessions.js").write_text("window.SESSIONS = " + json.dumps(kept, separators=(",", ":")) + ";\n", encoding="utf-8")
    # the tape files the page opens: the curated example, and the days that have an incident on the Execution test page
    want = {(sid, d) for sid, days in incident_days.items() for d in days}
    story = DASH / "runs" / "pub-story.js"
    if story.exists():
        ex = (load_js_object(story).get("tape_example") or {})
        if ex.get("session") and ex.get("day"):
            want.add((ex["session"], ex["day"]))
    for sid, day in sorted(want):
        src = live / f"tape-{sid}-{day}.js"
        if not src.exists():
            continue
        if src.stat().st_size > TAPE_MAX_BYTES:
            print(f"snapshot: skip {src.name}: above {TAPE_MAX_BYTES / 1e6:.1f} MB")
            continue
        tape = allow(load_js_object(src), TAPE_ALLOW)
        (snap / src.name).write_text(f'window.TAPES = window.TAPES || {{}};\nwindow.TAPES["{sid}|{day}"] = {json.dumps(tape, separators=(",", ":"))};\n', encoding="utf-8")
    return datetime.fromtimestamp(max(built) / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M") if built and max(built) else ""


def load_run(path: Path) -> dict:
    s = path.read_text(encoding="utf-8")
    return json.loads(s[s.index("= {") + 2: s.rstrip().rstrip(";").rindex("}") + 1])


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m scripts.publish_dashboard")
    ap.add_argument("--runs", default=None, help="comma-separated run ids (default: every non-demo run)")
    ap.add_argument("--out", default="dashboard_public")
    ap.add_argument("--every-min", type=int, default=30)
    ap.add_argument("--live-snapshot", action="store_true", help="also publish a frozen, sanitised copy of the live sessions under snapshot/")
    args = ap.parse_args(argv)
    idx_txt = (DASH / "runs" / "index.js").read_text(encoding="utf-8")
    index = json.loads(idx_txt[idx_txt.index("["): idx_txt.rindex("]") + 1])
    if args.runs:
        wanted = args.runs.split(",")
    else:                                   # every non-demo run, the Verdict bundle, and only the newest book bundle
        books = sorted(r["run_id"] for r in index if r["kind"] == "book")
        wanted = [r["run_id"] for r in index if r["kind"] != "demo" and (r["kind"] != "book" or r["run_id"] == books[-1])]
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    (out / "runs").mkdir(parents=True)
    shutil.copytree(DASH / "js", out / "js")
    shutil.copy2(DASH / "data.js", out / "data.js")
    for s in OPERATIONS_SCRIPTS:                                  # Operations is not in the public copy at all
        (out / s).unlink(missing_ok=True)
    snapshot_at = write_snapshot(out) if args.live_snapshot else ""
    html = strip_operations((DASH / "index.html").read_text(encoding="utf-8"))
    flag = "window.PUBLIC_SITE = true;" + (f' window.SNAPSHOT_AT = "{snapshot_at}";' if snapshot_at else "")
    html = html.replace('<script src="data.js"></script>', f'<script>{flag}</script>\n<script src="data.js"></script>', 1)
    (out / "index.html").write_text(html, encoding="utf-8")
    from scripts import build_story                               # the Story bundle: with the snapshot's live facts, or without any
    story = build_story.build_story(DASH.resolve().parent, live=args.live_snapshot)
    build_story.write_story(story, out / "runs")
    pub_index = []
    for rid in wanted:
        entry = next((r for r in index if r["run_id"] == rid), None)
        if entry is None:
            print(f"skip {rid}: not in dashboard/runs/index.js")
            continue
        b = public_bundle(load_run(DASH / "runs" / f"{rid}.js"), every_min=args.every_min)
        problems = validate_bundle(b)
        if problems:
            raise SystemExit(f"{rid}: invalid bundle: {problems[:3]}")
        text = f'{JS_PREFIX}\nwindow.RUNS["{b["run_id"]}"] = {json.dumps(b, separators=(",", ":"))};\n'
        (out / "runs" / f"{b['run_id']}.js").write_text(text, encoding="utf-8")
        pub_index.append({**entry, "run_id": b["run_id"]})
        print(f"{rid} -> runs/{b['run_id']}.js ({len(text) / 1e6:.1f} MB)")
    (out / "runs" / "index.js").write_text("window.RUN_INDEX = " + json.dumps(pub_index, indent=1) + ";\n", encoding="utf-8")
    leaks = scan_for_leaks(out)
    if leaks:
        shutil.rmtree(out)                                        # nothing partial is left behind
        raise SystemExit("publish refused, the copy would leak:\n  " + "\n  ".join(leaks[:10]))
    big = [p for p in out.rglob("*") if p.is_file() and p.stat().st_size > 3e6 and p.name != "data.js"]
    if big:
        print("warning: files above 3 MB:", ", ".join(str(p) for p in big))
    print(f"publishable copy -> {out}/")


if __name__ == "__main__":
    main()
