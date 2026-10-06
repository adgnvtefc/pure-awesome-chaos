"""One whole night, start to finish.

    preflight -> dice -> pitch -> design -> build sessions -> final tests -> retro -> gallery

Folder layout for a night:
    nights/2026-10-07-sneeze-radio/
        app/          the agent's sandbox: the app, its tests, SPEC/PLAN/PROGRESS.md, a git history
        night.json    status + stats (the gallery reads this)
        REPORT.md     the agent's morning report
        night.log     human-readable log (tail -f it)
        log.jsonl     every model message and tool call
"""

import json
import os
import re
import shlex
import shutil
import signal
import time
from pathlib import Path

from chaos import config, dice, gallery, llm, memory, prompts, sandbox
from chaos.agent import run_session
from chaos.log import NightLog
from chaos.tools import Workspace


class NightFailed(Exception):
    pass


def run_night(hours: float = config.HOURS) -> Path:
    start = time.time()
    deadline = start + hours * 3600
    build_until = deadline - config.RETRO_RESERVE_MIN * 60
    date = time.strftime("%Y-%m-%d")

    config.NIGHTS.mkdir(parents=True, exist_ok=True)
    _acquire_lock()
    night_dir = _unique_dir(config.NIGHTS / f"{date}-pitching")
    night_dir.mkdir(parents=True)
    log = NightLog(night_dir)
    state = {"date": date, "status": "running", "model": config.MODEL, "started": start, "hours": hours}
    _save(night_dir, state)  # the dashboard can see the night from its first second
    # SIGTERM (the dashboard's stop button, or switching the schedule off mid-run)
    # becomes a clean interrupt: the finally block below still records the night.
    signal.signal(signal.SIGTERM, _interrupt)

    try:
        log.say(f"=== pure-awesome-chaos night {date} | model {config.MODEL} | {hours:g}h ===")
        preflight(night_dir / "app", log)

        state["dice"] = dice.roll(seed=int(start))
        log.say("dice: " + " | ".join(f"{k}: {v}" for k, v in state["dice"].items() if k != "seed"))
        pick, ideas = pitch(state["dice"], log)
        state.update(name=pick["name"], slug=pick["slug"], pitch=pick["pitch"], why=pick.get("why", ""), ideas=ideas)
        log.say(f"tonight: {pick['name']} — {pick['pitch']}")

        # Now we know what it is, give the folder its real name.
        named = _unique_dir(config.NIGHTS / f"{date}-{pick['slug']}")
        night_dir.rename(named)
        night_dir, log = named, NightLog(named)
        app = night_dir / "app"
        ws = Workspace(app)
        memory.record_idea({"date": date, "name": pick["name"], "pitch": pick["pitch"], **state["dice"]})
        _setup_app(app)
        _save(night_dir, state)

        system = prompts.SYSTEM.format(toolbox=prompts.TOOLBOX, lessons=memory.lessons_text())
        state["sessions"] = []

        design(ws, system, state, log, build_until, hours)
        _save(night_dir, state)
        build(ws, system, state, night_dir, log, build_until)

        state["tests"] = run_tests(app)
        log.say(f"final tests: {state['tests']['summary']}")
        retro(ws, night_dir, state, log, start)
        state["status"] = "done"
    except KeyboardInterrupt:
        state["status"] = "interrupted"
        log.say("interrupted by human")
    except Exception as e:  # noqa: BLE001 - always leave a record of what happened
        state["status"] = "failed"
        state["error"] = f"{type(e).__name__}: {e}"
        log.say(f"NIGHT FAILED: {state['error']}")
        log.event("error", error=state["error"])
    finally:
        state["ended"] = time.time()
        if (night_dir / "app").exists():
            if "tests" not in state and state.get("sessions"):
                state["tests"] = run_tests(night_dir / "app")
            state["plan_done"], state["plan_total"] = plan_status(Workspace(night_dir / "app"))
        _save(night_dir, state)
        gallery.build()
        config.LOCK_FILE.unlink(missing_ok=True)
        log.say(f"=== night over: {state['status']} after {(state['ended'] - start) / 60:.0f} min ===")
    return night_dir


# --- phases ---


def preflight(app: Path, log: NightLog) -> None:
    if not (config.TOOLBOX_BIN / "python").exists():
        raise NightFailed("Toolbox missing. Run scripts/setup_toolbox.sh")
    try:
        models = llm.server_models()
    except Exception as e:  # noqa: BLE001
        raise NightFailed(f"Model server unreachable at {config.BASE_URL}: {e}") from e
    if config.MODEL not in models:
        raise NightFailed(f"Model {config.MODEL} not served. Available: {models}")
    app.mkdir(parents=True, exist_ok=True)
    results = sandbox.selftest(app)
    failed = [desc for desc, ok in results if not ok]
    shutil.rmtree(app)
    if failed:
        raise NightFailed(f"Sandbox self-test failed, refusing to run unattended: {failed}")
    log.say(f"preflight ok: server up, sandbox holds ({len(results)} checks)")


