"""Recruiter-ready spec R5: every .bat a .py, .js or .md file names exists at the path it gives; the root holds only the
three launchers the Windows Startup entry and the owner use; the moved launchers still run from the repo root."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".venv", "data", "dashboard_public", "__pycache__", ".pytest_cache", ".git", "node_modules"}
# The build ledger (a log) names old, stale and deleted launchers on purpose.
SKIP_FILES = {"docs/progress/v2_ledger.md"}
ROOT_BATS = {"run_24x7.bat", "install_autostart.bat", "run_dashboard.bat"}
MENTION = re.compile(r"(?<![\w*-])((?:[\w.-]+[\\/])*[\w-]+\.bat)\b")


def _sources():
    for f in sorted(ROOT.rglob("*")):
        rel = f.relative_to(ROOT)
        if f.is_file() and f.suffix in (".py", ".js", ".md") and not SKIP_DIRS & set(rel.parts) and rel.as_posix() not in SKIP_FILES:
            yield rel.as_posix(), f.read_text(encoding="utf-8", errors="ignore")


def test_every_bat_mentioned_exists_at_the_path_given():
    missing = []
    for rel, text in _sources():
        for m in MENTION.finditer(text):
            name = m.group(1).replace("\\", "/")
            if not (ROOT / name).is_file():
                missing.append(f"{rel}: {m.group(1)}")
    assert not missing, "\n".join(sorted(set(missing)))


def test_root_has_only_the_three_launchers_and_no_empty_files():
    assert {p.name for p in ROOT.glob("*.bat")} == ROOT_BATS
    assert not [p.name for p in ROOT.iterdir() if p.is_file() and p.stat().st_size == 0 and not p.name.startswith(".")]


def test_moved_launchers_change_to_the_repo_root_first():
    bats = sorted((ROOT / "scripts" / "windows").glob("*.bat"))
    assert bats
    for b in bats:
        lines = [ln.strip() for ln in b.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip()]
        first = next(ln for ln in lines if not re.match(r"(@echo|rem\b|::)", ln, re.I))      # the first command, after comments
        assert first == 'cd /d "%~dp0..\\.."', b.name
