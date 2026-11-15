"""Showcase spec section 8 (replaces live spec rule 3): by default nothing live reaches the public copy; with --live-snapshot a
frozen, sanitised copy of the sessions and the chosen tapes is published under snapshot/ only; nothing from Operations is ever
published; a path, a private address or a credential word in a session bundle makes the publish fail.

INTENTIONALLY CHANGED in showcase task S7: the old test asserted that no session or tape file is ever published."""
import json
import shutil
from pathlib import Path

import pytest

from scripts import publish_dashboard as pd_

ROOT = Path(__file__).resolve().parents[1]
SID = "testnet-BTCUSDT-join"
T = 1_794_700_000_000                      # 2026-11-14 23:46 UTC
DAY = "2026-11-14"


def session(extra=None, note="a book glitch"):
    b = {"meta": {"id": SID, "source": "testnet", "symbol": "BTCUSDT", "policy": "join", "lot_usd": 100, "q_max": 10, "max_loss": 20,
                  "fee_bps": 10, "built_ms": T, "thresholds": {}, "first_ms": T - 1000, "last_ms": T, "label": "TESTNET: execution test, not a result"},
         "now": {"state": {}, "lots": 0, "pos_usd": 0, "open": {}, "last_fill_ms": T, "state_logged": True, "open_incidents": 0, "mid": 1.0,
                 "process": {"running": True, "uptime_s": 5, "restarts": 0, "pid": 4242, "cmd": "python -m mm.testnet --symbols BTCUSDT"}},
         "fills": [{"i": 1, "t": T, "side": 1, "price": 1.0, "qty": 1.0, "mid": 1.0, "artifact": True, "caption": note, "host": "x"}],
         "incidents": [{"id": "artifact-1", "kind": "artifact_fill", "severity": "high", "t0": T, "t1": T, "sentence": note, "fills": [1],
                        "cost_usd": 1.0, "log_file": "somewhere"}],
         "funnel": {"placed": 1, "cancelled": 0, "rejected": 0, "filled": 1, "partial": 0, "by_hour": [], "reject_reasons": []},
         "takeaways": {}, "headline": "h", "debug": {"secret_field": 1}}
    b.update(extra or {})
    return b


@pytest.fixture()
def site(tmp_path, monkeypatch):
    dash = tmp_path / "dashboard"
    shutil.copytree(ROOT / "dashboard", dash, ignore=shutil.ignore_patterns("live"))
    live = dash / "live"
    live.mkdir()
    put_live(live, session())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pd_, "DASH", Path("dashboard"))
    return tmp_path


def put_live(live: Path, b: dict, tape_day=DAY):
    (live / "sessions.js").write_text('window.SESSIONS = [{"id":"%s","source":"testnet","symbol":"BTCUSDT","policy":"join","first_ms":%d,"last_ms":%d,'
                                      '"n_fills":1,"host":"x"}];\n' % (SID, T - 1000, T))
    (live / f"session-{SID}.js").write_text(f'window.SESSION_DATA = window.SESSION_DATA || {{}};\nwindow.SESSION_DATA["{SID}"] = {json.dumps(b)};\n')
    tape = {"windows": [{"t0": T - 60000, "t1": T + 300000, "touch": [[T, 1, 2, 1, 1]], "trades": [], "orders": []}], "id": SID, "date": tape_day, "path": "C:/x"}
    (live / f"tape-{SID}-{tape_day}.js").write_text(f'window.TAPES = window.TAPES || {{}};\nwindow.TAPES["{SID}|{tape_day}"] = {json.dumps(tape)};\n')
    (live / f"tape-{SID}-2026-11-01.js").write_text('window.TAPES = window.TAPES || {};\nwindow.TAPES["x|y"] = {"windows": []};\n')   # a day nothing refers to
    (live / "status.js").write_text('window.LIVE = {"supervisor": {"host": "pc", "ip": "192.168.1.5"}};\n')


def files(pub: Path):
    return [p.relative_to(pub).as_posix() for p in pub.rglob("*") if p.is_file()]


def test_default_publish_has_no_live_files(site):
    pd_.main(["--out", "pub"])
    pub = site / "pub"
    names = files(pub)
    assert not any(n.startswith("snapshot/") or n.startswith("live/") for n in names)
    assert not [n for n in names if "session-" in n or "tape-" in n or n.endswith("status.js")]
    html = (pub / "index.html").read_text(encoding="utf-8")
    assert "window.PUBLIC_SITE = true;" in html and "SNAPSHOT_AT" not in html


