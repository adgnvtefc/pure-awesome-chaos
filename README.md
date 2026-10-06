# pure-awesome-chaos

Every night, a local model on this Mac Studio invents a weird little app, builds it,
tests it, and writes down what it learned. You wake up to a gallery.
# HUMAN NOTE:

This repository is entirely claude-code'd and made just for fun as an exploration of agentic coding capabilities and local AI. 

## A night

```
preflight   model server up? sandbox walls hold? (refuses to run if not)
dice        random theme + form + twist + mood, so it never builds a todo app
pitch       brainstorm 5 ideas, pick the most fun one it can actually finish
design      SPEC.md + PLAN.md checklist (one session)
build       many short sessions, each with a fresh context, handing off via
            PLAN.md / PROGRESS.md; harness runs the tests + git-commits after each
stretch     plan done & tests green? add delight, up to 2 rounds, then stop early
retro       morning REPORT.md + 1-3 lessons -> memory/lessons.md
gallery     gallery/index.html
```

Short sessions are the key design choice: local models get noticeably worse deep into a
long context, so the night is a relay of fresh agents that only share files.

## Commands

```bash
uv run chaos dashboard       # the control room: http://127.0.0.1:8642
uv run chaos selftest        # model server + sandbox checks
uv run chaos dice            # roll ingredients for fun
uv run chaos night --hours 1 # run a night right now
uv run chaos status          # what's happening / happened
uv run chaos gallery         # rebuild gallery/index.html
open gallery/index.html
```

Watch a night live: `tail -f nights/<latest>/night.log`

## Layout

```
src/chaos/         the harness
  night.py           the pipeline above
  agent.py           one session: tool-calling loop, context limits, nudges
  tools.py           list/read/write/edit files (folder-confined) + run (sandboxed)
  sandbox.sb/.py     macOS seatbelt profile + runner + self-test
  prompts.py         every prompt the model sees: tune these first
  dice.py            the ingredient lists: edit freely
  memory.py          lessons + idea history across nights
  gallery.py         the morning page
  schedule.py        the two switches: launchd job + pmset wake
  dashboard.py/.html the local control room
nights/<date>-<slug>/
  app/               the agent's world (its own git repo)
  REPORT.md  night.json  night.log  log.jsonl
memory/lessons.md    what it has learned (edit it! add your own)
memory/ideas.jsonl   everything it has ever built
toolbox/             the offline package kit (scripts/setup_toolbox.sh)
```

## The sandbox

Every shell command the agent runs (and every test run and git command the harness runs
on its behalf) goes through `sandbox-exec` with `src/chaos/sandbox.sb`:

- writes only inside tonight's `app/` folder (plus temp dirs)
- no internet, no DNS; `127.0.0.1` works so apps can serve and test themselves
- can't read your home folder (except its own folder, the toolbox, and Python)
- can't launch apps, send Apple Events, `sudo`, `ssh`, or signal other processes
- clean environment: none of your shell variables or secrets are passed in

The file tools resolve symlinks before checking paths, so a planted symlink can't trick
the harness into reading or writing outside the folder. `chaos selftest` proves all this,
and every night re-runs it before starting.

## Scheduling

Two switches, in the dashboard or the terminal:

```bash
uv run chaos schedule on|off|status   # launchd job: runs `chaos night` at 1:00 AM (no password)
uv run chaos wake on|off|status       # pmset: wakes the Mac at 1:00 AM (macOS asks for your password)
```

- **schedule** writes `~/Library/LaunchAgents/com.pure-awesome-chaos.nightly.plist` and loads
  it with `launchctl`. The job runs `caffeinate -i -s chaos night`, which keeps the Mac awake
  until the night ends. Switching it off mid-run stops the night cleanly.
- **wake** runs `pmset repeat wakeorpoweron MTWRFSU 01:00:00` as admin. It wakes at exactly the
  start time, because with a short sleep timer an earlier wake can fall back asleep first.
  macOS allows one repeating wake schedule, so the switch refuses to act if you have other
  repeating power events.

`CHAOS_START_HOUR` changes the hour. The oMLX server must be running at night (preflight fails
cleanly if it isn't).

## The dashboard

`uv run chaos dashboard` serves a page on 127.0.0.1 only: live status of the current night,
its log, a stop button, the two switches (each with a "what this does" explanation), past
nights, a sandbox self-test button, and the lessons. It rejects requests from other websites
(Host/Origin checks plus a custom header), and only serves files from `gallery/` and `nights/`.

## Knobs

`.env`: `CHAOS_MODEL`, `CHAOS_HOURS` (default 5.5). Everything else is in `src/chaos/config.py`.
To add packages the agent can use: edit and re-run `scripts/setup_toolbox.sh`, then update
`TOOLBOX` in `prompts.py`.
