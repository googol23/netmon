#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# uv can install a managed Python without changing the system Python.
if ! command -v uv >/dev/null 2>&1; then
  echo 'Installing uv (official Astral installer)...'
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- https://astral.sh/uv/install.sh | sh
  else
    echo 'Error: install curl or wget to bootstrap uv.' >&2
    exit 1
  fi
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
command -v uv >/dev/null 2>&1 || { echo 'Error: uv installation not found on PATH.' >&2; exit 1; }

# Reuse an existing compatible Python, or download Python 3.13.
if command -v python3.13 >/dev/null 2>&1; then
  interpreter="$(command -v python3.13)"
else
  echo 'Ensuring Python 3.13 is installed...'
  uv python install 3.13
  interpreter=3.13
fi

# Always rebuild the venv so an old Python 3.8/3.9 venv is not reused.
uv venv --clear --python "$interpreter" .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python -c 'import sys; assert sys.version_info >= (3, 13), sys.version'
printf 'Ready (%s): .venv/bin/python -m netmon start\n' "$(.venv/bin/python --version)"
