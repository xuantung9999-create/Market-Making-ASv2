"""24/7 supervisor: keeps the order-book recorder and the testnet traders running, restarts them
if they crash, and refreshes the dashboard's Live tab every minute.

    python -m scripts.supervise_live                  # uses config/live.json
    run_24x7.bat                                      # same, plus first-time setup (Windows)

What it runs (config/live.json):
  recorder   python -m mm.recorder --symbols-file config/candidates.txt   (public data, no keys;
             "depth": true in the recorder block adds --depth)
  testnet    one python -m mm.testnet process per entry (needs .env with testnet keys; if the keys
             are missing it waits and checks again every minute, the recorder keeps running)
  paper      python -m mm.paper --symbols ...   (config "paper": {"symbols": [...]}; no keys, no orders)

Restarts: a crashed process is restarted after 10 s, doubling up to 5 min while it keeps failing;
the wait resets once it has run for 10 minutes. Logs: results/live_<name>.log (rotated at 20 MB).
Ctrl+C: the testnet traders get a Ctrl+Break so they cancel their open orders, then everything stops.

State for the dashboard: data/live_status/supervisor.json (process, pid, uptime, restarts, last exit).

Dashboard over the home network: the supervisor also serves the dashboard/ folder (only that folder)
on port 8765 (config "dashboard_port", 0 = off). Open http://<PC address>:8765 from any phone or laptop
on the same Wi-Fi; the address is printed at start and shown on the PC status tab. Windows asks once
to allow Python through the firewall: allow it on private networks.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import platform
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

WIN = os.name == "nt"
DEFAULT_CONFIG = {
    "recorder": {"enabled": True, "symbols_file": "config/candidates.txt"},
    "testnet": [
        {"name": "testnet-join", "symbols": ["BTCUSDT"], "policy": "join"},
        {"name": "testnet-agent", "symbols": ["ETHUSDT"], "policy": "agent"},
    ],
    "dashboard_every_s": 60,
    "dashboard_port": 8765,
}


def load_config(path: Path) -> dict:
    if path.exists():
        cfg = json.loads(path.read_text())
        return {**DEFAULT_CONFIG, **cfg}
    return dict(DEFAULT_CONFIG)


def lan_addresses() -> list[str]:
    """This machine's addresses on the local network (best effort, no packets sent)."""
    import socket
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


_LIVE_JSON = re.compile(r"^/data/(live/heartbeat\.json|paper/snapshot\.json|testnet/[A-Z0-9]{2,20}/status\.json)$")


def live_data_path(base: Path, url_path: str) -> Optional[Path]:
    """The few live JSON files the dashboard's Live > Market feed polls, mapped into ``base/data``.
    Anything else under /data (parquet, fills, .env, ...) is refused, so the LAN never sees it."""
    path = url_path.split("?", 1)[0].split("#", 1)[0]
    m = _LIVE_JSON.match(path)
    return base / "data" / m.group(1) if m else None


def serve_dashboard(folder: Path, port: int):
    """Serve ``folder`` (read-only static files) on all interfaces in a background thread,
    plus the whitelisted live JSON files from ``folder.parent / data`` (see live_data_path)."""
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    base = folder.parent

    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.startswith("/data/"):
                f = live_data_path(base, self.path)
                if f is None or not f.is_file():
                    self.send_error(404)
                    return
                try:
                    body = f.read_bytes()
                except OSError:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

        def end_headers(self):
            if self.path.startswith(("/live/", "/data/")):
                self.send_header("Cache-Control", "no-store")
            super().end_headers()

    httpd = ThreadingHTTPServer(("0.0.0.0", port), partial(Quiet, directory=str(folder)))
    threading.Thread(target=httpd.serve_forever, daemon=True, name="dashboard-http").start()
    return httpd


def keys_present(env_path: Path) -> bool:
    from mm.testnet import load_env
    load_env(env_path)
    return bool(os.environ.get("BINANCE_TESTNET_API_KEY") and os.environ.get("BINANCE_TESTNET_API_SECRET"))


