"""Ctrl+Break (how scripts.supervise_live stops its children) must run the normal shutdown path.

On 2026-11-15 the traders died with 0xC000013A on Ctrl+Break and skipped cancel/save/stop-record. These tests
start a real child process the way the supervisor does (own process group, asyncio main loop), send it
CTRL_BREAK_EVENT and check that the `except KeyboardInterrupt` cleanup ran."""
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from mm.paper import install_break_handler

ROOT = Path(__file__).resolve().parents[1]
WIN = os.name == "nt"

CHILD = r"""
import asyncio, sys
from mm.paper import install_break_handler
if sys.argv[1] == "with":
    install_break_handler()
async def run():
    print("ready", flush=True)
    while True:
        await asyncio.sleep(0.05)
try:
    asyncio.run(run())
except KeyboardInterrupt:
    print("cleanup ran", flush=True)
"""


def _break_child(mode: str):
    p = subprocess.Popen([sys.executable, "-c", CHILD, mode], cwd=ROOT, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    try:
        assert p.stdout.readline().strip() == "ready"
        p.send_signal(signal.CTRL_BREAK_EVENT)
        out, _ = p.communicate(timeout=20)
    finally:
        if p.poll() is None:
            p.kill()
    return p.returncode, out


@pytest.mark.skipif(not WIN, reason="Ctrl+Break is Windows only")
def test_ctrl_break_runs_the_shutdown_path():
    code, out = _break_child("with")
    assert "cleanup ran" in out
    assert code == 0


@pytest.mark.skipif(not WIN, reason="Ctrl+Break is Windows only")
def test_without_the_handler_ctrl_break_kills_without_cleanup():
    """The bug this guards against: exit 0xC000013A and no cleanup."""
    code, out = _break_child("without")
    assert "cleanup ran" not in out
    assert code & 0xFFFFFFFF == 0xC000013A


def test_install_is_a_no_op_off_windows():
    assert install_break_handler() == hasattr(signal, "SIGBREAK")
    if hasattr(signal, "SIGBREAK"):
        assert signal.getsignal(signal.SIGBREAK) is signal.default_int_handler
        signal.signal(signal.SIGBREAK, signal.SIG_DFL)


def test_both_entry_points_install_it():
    for mod in ("mm/testnet.py", "mm/paper.py"):
        src = (ROOT / mod).read_text(encoding="utf-8")
        main = src[src.index("def _main("):]
        assert "install_break_handler()" in main.split("\n    ap = ")[0], mod
