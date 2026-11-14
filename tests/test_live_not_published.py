"""Live spec rule 3: nothing from data/testnet, data/paper or dashboard/live may reach the public copy."""
import shutil
from pathlib import Path

from scripts import publish_dashboard as pd_

ROOT = Path(__file__).resolve().parents[1]


def test_public_copy_has_no_live_files(tmp_path, monkeypatch):
    dash = tmp_path / "dashboard"
    shutil.copytree(ROOT / "dashboard", dash, ignore=shutil.ignore_patterns("live"))
    (dash / "live").mkdir()
    for name, body in {"sessions.js": "window.SESSIONS=[]", "session-testnet-BTCUSDT-join.js": "window.SESSION_DATA={}",
                       "tape-testnet-BTCUSDT-join-2026-11-14.js": "window.TAPES={}", "status.js": "window.LIVE={}"}.items():
        (dash / "live" / name).write_text(body)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pd_, "DASH", Path("dashboard"))
    pd_.main(["--out", "pub"])
    pub = tmp_path / "pub"
    files = [p for p in pub.rglob("*") if p.is_file()]
    assert not any("live" in p.relative_to(pub).parts[:-1] for p in files)
    for p in files:
        if p.suffix in (".js", ".html") and p.stat().st_size < 3e6:
            t = p.read_text(encoding="utf-8", errors="ignore")
            assert "SESSION_DATA" not in t.replace("window.SESSION_DATA", "") or p.parts[-2] == "js"
    assert not list(pub.rglob("session-*.js")) and not list(pub.rglob("tape-*.js"))


def test_dashboard_live_is_git_ignored():
    ig = (ROOT / ".gitignore").read_text().splitlines()
    assert "dashboard/live/*" in ig
