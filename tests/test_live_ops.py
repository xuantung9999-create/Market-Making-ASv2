"""24/7 ops: live status builder and the supervisor's restart logic."""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from scripts.build_live import build
from scripts.supervise_live import Supervisor

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
NOW_US = int(NOW.timestamp() * 1e6)
NOW_MS = NOW_US // 1000


def _write_testnet(base: Path):
    d = base / "data/testnet/BTCUSDT"
    d.mkdir(parents=True)
    (d / "status.json").write_text(json.dumps({"symbol": "BTCUSDT", "pos": 0.002, "lots": 1, "pnl": 1.5, "fills": 2,
                                                "rejects": 1, "stopped": False, "open": {"bid": 49999.99, "ask": None},
                                                "policy": "join"}))
    fills = [{"ts_us": NOW_US - 3_600_000_000, "side": 1, "price": 50000.0, "qty": 0.001, "mid": 50000.01, "pos": 0.001, "pnl": 0.5},
             {"ts_us": NOW_US - 60_000_000, "side": 1, "price": 50000.0, "qty": 0.001, "mid": 50001.0, "pos": 0.002, "pnl": 1.5},
             {"ts_us": NOW_US - 30 * 86_400_000_000, "side": 1, "price": 1.0, "qty": 1, "mid": 1, "pos": 1, "pnl": 0}]   # too old
    (d / "fills_2026-11-13.jsonl").write_text("\n".join(json.dumps(f) for f in fills) + "\nnot json\n")
    orders = [{"ts_us": NOW_US - 120_000_000, "op": "place", "side": 1, "price": "50000.00"},
              {"ts_us": NOW_US - 100_000_000, "op": "reject", "side": -1, "price": "49999.00", "error": "would cross"}]
    (d / "orders_2026-11-13.jsonl").write_text("\n".join(json.dumps(o) for o in orders) + "\n")
    (base / "data/testnet/feed").mkdir()            # ignored folders
    (base / "data/testnet/state").mkdir()


def _write_recorder(base: Path):
    for kind in ("book", "trades"):
        d = base / f"data/live/SKLUSDT/{kind}"
        d.mkdir(parents=True)
        times = [NOW_MS - 3_600_000 + i * 60_000 for i in range(30)] + [NOW_MS - 60_000]   # gap of ~29 min
        for t in times:
            (d / f"SKLUSDT_{kind}_{t}.parquet").write_bytes(b"")
        pd.DataFrame({"x": [1, 2, 3]}).to_parquet(d / f"SKLUSDT_{kind}_{times[-1]}.parquet")


def test_build_live(tmp_path):
    _write_testnet(tmp_path)
    _write_recorder(tmp_path)
    (tmp_path / "data/live_status").mkdir(parents=True)
    (tmp_path / "data/live_status/supervisor.json").write_text(json.dumps({"updated_ms": NOW_MS, "processes": []}))
    live = build(tmp_path, now=NOW)
    js = (tmp_path / "dashboard/live/status.js").read_text()
    assert js.startswith("window.LIVE = ") and json.loads(js[len("window.LIVE = "):].rstrip(";\n"))["built_ms"] == NOW_MS
    assert [t["symbol"] for t in live["testnet"]] == ["BTCUSDT"]
    t = live["testnet"][0]
    assert len(t["fills"]) == 2 and t["fills"][0]["pnl"] == 1.5          # newest first, old fill dropped
    assert t["fills_24h"] == 2 and t["curve"]["pnl"] == [0.5, 1.5]
    assert sum(h["reject"] for h in t["hours"]) == 1 and t["events"][0]["op"] == "reject"
    r = live["recorder"][0]
    assert r["symbol"] == "SKLUSDT" and r["book"]["age_s"] == 60
    assert r["book"]["gaps_24h"] == 1 and r["book"]["rows_last_part"] == 3
    assert live["supervisor"]["updated_ms"] == NOW_MS


def test_build_live_empty(tmp_path):
    live = build(tmp_path, now=NOW)
    assert live["testnet"] == [] and live["recorder"] == [] and live["supervisor"] is None


def test_supervisor_restarts_and_waits_for_keys(tmp_path, monkeypatch):
    monkeypatch.delenv("BINANCE_TESTNET_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_TESTNET_API_SECRET", raising=False)
    cfg = {"recorder": {"enabled": False}, "testnet": [{"name": "tn", "symbols": ["BTCUSDT"], "policy": "join"}]}
    sup = Supervisor(cfg, base=tmp_path)
    crash = sup.children[0]
    crash.args = ["-c", "import sys; sys.exit(3)"]
    sup.check(time.time())
    assert not crash.running() and "keys" in crash.waiting          # no .env -> not started

    (tmp_path / ".env").write_text("BINANCE_TESTNET_API_KEY=\nBINANCE_TESTNET_API_SECRET=\n")
    sup.last_keycheck = -1e9
    sup.check(time.time())
    assert crash.proc is None                                         # empty keys still wait
    (tmp_path / ".env").write_text("BINANCE_TESTNET_API_KEY=k\nBINANCE_TESTNET_API_SECRET=s\n")
    sup.last_keycheck = -1e9
    sup.check(time.time())
    assert crash.proc is not None
    crash.proc.wait(timeout=20)
    sup.check(time.time())                                            # sees the exit
    assert crash.restarts == 1 and crash.last_exit == 3 and crash.backoff == 20.0
    assert crash.proc is None                                         # waiting out the backoff
    sup.check(crash.next_start + 0.1)
    assert crash.proc is not None
    crash.proc.wait(timeout=20)
    st = sup.write_status()
    assert st["processes"][0]["name"] == "tn" and st["keys"] is True
    sup.stop()
    assert json.loads((tmp_path / "data/live_status/supervisor.json").read_text())["stopped"] is True
    assert (tmp_path / "results/live_tn.log").exists()


def test_supervisor_recorder_depth_flag(tmp_path):
    off = Supervisor({"recorder": {"enabled": True}, "testnet": []}, base=tmp_path).children[0]
    on = Supervisor({"recorder": {"enabled": True, "depth": True}, "testnet": []}, base=tmp_path).children[0]
    assert "--depth" not in off.args
    assert on.args[-1] == "--depth" and on.args[:2] == ["-m", "mm.recorder"]


def test_dashboard_server_serves_only_dashboard(tmp_path):
    import urllib.error
    import urllib.request
    from scripts.supervise_live import serve_dashboard
    (tmp_path / "dashboard/live").mkdir(parents=True)
    (tmp_path / "dashboard/index.html").write_text("hello")
    (tmp_path / "dashboard/live/status.js").write_text("window.LIVE={};")
    (tmp_path / ".env").write_text("SECRET=1")
    httpd = serve_dashboard(tmp_path / "dashboard", 0)
    port = httpd.server_address[1]
    try:
        assert urllib.request.urlopen(f"http://127.0.0.1:{port}/index.html").read() == b"hello"
        r = urllib.request.urlopen(f"http://127.0.0.1:{port}/live/status.js")
        assert r.headers["Cache-Control"] == "no-store"
        try:
            body = urllib.request.urlopen(f"http://127.0.0.1:{port}/../.env").read()
        except urllib.error.HTTPError:
            body = b""
        assert b"SECRET" not in body
    finally:
        httpd.shutdown()