def test_the_default_story_is_built_without_the_live_sessions(site):
    pd_.main(["--out", "pub"])
    story = (site / "pub" / "runs" / "pub-story.js").read_text(encoding="utf-8")
    assert '"tape_example":null' in story or '"tape_example":' not in story        # no live tape in the story
    assert "artifact-1" not in story and "orders placed" not in story.split('"execution"')[1][:400].replace("real orders", "")


def test_live_snapshot_publishes_sessions_and_the_chosen_tapes_under_snapshot_only(site):
    pd_.main(["--out", "pub", "--live-snapshot"])
    pub = site / "pub"
    names = files(pub)
    assert f"snapshot/session-{SID}.js" in names and "snapshot/sessions.js" in names
    assert f"snapshot/tape-{SID}-{DAY}.js" in names                        # the day with an incident
    assert f"snapshot/tape-{SID}-2026-11-01.js" not in names               # a day nothing refers to is not published
    assert not [n for n in names if ("session-" in n or "tape-" in n) and not n.startswith("snapshot/")]
    assert not [n for n in names if n.endswith("status.js")]                # status.js is never present
    html = (pub / "index.html").read_text(encoding="utf-8")
    assert 'window.SNAPSHOT_AT = "2026-11-14 ' in html


def test_the_snapshot_keeps_only_allow_listed_keys(site):
    pd_.main(["--out", "pub", "--live-snapshot"])
    snap = site / "pub" / "snapshot"
    txt = (snap / f"session-{SID}.js").read_text(encoding="utf-8")
    b = json.loads(txt[txt.index("= {", 60) + 2: txt.rstrip().rstrip(";").rindex("}") + 1])
    assert "pid" not in b["now"]["process"] and "cmd" not in b["now"]["process"] and b["now"]["process"]["restarts"] == 0
    assert "debug" not in b and "host" not in b["fills"][0] and "log_file" not in b["incidents"][0]
    assert b["fills"][0]["caption"] and b["incidents"][0]["sentence"]
    assert "host" not in (snap / "sessions.js").read_text(encoding="utf-8")
    assert "path" not in (snap / f"tape-{SID}-{DAY}.js").read_text(encoding="utf-8").split("= ", 2)[2]


def test_operations_pages_and_scripts_are_not_in_the_public_copy(site):
    pd_.main(["--out", "pub", "--live-snapshot"])
    pub = site / "pub"
    html = (pub / "index.html").read_text(encoding="utf-8")
    for gone in ('class="tab-wrap" data-tab="l-health"', 'href="#l-health"','id="view-live"', 'id="view-pcstatus"', "js/live.js", "js/views/pcstatus.js", "Operations</a>", "data-local-only"):
        assert gone not in html, gone
    assert not (pub / "js" / "live.js").exists() and not (pub / "js" / "views" / "pcstatus.js").exists()
    assert not (pub / ".env").exists() and not (pub / "data").exists()


@pytest.mark.parametrize("planted", ["C:\\Users\\Admin\\data\\x.log", "C:/Users/Admin/x.log", "/home/pc/mm/x.log", "/Users/me/x",
                                     "10.0.0.7", "192.168.1.20", "172.20.3.4", "my secret key", "the Signature", "apiKey"])
def test_a_planted_path_private_ip_or_secret_in_a_session_bundle_fails_the_publish(site, planted):
    put_live(site / "dashboard" / "live", session(note=f"see {planted} now"))
    with pytest.raises(SystemExit) as e:
        pd_.main(["--out", "pub", "--live-snapshot"])
    assert "leak" in str(e.value)
    assert not (site / "pub").exists()                                     # nothing partial is left behind


def test_the_host_name_and_a_process_id_field_fail_the_publish(site, monkeypatch):
    monkeypatch.setattr(pd_, "host_names", lambda: ["desk-pc-7"])
    put_live(site / "dashboard" / "live", session(note="ran on DESK-PC-7"))
    with pytest.raises(SystemExit) as e:
        pd_.main(["--out", "pub", "--live-snapshot"])
    assert "host name" in str(e.value)
    # a process id field kept by the allow-list would also be refused: the scanner looks for it in any written file
    leaks = pd_.scan_for_leaks(site, hosts=[])
    assert isinstance(leaks, list)
    probe = site / "probe"
    probe.mkdir()
    (probe / "x.js").write_text('{"pid": 12}')
    assert any("process id" in m for m in pd_.scan_for_leaks(probe, hosts=[]))


