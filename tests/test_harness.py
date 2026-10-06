"""Tests for the harness's own moving parts (no model needed)."""

import json
import os
from pathlib import Path

import pytest

from chaos import night, sandbox
from chaos.tools import Workspace


@pytest.fixture
def ws(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    return Workspace(app)


def test_write_read_edit_roundtrip(ws):
    assert "Created" in ws.execute("write_file", json.dumps({"path": "src/a.py", "content": "x = 1\ny = 2\n"}))
    assert "2| y = 2" in ws.execute("read_file", json.dumps({"path": "src/a.py"}))
    assert ws.execute("edit_file", json.dumps({"path": "src/a.py", "old_text": "y = 2", "new_text": "y = 3"})) == "Edited src/a.py."
    assert (ws.root / "src/a.py").read_text() == "x = 1\ny = 3\n"


def test_paths_cannot_escape(ws):
    for bad in ["../outside.txt", "/etc/passwd", "a/../../outside.txt"]:
        assert ws.execute("write_file", json.dumps({"path": bad, "content": "x"})).startswith("ERROR")
    assert not (ws.root.parent / "outside.txt").exists()
    assert ws.errors == 3


def test_symlink_escape_is_blocked(ws, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("hunter2")
    os.symlink(secret, ws.root / "innocent.txt")
    assert ws.execute("read_file", json.dumps({"path": "innocent.txt"})).startswith("ERROR")
    assert ws.execute("write_file", json.dumps({"path": "innocent.txt", "content": "pwned"})).startswith("ERROR")
    assert secret.read_text() == "hunter2"
    assert night._read(ws, "innocent.txt") == ""  # the orchestrator's own reads are guarded too


def test_edit_needs_unique_match(ws):
    (ws.root / "f.txt").write_text("a\na\n")
    assert "appears 2 times" in ws.execute("edit_file", json.dumps({"path": "f.txt", "old_text": "a", "new_text": "b"}))
    assert "not found" in ws.execute("edit_file", json.dumps({"path": "f.txt", "old_text": "zzz", "new_text": "b"}))


def test_bad_calls_never_raise(ws):
    assert ws.execute("nope", "{}").startswith("ERROR: Unknown tool")
    assert "not valid JSON" in ws.execute("write_file", '{"path": "a.py", "content": "unterminated')
    assert ws.execute("write_file", json.dumps({"filename": "a.py"})).startswith("ERROR: bad arguments")


def test_plan_status(ws):
    (ws.root / "PLAN.md").write_text("# Plan\n- [x] one\n- [X] two\n- [ ] three\n  - [ ] nested\nnot - [ ] a step\n")
    assert night.plan_status(ws) == (2, 4)


def test_parse_json_tolerates_chatter():
    text = 'Sure! Here you go:\n```json\n{"pick": {"name": "Moss Radio", "pitch": "p"}}\n```\nEnjoy!'
    assert night._parse_json(text)["pick"]["name"] == "Moss Radio"
    assert night._parse_json("no json here") is None


def test_sections():
    s = night._sections("# REPORT\nIt works.\n\n# LESSONS\n- test early\n- small files\n\n# RATING\n8\n")
    assert s["REPORT"] == "It works."
    assert s["LESSONS"].splitlines() == ["- test early", "- small files"]
    assert s["RATING"] == "8"


def test_slugify():
    assert night._slugify("Sneeze Radio 3000!!") == "sneeze-radio-3000"
    assert night._slugify("???") == "mystery-app"


def test_truncate_keeps_the_tail():
    text = "HEAD" + "x" * 50_000 + "THE ERROR IS HERE"
    out = sandbox.truncate(text, 1000)
    assert len(out) < 1200 and out.startswith("HEAD") and out.endswith("THE ERROR IS HERE")


def test_run_tests_parses_pytest(tmp_path):
    app = tmp_path / "app"
    (app / "tests").mkdir(parents=True)
    (app / "pytest.ini").write_text("[pytest]\ntestpaths = tests\naddopts = -p no:cacheprovider\n")
    (app / "tests" / "test_x.py").write_text("def test_a(): pass\ndef test_b(): pass\ndef test_c(): assert False\n")
    result = night.run_tests(app)
    assert (result["passed"], result["failed"]) == (2, 1)


def test_run_timeout_kills_the_whole_group(tmp_path):
    r = sandbox.run("sleep 30 & sleep 30; echo never", tmp_path, timeout=2)
    assert r.timed_out and "never" not in r.output


def test_stumbles_are_recorded_for_the_retro(ws):
    ws.execute("run", json.dumps({"command": "python -c 'import nonexistent_pkg'"}))
    ws.execute("read_file", json.dumps({"path": "missing.py"}))
    ws.execute("run", json.dumps({"command": "echo fine"}))
    assert len(ws.stumbles) == 2
    assert "ModuleNotFoundError" in ws.stumbles[0]
    assert "does not exist" in ws.stumbles[1]
