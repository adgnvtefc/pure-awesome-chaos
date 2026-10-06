#!/bin/zsh
# Builds the offline toolbox: the only third-party packages the overnight agent can use.
# The agent has no internet, so anything not installed here doesn't exist for it.
# Re-run after editing the list; the next night picks up the change automatically.
set -euo pipefail
cd "$(dirname "$0")/.."
uv venv toolbox/.venv --python 3.12 --allow-existing
uv pip install --python toolbox/.venv/bin/python \
  pytest pytest-asyncio pytest-timeout \
  numpy pillow matplotlib \
  rich textual \
  pygame \
  flask
toolbox/.venv/bin/python -m pip --version >/dev/null 2>&1 || true
toolbox/.venv/bin/python -c "import pytest, numpy, PIL, matplotlib, rich, textual, pygame, flask; print('toolbox ok')"
