"""Records the size of the passing test suite so the dashboard never shows a typed-in test count
(showcase spec section 9, rule 9). ``scripts/build_dashboard.py`` reads ``results/tests_passed.json`` into
``data.js`` (``tests_passed``). Only a complete, green run of the whole suite writes it."""
import json
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent / "results" / "tests_passed.json"


def pytest_sessionfinish(session, exitstatus):
    cfg = session.config
    args = [str(a) for a in cfg.invocation_params.args if not str(a).startswith("-")]
    partial = bool(cfg.getoption("keyword", "") or cfg.getoption("markexpr", "") or cfg.getoption("deselect", None)
                   or cfg.getoption("lf", False) or cfg.getoption("ff", False)
                   or any(a.replace("\\", "/").rstrip("/") not in ("", ".", "tests") for a in args))
    if int(exitstatus) != 0 or partial or session.testscollected < 1:
        return
    try:
        OUT.parent.mkdir(exist_ok=True)
        OUT.write_text(json.dumps({"passed": int(session.testscollected),
                                   "at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}) + "\n", encoding="utf-8")
    except OSError:
        pass
