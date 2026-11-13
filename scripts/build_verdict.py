"""Build dashboard/runs/pub-verdict.js from the committed queue-baseline and walk-forward runs.

Usage: python scripts/build_verdict.py [dashboard/runs]
Run scripts/slim_runs.py first if the run files are still large (they are read whole)."""
from __future__ import annotations

import sys
from pathlib import Path

from mm import report as rep
from scripts.slim_runs import load

SOURCES = ("qb-", "wf-")


def main(argv: list[str] | None = None) -> int:
    root = Path((argv or sys.argv[1:] or ["dashboard/runs"])[0])
    runs = [load(p) for p in sorted(root.glob("*.js")) if p.name.startswith(SOURCES)]
    if not runs:
        print("no qb-*/wf-* run files found", file=sys.stderr)
        return 1
    b = rep.verdict_bundle(runs)
    path = rep.write_bundle(b, root, slim=False)
    print(f"verdict -> {path} ({path.stat().st_size / 1e3:.0f} kB)")
    print(b["takeaways"].get("headline", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
