"""Static checks on the dashboard files (read as text, no browser)."""
import re
from pathlib import Path

DASH = Path(__file__).resolve().parent.parent / "dashboard"
RESEARCH_VIEWS = ["simulator", "model", "replication", "real-data", "backtest",
                  "universe", "informed", "tuning", "about"]
DESK_VIEWS = ["overview", "pnl", "execution", "risk", "model-health",
              "signals", "market", "simlive", "health"]


def _html():
    return (DASH / "index.html").read_text(encoding="utf-8")


def _js_files():
    return [p for p in (DASH / "js").rglob("*.js")]


def test_research_view_ids_present():
    html = _html()
    for v in RESEARCH_VIEWS:
        assert f'id="view-{v}"' in html, v


def test_desk_view_ids_present():
    html = _html()
    for v in DESK_VIEWS:
        assert f'id="view-{v}"' in html, v


def test_no_long_inline_scripts():
    html = _html()
    for body in re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, flags=re.S):
        assert body.count("\n") <= 20, "inline <script> longer than 20 lines"


def test_script_src_paths_exist():
    html = _html()
    for src in re.findall(r'<script[^>]*\bsrc="([^"]+)"', html):
        if src.startswith(("http://", "https://")):
            continue
        assert (DASH / src).exists(), src


def test_no_fetch_anywhere_except_live_poller():
    files = [DASH / "index.html"] + _js_files()
    for f in files:
        if f.name == "live.js":
            continue
        assert "fetch(" not in f.read_text(encoding="utf-8"), f.name


def test_source_js_has_no_fetch():
    src = DASH / "js" / "source.js"
    assert src.exists()
    assert "fetch(" not in src.read_text(encoding="utf-8")


# ---------------------------------------------------------------- redesign shell (R1)
from html.parser import HTMLParser

OLD_NESTED = ["model", "replication", "signals", "market", "simlive", "health"]


