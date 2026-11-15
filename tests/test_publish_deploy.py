"""Recruiter-ready spec R1: `publish_dashboard --deploy` (section 5.3). Git is never run: a fake runner records the calls."""
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import publish_dashboard as pd_

URL = "https://github.com/example/Repo.git"


class FakeGit:
    """Records every git call; on `add` it records the files of the tree that will be committed."""

    def __init__(self, push_rc=0, push_err=""):
        self.calls, self.tree, self.push_rc, self.push_err = [], None, push_rc, push_err

    def __call__(self, args, cwd):
        self.calls.append((list(args), Path(cwd)))
        if "add" in args:
            self.tree = sorted(p.relative_to(cwd).as_posix() for p in Path(cwd).rglob("*") if p.is_file())
        if "push" in args:
            return SimpleNamespace(returncode=self.push_rc, stdout="", stderr=self.push_err)
        if "config" in args:
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "config").write_text(
        '[core]\n\tbare = false\n[remote "upstream"]\n\turl = https://wrong.example/x.git\n'
        f'[remote "origin"]\n\turl = {URL}\n\tfetch = +refs/heads/*:refs/remotes/origin/*\n', encoding="utf-8")
    for d in ("mm", "scripts", "results"):
        (root / d).mkdir()
    (root / "mm" / "a.py").write_text("x = 1\n")
    (root / "scripts" / "b.py").write_text("y = 2\n")
    (root / "README.md").write_text("# Title\n\nLive page\n", encoding="utf-8")
    rec = root / "results" / "tests_passed.json"
    rec.write_text('{"passed": 1}\n')
    later = time.time() + 5
    os.utime(rec, (later, later))
    out = root / "dashboard_public"
    (out / "js").mkdir(parents=True)
    (out / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    (out / "js" / "core.js").write_text("var a = 1;", encoding="utf-8")
    return root


def test_deploy_without_live_snapshot_refuses():
    with pytest.raises(SystemExit) as e:
        pd_.main(["--deploy"])
    assert "--live-snapshot" in str(e.value.code)


def test_readme_draft_marker_refuses(repo):
    (repo / "README.md").write_text("# T\n<!-- DRAFT: owner to edit, then delete this line -->\n- box\n", encoding="utf-8")
    assert any("draft" in r.lower() for r in pd_.deploy_refusals(repo))


def test_clean_repo_has_no_refusals(repo):
    assert pd_.deploy_refusals(repo) == []


def test_missing_tests_record_refuses(repo):
    (repo / "results" / "tests_passed.json").unlink()
    assert any("missing" in r for r in pd_.deploy_refusals(repo))


def test_stale_tests_record_refuses(repo):
    newer = time.time() + 60
    os.utime(repo / "mm" / "a.py", (newer, newer))
    assert any("older than mm/a.py" in r for r in pd_.deploy_refusals(repo))


def test_main_refuses_before_publishing_when_the_draft_is_there(repo, monkeypatch):
    (repo / "README.md").write_text("<!-- DRAFT -->\n", encoding="utf-8")
    monkeypatch.setattr(pd_, "DASH", repo / "dashboard")
    with pytest.raises(SystemExit) as e:
        pd_.main(["--live-snapshot", "--deploy", "--out", str(repo / "never")])
    assert "draft" in str(e.value.code).lower() and not (repo / "never").exists()


def test_planted_secret_refuses(repo, capsys):
    (repo / "dashboard_public" / "js" / "core.js").write_text('var k = "api_key=abc";', encoding="utf-8")
    fake = FakeGit()
    assert pd_.deploy(repo / "dashboard_public", repo, "2026-11-15 07:33", runner=fake, git="git", hosts=[]) != 0
    assert "leak" in capsys.readouterr().out and fake.calls == []


def test_pushed_tree_is_the_public_copy_plus_nojekyll_to_gh_pages_on_origin(repo, capsys):
    fake = FakeGit()
    code = pd_.deploy(repo / "dashboard_public", repo, "2026-11-15 07:33", runner=fake, git="git", hosts=[])
    assert code == 0
    assert fake.tree == [".nojekyll", "index.html", "js/core.js"]
    remote = next(a for a, _ in fake.calls if "remote" in a)
    assert remote[-1] == URL
    push = next(a for a, _ in fake.calls if "push" in a)
    assert "--force" in push and push[-2] == "origin" and push[-1] == "HEAD:refs/heads/gh-pages"
    commit = next(a for a, _ in fake.calls if "commit" in a)
    assert commit[-1] == "Publish 2026-11-15 07:33"
    # nothing ran in the repo itself except reading the identity; the work tree is a temporary copy
    assert all(cwd != repo or "config" in a for a, cwd in fake.calls)
    assert all(repo not in cwd.parents for a, cwd in fake.calls if "config" not in a)
    assert pd_.PUBLIC_URL in capsys.readouterr().out


def test_auth_failure_stops_with_the_hint(repo, capsys):
    fake = FakeGit(push_rc=128, push_err="fatal: could not read Username for 'https://github.com': terminal prompts disabled")
    assert pd_.deploy(repo / "dashboard_public", repo, "x", runner=fake, git="git", hosts=[]) != 0
    assert pd_.AUTH_HINT in capsys.readouterr().out


def test_no_git_found_prints_the_commands_and_fails(repo, capsys):
    code = pd_.deploy(repo / "dashboard_public", repo, "2026-11-15 07:33", runner=FakeGit(), git=None, hosts=[])
    out = capsys.readouterr().out
    assert code != 0 and "git push" in out and URL in out and "gh-pages" in out


def test_origin_url_is_read_from_git_config(repo):
    assert pd_.origin_url(repo) == URL
