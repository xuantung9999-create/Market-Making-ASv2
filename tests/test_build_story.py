"""Showcase spec S3: scripts/build_story.py writes every number and sentence of the Story page from the run bundles."""
import json
import math
import re
import shutil
from pathlib import Path

import pytest

from scripts import build_story as bst

ROOT = Path(__file__).resolve().parent.parent
FEE = 10.0


def js(path: Path, name: str, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'window.RUNS = window.RUNS || {{}};\nwindow.RUNS["{name}"] = {json.dumps(obj)};\n', encoding="utf-8")


def frow(symbol, variant, qm, net, gross, **kw):
    r = {"symbol": symbol, "variant": variant, "queue_mult": qm, "scenario": f"queue {qm:g}x", "days_total": 60, "n_days": 60,
         "fills": 1000, "net_bp": net, "gross_bp": gross, "net_se": 0.5, "gross_se": 0.5, "t": -9.1, "series": f"q{qm}"}
    r.update(kw)
    return r


def verdict(agent_fills=0, gross_q1=-8.2):
    forest = [
        frow("ALL", "join_touch", 0.0, -11.3, -1.3, scenario="front of queue, 100 ms (v1 assumption)", series="bridge q0 lat100"),
        frow("ALL", "join_touch", 0.5, -17.0, -7.0), frow("ALL", "join_touch", 1.0, gross_q1 - FEE, gross_q1), frow("ALL", "join_touch", 2.0, -19.0, -9.0),
        frow("AAAUSDT", "join_touch", 1.0, -19.0, -9.0), frow("BBBUSDT", "join_touch", 1.0, -17.2, -7.2),
        frow("ALL", "agent", 1.0, None, None, days_total=53, fills=agent_fills, n_days=0),
    ]
    forest[-1].pop("net_bp"), forest[-1].pop("gross_bp")
    compare = [{"symbol": "ALL", "variant": "join_touch", "queue_mult": 1.0, "fills": 1000, "pnl_total": -100.0, "mk_60": -6.0}]
    gates = {"A": {"pass": False, "conditions": [{"id": f"A{i}", "text": f"condition {i}", "value": None, "pass": False} for i in range(1, 6)]}}
    return {"schema": 1, "run_id": "pub-verdict", "built_utc": "2026-11-12 12:31", "config": {"maker_fee_bps": FEE, "latency_ms": 300},
            "forest": forest, "compare": compare, "gates": gates}


def wf_days(qm, with_fills=False):
    days = []
    for sym in ("AAAUSDT", "BBBUSDT"):
        for d in range(1, 4):
            for var in ("agent", "join_touch"):
                f = (50 if with_fills and var == "agent" else 0) if var == "agent" else 200
                days.append({"symbol": sym, "date": f"2026-10-0{d}", "variant": var, "fills": f, "notional": f * 100.0,
                             "pnl": (5.0 if with_fills else 0.0) if var == "agent" else -40.0})
    return {"config": {"queue_mult": qm, "maker_fee_bps": FEE}, "days": days,
            "edge": [{"symbol": "AAAUSDT", "action": "JOIN", "imb": 0, "vol": 0, "n": 400.0, "mean": -9.0, "se": 1.0},
                     {"symbol": "AAAUSDT", "action": "JOIN", "imb": 0, "vol": 1, "n": 0.0, "mean": 0.5, "se": 30.0}]}


