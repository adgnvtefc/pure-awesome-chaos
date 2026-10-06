"""Two logs per night: night.log for humans (tail -f it), log.jsonl with everything."""

import json
import time
from pathlib import Path


class NightLog:
    def __init__(self, night_dir: Path):
        self.text = night_dir / "night.log"
        self.jsonl = night_dir / "log.jsonl"

    def say(self, line: str) -> None:
        stamped = f"{time.strftime('%H:%M:%S')}  {line}"
        print(stamped, flush=True)
        with self.text.open("a") as f:
            f.write(stamped + "\n")

    def event(self, kind: str, **data) -> None:
        with self.jsonl.open("a") as f:
            f.write(json.dumps({"t": time.time(), "kind": kind, **data}, default=str) + "\n")


def preview(text: str, n: int = 140) -> str:
    one_line = " ".join((text or "").split())
    return one_line if len(one_line) <= n else one_line[: n - 1] + "…"
