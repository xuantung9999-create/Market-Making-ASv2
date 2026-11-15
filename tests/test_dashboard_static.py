"""Static checks on the dashboard files (read as text, no browser)."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

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


NAV_TABS = ["story", "verdict", "fills", "backtests", "exec-test"]           # showcase spec section 5: Story, then Evidence
APPENDIX_HREFS = ["#pnl", "#risk", "#book", "#book/market", "#data/health", "#data/simlive", "#simulator", "#archive",
                  "#about", "#l-health"]
WRAPPERS = set(NAV_TABS) | {"l-health", "book", "pnl", "risk", "data", "simulator", "archive", "about"}
OLD_HASHES = ["l-overview", "l-pnl", "l-exec", "l-model", "l-health", "overview", "execution", "model-health", "pnl", "risk",
              "book", "data", "simulator", "archive", "about", "signals", "market", "model", "replication", "real-data"]


def _nav():
    return re.findall(r'<nav class="tabs".*?</nav>', _html(), re.S)[0]


def test_nav_is_one_row_story_evidence_then_the_appendix_menu():
    """Showcase spec section 5 (changed in S2 from five live tabs + Research): one nav row, no second row."""
    nav = _nav()
    top = re.findall(r'<nav class="tabs"[^>]*>(.*?)<details', nav, re.S)[0]
    assert re.findall(r'<a href="#[^"]+" data-tab="([^"]+)"', top) == NAV_TABS
    menu = re.findall(r'<div class="menu".*?</div>', nav, re.S)[0]
    assert re.findall(r'<a href="([^"]+)"', menu) == APPENDIX_HREFS
    assert "Operations" in menu and "data-local-only" in menu
    assert "research-bar" not in _html() and nav.count("<nav") == 1


def test_header_holds_the_name_and_the_nav_only():
    header = re.findall(r"<header>.*?</header>", _html(), re.S)[0]
    for tag in ("<select", "<button", "<input", "livebar", "runbar", "sess-select"):
        assert tag not in header, tag
    assert "MM-AS" in header


def test_selectors_and_range_buttons_live_in_the_page_bar_and_show_only_where_used():
    html = _html()
    bar = re.findall(r'<div class="pagebar".*?\n  </div>\n  <div class="tab-wrap"', html, re.S)[0]
    for i in ("run-select", "f-symbol", "f-variant", "run-compare", "sess-select", "live-range"):
        assert f'id="{i}"' in bar, i
    core = (DASH / "js" / "core.js").read_text(encoding="utf-8")
    assert 'LIVE_VIEWS = ["lv-overview", "lv-pnl", "lv-exec", "lv-model"]' in core
    assert 'classList.toggle("live-view", LIVE_VIEWS.includes(view))' in core
    assert "body.live-view .livebar { display: flex; }" in html and ".livebar { display: none;" in html


def test_every_nav_link_points_at_a_tab_wrapper_and_every_view_is_in_one():
    t = _tree()
    html = _html()
    wrappers = set(re.findall(r'class="tab-wrap" data-tab="([^"]+)"', html))
    assert wrappers == WRAPPERS
    linked = {a["data-tab"] for a in t.tab_links if a.get("data-tab")}
    assert linked == WRAPPERS                                       # every wrapper is reachable from the nav
    for v in RESEARCH_VIEWS + DESK_VIEWS + ["live", "book", "story", "lv-overview", "lv-pnl", "lv-exec", "lv-model"]:
        assert t.under[f"view-{v}"], f"view-{v} is not inside a tab"
    for v in ("lv-overview", "lv-pnl", "lv-exec"):
        assert t.under[f"view-{v}"] == ["exec-test"], v
    assert t.under["view-lv-model"] == ["archive"] and t.under["view-backtest"] == ["backtests"] and t.under["view-execution"] == ["fills"] and t.under["view-overview"] == ["verdict"]


def test_every_old_hash_resolves_in_core_js():
    core = (DASH / "js" / "core.js").read_text(encoding="utf-8")
    assert "const TABS" in core and "const ALIASES" in core and "function subtabs" in core and "function resolveHash" in core
    for v in RESEARCH_VIEWS + DESK_VIEWS + ["live", "book", "archive", "data"]:
        assert f'"{v}"' in core, v
    for tab in WRAPPERS:
        assert f'"{tab}":' in core, tab
    # the tab keys that disappeared are aliases of their new place; the empty hash lands on the Story
    for old, new in {"overview": "verdict", "execution": "fills", "agent": "archive/model-health", "l-overview": "exec-test",
                     "l-pnl": "exec-test/pnl", "l-exec": "exec-test/tape", "l-model": "archive/lv-model"}.items():
        assert f'"{old}": "{new}"' in core, old
    assert 'DEFAULT_VIEW = { tab: "story", view: "story" }' in core and 'show(location.hash || "#" + DEFAULT_VIEW.tab)' in core


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_hash_map_resolves_every_old_hash_under_node():
    """Run the real resolveHash of core.js with the TABS/ALIASES text it defines, in node, with no browser."""
    core = (DASH / "js" / "core.js").read_text(encoding="utf-8")
    a, b = core.index("const TABS"), core.index("const EVIDENCE_TABS")
    r0, r1 = core.index("function resolveHash"), core.index("/* Segmented control")
    script = core[a:b] + "const DEFAULT_VIEW = { tab: 'story', view: 'story' };\n" + core[r0:r1] + """
    const hs = JSON.parse(process.argv[1]);
    console.log(JSON.stringify(hs.map(h => resolveHash(h))));
    """
    hashes = ["", "#story", "#" + "#".join(OLD_HASHES[:0])] + ["#" + h for h in OLD_HASHES] + ["#exec-test/tape", "#agent", "#backtests", "#agent/lv-model", "#nonsense"]
    r = subprocess.run(["node", "-e", script, json.dumps(hashes)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    got = dict(zip(hashes, json.loads(r.stdout)))
    assert got[""]["tab"] == "story" and got["#nonsense"]["tab"] == "story"
    assert (got["#overview"]["tab"], got["#overview"]["view"]) == ("verdict", "overview")
    assert (got["#execution"]["tab"], got["#execution"]["view"]) == ("fills", "execution")
    assert (got["#model-health"]["tab"], got["#model-health"]["view"]) == ("archive", "model-health")
    assert (got["#agent"]["tab"], got["#agent"]["view"]) == ("archive", "model-health")     # the Story's "See the evidence" link
    assert (got["#backtests"]["tab"], got["#backtests"]["view"]) == ("backtests", "backtest")
    assert (got["#l-overview"]["tab"], got["#l-overview"]["view"]) == ("exec-test", "lv-overview")
    # S6: the Execution test is one page; the old exec and P&L pages are sections of it
    assert (got["#l-exec"]["tab"], got["#l-exec"]["view"], got["#l-exec"]["section"]) == ("exec-test", "lv-overview", "tape")
    assert (got["#l-pnl"]["tab"], got["#l-pnl"]["view"], got["#l-pnl"]["section"]) == ("exec-test", "lv-overview", "pnl")
    assert (got["#l-model"]["tab"], got["#l-model"]["view"]) == ("archive", "lv-model")
    assert (got["#agent/lv-model"]["tab"], got["#agent/lv-model"]["view"]) == ("archive", "lv-model")
    assert (got["#l-health"]["tab"], got["#l-health"]["view"]) == ("l-health", "live")
    for old in ("signals", "market", "model", "replication", "real-data", "pnl", "risk", "book", "data", "simulator", "archive", "about"):
        assert got["#" + old]["tab"] in WRAPPERS, old
    assert got["#model"]["tab"] == "simulator" and got["#market"]["tab"] == "book" and got["#signals"]["tab"] == "archive"
    assert (got["#exec-test/tape"]["tab"], got["#exec-test/tape"]["section"]) == ("exec-test", "tape")


def test_page_change_scrolls_to_top_and_a_section_deep_link_scrolls_to_it():
    core = (DASH / "js" / "core.js").read_text(encoding="utf-8")
    assert "window.scrollTo(0, 0)" in core and "scrollIntoView" in core and "const changed = view !== shownView" in core


def test_footer_shows_only_the_provenance_that_applies_to_the_page():
    core = (DASH / "js" / "core.js").read_text(encoding="utf-8")
    assert "function drawFooter" in core and "Backtest built" in core and "Live snapshot frozen" in core and "Live data built" in core
    assert "if (story || !live)" in core and "if (story || live)" in core
    assert "foot-built" not in (DASH / "js" / "views" / "research.js").read_text(encoding="utf-8")


def test_operations_entry_is_removed_from_the_public_menu_and_the_name_is_one_everywhere():
    core = (DASH / "js" / "core.js").read_text(encoding="utf-8")
    assert "if (window.PUBLIC_SITE) d.querySelectorAll(\"[data-local-only]\").forEach(a => a.remove())" in core
    name = "Crypto market making: from Avellaneda–Stoikov to a queue-aware agent"
    html = _html()
    assert f"<title>{name}</title>" in html and f'<h1 class="story-title">{name}</h1>' in html
    assert "Avellaneda–Stoikov Market Maker" not in html


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


def test_no_duplicate_element_ids_and_the_live_views_are_loaded():
    """The live tabs share the page with the Research views: a repeated id draws a chart into the wrong tab."""
    from collections import Counter
    html = _html()
    dups = [i for i, n in Counter(re.findall(r'\sid="([^"]+)"', html)).items() if n > 1]
    assert not dups, dups
    for f in ("live_sessions.js", "views/lv_overview.js", "views/lv_pnl.js", "views/lv_exec.js", "views/lv_model.js", "views/lv_health.js"):
        assert f'src="js/{f}"' in html, f
        assert "fetch(" not in (DASH / "js" / f).read_text(encoding="utf-8"), f


# ---- showcase S4: the Story page draws the story bundle and types no finding ----
def _story_js():
    return (DASH / "js" / "views" / "story.js").read_text(encoding="utf-8")


def test_story_view_is_wired_and_reads_only_the_story_bundle():
    html, js = _html(), _story_js()
    assert 'id="story-body"' in html and 'src="runs/pub-story.js"' in html and 'src="js/views/story.js"' in html
    assert 'register("story", drawStory)' in js and "window.STORY" in js
    assert "fetch(" not in js


def test_story_view_types_no_digit_bearing_text_outside_the_format_helpers():
    """Python writes every sentence and number (spec S4): a string literal with a digit may only sit between the markers."""
    js = _story_js()
    a, b = js.index("/* ---- format helpers"), js.index("/* ---- end format helpers ---- */")
    outside = js[:a] + js[b:]
    outside = re.sub(r"/\*.*?\*/", "", outside, flags=re.S)
    outside = re.sub(r"(?m)//.*$", "", outside)
    literals = re.findall(r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'|`(?:\\.|[^`\\])*`', outside)
    def has_digit(s):       # template holes, HTML tag names (h2, h3) and a bare tag selector are not text
        if re.fullmatch(r"[\"'`]h\d[\"'`]", s):
            return False
        s = re.sub(r"\$\{[^}]*\}", "", s)
        s = re.sub(r"</?[a-zA-Z][a-zA-Z0-9]*", "", s)
        return bool(re.search(r"\d", s))
    bad = [s for s in literals if has_digit(s)]
    assert not bad, bad
    # the page HTML holds no number of the story either: only the heading and the empty container
    view = re.search(r'<section class="view" id="view-story">(.*?)</section>', _html(), re.S).group(1)
    assert not re.search(r"\d", re.sub(r'</?[a-zA-Z][a-zA-Z0-9]*|class="[^"]*"|id="[^"]*"', "", view))


def test_story_view_has_every_section_of_the_spec():
    js = _story_js()
    for fn in ("storyHero", "storyStack", "storyForest", "storyWaterfall", "storyLadder", "storyAgent", "storyExecution", "storyNext"):
        assert f"function {fn}(" in js and fn in js.split("function drawStory")[1], fn
    assert "displayModeBar: false" in js and "scrollZoom: false" in js


# ---- showcase S5: the three Evidence pages ----
def test_verdict_gate_table_prints_a_value_for_every_condition():
    js = (DASH / "js" / "views" / "overview.js").read_text(encoding="utf-8")
    assert "gateValueText(name, c)" in js and "value_text" in js
    story = (DASH / "runs" / "pub-story.js").read_text(encoding="utf-8")
    conds = json.loads(story[story.index("{"):story.rindex("}") + 1])["sections"]["agent"]["gate"]["conditions"]
    assert conds and all(c.get("value_text") for c in conds)


def test_fill_economics_page_holds_the_attribution_waterfall_and_the_page_sentence():
    html = _html()
    ex = re.search(r'<section class="view" id="view-execution">(.*?)</section>', html, re.S).group(1)
    assert 'id="fe-wf"' in ex and 'id="fe-headline"' in ex
    assert 'drawPnlWaterfall(b, "fe-wf")' in (DASH / "js" / "views" / "execution.js").read_text(encoding="utf-8")
    assert 'id="pnl-wf"' in html                       # the appendix P&L page keeps its own copy


def test_agent_page_has_its_sentence_and_the_paper_sessions_have_their_own_selector():
    html = _html()
    assert 'id="ag-headline"' in html and "ag-headline" in (DASH / "js" / "views" / "model.js").read_text(encoding="utf-8")
    ls = (DASH / "js" / "live_sessions.js").read_text(encoding="utf-8")
    assert 'v === "lv-model" ? "paper" : "testnet"' in ls and "mine.some" in ls
    assert '"agent": "archive/model-health"' in (DASH / "js" / "core.js").read_text(encoding="utf-8")


# ---- showcase S6: the Execution test is one page in the order of spec section 7
def test_execution_test_is_one_page_in_spec_order_with_the_pnl_folded_away():
    html = _html()
    v = re.search(r'<section class="view" id="view-lv-overview">(.*?)</section>', html, re.S).group(1)
    order = ["xt-purpose", 'id="xt-caught"', 'id="ov2-state"', 'id="lvx-state"', 'id="lvx-funnel"', 'id="lvx-wait"', 'id="lvx-markout"',
             'id="lvx-edge"', 'id="ov2-incidents"', 'id="sec-tape"', 'id="lvx-fills"', 'id="sec-pnl"']
    pos = [v.index(o) for o in order]
    assert pos == sorted(pos), order
    fold = re.search(r"<details[^>]*id=\"sec-pnl\"[^>]*>(.*)</details>", v, re.S)
    assert fold and "open" not in re.search(r"<details[^>]*>", v).group(0).split()      # collapsed by default
    for i in ("ov2-cum", "lvp-waterfall", "lvp-days", "lvp-worst", "xt-pnl-summary"):
        assert f'id="{i}"' in fold.group(0), i
    for old in ("lv-pnl", "lv-exec"):                      # the old pages stay as empty shells so every id and old link resolves
        assert re.search(rf'<section class="view" id="view-{old}"[^>]*></section>', html)


def test_execution_test_opens_on_the_curated_tape_and_draws_one_page():
    ex = (DASH / "js" / "views" / "lv_exec.js").read_text(encoding="utf-8")
    assert "STORY.tape_example" in ex and "Tape.example()" in ex and 'register("lv-overview"' in ex
    assert "drawLvOverview(); drawExecHead(); drawLvPnl(); drawLvExec();" in ex
    assert 'const all = "";' in (DASH / "js" / "live_sessions.js").read_text(encoding="utf-8")


def test_agent_pages_open_on_a_walk_forward_run_not_the_baseline():
    core = (DASH / "js" / "core.js").read_text(encoding="utf-8")
    assert 'AGENT_VIEWS = ["model-health", "signals"]' in core and "function ensureAgentRun" in core
    assert "ensureAgentRun();" in core and 'r.kind === "walkforward"' in core


# ---- showcase S8 (audit A3): the About page leads with the real result; the simulated numbers sit under Paper replication
def test_about_head_has_no_simulated_sharpe_or_fill_r2_and_replication_holds_them_with_a_caveat():
    r = (DASH / "js" / "views" / "research.js").read_text(encoding="utf-8")
    head = r[r.index("function drawHeader"):r.index("register(\"simulator\"")]
    assert "Sharpe, A-S vs benchmark" not in head and "Fill model fit on BTC" not in head and "Profit volatility cut" not in head
    assert "window.STORY.sections.hero" in head
    rep = r[r.index("function drawReplication"):r.index("function drawHeader") if False else r.index("/* =======================", r.index("function drawReplication"))]
    assert "Sharpe, A-S vs benchmark" in rep and "Fill-curve fit, BTC" in rep and 'getElementById("rep-tiles")' in rep
    view = re.search(r'<section class="view" id="view-replication">(.*?)</section>', _html(), re.S).group(1)
    assert 'id="rep-tiles"' in view and "no adverse selection, fees, tick size or latency" in view


# ---------------------------------------------------------------- session chart (C1)
SIMULATE_BOTH_SHA256 = "e925e6049d299abb85f485dc38ccaea936121aeaffa56be2e543886fea13a56e"


def _script_order():
    return re.findall(r'<script[^>]*\bsrc="([^"]+)"', _html())


def test_session_chart_is_loaded_after_core_and_before_every_view():
    order = _script_order()
    assert "js/session_chart.js" in order
    i = order.index("js/session_chart.js")
    assert order.index("js/core.js") < i
    first_view = min(k for k, s in enumerate(order) if s.startswith("js/views/"))
    assert i < first_view


def test_session_chart_is_self_contained():
    src = (DASH / "js" / "session_chart.js").read_text(encoding="utf-8")
    assert "fetch(" not in src
    for name in ("SIM", "Sess", "SESSION_DATA"):
        assert not re.search(r"\b" + name + r"\b", src), name
    assert "module.exports = { frameIndex, check, plotX }" in src


def test_session_chart_defines_and_exports_plotx():
    src = (DASH / "js" / "session_chart.js").read_text(encoding="utf-8")
    assert re.search(r"^function plotX\(xType, v\)", src, re.M)
    assert re.search(r"module\.exports = \{[^}]*\bplotX\b", src)
    assert re.search(r"return \{[^}]*\bplotX\b[^}]*\};\s*\}\)\(\);", src)


def test_session_chart_hands_plotly_no_raw_x_on_a_date_axis():
    src = (DASH / "js" / "session_chart.js").read_text(encoding="utf-8")
    assert "range: R.x" not in src
    for raw in ("x: e.x", "x: xEnd"):
        assert raw not in src, raw


def test_pc_status_activity_chart_gives_its_date_axis_iso_strings():
    src = (DASH / "js" / "views" / "live.js").read_text(encoding="utf-8")
    assert "new Date(h).toISOString()" in src
    assert "x: hs," not in src


def test_simulator_page_has_one_session_chart_and_no_old_replay_ids():
    html = _html()
    assert 'id="ch-session"' in html
    for gone in ("btn-replay", "ch-path", "ch-inv"):
        assert gone not in html, gone
        for f in _js_files():
            assert gone not in f.read_text(encoding="utf-8"), (gone, f.name)


def test_simulate_both_body_is_unchanged():
    import hashlib
    txt = (DASH / "js" / "views" / "research.js").read_text(encoding="utf-8")
    body = re.search(r"function simulateBoth\(.*?\n\}\n", txt, re.S).group(0)
    assert hashlib.sha256(body.encode("utf-8")).hexdigest() == SIMULATE_BOTH_SHA256


def test_research_js_dropped_the_old_path_helpers_and_mounts_the_chart():
    txt = (DASH / "js" / "views" / "research.js").read_text(encoding="utf-8")
    for gone in ("pathTraces", "pathLayout", "drawPath", "drawInv"):
        assert gone not in txt, gone
    assert "SessionChart.mount" in txt


# ---------------------------------------------------------------- session chart, live views (C3)
def _lv_chart_js():
    return (DASH / "js" / "views" / "lv_chart.js").read_text(encoding="utf-8")


def test_live_chart_cards_sit_where_the_spec_puts_them():
    html = _html()
    ov = re.search(r'<section class="view" id="view-lv-overview">(.*?)</section>', html, re.S).group(1)
    assert 'id="lvc-exec"' in ov and ov.index('id="xt-caught"') < ov.index('id="lvc-exec"') < ov.index('id="ov2-state"')
    mo = re.search(r'<section class="view" id="view-lv-model">(.*?)</section>', html, re.S).group(1)
    body = mo[mo.index('id="lvm-body"'):]
    assert 'id="lvc-agent"' in body and body.index('id="lvc-agent"') < body.index('id="lvm-strip"')
    assert html.count('id="lvc-exec"') == 1 and html.count('id="lvc-agent"') == 1


def test_live_chart_script_order_and_the_chart_file_is_loaded_with_the_bundle():
    order = _script_order()
    i = order.index("js/views/lv_chart.js")
    assert i > order.index("js/session_chart.js") and i > order.index("js/live_sessions.js")
    ls = (DASH / "js" / "live_sessions.js").read_text(encoding="utf-8")
    assert "chart-${id}.js" in ls and "S.charts" in ls
    assert "drawLvChart(" in (DASH / "js" / "views" / "lv_overview.js").read_text(encoding="utf-8")
    assert "drawLvChart(" in (DASH / "js" / "views" / "lv_model.js").read_text(encoding="utf-8")


def test_live_chart_adapter_does_no_arithmetic_and_types_no_number():
    js = re.sub(r"(?m)//.*$", "", re.sub(r"/\*.*?\*/", "", _lv_chart_js(), flags=re.S))
    for banned in ("Math.max", "Math.min", ".reduce(", "+="):
        assert banned not in js, banned
    assert "fetch(" not in js
    literals = re.findall(r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'|`(?:\\.|[^`\\])*`', js)
    fixed = "\"The session chart is written with the next 5-minute build.\""        # the one sentence the spec dictates; its number is the build cadence
    bad = [s for s in literals if s != fixed and re.search(r"\d", re.sub(r"\$\{[^}]*\}", "", s))]
    assert not bad, bad
    assert "The session chart is written with the next 5-minute build." in js


def test_fills_page_says_when_the_selected_variant_made_no_fills():
    html = _html()
    v = re.search(r'<section class="view" id="view-execution">(.*?)</section>', html, re.S).group(1)
    assert 'id="ex-nofill"' in v and v.index('id="fe-headline"') < v.index('id="ex-nofill"') < v.index('id="ex-side"')
    js = (DASH / "js" / "views" / "execution.js").read_text(encoding="utf-8")
    assert "drawNoFillNote(b)" in js and "made no fills" in js and "fetch(" not in js


# ---- Recruiter-ready spec R3: narrow screens (section 4)
def _view(name):
    return (DASH / "js" / "views" / name).read_text(encoding="utf-8")


def test_nav_row_scrolls_inside_itself_with_no_visible_scrollbar():
    css = _html()
    rules = re.findall(r"nav\.tabs\s*\{([^}]*)\}", css)
    assert any("overflow-x: auto" in r for r in rules)
    assert "scrollbar-width: none" in css and "nav.tabs::-webkit-scrollbar" in css and "header.nav-more::after" in css
    assert "navToActive()" in (DASH / "js" / "core.js").read_text(encoding="utf-8")


def test_forest_plots_measure_their_left_margin():
    for name, fn in (("story.js", "storyForest"), ("overview.js", "drawVerdictForest")):
        src = _view(name)
        body = src[src.index(f"function {fn}"):]
        body = body[:body.index("\n}\n")]
        assert "label_short" in body or "catLabel" in body, name
        for m in re.findall(r"\bl:\s*(\d+)", body):
            assert int(m) <= 120, f"{name} {fn}: fixed left margin {m}"
        assert "catMargin(" in body, name


def test_no_view_rotates_tick_labels():
    for p in (DASH / "js").rglob("*.js"):
        for m in re.findall(r"tickangle:\s*(-?\d+)", p.read_text(encoding="utf-8")):
            assert int(m) == 0, f"{p.name}: tickangle {m}"


def test_long_text_tables_carry_data_labels_and_stack():
    story = _view("story.js")
    assert 'class="gates story-gates stack"' in story and story.count('data-label="') >= 4
    ov = _view("overview.js")
    assert 'class="gates stack"' in ov and ov.count('data-label="') >= 4
    lv = _view("lv_overview.js")
    assert 'class="xt-caught stack"' in lv and lv.count('data-label="') >= 3
    assert "stack: true" in lv[lv.index("function drawIncidentList"):]
    sess = (DASH / "js" / "live_sessions.js").read_text(encoding="utf-8")
    assert 'data-label="${esc(c.label)}"' in sess and 'opt.stack ? " stack"' in sess
    css = _html()
    assert re.search(r"@media \(max-width: 640px\)[^@]*table\.stack thead \{ display: none; \}", css)


def test_wide_tables_pin_their_first_column_and_fade():
    css = _html()
    assert re.search(r"table:not\(\.stack\) td:first-child \{ position: sticky; left: 0", css)
    assert ".table-wrap.more-right" in css and "mask-image" in css
