"""Showcase spec S1: static checks on the views that must not compute or type numbers themselves."""
from pathlib import Path

DASH = Path(__file__).resolve().parent.parent / "dashboard"


def _src(*p):
    return (DASH.joinpath(*p)).read_text(encoding="utf-8")


def test_test_count_is_measured_not_typed():
    assert "testsPassed" not in _src("js", "core.js") + _src("js", "views", "research.js") + _src("js", "views", "data.js")
    assert "tests_passed" in _src("js", "views", "research.js")


def test_live_views_pick_the_range_entry_instead_of_slicing_numbers():
    ov = _src("js", "views", "lv_overview.js")
    assert "by_range" in _src("js", "live_sessions.js") and "rangeEntry(b)" in ov
    assert "r.t + 3.6e6" not in ov and "b.now.open_incidents" not in ov and "b.uptime_24h" not in _src("js", "views", "lv_exec.js")
    assert "tkOf(b)" in _src("js", "views", "lv_pnl.js") and "tkOf(b)" in _src("js", "views", "lv_exec.js")


def test_operations_view_shows_process_facts_only():
    live = _src("js", "views", "live.js")
    assert "s.pnl" not in live and "s.fills" not in live and "s.rejects" not in live and "s.pos" not in live
