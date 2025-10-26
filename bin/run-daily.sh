#!/bin/bash
# Paper Watcher - Daily Runner Shell Wrapper
# Convenience script for running daily.py

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PYTHON="$PROJECT_ROOT/venv/bin/python"

# Check if venv exists
if [ ! -f "$VENV_PYTHON" ]; then
    echo "Error: Virtual environment not found!"
    echo "Please run: python3 -m venv venv"
    echo "Then: pip install -r requirements.txt"
    exit 1
fi

# Change to project root
cd "$PROJECT_ROOT"

# Run the Python script
exec "$VENV_PYTHON" "$SCRIPT_DIR/run-daily.py" "$@"
