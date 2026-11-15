"""Recruiter-ready spec (docs/RECRUITER_READY_SPEC.md): numbers and short labels (R2), the Story ending (R4), the README (R6)."""
import json
import re
from pathlib import Path

import pytest

from scripts import build_story as bst
from scripts import build_verdict as bv
from tests.test_build_story import make_base, story

ROOT = Path(__file__).resolve().parent.parent


# ---- R2: short labels (spec 5.1)
def _all_short_ok(rows):
    shorts = [r["label_short"] for r in rows]
    assert all(isinstance(s, str) and 0 < len(s) <= bst.SHORT_MAX for s in shorts), shorts
    return shorts


def test_story_forest_rows_have_short_labels(tmp_path):
    rows = story(make_base(tmp_path))["sections"]["assumptions"]["rows"]
    shorts = _all_short_ok(rows)
    assert shorts == ["Front, 100 ms", "Queue 0.5x", "Queue 1x", "Queue 2x", "AAA 1x", "BBB 1x"]
    assert all(r["label"] for r in rows)                                    # the long label stays for hover and wide screens


def test_verdict_forest_rows_get_unique_short_labels():
    forest = [{"symbol": s, "variant": v, "queue_mult": q, "scenario": sc, "series": se, "days_total": 53 if v == "agent" else 60}
              for s in ("ALL", "ANKRUSDT", "COTIUSDT")
              for v, q, sc, se in (("join_touch", 0.0, "front of queue, 100 ms (v1 assumption)", "bridge q0 lat100"),
                                   ("join_touch", 0.5, "queue 0.5x (optimistic)", "q0.5"), ("join_touch", 1.0, "queue 1x (headline)", "q1.0"),
                                   ("join_touch", 2.0, "queue 2x (stress)", "q2.0"), ("agent", 1.0, "agent, queue 1x (headline)", None))]
    b = bv.finish({"forest": forest, "takeaways": {"headline": "h"}})
    shorts = _all_short_ok(b["forest"])
    assert len(set(shorts)) == len(shorts)
    assert shorts[:5] == ["Front, 100 ms", "Queue 0.5x", "Queue 1x", "Queue 2x", "Agent, 1x"] and "ANKR 1x" in shorts
    assert b["takeaways"]["ov-agent-tile"] == "in 53 counted days (106 coin-days)" and b["takeaways"]["headline"] == "h"


def test_story_waterfall_and_ladder_categories_break_instead_of_rotating(tmp_path):
    s = story(make_base(tmp_path))["sections"]
    terms = s["waterfall"]["terms"]
    assert terms[0]["label_short"] == "Spread<br>captured"
    for item in terms + s["ladder"]["points"]:
        assert item["label_short"] and all(len(line) <= bst.SHORT_MAX for line in item["label_short"].split("<br>")), item["label_short"]


@pytest.mark.skipif(not (ROOT / "dashboard/runs/pub-verdict.js").exists(), reason="no committed verdict bundle")
def test_the_committed_verdict_bundle_carries_short_labels():
    v = bst.load_js(ROOT / "dashboard/runs/pub-verdict.js")
    _all_short_ok(v["forest"])
    assert "counted days" in v["takeaways"]["ov-agent-tile"]


# ---- R2: numbers (spec 5.2)
def test_hero_agent_tile_names_counted_days_and_coin_days(tmp_path):
    t = {x["key"]: x for x in story(make_base(tmp_path))["sections"]["hero"]["tiles"]}["agent_fills"]
    assert t["coin_days"] == t["days"] * t["coins"]
    assert f"{t['days']} counted days" in t["context"] and f"{t['coin_days']:,} coin-days" in t["context"]
    assert t["text"] == f"0 fills · {t['days']} counted days ({t['coin_days']:,} coin-days)"


def test_coin_days_add_the_per_coin_agent_rows_when_they_exist():
    forest = [{"symbol": "ALL", "variant": "agent", "queue_mult": 1.0, "days_total": 53, "fills": 0}] + [
        {"symbol": s, "variant": "agent", "queue_mult": 1.0, "days_total": 53, "fills": 0} for s in ("A", "B", "C")]
    d = bst.agent_days(forest, ["A", "B", "C"])
    assert (d["days"], d["coins"], d["coin_days"]) == (53, 3, 159) and d["context"] == "in 53 counted days (159 coin-days)"


def test_readme_test_count_is_rounded_down_and_not_above_the_last_green_run():
    rec = ROOT / "results" / "tests_passed.json"
    if not rec.exists():
        pytest.skip("no green run recorded yet")
    passed = json.loads(rec.read_text(encoding="utf-8"))["passed"]
    m = re.search(r"[Oo]ver ([\d,]+) tests", (ROOT / "README.md").read_text(encoding="utf-8"))
    assert m, "the README states the test count as 'over N tests'"
    n = int(m.group(1).replace(",", ""))
    assert n % 100 == 0 and n <= passed and passed - n < 100, \
        f"README says over {n}; the last green run had {passed}: write 'over {passed // 100 * 100} tests'"
