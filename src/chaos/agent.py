"""One agent session: a fresh conversation that works until it calls end_session.

Sessions are deliberately short. Local models get noticeably worse deep into a
long context, so instead of one giant conversation the night is many sessions
that hand off through files (PLAN.md, PROGRESS.md) — like shift workers.
"""

import json
import time
from dataclasses import dataclass

from chaos import config, llm
from chaos.log import NightLog, preview
from chaos.tools import SCHEMAS, Workspace


@dataclass
class SessionResult:
    ended_by: str  # end_session | max_steps | context_full | no_tools | deadline
    summary: str
    steps: int
    prompt_tokens: int  # largest context seen
    completion_tokens: int  # total generated


WRAP_UP = (
    "(harness) Your context is getting long. Finish what you're doing now: make sure the "
    "tests pass, update PLAN.md and PROGRESS.md, then call end_session. The next session "
    "starts fresh and will only know what's in the files."
)
OUT_OF_TIME = (
    "(harness) The night's build time is almost over. Stop starting new work: get the tests "
    "passing, tick finished steps in PLAN.md, add your PROGRESS.md entry, then call end_session."
)
NUDGE = "(harness) Please continue by calling a tool. If this session's work is done, call end_session."
CUT_OFF = (
    "(harness) Your last reply hit the length limit and was cut off. Write smaller pieces: "
    "split big files into several modules, or use edit_file for changes."
)


def run_session(ws: Workspace, system: str, task: str, log: NightLog, label: str, deadline: float) -> SessionResult:
    messages = [{"role": "system", "content": system}, {"role": "user", "content": task}]
    nudges, warned = 0, False
    max_ctx = total_out = 0
    log.event("session_start", label=label, system=system, task=task)

    def done(ended_by: str, summary: str, steps: int) -> SessionResult:
        log.event("session_end", label=label, ended_by=ended_by, summary=summary, steps=steps)
        log.say(f"[{label}] ended ({ended_by}): {preview(summary, 200)}")
        return SessionResult(ended_by, summary, steps, max_ctx, total_out)

    for step in range(1, config.SESSION_MAX_STEPS + 1):
        if time.time() > deadline:
            return done("deadline", "Ran out of time.", step - 1)

        message, usage = llm.chat(messages, tools=SCHEMAS)
        messages.append(message)
        max_ctx = max(max_ctx, usage["prompt_tokens"])
        total_out += usage["completion_tokens"]
        log.event("assistant", label=label, step=step, message=message, usage=usage)
        if message["content"]:
            log.say(f"[{label}] says: {preview(message['content'])}")

        calls = message.get("tool_calls") or []
        if not calls:
            nudges += 1
            if nudges > config.NUDGE_LIMIT:
                return done("no_tools", message["content"] or "(stopped calling tools)", step)
            messages.append({"role": "user", "content": CUT_OFF if usage["finish_reason"] == "length" else NUDGE})
            continue
        nudges = 0

        ending = None
        for call in calls:
            name, args = call["function"]["name"], call["function"]["arguments"]
            if name == "end_session":
                ending = _summary_from(args)
                result = "Session ended."
            else:
                log.say(f"[{label}] {name}: {_describe_call(name, args)}")
                result = ws.execute(name, args)
                failed_run = name == "run" and not result.startswith("[exit code 0]")
                if result.startswith("ERROR") or failed_run:
                    log.say(f"[{label}]   -> {preview(result, 200)}")
            log.event("tool", label=label, step=step, name=name, arguments=args, result=result)
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})

        if ending is not None:
            return done("end_session", ending, step)
        if usage["finish_reason"] == "length":
            messages.append({"role": "user", "content": CUT_OFF})
        if usage["prompt_tokens"] > config.CTX_HARD:
            return done("context_full", "Context limit reached.", step)
        near_deadline = deadline - time.time() < config.DEADLINE_WARN_MIN * 60
        if not warned and (near_deadline or usage["prompt_tokens"] > config.CTX_SOFT):
            warned = True
            messages.append({"role": "user", "content": OUT_OF_TIME if near_deadline else WRAP_UP})

    return done("max_steps", "Step limit reached.", config.SESSION_MAX_STEPS)


def _summary_from(arguments_json: str) -> str:
    try:
        return str(json.loads(arguments_json or "{}").get("summary", "")) or "(no summary)"
    except (json.JSONDecodeError, AttributeError):
        return "(no summary)"


def _describe_call(name: str, arguments_json: str) -> str:
    try:
        args = json.loads(arguments_json or "{}")
    except json.JSONDecodeError:
        return "(unparseable arguments)"
    if name == "run":
        return preview(args.get("command", ""), 160)
    if name == "write_file":
        return f"{args.get('path')} ({str(args.get('content', '')).count(chr(10)) + 1} lines)"
    return preview(str(args.get("path", args)), 160)