def make_base(tmp_path, agent_fills=0, gross_q1=-8.2, live=True):
    base = tmp_path
    js(base / "dashboard/runs/pub-verdict.js", "pub-verdict", verdict(agent_fills, gross_q1))
    js(base / "dashboard/runs/wf-a-q1.js", "wf-a-q1", wf_days(1.0, agent_fills > 0))
    js(base / "dashboard/runs/wf-a-q2.js", "wf-a-q2", wf_days(2.0, agent_fills > 0))
    rows = ["variant,date,symbol,pnl,spread_capture,inventory_pnl,fees,notional_usdt,fills"]
    for d in range(1, 5):
        for s in ("AAAUSDT", "BBBUSDT", "CCCUSDT"):
            rows.append(f"q1.0,2026-10-0{d},{s},-15.0,10.0,-20.0,5.0,5000.0,30")
            rows.append(f"q2.0,2026-10-0{d},{s},-99.0,1.0,-1.0,9.0,5000.0,30")
    (base / "results").mkdir(exist_ok=True)
    (base / "results/queue_baseline.csv").write_text("\n".join(rows) + "\n")
    (base / "results/universe_backtest.csv").write_text(
        "symbol,tier,date,fill_rule,strategy,pnl,fills,notional_usdt,net_0bp,net_10bp\n"
        "ANKRUSDT,micro,2026-11-10,through,Join touch,27.8,184,17729.9,27.8,10.1\n"
        "ANKRUSDT,micro,2026-11-10,touch,Join touch,40.0,286,20000.0,40.0,20.0\n"
        "COTIUSDT,micro,2026-11-10,through,Join touch,1.0,10,1000.0,1.0,0.5\n")
    (base / "results/tests_passed.json").write_text('{"passed": 431, "at": "2026-11-15 03:00 UTC"}')
    (base / "docs").mkdir()
    (base / "docs/SPEC_V2_1.md").write_text("# spec\n\n**Status (14 Nov 2026): code is built; no pass rule has been evaluated\nyet, because each needs data.**\n")
    (base / "dashboard/index.html").write_text(
        "<h2>Known limitations so far</h2>\n<ul>\n<li>First limit. More words.</li>\n<li>Second &amp; limit. Extra.</li>\n"
        "<li>Third limit <b>bold</b>. Tail.</li>\n<li>Fourth.</li>\n</ul>\n")
    if live:
        for sid, src, fills, placed in (("testnet-BTC-join", "testnet", 7, 100), ("paper-ANKR-agent", "paper", 0, 0), ("paper-SKL-agent", "paper", 2, 0)):
            b = {"meta": {"id": sid, "source": src, "built_ms": 1_794_700_000_000, "first_ms": 1_794_500_000_000},
                 "funnel": {"placed": placed, "filled": fills, "rejected": 3 if placed else 0}, "fills": [{}] * fills,
                 "takeaways": {"why_out": f"why out {sid}"}, "states": {"bid": [], "ask": []}}
            p = base / f"dashboard/live/session-{sid}.js"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f'window.SESSION_DATA = window.SESSION_DATA || {{}};\nwindow.SESSION_DATA["{sid}"] = {json.dumps(b)};\n')
    return base


def story(base):
    return bst.build_story(base, now=1_794_700_000)


def test_five_conclusions_carry_numbers_read_from_the_bundles(tmp_path):
    s = story(make_base(tmp_path))
    c = {x["id"]: x["text"] for x in s["conclusions"]}
    assert c[1] == ("Even at zero fee, joining the best price loses 8.2 bp per dollar traded at a realistic queue position; "
                    "the 10 bp maker fee more than doubles it to -18.2 bp.")
    assert c[2] == ("At the front of the queue with 100 ms latency the same strategy is near break-even before fees (-1.3 bp); "
                    "behind the displayed size it is -8.2 bp.")
    assert c[3].startswith("A backtest with no queue model manufactured a +16 bp edge on ANKR from one day.")
    assert c[4] == ("The agent was right to refuse. It learned that every market state it could see loses money and made no fills "
                    "in 53 counted days. Gate A: fail, 0 of 5 conditions.")
    assert "Book imbalance is a real open bet" in c[5] and c[5].endswith("Not yet evaluated.") and "docs/SPEC_V2_1.md" in c[5]
    assert all(x["status"] == "ok" for x in s["conclusions"])
    assert "fees alone" not in " ".join(c.values()).lower()


def test_hero_tiles_and_facts_come_from_the_bundles(tmp_path):
    h = story(make_base(tmp_path))["sections"]["hero"]
    t = {x["key"]: x for x in h["tiles"]}
    assert t["net"]["value"] == pytest.approx(-18.2) and t["t"]["value"] == pytest.approx(-9.1)
    assert t["agent_fills"]["value"] == 0 and t["agent_fills"]["context"] == "in 53 days" and t["gate"]["value"] == "FAIL"
    assert h["facts_line"] == "431 tests · 60 days and 2 coins tested · 1,000 simulated fills · 100 real orders sent on testnet"
    assert h["sentence"].endswith("-18.2 bp per dollar traded after fees.")


def test_waterfall_terms_sum_to_the_net_to_1e6(tmp_path):
    w = story(make_base(tmp_path))["sections"]["waterfall"]
    assert w["status"] == "ok"
    assert sum(t["bp"] for t in w["terms"]) == pytest.approx(w["net_bp"], abs=1e-6)
    # 4 days x 3 coins x (10 - 20 - 5) over 4 x 15,000 USD of notional
    assert w["net_bp"] == pytest.approx(-15.0 * 12 / 60_000 * 1e4, abs=1e-6)
    assert [t["key"] for t in w["terms"]] == ["spread", "inventory", "fee"] and w["markout_60_bp"] == pytest.approx(-6.0)


