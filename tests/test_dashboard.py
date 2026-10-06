"""Schedule parsing + the dashboard server's safety checks (no model, no sudo needed)."""

import json
import os
import threading
import urllib.error
import urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer

import pytest

from chaos import config, dashboard, schedule

SCHED_WITH_WAKE = """Repeating power events:
  wakepoweron at 1:00AM every day
Scheduled power events:
 [0]  wake at 10/06/2026 19:57:16 by 'com.apple.alarm.user-invisible-com.apple.osanalytics'
"""
SCHED_WITH_OTHERS = """Repeating power events:
  wakepoweron at 7:00AM weekdays only
  shutdown at 11:00PM every day
"""
SCHED_EMPTY = """Scheduled power events:
 [0]  wake at 10/06/2026 19:57:16 by 'com.apple.alarm.user-invisible-com.apple.osanalytics'
"""


def test_wake_status_on_and_matching():
    s = schedule.wake_status(hour=1, sched_output=SCHED_WITH_WAKE)
    assert s["on"] and s["matches"] and s["other_repeating"] == []
    assert s["description"] == "wakepoweron at 1:00AM every day"


def test_wake_status_off_ignores_one_time_events():
    s = schedule.wake_status(hour=1, sched_output=SCHED_EMPTY)
    assert not s["on"] and not s["matches"]


def test_wake_status_wrong_time_and_other_events():
    s = schedule.wake_status(hour=1, sched_output=SCHED_WITH_OTHERS)
    assert s["on"] and not s["matches"]
    assert s["other_repeating"] == ["shutdown at 11:00PM every day"]


def test_clock_parsing():
    assert schedule._clock("1:00AM") == (1, 0)
    assert schedule._clock("12:30AM") == (0, 30)
    assert schedule._clock("12:00PM") == (12, 0)
    assert schedule._clock("11:00PM") == (23, 0)
    assert schedule._clock("01:00:00") == (1, 0)


def test_wake_command_matches_start_time():
    assert schedule.wake_command(True, 1) == "/usr/bin/pmset repeat wakeorpoweron MTWRFSU 01:00:00"
    assert schedule.wake_command(False) == "/usr/bin/pmset repeat cancel"


def test_next_run():
    assert schedule.next_run(1, datetime(2026, 10, 6, 17, 30)) == datetime(2026, 10, 7, 1, 0)
    assert schedule.next_run(1, datetime(2026, 10, 7, 0, 30)) == datetime(2026, 10, 7, 1, 0)
    assert schedule.next_run(1, datetime(2026, 10, 7, 1, 0)) == datetime(2026, 10, 8, 1, 0)


def test_plist_runs_night_under_caffeinate():
    d = schedule.plist_dict(schedule.LABEL, schedule.night_program(), 1)
    assert d["ProgramArguments"][:3] == ["/usr/bin/caffeinate", "-i", "-s"]
    assert d["ProgramArguments"][-2:] == ["night", "--scheduled"]
    assert d["StartCalendarInterval"] == {"Hour": 1, "Minute": 0}


# --- the dashboard server ---


@pytest.fixture
def server(tmp_path, monkeypatch):
    nights, gallery = tmp_path / "nights", tmp_path / "gallery"
    (nights / "2026-10-07-moss-radio").mkdir(parents=True)
    (nights / "2026-10-07-moss-radio" / "night.json").write_text(
        json.dumps({"date": "2026-10-07", "name": "<script>alert(1)</script>", "status": "done", "started": 1})
    )
    gallery.mkdir()
    (gallery / "index.html").write_text("gallery!")
    (tmp_path / "secret.txt").write_text("hunter2")
    os.symlink(tmp_path / "secret.txt", nights / "2026-10-07-moss-radio" / "sneaky.txt")
    monkeypatch.setattr(config, "NIGHTS", nights)
    monkeypatch.setattr(config, "GALLERY", gallery)
    monkeypatch.setattr(config, "LOCK_FILE", nights / ".running")

    srv = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def fetch(url, method="GET", headers=None, body=None):
    req = urllib.request.Request(url, method=method, headers=headers or {}, data=body)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_page_and_status(server):
    code, body = fetch(server + "/")
    assert code == 200 and b"control room" in body
    code, body = fetch(server + "/api/status")
    data = json.loads(body)
    assert code == 200
    assert {"schedule", "wake", "running", "latest", "nights", "server", "lessons"} <= data.keys()
    assert data["running"] is None
    assert data["nights"][0]["name"] == "<script>alert(1)</script>"  # raw in JSON; the page escapes it


def test_serves_gallery_and_nights_only(server):
    assert fetch(server + "/gallery/index.html") == (200, b"gallery!")
    assert fetch(server + "/nights/2026-10-07-moss-radio/night.json")[0] == 200
    for path in ["/.env", "/pyproject.toml", "/nights/../secret.txt", "/nights/%2e%2e/secret.txt",
                 "/gallery/../../.env", "/nights/2026-10-07-moss-radio/sneaky.txt"]:
        code, body = fetch(server + path)
        assert code == 404, path
        assert b"hunter2" not in body


def test_rejects_other_websites(server):
    port = server.rsplit(":", 1)[1]
    # DNS rebinding: a request that arrives for some other hostname.
    assert fetch(server + "/api/status", headers={"Host": f"evil.example:{port}"})[0] == 403
    # A POST without our header (what a cross-site form would send).
    assert fetch(server + "/api/stop", method="POST", body=b"{}")[0] == 403
    # A POST from another page's origin, even with the header.
    headers = {"X-Chaos": "1", "Origin": "https://evil.example", "Content-Type": "application/json"}
    assert fetch(server + "/api/stop", method="POST", headers=headers, body=b"{}")[0] == 403


def test_actions_report_errors_cleanly(server):
    headers = {"X-Chaos": "1", "Content-Type": "application/json"}
    code, body = fetch(server + "/api/stop", method="POST", headers=headers, body=b"{}")
    assert code == 400 and json.loads(body)["error"] == "Nothing is running."


def test_scheduled_runs_only_start_near_the_start_hour():
    w = schedule.in_start_window
    assert w(1, datetime(2026, 10, 7, 1, 0))  # right on time
    assert w(1, datetime(2026, 10, 7, 2, 15))  # a bit late is fine
    assert not w(1, datetime(2026, 10, 7, 8, 45))  # woke up for breakfast: skip
    assert not w(1, datetime(2026, 10, 7, 0, 59))  # just before: that's yesterday's slot
    assert w(23, datetime(2026, 10, 7, 0, 10))  # windows that cross midnight