class _Tree(HTMLParser):
    """Records tab links and, for every element with an id, the data-tab ancestors it sits under."""
    def __init__(self):
        super().__init__()
        self.stack, self.tab_links, self.in_nav, self.under = [], [], False, {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "nav" and "tabs" in (a.get("class") or ""):
            self.in_nav = True
        if self.in_nav and tag == "a":
            self.tab_links.append(a)
        if a.get("id"):
            self.under[a["id"]] = [t for t in self.stack if t]
        if tag not in ("br", "img", "input", "meta", "link", "hr"):
            self.stack.append(a.get("data-tab"))

    def handle_endtag(self, tag):
        if tag == "nav":
            self.in_nav = False
        if self.stack:
            self.stack.pop()


def _tree():
    t = _Tree()
    t.feed(_html())
    return t


def test_tab_row_has_exactly_eleven_links():
    assert len(_tree().tab_links) == 11


def test_tab_row_has_no_link_to_a_nested_view():
    views = {a.get("data-view") for a in _tree().tab_links}
    assert not views & set(OLD_NESTED)


def test_live_and_book_views_exist():
    html = _html()
    assert 'id="view-live"' in html and 'id="view-book"' in html


def test_model_and_replication_live_under_the_simulator_tab():
    under = _tree().under
    assert "simulator" in under["view-model"] and "simulator" in under["view-replication"]


def test_every_tab_link_points_at_a_tab_wrapper_and_every_view_is_in_one():
    t = _tree()
    html = _html()
    wrappers = set(re.findall(r'class="tab-wrap" data-tab="([^"]+)"', html))
    assert {a["data-view"] for a in t.tab_links} == wrappers
    for v in RESEARCH_VIEWS + DESK_VIEWS + ["live", "book"]:
        assert t.under[f"view-{v}"], f"view-{v} is not inside a tab"


def test_every_old_hash_resolves_to_a_tab_in_core_js():
    core = (DASH / "js" / "core.js").read_text(encoding="utf-8")
    assert "const TABS" in core and "function subtabs" in core
    for v in RESEARCH_VIEWS + DESK_VIEWS + ["live", "book", "archive", "data"]:
        assert f'"{v}"' in core, v


def test_demo_run_is_hidden_unless_asked_for():
    assert "demo=1" in (DASH / "js" / "core.js").read_text(encoding="utf-8")


# ---------------------------------------------------------------- live monitor (R7)
import json
import shutil
import subprocess

import pytest


def _live_js():
    return (DASH / "js" / "live.js").read_text(encoding="utf-8")


def test_live_js_is_the_only_file_that_fetches_and_only_over_http():
    src = _live_js()
    assert "fetch(" in src and "location.protocol" in src
    assert "/data/live/heartbeat.json" in src and "/data/paper/snapshot.json" in src and "/data/testnet/" in src
    assert "2000" in src and "10000" in src
    assert 'src="js/live.js"' in _html()


def test_live_view_has_its_panels_and_the_testnet_label():
    html = _html()
    for i in ("lv-status", "lv-feed", "lv-testnet", "lv-paper"):
        assert f'id="{i}"' in html, i
    assert "TESTNET: execution test, not a result" in _live_js()


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_live_state_machine_tolerates_one_bad_read_and_gives_up_after_three():
    script = """
    const L = require(process.argv[1]);
    const s = L.newSource();
    const out = [];
    out.push(L.status(s));                                  // nothing yet
    L.record(s, true, {a: 1}, 1000); out.push(L.status(s)); // ok
    L.record(s, false, null, 2000);  out.push(L.status(s)); // one bad read: data kept
    out.push(JSON.stringify(s.data));
    L.record(s, false, null, 3000);  L.record(s, false, null, 4000); out.push(L.status(s));
    L.record(s, true, {a: 2}, 5000); out.push(L.status(s)); // recovers
    out.push(L.ageClass(3), L.ageClass(30), L.ageClass(90), L.ageClass(null));
    console.log(JSON.stringify(out));
    """
    r = subprocess.run(["node", "-e", script, str(DASH / "js" / "live.js")], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == ["waiting", "ok", "retry", '{"a":1}', "nofeed", "ok", "ok", "amber", "red", "na"]


# ---- Sim vs live (D11): the comparison arithmetic lives in js/compare.js and runs under node -------
def _compare(a, b, va="agent", vb="agent"):
    script = """
    const C = require(process.argv[1]);
    const [a, b, va, vb] = JSON.parse(process.argv[2]);
    console.log(JSON.stringify(C.compareRuns(a, b, va, vb)));
    """
    r = subprocess.run(["node", "-e", script, str(DASH / "js" / "compare.js"), json.dumps([a, b, va, vb])],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _run(rows, variant="agent"):
    return {"days": [dict(symbol=s, date=d, variant=variant, fills=f, notional=n, pnl=p, net_edge_bp=e)
                     for s, d, f, n, p, e in rows]}


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_compare_consistent_when_fills_within_30pct_and_edge_within_2bp():
    sim = _run([("A", "d1", 100, 10_000, -5.0, -3.0), ("A", "d2", 120, 12_000, -6.0, -3.0), ("B", "d1", 50, 5_000, -2.0, -3.0)])
    live = _run([("A", "d1", 90, 9_000, -4.0, -2.0), ("A", "d2", 130, 13_000, -7.0, -2.5), ("B", "d3", 999, 9_999, 9.0, 9.0)], "paper")
    out = _compare(sim, live, "agent", "paper")
    assert out["verdict"]["state"] == "consistent"
    assert out["common_days"] == 2                                   # B d1 and B d3 are not in both
    by = {r["label"]: r for r in out["rows"]}
    assert by["Fills per coin-day"]["a"] == 110 and by["Fills per coin-day"]["b"] == 110
    assert out["curves"]["dates"] == ["d1", "d2"] and out["curves"]["a"] == [-5.0, -11.0] and out["curves"]["b"] == [-4.0, -11.0]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_compare_flags_disagreement_overlap_and_no_fills():
    base = [("A", "d1", 100, 10_000, -5.0, -3.0)]
    assert _compare(_run(base), _run([("A", "d1", 200, 20_000, -9.0, -3.0)]))["verdict"]["state"] == "disagree"      # 2x fills
    assert _compare(_run(base), _run([("A", "d1", 100, 10_000, -5.0, 0.5)]))["verdict"]["state"] == "disagree"       # 3.5 bp edge gap
    assert _compare(_run(base), _run([("B", "d1", 100, 10_000, -5.0, -3.0)]))["verdict"]["state"] == "no-overlap"
    v = _compare(_run(base), _run([("A", "d1", 0, 0, 0.0, None)]))["verdict"]
    assert v["state"] == "no-fills"
    assert "fills_ratio" in _compare(_run(base), _run(base))["verdict"]


def test_universe_and_sim_vs_live_views_are_built_not_placeholders():
    html = _html()
    for i in ("un-table", "un-vol", "sl-verdict", "sl-table", "sl-pnl", "sl-fills", "sl-mk"):
        assert f'id="{i}"' in html, i
    for js in ("js/compare.js", "js/views/universe.js", "js/views/simlive.js"):
        assert f'src="{js}"' in html and (DASH / js).exists(), js
    assert "Next on the build list" not in html
    assert "fetch(" not in (DASH / "js" / "views" / "simlive.js").read_text(encoding="utf-8")


def test_data_tab_has_the_tape_validation_card():
    assert 'id="dh-tape"' in _html() and 'id="dh-tape-verdict"' in _html()
    js = (DASH / "js" / "views" / "data.js").read_text(encoding="utf-8")
    assert "drawDataTape" in js and "tape_validation" in js


def test_time_range_buttons_are_shared_and_default_to_all():
    core = (DASH / "js" / "core.js").read_text(encoding="utf-8")
    assert 'const RANGE = { days: "all" }' in core and "function rangeX" in core
    for f in ("pnl", "risk"):
        assert "rangeX(" in (DASH / "js" / "views" / f"{f}.js").read_text(encoding="utf-8"), f


def test_book_view_has_the_depth_panels_and_a_recorder_hint():
    assert 'id="bk-ladder"' in _html() and 'id="bk-depth"' in _html()
    js = (DASH / "js" / "views" / "book.js").read_text(encoding="utf-8")
    assert "drawBookDepth" in js and "--depth" in js
