"""Run shell commands inside the macOS sandbox (see sandbox.sb).

Rule: the orchestrator never executes anything from an app folder outside the
sandbox — not the agent's commands, not the tests, not even git (a repo's
config or hooks can run arbitrary commands).
"""

import os
import re
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

from chaos import config

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


@dataclass
class RunResult:
    exit_code: int
    output: str
    timed_out: bool

    def describe(self) -> str:
        status = "TIMED OUT (killed)" if self.timed_out else f"exit code {self.exit_code}"
        return f"[{status}]\n{self.output}" if self.output else f"[{status}] (no output)"


def _python_install_dir() -> Path:
    # The toolbox venv's python is a symlink into uv's managed install; it must stay readable.
    return Path(os.path.realpath(config.TOOLBOX_BIN / "python")).parents[1]


def sandbox_env(app_dir: Path) -> dict[str, str]:
    """A clean environment: none of your shell's variables (or secrets) leak in."""
    return {
        "PATH": f"{config.TOOLBOX_BIN}:/usr/bin:/bin:/usr/sbin:/sbin",
        "VIRTUAL_ENV": str(config.TOOLBOX_BIN.parent),
        "HOME": str(app_dir),  # anything that writes ~/.something lands in the app folder
        "TMPDIR": "/private/tmp",
        "LANG": "en_US.UTF-8",
        "TERM": "dumb",
        "NO_COLOR": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "MPLBACKEND": "Agg",
        "MPLCONFIGDIR": str(app_dir / ".cache" / "matplotlib"),
        "SDL_VIDEODRIVER": "dummy",
        "SDL_AUDIODRIVER": "dummy",
        "PYGAME_HIDE_SUPPORT_PROMPT": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "chaos",
        "GIT_AUTHOR_EMAIL": "chaos@localhost",
        "GIT_COMMITTER_NAME": "chaos",
        "GIT_COMMITTER_EMAIL": "chaos@localhost",
    }


def run(command: str, app_dir: Path, timeout: int = config.RUN_DEFAULT_TIMEOUT) -> RunResult:
    app_dir = app_dir.resolve()
    args = [
        "/usr/bin/sandbox-exec",
        "-D", f"NIGHT_DIR={app_dir}",
        "-D", f"TOOLBOX={config.TOOLBOX.resolve()}",
        "-D", f"UV_PYTHON={_python_install_dir()}",
        "-D", f"HOME_DIR={Path.home()}",
        "-f", str(config.SANDBOX_PROFILE),
        "/bin/bash", "-c", command,
    ]
    proc = subprocess.Popen(
        args,
        cwd=app_dir,
        env=sandbox_env(app_dir),
        stdin=subprocess.DEVNULL,  # nobody is at the keyboard
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,  # own process group, so a timeout kills servers & children too
    )
    timed_out = False
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(proc.pid, signal.SIGKILL)
        out, _ = proc.communicate()
    except BaseException:  # night interrupted mid-command: don't leave its processes behind
        os.killpg(proc.pid, signal.SIGKILL)
        raise
    text = ANSI.sub("", out.decode("utf-8", errors="replace"))
    return RunResult(proc.returncode, truncate(text.strip()), timed_out)


def truncate(text: str, limit: int = config.TOOL_OUTPUT_CHARS) -> str:
    """Keep the head and (mostly) the tail: errors and test summaries live at the end."""
    if len(text) <= limit:
        return text
    head, tail = limit * 3 // 10, limit * 7 // 10
    return f"{text[:head]}\n\n... [{len(text) - head - tail} characters cut] ...\n\n{text[-tail:]}"


# --- Self-test: proves the walls hold before we leave a model alone all night ---

SELFTEST = [
    # (description, command, should_succeed)
    ("write inside app folder", "echo hi > .selftest && cat .selftest && rm .selftest", True),
    ("toolbox python + packages", "python -c 'import numpy, PIL, pygame, flask, textual, rich, matplotlib'", True),
    ("localhost server", "python -c \"import http.server as h, threading, urllib.request as u; "
     "s = h.HTTPServer(('127.0.0.1', 0), h.SimpleHTTPRequestHandler); "
     "threading.Thread(target=s.serve_forever, daemon=True).start(); "
     "u.urlopen(f'http://127.0.0.1:{s.server_port}/')\"", True),
    ("internet blocked", "python -c \"import socket; socket.create_connection(('1.1.1.1', 443), timeout=5)\"", False),
    ("DNS blocked", "python -c \"import socket; socket.getaddrinfo('example.com', 443)\"", False),
    ("write outside blocked", f"touch '{Path.home()}/.chaos-escape-test'", False),
    ("home folder listing blocked", f"ls '{Path.home()}'", False),
    ("project files unreadable", f"cat '{config.ROOT}/.env'", False),
    ("open apps blocked", "/usr/bin/open -g -a Calculator", False),
]


def selftest(app_dir: Path) -> list[tuple[str, bool]]:
    """Run each check in the sandbox. Returns (description, passed) pairs."""
    results = []
    for desc, cmd, should_succeed in SELFTEST:
        r = run(cmd, app_dir, timeout=30)
        results.append((desc, (r.exit_code == 0) == should_succeed))
    escape = Path.home() / ".chaos-escape-test"
    if escape.exists():  # belt and braces
        escape.unlink()
        results.append(("escape file really absent", False))
    return results
