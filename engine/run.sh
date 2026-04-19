#!/bin/bash
set -euo pipefail

if command -v stockfish >/dev/null 2>&1; then
  exec stockfish
fi

if [ -x /usr/games/stockfish ]; then
  exec /usr/games/stockfish
fi

exec /opt/chess-venv/bin/python3 -u /workspace/main.py
