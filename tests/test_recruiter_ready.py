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
    assert b["takeaways"]["ov-agent-tile"] == "in 53 test days (106 coin-days)" and b["takeaways"]["headline"] == "h"


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
    assert "test days" in v["takeaways"]["ov-agent-tile"]


# ---- R2: numbers (spec 5.2)
def test_hero_agent_tile_names_counted_days_and_coin_days(tmp_path):
    t = {x["key"]: x for x in story(make_base(tmp_path))["sections"]["hero"]["tiles"]}["agent_fills"]
    assert t["coin_days"] == t["days"] * t["coins"]
    assert f"{t['days']} test days" in t["context"] and f"{t['coin_days']:,} coin-days" in t["context"]
    assert t["text"] == f"0 fills · {t['days']} test days ({t['coin_days']:,} coin-days)"


def test_coin_days_add_the_per_coin_agent_rows_when_they_exist():
    forest = [{"symbol": "ALL", "variant": "agent", "queue_mult": 1.0, "days_total": 53, "fills": 0}] + [
        {"symbol": s, "variant": "agent", "queue_mult": 1.0, "days_total": 53, "fills": 0} for s in ("A", "B", "C")]
    d = bst.agent_days(forest, ["A", "B", "C"])
    assert (d["days"], d["coins"], d["coin_days"]) == (53, 3, 159) and d["context"] == "in 53 test days (159 coin-days)"


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


# ---- R4: the Story ends on the next experiment (spec 5.4)
def test_story_ends_on_what_is_next_and_links_to_method_and_limits(tmp_path):
    s = story(make_base(tmp_path))
    last_key = list(s["sections"])[-1]
    nxt = s["sections"][last_key]
    assert last_key == "next" and nxt["title"] == "What is next." and nxt["status"] == "ok"
    text = json.dumps(nxt)
    assert "Sharpe" not in text and "limits" not in nxt
    assert nxt["limits_line"]["href"] == "#about" and nxt["limits_line"]["lead"] == "What these simulations cannot show:"
    assert nxt["limits_line"]["label"] == "Method and limits" and nxt["sentence"].endswith("Not yet evaluated.")


def test_the_caveats_move_to_the_about_page_unchanged(tmp_path):
    s = story(make_base(tmp_path))
    assert s["about_limits"] == {"title": "What this cannot show", "items": ["First limit.", "Second & limit.", "Third limit bold."]}
    html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
    about = html[html.index('id="view-about"'):]
    assert about.index('id="about-cannot"') < about.index("What this is")          # at the top of the page
    js = (ROOT / "dashboard" / "js" / "views" / "story.js").read_text(encoding="utf-8")
    fn = js[js.index("function drawAboutLimits"):]
    assert "about_limits" in fn and "L.title" in fn and "L.items" in fn
    assert "drawAboutLimits()" in (ROOT / "dashboard" / "js" / "views" / "research.js").read_text(encoding="utf-8")


@pytest.mark.skipif(not (ROOT / "dashboard/runs/pub-story.js").exists(), reason="no story bundle")
def test_committed_story_bundle_ends_without_simulator_caveats():
    s = bst.load_js(ROOT / "dashboard/runs/pub-story.js")
    nxt = s["sections"]["next"]
    assert "Sharpe" not in json.dumps(nxt) and nxt["limits_line"]["href"] == "#about"
    assert any("Sharpe" in x for x in s["about_limits"]["items"]) and len(s["about_limits"]["items"]) == 3


# ---- R6: README and history (spec 5.5, 5.6)
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)\)")


def _local_links(md: Path):
    for target in LINK.findall(md.read_text(encoding="utf-8")):
        if re.match(r"[a-z]+:", target) or target.startswith("#"):
            continue
        yield target.split("#")[0]


@pytest.mark.parametrize("doc", ["README.md", "notes/HISTORY.md", "docs/DASHBOARD_GUIDE.md"])
def test_every_image_and_file_link_resolves(doc):
    md = ROOT / doc
    bad = [t for t in _local_links(md) if not (md.parent / t).resolve().exists()]
    assert not bad, f"{doc}: {bad}"


def test_readme_leads_with_the_live_url_and_has_the_owner_approved_box():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    from scripts.publish_dashboard import PUBLIC_URL
    first = [ln for ln in text.splitlines() if ln.strip()][1]                 # the line under the title
    assert PUBLIC_URL in first and first.startswith("**Live page")
    # the owner chose the wording of the box on 15 Nov 2026, so the draft marker (which blocks deploy) is gone
    assert "What I did myself" in text and "<!-- DRAFT" not in text and "draft for the owner" not in text
    assert "SITE block" not in text and "## Dashboard" not in text
    assert "notes/HISTORY.md" in text


def test_readme_sections_come_in_the_spec_order():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    order = ["The result is negative", "showcase-story-1440.png", "## What was built", "What I did myself", "## How it was built",
             "## What is next", "## Run it", "## Testnet trading", "## Layout", "## Model", "notes/HISTORY.md"]
    pos = [text.index(s) for s in order]
    assert pos == sorted(pos)
    assert text.count("![") == 1                                                 # one screenshot embedded, the others linked


def test_history_keeps_the_moved_sections_and_the_day_by_day_commands():
    text = (ROOT / "notes" / "HISTORY.md").read_text(encoding="utf-8")
    for s in ("First real-data result (Day 7)", "From BTC to micro caps (Day 8)", "Informed traders (Day 9", "Tuning and signals",
              "Paper replication", "python -m scripts.run_sweep", "Superseded"):
        assert s in text, s
    assert "at the top of this page" not in text                                 # the superseded note reads on its own


# ---- R7: the page's test count follows the last green run without rebuilding data.js from raw data
def test_refresh_tests_changes_only_the_test_count(tmp_path, monkeypatch):
    from scripts import build_dashboard as bd
    monkeypatch.chdir(tmp_path)
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "tests_passed.json").write_text('{"passed": 567}')
    data = tmp_path / "data.js"
    payload = {"built": "x", "tests_passed": 427, "real_days": [{"symbol": "BTCUSDT"}], "sweep": {"a": [1, 2]}}
    data.write_text("// Generated by scripts/build_dashboard.py. Do not edit by hand.\nwindow.DASH = " + json.dumps(payload) + ";\n", encoding="utf-8")
    assert bd.refresh_tests(data) == 567
    text = data.read_text(encoding="utf-8")
    assert text.startswith("// Generated") and json.loads(text.partition("window.DASH = ")[2].rstrip().rstrip(";")) == {**payload, "tests_passed": 567}