def test_ladder_has_its_four_points_in_order(tmp_path):
    pts = story(make_base(tmp_path))["sections"]["ladder"]["points"]
    assert [p["key"] for p in pts] == ["v1", "front", "q1", "q2"]
    assert pts[0]["gross_bp"] == pytest.approx(27.8 / 17729.9 * 1e4, abs=1e-6) and pts[0]["net_bp"] == pytest.approx(pts[0]["gross_bp"] - FEE)
    assert pts[0]["one_day"] and "no queue model" in pts[0]["label"] and pts[1]["label"] == "front of queue, 100 ms"
    assert pts[2]["label"] == "queue 1x, 300 ms" and (pts[3]["gross_bp"], pts[3]["net_bp"]) == (-9.0, -19.0)


def test_gate_scoreboard_gives_a_value_sentence_for_every_condition(tmp_path):
    rows = story(make_base(tmp_path))["sections"]["agent"]["gate"]["conditions"]
    assert [r["id"] for r in rows] == ["A1", "A2", "A3", "A4", "A5"] and all(r["value_text"] for r in rows)
    assert "no counted coin-days" in rows[0]["value_text"] and rows[1]["value_text"] == "0 of 2 coins with positive total net P&L"
    assert "against join touch" in rows[4]["value_text"] and rows[4]["value"] == 0.0


def test_forest_rows_and_stack_boxes(tmp_path):
    s = story(make_base(tmp_path))["sections"]
    rows = s["assumptions"]["rows"]
    assert s["assumptions"]["title"] == "Every assumption loses money." and len(rows) == 6 and len(rows) <= 8
    assert [r["pooled"] for r in rows] == [True] * 4 + [False] * 2
    boxes = {b["key"]: b for b in s["stack"]["boxes"]}
    assert list(boxes) == ["data", "calibration", "simulator", "agent", "paper", "testnet"]
    assert boxes["calibration"]["number"]["value"] == 2 and boxes["testnet"]["number"]["value"] == 100 and boxes["paper"]["number"]["value"] == 2
    assert boxes["agent"]["number"]["value"] == 12 and boxes["simulator"]["module"] == "mm/queue_sim.py"


def test_agent_section_uses_the_paper_sessions_own_sentence_and_the_snapshot_date(tmp_path):
    s = story(make_base(tmp_path))
    ag = s["sections"]["agent"]
    assert ag["paper_line"].startswith("On live data since ") and "the paper trader (2 coins) has made 2 fills." in ag["paper_line"]
    assert "why out paper-SKL-agent" in ag["paper_line"]
    assert s["provenance"]["live_snapshot"].endswith("UTC") and s["provenance"]["backtest_built"] == "2026-11-12 12:31 UTC"
    ex = s["sections"]["execution"]
    assert ex["numbers"] == {"placed": 100, "filled": 7, "rejected": 3, "fills": 7} and ex["label"] == "TESTNET: execution test, not a result"
    nxt = s["sections"]["next"]
    assert nxt["limits"] == ["First limit.", "Second & limit.", "Third limit bold."]


def test_wording_follows_the_numbers_when_they_change(tmp_path):
    s = story(make_base(tmp_path, agent_fills=500, gross_q1=+2.0))
    c = {x["id"]: x["text"] for x in s["conclusions"]}
    assert "fees decide the result" in c[1] and "more than doubles" not in c[1] and c[1].startswith("Before fees")
    assert "right to refuse" not in c[4] and "500 fills in 53 days" in c[4]
    assert s["sections"]["agent"]["title"] == "The agent traded."


