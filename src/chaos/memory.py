"""What carries over between nights: lessons learned and every idea ever built."""

import json
import re
import time

from chaos import config, llm

MAX_LESSONS = 30  # past this, ask the model to merge them down
CONSOLIDATED_LESSONS = 20


def lessons() -> list[str]:
    if not config.LESSONS_FILE.exists():
        return []
    return [ln[2:].strip() for ln in config.LESSONS_FILE.read_text().splitlines() if ln.startswith("- ")]


def lessons_text() -> str:
    found = lessons()
    return "\n".join(f"- {x}" for x in found) if found else "(none yet: tonight is the first night)"


def _write_lessons(items: list[str]) -> None:
    config.MEMORY.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"- {x}" for x in items)
    config.LESSONS_FILE.write_text(
        "# Lessons\n\nDistilled from past nights. Injected into every session's system prompt.\n"
        "Edit freely: add your own, delete bad ones.\n\n" + body + "\n"
    )


def add_lessons(new: list[str], date: str) -> None:
    items = lessons() + [f"({date}) {x.strip()}" for x in new if x.strip()]
    if len(items) > MAX_LESSONS:
        items = consolidate(items)
    _write_lessons(items)


def consolidate(items: list[str]) -> list[str]:
    """Merge duplicates, drop the obvious, keep the most useful. Falls back to newest-N."""
    prompt = (
        f"Here are {len(items)} lessons an autonomous coding agent learned over many nights:\n\n"
        + "\n".join(f"- {x}" for x in items)
        + f"\n\nRewrite them as at most {CONSOLIDATED_LESSONS} lessons: merge duplicates, keep the "
        "most practical and specific ones, drop vague ones. Keep each to one sentence. Drop the "
        "dates. Reply with ONLY the list, one lesson per line, each starting with '- '."
    )
    try:
        message, _ = llm.chat([{"role": "user", "content": prompt}], temperature=0.3)
        merged = [ln[2:].strip() for ln in message["content"].splitlines() if ln.startswith("- ")]
        if 5 <= len(merged) <= CONSOLIDATED_LESSONS:
            return [f"(merged {time.strftime('%Y-%m-%d')}) {re.sub(r'^\(.*?\)\s*', '', x)}" for x in merged]
    except Exception:  # noqa: BLE001 - never lose the night over housekeeping
        pass
    return items[-CONSOLIDATED_LESSONS:]


def past_ideas() -> list[dict]:
    if not config.IDEAS_FILE.exists():
        return []
    return [json.loads(ln) for ln in config.IDEAS_FILE.read_text().splitlines() if ln.strip()]


def record_idea(entry: dict) -> None:
    config.MEMORY.mkdir(parents=True, exist_ok=True)
    with config.IDEAS_FILE.open("a") as f:
        f.write(json.dumps(entry) + "\n")
