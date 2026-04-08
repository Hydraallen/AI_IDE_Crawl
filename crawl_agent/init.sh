#!/bin/bash
# crawl_agent init.sh - Activate project root .venv and verify dependencies
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_ROOT/.venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "Error: .venv not found at $VENV_DIR"
    echo "Run: cd $PROJECT_ROOT && python3 -m venv .venv && source .venv/bin/activate && pip install -r crawl_agent/requirements.txt"
    exit 1
fi

source "$VENV_DIR/bin/activate"
echo "Virtual environment activated: $VENV_DIR"

python -c "import langchain; import warcio; import bs4; print('All dependencies OK')"