@pytest.mark.parametrize("gone, sections, conclusion_ids", [
    ("dashboard/runs/pub-verdict.js", {"hero", "assumptions", "waterfall", "ladder", "agent"}, {1, 2, 3, 4}),
    ("results/queue_baseline.csv", {"waterfall"}, set()),
    ("results/universe_backtest.csv", {"ladder"}, {3}),
    ("docs/SPEC_V2_1.md", {"next"}, {5}),
    ("dashboard/index.html", {"next"}, set()),
    ("dashboard/live", {"execution"}, set()),
])
def test_a_missing_source_gives_a_marker_and_no_number(tmp_path, gone, sections, conclusion_ids):
    base = make_base(tmp_path)
    p = base / gone
    shutil.rmtree(p) if p.is_dir() else p.unlink()
    s = story(base)
    got = {k for k, v in s["sections"].items() if v["status"] == "missing"}
    assert sections <= got
    for k in got:
        sec = s["sections"][k]
        assert set(sec) == {"status", "title", "missing", "sentence"}, k            # no tiles, rows, points or numbers at all
        assert sec["missing"] and sec["missing"][0].replace("\\", "/") in sec["sentence"]
    assert {c["id"] for c in s["conclusions"] if c["status"] == "missing"} == conclusion_ids
    assert gone.replace("dashboard/live", "dashboard/live/session-*.js") in " ".join(s["sources_missing"]) or gone.split("/")[-1] in " ".join(s["sources_missing"])
    assert s["sections"]["stack"]["status"] == "ok"                                  # the stack never disappears


def test_nothing_missing_means_nothing_flagged(tmp_path):
    s = story(make_base(tmp_path))
    assert s["sources_missing"] == [] and all(v["status"] == "ok" for v in s["sections"].values())


def test_bundle_has_no_nan_and_writes_strict_json(tmp_path):
    base = make_base(tmp_path)
    v = verdict()
    v["forest"][2]["net_se"] = float("nan")
    v["forest"][2]["t"] = float("inf")
    js(base / "dashboard/runs/pub-verdict.js", "pub-verdict", v)          # json.dumps writes NaN / Infinity, as the old bundles could
    s = story(base)
    path = bst.write_story(s, base / "dashboard/runs")
    text = path.read_text(encoding="utf-8")
    assert text.startswith("window.STORY = ") and "NaN" not in text and "Infinity" not in text
    obj = json.loads(text[text.index("= {") + 2: text.rindex("}") + 1], parse_constant=lambda c: pytest.fail(c))
    assert obj["sections"]["hero"]["tiles"][1]["value"] is None            # the t-statistic that was infinite is absent, not a number

    def walk(x):
        if isinstance(x, dict):
            [walk(v) for v in x.values()]
        elif isinstance(x, list):
            [walk(v) for v in x]
        elif isinstance(x, float):
            assert math.isfinite(x)
    walk(obj)


def test_build_verdict_builds_the_story_too():
    src = (ROOT / "scripts" / "build_verdict.py").read_text(encoding="utf-8")
    assert "build_story.main(" in src


REAL = all((ROOT / p).exists() for p in ("dashboard/runs/pub-verdict.js", "results/queue_baseline.csv", "results/universe_backtest.csv",
                                         "dashboard/runs/wf-2026-11-12-q1.js", "docs/SPEC_V2_1.md"))


@pytest.mark.skipif(not REAL, reason="the committed run files are not in this checkout")
def test_on_the_real_files_the_story_agrees_with_the_verdict_bundle():
    s = bst.build_story(ROOT)
    v = bst.load_js(ROOT / "dashboard/runs/pub-verdict.js")
    q1 = next(r for r in v["forest"] if r["symbol"] == "ALL" and r["variant"] == "join_touch" and r["queue_mult"] == 1.0)
    w = s["sections"]["waterfall"]
    assert w["status"] == "ok" and w["net_bp"] == pytest.approx(q1["net_bp"], abs=1e-6)         # same days, same ratio
    assert sum(t["bp"] for t in w["terms"]) == pytest.approx(w["net_bp"], abs=1e-6)
    assert w["markout_60_bp"] == pytest.approx(-6.0, abs=0.05)
    assert [p["key"] for p in s["sections"]["ladder"]["points"]] == ["v1", "front", "q1", "q2"]
    assert round(s["sections"]["ladder"]["points"][0]["gross_bp"]) == 16
    headline = v["takeaways"]["headline"]
    assert f"{abs(q1['net_bp']):.1f}" in headline and f"{q1['net_bp']:.1f}" in s["sections"]["hero"]["sentence"]
    assert "no fills in 53 days" in headline and "made no fills in 53 counted days" in s["conclusions"][3]["text"]
    assert re.search(r"-1\.3 bp", s["conclusions"][1]["text"]) and "loses 8.2 bp" in s["conclusions"][0]["text"]
    assert s["conclusions"][4]["text"].endswith("Not yet evaluated.")
    text = json.dumps(s, allow_nan=False)                                                        # strict: no NaN anywhere
    assert "NaN" not in text


# ---- showcase S6: what the test caught and the curated tape
def _row(i, finding, n, status="by design", task=None, usd=None):
    r = {"id": i, "finding": finding, "status": status, "task": task, "n": n, "unit": "things", "evidence": "e", "cites": {}}
    if usd is not None:
        r["usd"] = usd
    return r


