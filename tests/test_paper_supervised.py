"""Task L2: the paper trader runs under the 24/7 supervisor (ANKR, COTI, SKL), learning its tick size from the
recorder's own book files when no history was downloaded."""
import json

import numpy as np
import pandas as pd

from mm.paper import PaperSession, book_tick
from scripts.supervise_live import Supervisor, load_config


def write_book(tmp_path, sym, tick, n=400):
    d = tmp_path / "live" / sym / "book"
    d.mkdir(parents=True)
    rng = np.random.default_rng(0)
    k = 2000 + np.cumsum(rng.integers(-2, 3, n))
    pd.DataFrame({"recv_us": np.arange(n) * 1000, "update_id": np.arange(n), "bid": k * tick,
                  "bid_qty": 1.0, "ask": (k + 1) * tick, "ask_qty": 1.0}).to_parquet(d / f"{sym}_book_1.parquet")


def test_book_tick_from_the_recorded_feed(tmp_path):
    write_book(tmp_path, "ANKRUSDT", 1e-5)
    assert abs(book_tick("ANKRUSDT", tmp_path) - 1e-5) < 1e-12
    assert book_tick("NOPEUSDT", tmp_path) is None


def test_session_gets_its_tick_without_downloaded_history(tmp_path):
    write_book(tmp_path, "ANKRUSDT", 1e-5)
    s = PaperSession(["ANKRUSDT"], tmp_path / "state", tmp_path / "paper", data_dir=tmp_path)
    assert abs(s._tick("ANKRUSDT") - 1e-5) < 1e-12


def test_live_config_runs_the_paper_trader(tmp_path):
    cfg = load_config(__import__("pathlib").Path("config/live.json"))
    sup = Supervisor(cfg, base=tmp_path)
    paper = [c for c in sup.children if c.name == "paper"]
    assert len(paper) == 1 and not paper[0].needs_keys
    a = paper[0].args
    assert a[:2] == ["-m", "mm.paper"] and a[a.index("--symbols") + 1] == "ANKRUSDT,COTIUSDT,SKLUSDT"


def test_default_config_has_no_paper_entry_unless_asked(tmp_path):
    sup = Supervisor({"recorder": {"enabled": False}, "testnet": []}, base=tmp_path)
    assert sup.children == []
