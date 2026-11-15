"""Build dashboard/runs/pub-verdict.js from the committed queue-baseline and walk-forward runs.

Usage: python scripts/build_verdict.py [dashboard/runs]
Run scripts/slim_runs.py first if the run files are still large (they are read whole)."""
from __future__ import annotations

import sys
from pathlib import Path

from mm import report as rep
from scripts.slim_runs import load

SOURCES = ("qb-", "wf-")


def finish(b: dict) -> dict:
    """The phone additions of the recruiter-ready spec (5.1, 5.2): label_short on every forest row, and the Agent fills tile's
    context ('in 53 test days (159 coin-days)') in the takeaways the Verdict tab prints."""
    from scripts import build_story
    b = {**b, "forest": build_story.add_short_labels(b.get("forest") or [])}
    coins = sorted({r["symbol"] for r in b["forest"] if r.get("symbol") != "ALL" and r.get("variant") == "join_touch"})
    agd = build_story.agent_days(b["forest"], coins)
    if agd:
        b["takeaways"] = {**(b.get("takeaways") or {}), "ov-agent-tile": agd["context"]}
    return b


def main(argv: list[str] | None = None) -> int:
    root = Path((argv or sys.argv[1:] or ["dashboard/runs"])[0])
    runs = [load(p) for p in sorted(root.glob("*.js")) if p.name.startswith(SOURCES)]
    if not runs:
        print("no qb-*/wf-* run files found", file=sys.stderr)
        return 1
    b = finish(rep.verdict_bundle(runs))
    path = rep.write_bundle(b, root, slim=False)
    print(f"verdict -> {path} ({path.stat().st_size / 1e3:.0f} kB)")
    print(b["takeaways"].get("headline", ""))
    from scripts import build_story            # the Story page reads the verdict bundle: rebuild it with it
    build_story.main([str(root.parent.parent)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
