#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if command -v stockfish >/dev/null 2>&1; then
  export STOCKFISH_THREADS="1"
  export STOCKFISH_HASH_MB="128"
  export STOCKFISH_BIN="stockfish"
  exec /opt/chess-venv/bin/python3 -u "$ROOT_DIR/engine/stockfish_proxy.py"
fi

if [ -x /usr/games/stockfish ]; then
  export STOCKFISH_THREADS="1"
  export STOCKFISH_HASH_MB="128"
  export STOCKFISH_BIN="/usr/games/stockfish"
  exec /opt/chess-venv/bin/python3 -u "$ROOT_DIR/engine/stockfish_proxy.py"
fi

exec /opt/chess-venv/bin/python3 -u "$ROOT_DIR/main.py"
