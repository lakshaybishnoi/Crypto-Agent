#!/usr/bin/env sh
set -eu

PYTHON_BIN="${PYTHON:-python3}"
VENV_DIR="${VENV:-.venv}"

mkdir -p data logs

if [ ! -f .env ] && [ -f .env.example ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
  echo "Created virtual environment at $VENV_DIR"
fi

VENV_PY="$VENV_DIR/bin/python"
"$VENV_PY" -m pip install --upgrade pip setuptools wheel

if [ -f requirements.txt ]; then
  "$VENV_PY" -m pip install -r requirements.txt
fi

if [ -f pyproject.toml ]; then
  if grep -q "^dev =" pyproject.toml; then
    "$VENV_PY" -m pip install -e ".[dev]"
  else
    "$VENV_PY" -m pip install -e .
  fi
fi

echo "Bootstrap complete"