def test_ordinary_text_and_urls_do_not_trip_the_scanner(tmp_path):
    (tmp_path / "ok.js").write_text('{"u":"https://github.com/x/y/blob/main/docs/SPEC_V2_1.md","m":"mm/queue_sim.py","n":[10.5,172.5,3.14],'
                                    '"s":"Sold 0.00166 at 60118, 1485.2 bp below the mid 70604.5"}')
    assert pd_.scan_for_leaks(tmp_path, hosts=[]) == []


def test_dashboard_live_is_git_ignored():
    ig = (ROOT / ".gitignore").read_text().splitlines()
    assert "dashboard/live/*" in ig


# ---------------------------------------------------------------- session chart files (dashboard chart spec section 8, task C4)
def chart(title="Mid fell from 67,540 to 64,450", extra=None):
    r = {"panels": ["price", "quotes", "inventory"], "t": [T - 2000, T - 1000, T], "mid": [1.0, 1.1, 1.0], "bid_bp": [None, -1.0, -1.0],
         "ask_bp": [None, 1.0, 1.0], "lots": [0, 1, 1], "max_abs_lots": [0, 1, 1], "fills_cum": [0, 1, 1], "buys_cum": [0, 1, 1],
         "sells_cum": [0, 0, 0], "width_bp": [None, 2.0, 2.0], "fill_ids": None, "axes": {"price": [0.9, 1.2], "bp": [-2, 2], "debug": 1},
         "off_scale": None, "titles": {"card": "c", "sub": "s", "price": title, "quotes": "q", "inventory": "i"},
         "events": [{"panel": "inventory", "t": T, "y": 1, "text": "peak", "host": "x"}], "empty": None, "debug_path": "x"}
    r.update(extra or {})
    return {"id": SID, "built_ms": T, "by_range": {k: r for k in ("6h", "24h", "3d", "all")}, "debug": {"secret_field": 1}}


def put_chart(live: Path, c: dict):
    (live / f"chart-{SID}.js").write_text(f'window.SESSION_CHART = window.SESSION_CHART || {{}};\nwindow.SESSION_CHART["{SID}"] = {json.dumps(c)};\n')


def test_default_publish_writes_no_chart_file(site):
    put_chart(site / "dashboard" / "live", chart())
    pd_.main(["--out", "pub"])
    assert not [n for n in files(site / "pub") if "chart-" in n]


def test_live_snapshot_writes_chart_files_under_snapshot_only(site):
    put_chart(site / "dashboard" / "live", chart())
    pd_.main(["--out", "pub", "--live-snapshot"])
    names = files(site / "pub")
    assert f"snapshot/chart-{SID}.js" in names
    assert [n for n in names if n.split("/")[-1].startswith("chart-")] == [f"snapshot/chart-{SID}.js"]


def test_a_chart_file_keeps_only_allow_listed_keys(site):
    put_chart(site / "dashboard" / "live", chart())
    pd_.main(["--out", "pub", "--live-snapshot"])
    txt = (site / "pub" / "snapshot" / f"chart-{SID}.js").read_text(encoding="utf-8")
    c = json.loads(txt[txt.index("= {", 60) + 2: txt.rstrip().rstrip(";").rindex("}") + 1])
    assert set(c) == {"id", "built_ms", "by_range"}
    r = c["by_range"]["all"]
    assert set(r) <= set(pd_.CHART_ALLOW["by_range"]["all"]) and "debug_path" not in r and "debug" not in r["axes"]
    assert "host" not in r["events"][0] and r["titles"]["price"].startswith("Mid fell")
    assert set(pd_.CHART_ALLOW["by_range"]["all"]) >= {"panels", "t", "mid", "bid_bp", "ask_bp", "lots", "max_abs_lots", "fills_cum", "buys_cum",
                                                      "sells_cum", "width_bp", "pnl", "pnl_ex_artifact", "pnl_peak", "fill_ids", "axes",
                                                      "off_scale", "titles", "events", "empty"}


@pytest.mark.parametrize("planted", ["C:\\Users\\Admin\\data\\x.log", "/home/pc/mm/x.log", "192.168.1.20", "my secret key"])
def test_a_planted_path_or_secret_in_a_chart_file_fails_the_publish(site, planted):
    put_chart(site / "dashboard" / "live", chart(title=f"see {planted} now"))
    with pytest.raises(SystemExit) as e:
        pd_.main(["--out", "pub", "--live-snapshot"])
    assert "leak" in str(e.value)
    assert not (site / "pub").exists()


def test_fill_distance_is_published_with_the_fills():
    assert "dist_bp" in pd_.SESSION_ALLOW["fills"][0]
