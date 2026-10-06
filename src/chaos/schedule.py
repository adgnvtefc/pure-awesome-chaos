"""Turning the nightly run and the nightly wake-up on and off.

These are two separate macOS mechanisms, which is why there are two switches:

1. launchd (the "run" switch) — macOS's built-in job scheduler. We hand it a small
   file (a "LaunchAgent" plist) saying "run `chaos night` at 1:00 every day".
   It runs as you, so no password is needed.

2. pmset (the "wake" switch) — macOS's power settings. A launchd job can't run
   while the Mac is asleep (it waits until the Mac wakes up), so we also ask the
   power manager to wake the machine at the same time. That's a system-wide
   setting, so macOS asks for an admin password.
"""

import os
import plistlib
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from chaos import config

LABEL = "com.pure-awesome-chaos.nightly"
START_HOUR = int(os.environ.get("CHAOS_START_HOUR", "1"))
# If the Mac was asleep at the start time, launchd runs the job as soon as it wakes,
# which could be 9am when you sit down. Scheduled runs only start inside this window.
START_WINDOW_MIN = 90
WAKE_DAYS = "MTWRFSU"  # pmset's day letters: Mon Tue Wed thuRsday Fri Sat sUnday
LAUNCHD_LOG = config.ROOT / "logs" / "launchd.log"


class ScheduleError(Exception):
    pass


# --- 1. launchd: run `chaos night` every night ---


def plist_path(label: str = LABEL) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"


def _service(label: str) -> str:
    return f"gui/{os.getuid()}/{label}"  # "gui/501" = jobs that run in your logged-in session


def night_program() -> list[str]:
    # caffeinate runs the command and keeps the Mac awake until it exits:
    #   -i  don't idle-sleep    -s  don't system-sleep (while plugged in)
    return ["/usr/bin/caffeinate", "-i", "-s", str(config.ROOT / ".venv" / "bin" / "chaos"), "night", "--scheduled"]


def plist_dict(label: str, program: list[str], hour: int) -> dict:
    return {
        "Label": label,
        "ProgramArguments": program,
        "WorkingDirectory": str(config.ROOT),
        "StartCalendarInterval": {"Hour": hour, "Minute": 0},  # every day at hour:00
        "StandardOutPath": str(LAUNCHD_LOG),
        "StandardErrorPath": str(LAUNCHD_LOG),
    }


def install(label: str = LABEL, program: list[str] | None = None, hour: int = START_HOUR) -> None:
    LAUNCHD_LOG.parent.mkdir(parents=True, exist_ok=True)
    path = plist_path(label)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps(plist_dict(label, program or night_program(), hour)))
    # Unload any older copy first, then load the new one.
    subprocess.run(["launchctl", "bootout", _service(label)], capture_output=True)
    r = subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(path)], capture_output=True, text=True)
    if r.returncode != 0:
        raise ScheduleError(f"launchctl bootstrap failed: {r.stderr.strip() or r.returncode}")


def uninstall(label: str = LABEL) -> None:
    # Note: if a night is running, this stops it too (it gets SIGTERM and shuts down cleanly).
    subprocess.run(["launchctl", "bootout", _service(label)], capture_output=True)
    plist_path(label).unlink(missing_ok=True)


def is_installed(label: str = LABEL) -> bool:
    return subprocess.run(["launchctl", "print", _service(label)], capture_output=True).returncode == 0


def next_run(hour: int = START_HOUR, now: datetime | None = None) -> datetime:
    now = now or datetime.now()
    run = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    return run if run > now else run + timedelta(days=1)


def in_start_window(hour: int = START_HOUR, now: datetime | None = None, window_min: int = START_WINDOW_MIN) -> bool:
    """Is it within `window_min` minutes after the most recent hour:00?"""
    now = now or datetime.now()
    last = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if last > now:
        last -= timedelta(days=1)
    return now - last < timedelta(minutes=window_min)


# --- 2. pmset: wake the Mac up for it ---


def wake_command(on: bool, hour: int = START_HOUR) -> str:
    # Wake at exactly the start time, not a few minutes early: this Mac's sleep
    # timer is 1 minute, so an early wake could fall back asleep before the job
    # starts. If the wake lands a second late, launchd runs the missed job
    # immediately on waking, and caffeinate then holds the Mac awake.
    if on:
        return f"/usr/bin/pmset repeat wakeorpoweron {WAKE_DAYS} {hour:02d}:00:00"
    return "/usr/bin/pmset repeat cancel"


def parse_repeating(sched_output: str) -> list[dict]:
    """Pull the 'Repeating power events' section out of `pmset -g sched`."""
    events, in_section = [], False
    for line in sched_output.splitlines():
        if line.startswith("Repeating power events"):
            in_section = True
            continue
        if in_section:
            if not line.startswith((" ", "\t")):
                break
            m = re.match(r"\s*(\w+)\s+at\s+(\S+)\s*(.*)", line)
            if m:
                events.append({"type": m.group(1), "time": m.group(2), "days": m.group(3).strip(), "raw": line.strip()})
    return events


def _is_wake(event: dict) -> bool:
    return event["type"].lower() in {"wake", "poweron", "wakepoweron", "wakeorpoweron"}


def _clock(time_text: str) -> tuple[int, int] | None:
    """'1:00AM' -> (1, 0); '13:00:00' -> (13, 0)."""
    m = re.match(r"(\d{1,2}):(\d{2})(?::\d{2})?\s*([AP]M)?", time_text, re.I)
    if not m:
        return None
    hour, minute, ampm = int(m.group(1)), int(m.group(2)), (m.group(3) or "").upper()
    if ampm == "PM" and hour != 12:
        hour += 12
    if ampm == "AM" and hour == 12:
        hour = 0
    return hour, minute


def wake_status(hour: int = START_HOUR, sched_output: str | None = None) -> dict:
    if sched_output is None:
        sched_output = subprocess.run(["pmset", "-g", "sched"], capture_output=True, text=True).stdout
    events = parse_repeating(sched_output)
    wakes = [e for e in events if _is_wake(e)]
    others = [e for e in events if not _is_wake(e)]
    wake = wakes[0] if wakes else None
    return {
        "on": wake is not None,
        "matches": wake is not None and _clock(wake["time"]) == (hour, 0),
        "description": wake["raw"] if wake else None,
        "other_repeating": [e["raw"] for e in others],
    }


def set_wake(on: bool, hour: int = START_HOUR) -> None:
    """Shows macOS's own password dialog. Blocks until you answer it."""
    status = wake_status(hour)
    if status["other_repeating"]:
        # pmset keeps just one repeating schedule; changing ours would clobber these.
        raise ScheduleError(
            "You have other repeating power events (" + "; ".join(status["other_repeating"]) + "). "
            "Changing the wake schedule here would wipe them, so I won't. Set it in Terminal with pmset instead."
        )
    action = f"wake your Mac at {hour}:00 every night" if on else "stop waking your Mac every night"
    script = (
        f'do shell script "{wake_command(on, hour)}" '
        f'with prompt "pure-awesome-chaos wants to {action}." with administrator privileges'
    )
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        if "-128" in r.stderr:  # AppleScript's "User canceled."
            raise ScheduleError("Cancelled. Nothing changed.")
        raise ScheduleError(r.stderr.strip() or "pmset failed")


def sleep_minutes() -> int | None:
    """The Mac's idle-sleep timer (0 = never sleeps)."""
    out = subprocess.run(["pmset", "-g"], capture_output=True, text=True).stdout
    m = re.search(r"^\s*sleep\s+(\d+)", out, re.M)
    return int(m.group(1)) if m else None
