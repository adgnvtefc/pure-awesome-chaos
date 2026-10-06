"""The agent's tools: implementations + the JSON schemas the model sees.

File tools run here in the orchestrator but are confined to the app folder.
`run` goes through the sandbox. Every tool returns a string and never raises:
errors go back to the model so it can see what went wrong and try again.
"""

import json
from pathlib import Path

from chaos import config, sandbox

SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".cache", ".venv", "node_modules"}


class ToolError(Exception):
    """A mistake the model made; the message is shown to it."""


class Workspace:
    def __init__(self, app_dir: Path):
        self.root = app_dir.resolve()
        self.errors = 0  # tool calls that failed, for the retro
        self.stumbles: list[str] = []  # what went wrong, in the model's own commands

    def stumble(self, what: str, error: str) -> None:
        last = [ln.strip() for ln in error.splitlines() if ln.strip()]
        self.stumbles.append(f"{' '.join(what.split())[:120]}  ->  {(last[-1] if last else error)[:200]}")

    # -- path safety --

    def path(self, rel: str) -> Path:
        # resolve() follows symlinks, so a link pointing outside the folder is caught too.
        p = (self.root / rel).resolve()
        if p != self.root and not p.is_relative_to(self.root):
            raise ToolError(f"'{rel}' is outside your working folder. Use paths relative to it.")
        return p

    def rel(self, p: Path) -> str:
        return str(p.relative_to(self.root)) or "."

    # -- tools --

    def list_files(self, path: str = ".") -> str:
        base = self.path(path)
        if not base.is_dir():
            raise ToolError(f"'{path}' is not a directory.")
        lines = []
        for p in sorted(base.rglob("*")):
            if any(part in SKIP_DIRS for part in p.relative_to(self.root).parts):
                continue
            if p.is_file():
                lines.append(f"{self.rel(p)}  ({p.stat().st_size} bytes)")
            if len(lines) >= 300:
                lines.append("... (more files not shown)")
                break
        return "\n".join(lines) or "(empty)"

    def read_file(self, path: str, start_line: int = 1, max_lines: int = config.READ_DEFAULT_LINES) -> str:
        p = self.path(path)
        if not p.is_file():
            raise ToolError(f"'{path}' does not exist. Use list_files to see what's there.")
        lines = p.read_text(errors="replace").splitlines()
        start = max(1, int(start_line))
        chunk = lines[start - 1 : start - 1 + int(max_lines)]
        body = "\n".join(f"{i:4d}| {line}" for i, line in enumerate(chunk, start))
        end = start + len(chunk) - 1
        if end < len(lines):
            body += f"\n... ({len(lines) - end} more lines; call read_file with start_line={end + 1})"
        return f"{path} (lines {start}-{end} of {len(lines)}):\n{body}" if lines else f"{path} is empty."

    def write_file(self, path: str, content: str) -> str:
        p = self.path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        existed = p.exists()
        p.write_text(content)
        n = content.count("\n") + (0 if content.endswith("\n") or not content else 1)
        return f"{'Overwrote' if existed else 'Created'} {path} ({n} lines)."

    def edit_file(self, path: str, old_text: str, new_text: str) -> str:
        p = self.path(path)
        if not p.is_file():
            raise ToolError(f"'{path}' does not exist.")
        text = p.read_text()
        count = text.count(old_text)
        if not old_text or count == 0:
            raise ToolError(
                f"old_text was not found in {path}. It must match the file exactly, including "
                "indentation. Read the file again to get the current text."
            )
        if count > 1:
            raise ToolError(f"old_text appears {count} times in {path}. Include more surrounding lines so it is unique.")
        p.write_text(text.replace(old_text, new_text, 1))
        return f"Edited {path}."

    def run(self, command: str, timeout: int = config.RUN_DEFAULT_TIMEOUT) -> str:
        timeout = max(1, min(int(timeout), config.RUN_MAX_TIMEOUT))
        result = sandbox.run(command, self.root, timeout)
        if result.exit_code != 0 or result.timed_out:
            self.stumble(f"run: {command}", "timed out" if result.timed_out else result.output)
        return result.describe()

    # -- dispatch --

    def execute(self, name: str, arguments_json: str) -> str:
        fn = {
            "list_files": self.list_files,
            "read_file": self.read_file,
            "write_file": self.write_file,
            "edit_file": self.edit_file,
            "run": self.run,
        }.get(name)
        try:
            if fn is None:
                raise ToolError(f"Unknown tool '{name}'. Available: {', '.join(t['function']['name'] for t in SCHEMAS)}.")
            try:
                args = json.loads(arguments_json or "{}")
            except json.JSONDecodeError as e:
                raise ToolError(
                    f"Your arguments were not valid JSON ({e}). If you were writing a long file, "
                    "your reply may have been cut off: split it into smaller files or edits."
                )
            if not isinstance(args, dict):
                raise ToolError("Arguments must be a JSON object.")
            return fn(**args)
        except ToolError as e:
            self.errors += 1
            self.stumble(name, str(e))
            return f"ERROR: {e}"
        except TypeError as e:  # wrong/missing argument names
            self.errors += 1
            return f"ERROR: bad arguments for {name}: {e}"
        except Exception as e:  # noqa: BLE001 - the model must always get an answer
            self.errors += 1
            return f"ERROR: {name} failed: {type(e).__name__}: {e}"


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


SCHEMAS = [
    _tool(
        "list_files",
        "List all files under a folder (recursively) with their sizes.",
        {"path": {"type": "string", "description": "Folder relative to your working folder. Default '.'."}},
        [],
    ),
    _tool(
        "read_file",
        "Read a text file. Lines are numbered for reference only; the numbers are not part of the file.",
        {
            "path": {"type": "string"},
            "start_line": {"type": "integer", "description": "First line to read (1-based). Default 1."},
            "max_lines": {"type": "integer", "description": f"How many lines. Default {config.READ_DEFAULT_LINES}."},
        },
        ["path"],
    ),
    _tool(
        "write_file",
        "Create a file or completely replace its contents. Creates parent folders. "
        "For small changes to an existing file, prefer edit_file.",
        {"path": {"type": "string"}, "content": {"type": "string", "description": "The full file contents."}},
        ["path", "content"],
    ),
    _tool(
        "edit_file",
        "Replace one exact snippet of a file with new text. old_text must appear exactly once "
        "(copy it precisely from read_file output, without the line numbers).",
        {
            "path": {"type": "string"},
            "old_text": {"type": "string", "description": "Exact existing text, including indentation."},
            "new_text": {"type": "string", "description": "Replacement text."},
        },
        ["path", "old_text", "new_text"],
    ),
    _tool(
        "run",
        "Run a bash command in your working folder and get its output and exit code. "
        "Use it to run tests (python -m pytest -q), run your app, or inspect things. "
        "No internet, no keyboard input; commands that outlive the timeout are killed.",
        {
            "command": {"type": "string"},
            "timeout": {"type": "integer", "description": f"Seconds. Default {config.RUN_DEFAULT_TIMEOUT}, max {config.RUN_MAX_TIMEOUT}."},
        },
        ["command"],
    ),
    _tool(
        "end_session",
        "Call this when this session's work is finished (after updating PLAN.md and PROGRESS.md).",
        {"summary": {"type": "string", "description": "One line: what you accomplished this session."}},
        ["summary"],
    ),
]
