#!/bin/bash
# Crawler execution script
# Usage: ./run_crawler.sh [OPTIONS]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/venv/bin/python"

if [ ! -f "$VENV_PYTHON" ]; then
    echo "Error: Virtual environment not found!"
    echo "Please run: python3 -m venv venv"
    exit 1
fi

"$VENV_PYTHON" -m src.crawler.main "$@"
