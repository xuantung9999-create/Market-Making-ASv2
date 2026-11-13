"""Apply the bundle diet to the committed run files in place (docs/DASHBOARD_REDESIGN.md section 5).

Usage: python scripts/slim_runs.py [dashboard/runs]
Safe to repeat: slimming a slimmed run changes nothing."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from mm import report as rep

SKIP = {"index.js", "demo.js", f"{rep.VERDICT_ID}.js"}


def load(path: Path) -> dict:
    s = path.read_text(encoding="utf-8")
    return json.loads(s[s.index("= {") + 2: s.rstrip().rstrip(";").rindex("}") + 1])


def main(argv: list[str] | None = None) -> int:
    root = Path((argv or sys.argv[1:] or ["dashboard/runs"])[0])
    for p in sorted(root.glob("*.js")):
        if p.name in SKIP:
            continue
        before = p.stat().st_size
        rep.write_bundle(load(p), root)
        print(f"{p.name}: {before / 1e6:.1f} MB -> {p.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