def pitch(rolled: dict, log: NightLog) -> tuple[dict, list]:
    past = memory.past_ideas()[-40:]
    past_text = "\n".join(f"- {p['name']}: {p['pitch']}" for p in past) or "(none yet)"
    prompt = prompts.PITCH.format(**rolled, past=past_text, toolbox=prompts.TOOLBOX)
    for attempt in range(3):
        message, _ = llm.chat([{"role": "user", "content": prompt}], temperature=1.0)
        log.event("pitch", attempt=attempt, content=message["content"])
        data = _parse_json(message["content"])
        pick = (data or {}).get("pick") or {}
        if pick.get("name") and pick.get("pitch"):
            pick["slug"] = _slugify(pick.get("slug") or pick["name"])
            return pick, data.get("ideas", [])
        log.say(f"pitch attempt {attempt + 1} unparseable, retrying")
    raise NightFailed("Model never produced a parseable pitch.")


def design(ws: Workspace, system: str, state: dict, log: NightLog, build_until: float, hours: float) -> None:
    task = prompts.DESIGN.format(
        name=state["name"], pitch=state["pitch"], hours=max(1, round(hours - 1)), **_dice_fields(state)
    )
    for attempt in range(2):
        result = run_session(ws, system, task, log, f"design{'' if attempt == 0 else '-retry'}", build_until)
        state["sessions"].append(_session_record("design", result, ws))
        done, total = plan_status(ws)
        if _read(ws, "SPEC.md") and total > 0:
            log.say(f"design ok: {total} plan steps")
            return
        task += "\n\n(harness) SPEC.md and a PLAN.md with '- [ ] ' checklist lines are required before ending."
    raise NightFailed("Design phase did not produce SPEC.md and a PLAN.md checklist.")


def build(ws: Workspace, system: str, state: dict, night_dir: Path, log: NightLog, build_until: float) -> None:
    tests = run_tests(ws.root)
    snapshot(ws.root, "design")
    stuck = stretch_round = 0
    n = 0
    while build_until - time.time() > config.MIN_SESSION_MIN * 60:
        n += 1
        done, total = plan_status(ws)
        minutes = int((build_until - time.time()) / 60)
        if total and done >= total and tests["failed"] == 0 and tests["passed"] > 0:
            if stretch_round >= config.STRETCH_ROUNDS:
                log.say("plan complete, tests green, stretch rounds used up: finishing early")
                break
            stretch_round += 1
            label, task = f"stretch{stretch_round}", prompts.STRETCH.format(minutes=minutes, round=stretch_round)
        else:
            label = f"build{n}"
            task = prompts.BUILD.format(n=n, minutes=minutes, done=done, total=total, tests=_tests_for_prompt(tests))

        log.say(f"--- {label}: plan {done}/{total}, tests {tests['summary']}, {minutes} min left ---")
        result = run_session(ws, system, task, log, label, build_until)
        tests = run_tests(ws.root)
        if result.ended_by != "end_session":
            _append(ws, "PROGRESS.md", f"\n(harness note) {label} was cut off ({result.ended_by}) before it could "
                    f"hand off. Tests afterwards: {tests['summary']}. Check PLAN.md ticks against the actual code.\n")
        changed = snapshot(ws.root, f"{label}: {result.summary}")
        state["sessions"].append(_session_record(label, result, ws, tests))
        state["tests"] = tests
        state["plan_done"], state["plan_total"] = plan_status(ws)
        _save(night_dir, state)

        stuck = 0 if changed else stuck + 1
        if stuck >= config.STUCK_LIMIT:
            log.say(f"{stuck} sessions in a row changed nothing: calling it a night")
            break


def retro(ws: Workspace, night_dir: Path, state: dict, log: NightLog, start: float) -> None:
    sessions = state.get("sessions", [])
    stats = "\n".join(
        [
            f"- duration: {(time.time() - start) / 60:.0f} minutes, {len(sessions)} sessions",
            f"- how sessions ended: {_count(s['ended_by'] for s in sessions)}",
            f"- tool errors (bad paths, failed edits, invalid arguments): {ws.errors}",
            f"- tests after each session: {', '.join(s.get('tests') or '-' for s in sessions)}",
        ]
    )
    stumbles = list(dict.fromkeys(ws.stumbles))[-15:]  # unique, most recent
    if stumbles:
        stats += "\n\nThings that went wrong along the way (command -> last line of its error):\n"
        stats += "\n".join(f"- {x}" for x in stumbles)
    prompt = prompts.RETRO.format(
        spec=_clip(_read(ws, "SPEC.md"), 6000),
        plan=_clip(_read(ws, "PLAN.md"), 4000),
        progress=_clip(_read(ws, "PROGRESS.md"), 8000),
        tests=_tests_for_prompt(state["tests"]),
        stats=stats,
    )
    message, _ = llm.chat([{"role": "user", "content": prompt}], temperature=0.6)
    log.event("retro", content=message["content"])
    sections = _sections(message["content"])

    report = sections.get("REPORT") or message["content"]
    (night_dir / "REPORT.md").write_text(f"# {state['name']}\n\n> {state['pitch']}\n\n{report}\n")
    lessons = [ln[2:].strip() for ln in sections.get("LESSONS", "").splitlines() if ln.startswith("- ")][:3]
    memory.add_lessons(lessons, state["date"])
    rating = re.search(r"\d+", sections.get("RATING", ""))
    state["fun_rating"] = min(10, int(rating.group())) if rating else None
    state["lessons"] = lessons
    log.say(f"retro: fun {state['fun_rating']}/10, lessons: {lessons}")


