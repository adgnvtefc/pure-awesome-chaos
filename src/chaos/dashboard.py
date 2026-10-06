"""A local control room at http://127.0.0.1:8642

Shows what's happening and has the two switches: run nightly, wake the Mac.

Safety: it listens on 127.0.0.1 only (nothing else on your network can reach it),
and it only answers this page. Without the checks in _allowed(), any website you
visit could quietly POST to localhost and flip your switches.
"""

import json
import os
import signal
import subprocess
import tempfile
import time
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from chaos import config, llm, memory, sandbox, schedule

PORT = 8642
PAGE = Path(__file__).with_name("dashboard.html")
LOG_LINES = 80


# --- what's going on ---


def running_pid() -> int | None:
    """The pid of the night in progress, if any (from the lock file the night holds)."""
    try:
        pid = int(config.LOCK_FILE.read_text().strip())
        os.kill(pid, 0)  # signal 0 = "are you there?"; doesn't touch the process
        return pid
    except (FileNotFoundError, ValueError, ProcessLookupError):
        return None
    except PermissionError:
        return pid


def all_nights() -> list[dict]:
    nights = []
    for f in config.NIGHTS.glob("*/night.json"):
        try:
            s = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        tests = s.get("tests") or {}
        nights.append(
            {
                "dir": f.parent.name,
                "date": s.get("date"),
                "name": s.get("name"),
                "pitch": s.get("pitch"),
                "status": s.get("status"),
                "error": s.get("error"),
                "dice": s.get("dice"),
                "started": s.get("started"),
                "ended": s.get("ended"),
                "hours": s.get("hours"),
                "plan_done": s.get("plan_done", 0),
                "plan_total": s.get("plan_total", 0),
                "tests": tests.get("summary"),
                "tests_passed": tests.get("passed", 0),
                "tests_failed": tests.get("failed", 0),
                "sessions": len(s.get("sessions") or []),
                "fun": s.get("fun_rating"),
            }
        )
    nights.sort(key=lambda n: n.get("started") or 0, reverse=True)
    return nights


def log_tail(night_dir: str, n: int = LOG_LINES) -> list[str]:
    log = config.NIGHTS / night_dir / "night.log"
    if not log.exists():
        return []
    return log.read_text(errors="replace").splitlines()[-n:]


_health = {"checked": 0.0, "value": None}


def server_health(max_age: float = 15) -> dict:
    if time.time() - _health["checked"] > max_age:
        try:
            models = llm.server_models(timeout=5)
            _health["value"] = {"up": True, "models": models, "model": config.MODEL, "has_model": config.MODEL in models}
        except (Exception, SystemExit) as e:  # noqa: BLE001 - SystemExit = no API key
            _health["value"] = {"up": False, "error": str(e)[:200], "model": config.MODEL}
        _health["checked"] = time.time()
    return _health["value"]


def status() -> dict:
    nights = all_nights()
    pid = running_pid()
    latest = nights[0] if nights else None
    return {
        "now": time.time(),
        "start_hour": schedule.START_HOUR,
        "schedule": {
            "on": schedule.is_installed(),
            "next_run": schedule.next_run().timestamp(),
            "plist": str(schedule.plist_path()),
            "command": " ".join(schedule.night_program()),
        },
        "wake": {
            **schedule.wake_status(),
            "command_on": "sudo " + schedule.wake_command(True),
            "command_off": "sudo " + schedule.wake_command(False),
        },
        "sleep_minutes": schedule.sleep_minutes(),
        "running": {"pid": pid} if pid else None,
        "latest": {**latest, "log": log_tail(latest["dir"])} if latest else None,
        "nights": nights,
        "server": server_health(),
        "lessons": memory.lessons(),
    }


# --- actions ---


def stop_night() -> None:
    pid = running_pid()
    if pid is None:
        raise schedule.ScheduleError("Nothing is running.")
    os.kill(pid, signal.SIGTERM)  # the night catches this, records itself, and exits


def selftest() -> list[dict]:
    with tempfile.TemporaryDirectory(dir=config.ROOT) as tmp:
        results = [{"check": desc, "ok": ok} for desc, ok in sandbox.selftest(Path(tmp))]
    _health["checked"] = 0  # re-check the model server too
    health = server_health()
    results.insert(0, {"check": f"model server serves {config.MODEL}", "ok": bool(health.get("has_model"))})
    return results


ACTIONS = {
    "/api/schedule": lambda body: schedule.install() if body.get("on") else schedule.uninstall(),
    "/api/wake": lambda body: schedule.set_wake(bool(body.get("on"))),
    "/api/stop": lambda body: stop_night(),
}


# --- the web server ---


def _served_roots() -> dict[str, Path]:
    return {"/gallery/": config.GALLERY, "/nights/": config.NIGHTS}


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass  # keep the terminal quiet

    def translate_path(self, path: str) -> str:
        """Only /gallery/... and /nights/... map to files; nothing else on disk is reachable."""
        path = unquote(urlparse(path).path)
        for prefix, root in _served_roots().items():
            if path.startswith(prefix):
                return str(root / path[len(prefix):])
        return "/nonexistent"

    def _servable(self) -> bool:
        # resolve() collapses ../ and follows symlinks, so neither a crafted URL nor a
        # symlink planted in an app folder can reach a file outside these folders.
        target = Path(self.translate_path(self.path)).resolve()
        return any(target.is_relative_to(root.resolve()) for root in _served_roots().values())

    def _allowed(self) -> bool:
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        # Host check: stops "DNS rebinding" (a website pointing its own domain at 127.0.0.1).
        if self.headers.get("Host") not in hosts:
            return False
        # Origin check: a browser always says which page sent a POST; it must be this one.
        origin = self.headers.get("Origin")
        return origin is None or origin in {f"http://{h}" for h in hosts}

    def _json(self, code: int, data) -> None:
        body = json.dumps(data, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if not self._allowed():
            return self.send_error(403)
        path = urlparse(self.path).path
        if path == "/":
            body = PAGE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/status":
            return self._json(200, status())
        if self._servable():  # the gallery and the nights' files, read-only
            return super().do_GET()
        self.send_error(404)

    def do_POST(self) -> None:
        # The custom header can't be sent cross-site without the browser asking us
        # first (a CORS preflight), which we never approve.
        if not self._allowed() or self.headers.get("X-Chaos") != "1":
            return self.send_error(403)
        path = urlparse(self.path).path
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            if path == "/api/selftest":
                return self._json(200, {"results": selftest()})
            if path not in ACTIONS:
                return self.send_error(404)
            ACTIONS[path](body)
        except schedule.ScheduleError as e:
            return self._json(400, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            return self._json(500, {"error": f"{type(e).__name__}: {e}"})
        self._json(200, status())

    def do_HEAD(self) -> None:
        self.send_error(405)


def serve(port: int = PORT, open_browser: bool = True) -> None:
    url = f"http://127.0.0.1:{port}/"
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        # Port taken. If it's already our dashboard, just open it; otherwise say so.
        try:
            with urllib.request.urlopen(url + "api/status", timeout=3) as r:
                json.load(r)
        except Exception:  # noqa: BLE001
            raise SystemExit(f"Port {port} is used by something else. Try: chaos dashboard --port 8643")
        print(f"The dashboard is already running: {url}")
        if open_browser:
            subprocess.Popen(["open", url])
        return
    server.daemon_threads = True
    print(f"pure-awesome-chaos dashboard: {url}   (Ctrl+C to stop)")
    if open_browser:
        subprocess.Popen(["open", url])
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
