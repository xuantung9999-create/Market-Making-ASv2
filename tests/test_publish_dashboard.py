"""R10: the publishable copy carries the Verdict bundle and the newest book bundle, never demo data."""
import json
import shutil
from pathlib import Path

import pytest

from scripts import publish_dashboard as pd_

ROOT = Path(__file__).resolve().parents[1]


def read_js(path: Path) -> dict:
    return pd_.load_run(path)


@pytest.fixture()
def site(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "dashboard", tmp_path / "dashboard")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pd_, "DASH", Path("dashboard"))
    return tmp_path


def test_default_publish_includes_the_verdict_bundle_and_no_demo(site):
    pd_.main(["--out", "pub"])
    out = site / "pub" / "runs"
    idx = json.loads((out / "index.js").read_text()[len("window.RUN_INDEX = "):].rstrip().rstrip(";"))
    ids = [r["run_id"] for r in idx]
    assert "pub-verdict" in ids and (out / "pub-verdict.js").exists()
    assert not any("demo" in i for i in ids) and not (out / "demo.js").exists()
    src = read_js(ROOT / "dashboard" / "runs" / "pub-verdict.js")
    pub = read_js(out / "pub-verdict.js")
    assert pub["forest"] == src["forest"] and pub["takeaways"] == src["takeaways"]


def test_the_newest_book_bundle_is_published_and_older_ones_are_not(site):
    runs = site / "dashboard" / "runs"
    base = read_js(runs / "pub-verdict.js")
    entries = json.loads((runs / "index.js").read_text()[len("window.RUN_INDEX = "):].rstrip().rstrip(";"))
    for rid in ("book-2026-11-10", "book-2026-11-12"):
        b = {**base, "run_id": rid, "kind": "book"}
        (runs / f"{rid}.js").write_text(f'window.RUNS["{rid}"] = {json.dumps(b)};\n')
        entries.append({**next(e for e in entries if e["run_id"] == "pub-verdict"), "run_id": rid, "kind": "book"})
    (runs / "index.js").write_text("window.RUN_INDEX = " + json.dumps(entries) + ";\n")
    pd_.main(["--out", "pub"])
    names = {p.name for p in (site / "pub" / "runs").iterdir()}
    assert "pub-book-2026-11-12.js" in names and "pub-book-2026-11-10.js" not in names
    idx = json.loads((site / "pub" / "runs" / "index.js").read_text()[len("window.RUN_INDEX = "):].rstrip().rstrip(";"))
    assert [r["kind"] for r in idx].count("book") == 1