# --- helpers ---


def run_tests(app: Path) -> dict:
    r = sandbox.run("python -m pytest -q --timeout=60", app, timeout=600)
    counts = {k: 0 for k in ("passed", "failed", "error")}
    tail = "\n".join(r.output.splitlines()[-3:])
    for num, kind in re.findall(r"(\d+) (passed|failed|errors?)", tail):
        counts["error" if kind.startswith("error") else kind] += int(num)
    failed = counts["failed"] + counts["error"]
    if r.timed_out:
        summary = "test run timed out (a test probably hangs waiting for input or never exits)"
        failed = max(failed, 1)
    elif counts["passed"] == 0 and failed == 0:
        summary = "no tests found or collection failed"
    else:
        summary = f"{counts['passed']} passed, {failed} failed"
    return {"passed": counts["passed"], "failed": failed, "summary": summary, "output": r.output[-2500:], "exit": r.exit_code}


def plan_status(ws: Workspace) -> tuple[int, int]:
    text = _read(ws, "PLAN.md")
    done = len(re.findall(r"^\s*[-*] \[[xX]\]", text, re.M))
    todo = len(re.findall(r"^\s*[-*] \[ \]", text, re.M))
    return done, done + todo


def snapshot(app: Path, message: str) -> bool:
    """Commit the app folder (inside the sandbox). Returns True if anything changed."""
    status = sandbox.run("git status --porcelain", app, timeout=60)
    if not status.output.strip():
        return False
    sandbox.run(f"git add -A && git commit -q -m {shlex.quote(message[:200])}", app, timeout=60)
    return True


def _setup_app(app: Path) -> None:
    app.mkdir(parents=True, exist_ok=True)
    # Its own pytest.ini stops pytest from wandering into (unreadable) parent folders.
    (app / "pytest.ini").write_text("[pytest]\ntestpaths = tests\naddopts = -p no:cacheprovider\nasyncio_mode = auto\n")
    (app / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n.cache/\n")
    sandbox.run("git init -q", app, timeout=30)


def _append(ws: Workspace, rel: str, text: str) -> None:
    try:
        with ws.path(rel).open("a") as f:
            f.write(text)
    except Exception:  # noqa: BLE001
        pass


def _read(ws: Workspace, rel: str) -> str:
    # Through Workspace.path(): a symlink planted in app/ can't make us read files elsewhere.
    try:
        p = ws.path(rel)
        return p.read_text(errors="replace") if p.is_file() else ""
    except Exception:  # noqa: BLE001
        return ""


def _session_record(label: str, result, ws: Workspace, tests: dict | None = None) -> dict:
    return {
        "label": label,
        "ended_by": result.ended_by,
        "summary": result.summary,
        "steps": result.steps,
        "max_context": result.prompt_tokens,
        "generated_tokens": result.completion_tokens,
        "tests": tests["summary"] if tests else None,
        "plan": "{}/{}".format(*plan_status(ws)),
        "at": time.time(),
    }


def _tests_for_prompt(tests: dict) -> str:
    if tests["failed"] == 0:
        return tests["summary"]
    return f"{tests['summary']}. End of the output:\n```\n{tests['output'][-1500:]}\n```"


def _dice_fields(state: dict) -> dict:
    return {k: state["dice"][k] for k in ("theme", "form", "twist", "mood")}


def _parse_json(text: str) -> dict | None:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def _sections(text: str) -> dict[str, str]:
    parts = re.split(r"^#\s+(REPORT|LESSONS|RATING)\s*$", text, flags=re.M)
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "mystery-app"


def _unique_dir(p: Path) -> Path:
    candidate, i = p, 2
    while candidate.exists():
        candidate = p.with_name(f"{p.name}-{i}")
        i += 1
    return candidate


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n // 3] + "\n...\n" + text[-(2 * n // 3) :]


def _count(items) -> str:
    counts: dict[str, int] = {}
    for x in items:
        counts[x] = counts.get(x, 0) + 1
    return ", ".join(f"{k} x{v}" for k, v in counts.items())


def _save(night_dir: Path, state: dict) -> None:
    (night_dir / "night.json").write_text(json.dumps(state, indent=2, default=str))


def _interrupt(signum, frame):
    raise KeyboardInterrupt


def _acquire_lock() -> None:
    if config.LOCK_FILE.exists():
        pid = int(config.LOCK_FILE.read_text().strip() or 0)
        try:
            os.kill(pid, 0)
            raise SystemExit(f"Another night is already running (pid {pid}).")
        except ProcessLookupError:
            pass  # stale lock from a crashed run
    config.LOCK_FILE.write_text(str(os.getpid()))
