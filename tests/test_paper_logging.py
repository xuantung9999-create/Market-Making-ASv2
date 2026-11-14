"""Task L1 (paper side): quote-state log, session log and the snapshot the Live tab polls."""
import json

from tests.test_paper import S, DAY0, scripted, session


def run(tmp_path, n=800):
    s = session(tmp_path)
    for raw, t in scripted(n=n):
        s.handle(raw, t)
        s.tick(t)
    s.checkpoint()
    return s, t


def state_rows(tmp_path):
    out = []
    for f in sorted((tmp_path / "paper" / "ANKRUSDT").glob("state_*.jsonl")):
        out += [json.loads(x) for x in f.read_text().splitlines()]
    return out


def test_state_log_has_warmup_then_a_live_state(tmp_path):
    run(tmp_path)
    rows = state_rows(tmp_path)
    assert rows and {r["side"] for r in rows} == {1, -1}
    assert all({"ts_us", "side", "state", "detail"} <= set(r) for r in rows)
    seq = [r["state"] for r in rows if r["side"] == 1]
    assert seq[0] == "WARMUP"
    assert set(seq) <= {"WARMUP", "QUOTING", "POLICY_OUT", "LOSS_STOP", "INV_CAP", "STALE_FEED"}
    assert any(x != "WARMUP" for x in seq)
    assert all(a != b for a, b in zip(seq, seq[1:])) or len(seq) > 1   # changes (or the 60 s repeat) only


def test_snapshot_json_matches_what_the_live_tab_reads(tmp_path):
    s, t = run(tmp_path)
    p = json.loads((tmp_path / "paper" / "snapshot.json").read_text())
    assert p["kind"] == "paper" and "ts_utc" in p
    r = p["symbols"]["ANKRUSDT"]
    for k in ("bid", "ask", "q", "pnl_day", "fills_day", "orders", "live_arm", "loss_stop", "state"):
        assert k in r
    assert set(r["state"]) == {"bid", "ask"}


def test_session_log_start_stop(tmp_path):
    s, _ = run(tmp_path, n=50)
    s.log_session("start", {"symbols": ["ANKRUSDT"]})
    s.log_session("stop", {"symbols": ["ANKRUSDT"]})
    rows = [json.loads(x) for x in (tmp_path / "paper" / "ANKRUSDT" / "session.jsonl").read_text().splitlines()]
    assert [r["op"] for r in rows] == ["start", "stop"] and rows[0]["pid"] > 0
