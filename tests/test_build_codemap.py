"""Code map page (scripts/build_codemap.py): graphify's page gets the site's title, a back link and a phone layout;
the header links to it and the publish step copies it."""
from pathlib import Path

from scripts.build_codemap import BACK, TITLE, adapt

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ("<html><head><title>graphify - graphify-out/graph.html</title><style>body{}</style></head>"
          '<body><div id="graph"></div><div id="sidebar"><div id="theme-wrap"></div></div></body></html>')


def test_adapt_sets_title_back_link_and_phone_layout():
    out = adapt(SAMPLE)
    assert TITLE in out and "graphify-out/graph.html" not in out
    assert out.index(BACK) > out.index('<div id="sidebar">') and out.index(BACK) < out.index('id="theme-wrap"')
    assert "@media (max-width: 640px)" in out and out.count("</style>") == 1


def test_header_links_the_code_map_and_publish_copies_it():
    html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
    header = html[html.index("<header>"):html.index("</header>")]
    assert 'href="codemap.html"' in header
    assert '"codemap.html"' in (ROOT / "scripts" / "publish_dashboard.py").read_text(encoding="utf-8")