def test_caught_items_add_counts_across_sessions_and_say_the_status():
    items = bst.caught_items([_row("a", "Orders were rejected", 420), _row("b", "Restart state lost", 2, "fixed", "live spec L1b"),
                              _row("a", "Orders were rejected", 29), _row("c", "Glitch fills", 11, usd=-71.17), _row("c", "Glitch fills", 1, usd=20.09)])
    assert [i["id"] for i in items] == ["a", "b", "c"]
    assert items[0]["n"] == 449 and "449 things" in items[0]["text"] and items[0]["text"].endswith("Status: by design.")
    assert "Status: fixed, live spec L1b." in items[1]["text"]
    assert items[2]["usd"] == pytest.approx(-51.08) and "-51.08 USDT" in items[2]["text"]


def _glitch_session(base, big, small):
    fills = [{"i": 1, "t": 1_794_700_000_000, "price": 100.0, "mid": 90.0, "qty": small, "artifact": True, "caption": "small"},
             {"i": 2, "t": 1_794_700_500_000, "price": 130.0, "mid": 100.0, "qty": big, "artifact": True, "caption": "big",
              "mk_60": None},
             {"i": 3, "t": 1_794_700_900_000, "price": 500.0, "mid": 100.0, "qty": 50.0, "artifact": False, "caption": "not a glitch"}]
    b = {"meta": {"id": "testnet-X-join", "source": "testnet", "symbol": "XUSDT", "built_ms": 1, "first_ms": 1},
         "funnel": {"placed": 1, "filled": 1, "rejected": 0}, "fills": fills, "takeaways": {}, "states": {"bid": [], "ask": []}}
    (base / "dashboard/live").mkdir(parents=True, exist_ok=True)
    (base / "dashboard/live/session-testnet-X-join.js").write_text(
        f'window.SESSION_DATA = window.SESSION_DATA || {{}};\nwindow.SESSION_DATA["testnet-X-join"] = {json.dumps(b)};\n')
    return fills


def _tape_file(base, t, day):
    w = {"t0": t - 120_000, "t1": t + 400_000,
         "touch": [[t - 100_000, 99, 101, 1, 1], [t - 30_000, 99, 101, 1, 1], [t + 100_000, 98, 100, 1, 1], [t + 399_000, 98, 100, 1, 1]],
         "trades": [[t - 90_000, 100, 1, 1], [t + 10_000, 100, 1, -1]],
         "orders": [{"side": 1, "price": 99.0, "t_place": t - 80_000, "t_end": t, "end": "fill"},
                    {"side": -1, "price": 101.0, "t_place": t - 300_000, "t_end": t - 200_000, "end": "cancel"}]}
    (base / f"dashboard/live/tape-testnet-X-join-{day}.js").write_text(
        f'window.TAPES = window.TAPES || {{}};\nwindow.TAPES["testnet-X-join|{day}"] = {json.dumps({"windows": [w]})};\n')


def test_tape_example_is_the_largest_glitch_fill_with_its_window_trimmed(tmp_path):
    base = make_base(tmp_path, live=False)
    fills = _glitch_session(base, big=0.5, small=0.5)                    # money away from the mid: 10 * 0.5 against 30 * 0.5
    t = fills[1]["t"]
    _tape_file(base, t, "2026-11-14")
    s = story(base)
    ex = s["sections"]["execution"]["tape"]
    assert ex["i"] == 2 and ex["session"] == "testnet-X-join" and ex["caption"] == "big" and ex["day"] == "2026-11-14"
    assert s["tape_example"]["t"] == t and "window" not in s["tape_example"]
    w = ex["window"]
    assert w["t0"] == t - 60_000 and w["t1"] == t + 300_000 and all(t - 60_000 <= r[0] <= t + 300_000 for r in w["touch"] + w["trades"])
    assert [o["price"] for o in w["orders"]] == [99.0]                   # the order that ended before the window is dropped
    assert s["sections"]["execution"]["tape_missing"] is None


def test_missing_tape_gives_a_reason_and_no_example(tmp_path):
    base = make_base(tmp_path, live=False)
    _glitch_session(base, big=0.5, small=0.5)                            # no tape file written
    s = story(base)
    e = s["sections"]["execution"]
    assert e["tape"] is None and s["tape_example"] is None and "tape-testnet-X-join" in e["tape_missing"]
