"""Code map page for the dashboard: an interactive graph of the code, built by graphify (github.com/Graphify-Labs/graphify).

    python -m scripts.build_codemap                    # needs the graphify CLI: pip install graphifyy (or GRAPHIFY=<path to graphify>)

Copies the code (mm/, scripts/, dashboard/js/) to a temporary folder, runs `graphify update` there (AST only: no LLM,
nothing leaves the machine, nothing is written into the repo), then writes dashboard/codemap.html with the site's title,
a link back to the dashboard and a stacked layout on phones. The publish step copies it into the public site.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dashboard" / "codemap.html"
SOURCES = ("mm", "scripts", "dashboard/js")
TITLE = "<title>MM-AS Code Map</title>"
BACK = ('<div id="mmas-back" style="padding:10px 12px;border-bottom:1px solid var(--border);font-size:12px">'
        '<a href="index.html#story" style="color:#3987e5;text-decoration:none">&larr; Back to the dashboard</a>'
        '<div style="color:var(--text-2);margin-top:4px">Every function, class and file of the project, linked by calls and imports. '
        'Search a name, or untick groups below.</div></div>')
PHONE_CSS = ("@media (max-width: 640px) { body { flex-direction: column; height: auto; min-height: 100vh; overflow: auto; } "
             "#graph { flex: none; height: 62vh; } #sidebar { width: 100%; border-left: 0; border-top: 1px solid var(--border); } }")


def adapt(html: str) -> str:
    """graphify's graph.html -> the site's page: title, back link at the top of the sidebar, phone layout."""
    start = html.index("<title>")
    html = html[:start] + TITLE + html[html.index("</title>", start) + len("</title>"):]
    html = html.replace('<div id="sidebar">', '<div id="sidebar">\n  ' + BACK, 1)
    html = html.replace("</style>", "  " + PHONE_CSS + "\n</style>", 1)
    return html


def graphify_cmd() -> str:
    exe = os.environ.get("GRAPHIFY") or shutil.which("graphify")
    if not exe:
        raise SystemExit("graphify not found: pip install graphifyy, or set GRAPHIFY to the graphify executable")
    return exe


def build() -> Path:
    exe = graphify_cmd()
    with tempfile.TemporaryDirectory(prefix="mmas-codemap-") as tmp:
        work = Path(tmp)
        for rel in SOURCES:
            shutil.copytree(ROOT / rel, work / rel, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        subprocess.run([exe, "update", "."], cwd=work, check=True)
        html = (work / "graphify-out" / "graph.html").read_text(encoding="utf-8")
    OUT.write_text(adapt(html), encoding="utf-8")
    print(f"code map -> {OUT.relative_to(ROOT).as_posix()} ({OUT.stat().st_size / 1e6:.1f} MB)")
    return OUT


if __name__ == "__main__":
    build()