@dataclass
class Child:
    name: str
    args: list
    needs_keys: bool = False
    proc: Optional[subprocess.Popen] = None
    started: Optional[float] = None
    restarts: int = 0
    backoff: float = 10.0
    next_start: float = 0.0
    last_exit: Optional[int] = None
    last_exit_utc: Optional[str] = None
    waiting: str = ""
    log: Optional[object] = field(default=None, repr=False)

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None


class Supervisor:
    def __init__(self, cfg: dict, base: Path = Path("."), python: str = sys.executable):
        self.cfg, self.base, self.python = cfg, base, python
        self.children: list[Child] = []
        rec = cfg.get("recorder") or {}
        if rec.get("enabled", True):
            rec_args = ["-m", "mm.recorder", "--symbols-file", rec.get("symbols_file", "config/candidates.txt")]
            if rec.get("depth"):
                rec_args.append("--depth")              # 10-level partial depth, 1 s snapshots -> <SYMBOL>/depth
            self.children.append(Child("recorder", rec_args))
        for t in cfg.get("testnet") or []:
            args = ["-m", "mm.testnet", "--symbols", ",".join(t["symbols"]), "--policy", t.get("policy", "agent")]
            for k, flag in (("lot_usd", "--lot-usd"), ("q_max", "--q-max"), ("max_loss", "--max-loss"), ("warmup", "--warmup")):
                if k in t:
                    args += [flag, str(t[k])]
            self.children.append(Child(t.get("name", "testnet"), args, needs_keys=True))
        pp = cfg.get("paper")
        if pp and pp.get("enabled", True):               # the paper trader: real mainnet book, simulated fills, no keys
            self.children.append(Child(pp.get("name", "paper"),
                                       ["-m", "mm.paper", "--symbols", ",".join(pp["symbols"])]))
        self.started = time.time()
        self.status_path = base / "data/live_status/supervisor.json"
        self.last_dash = 0.0
        self.last_keycheck = -1e9
        self.has_keys = False
        self.httpd = None
        self.urls: list[str] = []

    # ------------------------------------------------------------------ processes
    def _open_log(self, c: Child):
        p = self.base / "results" / f"live_{c.name}.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and p.stat().st_size > 20_000_000:
            p.replace(p.with_suffix(".log.1"))
        return open(p, "a", buffering=1)

    def start(self, c: Child) -> None:
        c.log = self._open_log(c)
        c.log.write(f"\n=== {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC start: {' '.join(c.args)} ===\n")
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if WIN else 0
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        c.proc = subprocess.Popen([self.python, *c.args], cwd=self.base, stdout=c.log, stderr=subprocess.STDOUT,
                                  env=env, creationflags=flags)
        c.started, c.waiting = time.time(), ""
        print(f"[{time.strftime('%H:%M:%S')}] started {c.name} (pid {c.proc.pid})", flush=True)

    def check(self, now: float) -> None:
        if now - self.last_keycheck >= 60:
            self.has_keys = keys_present(self.base / ".env")
            self.last_keycheck = now
        for c in self.children:
            if c.running():
                if now - (c.started or now) > 600:
                    c.backoff = 10.0
                continue
            if c.proc is not None:                       # it exited
                c.last_exit = c.proc.returncode
                c.last_exit_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                c.proc = None
                if c.log:
                    c.log.close()
                c.restarts += 1
                c.next_start = now + c.backoff
                print(f"[{time.strftime('%H:%M:%S')}] {c.name} exited with code {c.last_exit}; "
                      f"restart in {c.backoff:.0f}s (see results/live_{c.name}.log)", flush=True)
                c.backoff = min(c.backoff * 2, 300.0)
            if c.needs_keys and not self.has_keys:
                c.waiting = "waiting for testnet keys in .env"
                continue
            if now >= c.next_start:
                self.start(c)

    def stop(self) -> None:
        for c in self.children:
            if c.running() and c.needs_keys:              # let traders cancel their orders
                try:
                    c.proc.send_signal(signal.CTRL_BREAK_EVENT if WIN else signal.SIGINT)
                except (OSError, ValueError):
                    pass
        deadline = time.time() + 25
        for c in self.children:
            if c.running() and c.needs_keys:
                try:
                    c.proc.wait(timeout=max(0.1, deadline - time.time()))
                except subprocess.TimeoutExpired:
                    pass
        for c in self.children:
            if c.running():
                c.proc.terminate()
                try:
                    c.proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    c.proc.kill()
            if c.log:
                c.log.close()
        self.write_status(stopped=True)

    # ------------------------------------------------------------------ status and dashboard
    def write_status(self, stopped: bool = False) -> dict:
        now = time.time()
        st = {
            "updated_ms": int(now * 1000),
            "since_ms": int(self.started * 1000),
            "stopped": stopped,
            "host": platform.node(),
            "keys": self.has_keys,
            "dashboard_urls": self.urls,
            "processes": [{"name": c.name, "running": c.running(), "pid": c.proc.pid if c.running() else None,
                           "uptime_s": round(now - c.started) if c.running() and c.started else None,
                           "restarts": c.restarts, "last_exit": c.last_exit, "last_exit_utc": c.last_exit_utc,
                           "waiting": c.waiting, "cmd": " ".join(c.args)} for c in self.children],
        }
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.status_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, indent=1))
        tmp.replace(self.status_path)
        return st

    def refresh_dashboard(self) -> None:
        try:
            from scripts.build_live import build
            build(self.base)
        except Exception as e:                            # noqa: BLE001 - never let the dashboard stop trading
            print(f"dashboard refresh failed: {e!r}", flush=True)
        self._refresh_sessions()

    def _refresh_sessions(self) -> None:
        """Session bundles (live spec L4): heavy, so at most every 5 minutes and off the supervisor's thread."""
        t = getattr(self, "_sessions_thread", None)
        if t is not None and t.is_alive():
            return
        def work():
            try:
                from scripts.build_session import build_if_due
                build_if_due(self.base)
            except Exception as e:                        # noqa: BLE001 - never let the dashboard stop trading
                print(f"session bundles failed: {e!r}", flush=True)
        self._sessions_thread = threading.Thread(target=work, daemon=True, name="session-bundles")
        self._sessions_thread.start()

    def loop(self, hours: Optional[float] = None) -> None:
        end = None if hours is None else time.time() + hours * 3600
        every = float(self.cfg.get("dashboard_every_s", 60))
        port = int(self.cfg.get("dashboard_port", 0) or 0)
        if port:
            try:
                self.httpd = serve_dashboard(self.base / "dashboard", port)
                self.urls = [f"http://{ip}:{port}" for ip in lan_addresses()] or [f"http://localhost:{port}"]
                print(f"dashboard on your network: {'  '.join(self.urls)}  (same Wi-Fi; PC status tab)", flush=True)
            except OSError as e:
                print(f"dashboard server not started on port {port}: {e}", flush=True)
        print(f"supervisor running {', '.join(c.name for c in self.children)}. Ctrl+C to stop everything.", flush=True)
        try:
            while end is None or time.time() < end:
                now = time.time()
                self.check(now)
                if now - self.last_dash >= every:
                    self.write_status()
                    self.refresh_dashboard()
                    self.last_dash = now
                time.sleep(5)
        except KeyboardInterrupt:
            print("stopping: cancelling testnet orders, then closing everything...", flush=True)
        finally:
            self.stop()
            self.refresh_dashboard()
            if self.httpd:
                self.httpd.shutdown()
            print("all stopped", flush=True)


def _main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m scripts.supervise_live")
    ap.add_argument("--config", default="config/live.json")
    ap.add_argument("--hours", type=float, default=None)
    args = ap.parse_args(argv)
    if WIN and hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, signal.default_int_handler)
    Supervisor(load_config(Path(args.config))).loop(args.hours)


if __name__ == "__main__":
    _main()
