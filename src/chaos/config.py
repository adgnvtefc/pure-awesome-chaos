"""Paths and knobs. Anything you might want to tune lives here (or in .env)."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

NIGHTS = ROOT / "nights"
MEMORY = ROOT / "memory"
GALLERY = ROOT / "gallery"
LESSONS_FILE = MEMORY / "lessons.md"
IDEAS_FILE = MEMORY / "ideas.jsonl"
LOCK_FILE = NIGHTS / ".running"

TOOLBOX = ROOT / "toolbox"
TOOLBOX_BIN = TOOLBOX / ".venv" / "bin"
SANDBOX_PROFILE = Path(__file__).with_name("sandbox.sb")

# --- Model server (oMLX, OpenAI-compatible) ---
BASE_URL = os.environ.get("OMLX_BASE_URL", "http://127.0.0.1:8000/v1")
API_KEY = os.environ.get("OMLX_API_KEY", "")
MODEL = os.environ.get("CHAOS_MODEL", "Qwen3.8-27B-MLX-8bit")
MAX_TOKENS = int(os.environ.get("CHAOS_MAX_TOKENS", "16384"))  # per reply; thinking + one big file
CALL_TIMEOUT = 900  # seconds for one model reply (33 tok/s * 16k tokens ~ 8 min)

# --- The night ---
HOURS = float(os.environ.get("CHAOS_HOURS", "5.5"))  # 1:00am start -> done by 6:30am
RETRO_RESERVE_MIN = 15  # stop building this many minutes before the deadline
STRETCH_ROUNDS = 2  # extra "make it more delightful" rounds once the plan is done
STUCK_LIMIT = 4  # end the night after this many sessions in a row change nothing
DEADLINE_WARN_MIN = 10  # tell the session to wrap up this long before the build deadline
MIN_SESSION_MIN = 8  # don't start a session with less time than this left

# --- One build session (fresh context each time) ---
SESSION_MAX_STEPS = 60
CTX_SOFT = 48_000  # prompt tokens: ask the model to wrap up
CTX_HARD = 72_000  # prompt tokens: end the session
NUDGE_LIMIT = 2  # replies without a tool call before we give up on the session

# --- Tools ---
RUN_DEFAULT_TIMEOUT = 120
RUN_MAX_TIMEOUT = 600
TOOL_OUTPUT_CHARS = 10_000
READ_DEFAULT_LINES = 400
