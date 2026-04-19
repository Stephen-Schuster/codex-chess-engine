#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
import threading


def forward_output(pipe, target) -> None:
    for line in iter(pipe.readline, ""):
        target.write(line)
        target.flush()


def main() -> int:
    stockfish_bin = os.environ.get("STOCKFISH_BIN", "stockfish")

    proc = subprocess.Popen(
        [stockfish_bin],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    assert proc.stdin is not None
    assert proc.stdout is not None
    assert proc.stderr is not None

    out_thread = threading.Thread(target=forward_output, args=(proc.stdout, sys.stdout), daemon=True)
    err_thread = threading.Thread(target=forward_output, args=(proc.stderr, sys.stderr), daemon=True)
    out_thread.start()
    err_thread.start()

    threads = int(os.environ.get("STOCKFISH_THREADS", "2"))
    threads = max(1, min(4, threads))
    hash_mb = int(os.environ.get("STOCKFISH_HASH_MB", "128"))
    hash_mb = max(16, min(2048, hash_mb))
    move_overhead = int(os.environ.get("STOCKFISH_MOVE_OVERHEAD", "30"))
    move_overhead = max(0, min(5000, move_overhead))

    options_sent = False

    for raw in sys.stdin:
        proc.stdin.write(raw)
        if raw.strip() == "uci" and not options_sent:
            proc.stdin.write(f"setoption name Threads value {threads}\n")
            proc.stdin.write(f"setoption name Hash value {hash_mb}\n")
            proc.stdin.write("setoption name Skill Level value 20\n")
            proc.stdin.write("setoption name UCI_LimitStrength value false\n")
            proc.stdin.write(f"setoption name Move Overhead value {move_overhead}\n")
            options_sent = True
        proc.stdin.flush()
        if raw.strip() == "quit":
            break

    try:
        return proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
