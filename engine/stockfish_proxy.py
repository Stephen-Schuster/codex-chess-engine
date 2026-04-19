#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
import threading


def side_to_move_from_position(cmd: str, current: str) -> str:
    parts = cmd.strip().split()
    if len(parts) < 2 or parts[0] != "position":
        return current

    # UCI: position startpos [moves ...]
    if parts[1] == "startpos":
        side = "w"
        if "moves" in parts:
            moves_idx = parts.index("moves")
            ply = len(parts) - (moves_idx + 1)
            if ply % 2 == 1:
                side = "b"
        return side

    # UCI: position fen <6 fen fields> [moves ...]
    if parts[1] == "fen" and len(parts) >= 8:
        side = parts[3] if parts[3] in {"w", "b"} else current
        if "moves" in parts:
            moves_idx = parts.index("moves")
            ply = len(parts) - (moves_idx + 1)
            if ply % 2 == 1:
                side = "b" if side == "w" else "w"
        return side

    return current


def forward_output(pipe, target) -> None:
    for line in iter(pipe.readline, ""):
        try:
            target.write(line)
            target.flush()
        except BrokenPipeError:
            return


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

    threads = int(os.environ.get("STOCKFISH_THREADS", "4"))
    cpu_count = os.cpu_count() or 1
    max_threads = int(os.environ.get("STOCKFISH_MAX_THREADS", str(cpu_count)))
    max_threads = max(1, min(cpu_count, max_threads))
    threads = max(1, min(max_threads, threads))
    hash_mb = int(os.environ.get("STOCKFISH_HASH_MB", "256"))
    hash_mb = max(16, min(2048, hash_mb))
    move_overhead = int(os.environ.get("STOCKFISH_MOVE_OVERHEAD", "20"))
    move_overhead = max(0, min(5000, move_overhead))
    slow_mover = int(os.environ.get("STOCKFISH_SLOW_MOVER", "90"))
    slow_mover = max(10, min(1000, slow_mover))
    low_time_ms = int(os.environ.get("STOCKFISH_LOW_TIME_MS", "12000"))
    low_time_ms = max(1000, min(300000, low_time_ms))
    low_time_overhead = int(os.environ.get("STOCKFISH_LOW_TIME_OVERHEAD", "28"))
    low_time_overhead = max(0, min(5000, low_time_overhead))
    low_time_slow = int(os.environ.get("STOCKFISH_LOW_TIME_SLOW", "70"))
    low_time_slow = max(10, min(1000, low_time_slow))
    panic_time_ms = int(os.environ.get("STOCKFISH_PANIC_TIME_MS", "4000"))
    panic_time_ms = max(500, min(120000, panic_time_ms))
    panic_overhead = int(os.environ.get("STOCKFISH_PANIC_OVERHEAD", "40"))
    panic_overhead = max(0, min(5000, panic_overhead))
    panic_slow = int(os.environ.get("STOCKFISH_PANIC_SLOW", "55"))
    panic_slow = max(10, min(1000, panic_slow))
    critical_time_ms = int(os.environ.get("STOCKFISH_CRITICAL_TIME_MS", "1500"))
    critical_time_ms = max(200, min(60000, critical_time_ms))
    critical_overhead = int(os.environ.get("STOCKFISH_CRITICAL_OVERHEAD", "70"))
    critical_overhead = max(0, min(5000, critical_overhead))
    critical_slow = int(os.environ.get("STOCKFISH_CRITICAL_SLOW", "45"))
    critical_slow = max(10, min(1000, critical_slow))
    profile_hysteresis_ms = int(os.environ.get("STOCKFISH_PROFILE_HYSTERESIS_MS", "600"))
    profile_hysteresis_ms = max(0, min(20000, profile_hysteresis_ms))

    options_sent = False
    side_to_move = "w"
    current_level = 0
    current_overhead = move_overhead
    current_slow = slow_mover
    current_threads = threads
    low_threads = int(os.environ.get("STOCKFISH_LOW_THREADS", str(threads)))
    panic_threads = int(os.environ.get("STOCKFISH_PANIC_THREADS", str(threads)))
    critical_threads = int(os.environ.get("STOCKFISH_CRITICAL_THREADS", "1"))
    low_threads = max(1, min(threads, low_threads))
    panic_threads = max(1, min(threads, panic_threads))
    critical_threads = max(1, min(threads, critical_threads))

    def apply_time_profile(overhead_value: int, slow_value: int) -> None:
        nonlocal current_overhead, current_slow
        if overhead_value == current_overhead and slow_value == current_slow:
            return
        proc.stdin.write(f"setoption name Move Overhead value {overhead_value}\n")
        proc.stdin.write(f"setoption name Slow Mover value {slow_value}\n")
        current_overhead = overhead_value
        current_slow = slow_value

    def choose_remaining_ms(go_line: str, stm: str) -> int | None:
        wtime, btime = parse_go_times(go_line)

        if wtime is None and btime is None:
            return None
        if stm == "w" and wtime is not None:
            return wtime
        if stm == "b" and btime is not None:
            return btime
        valid = []
        if wtime is not None:
            valid.append(wtime)
        if btime is not None:
            valid.append(btime)
        return min(valid)

    def parse_go_times(go_line: str) -> tuple[int | None, int | None]:
        parts = go_line.strip().split()
        wtime = None
        btime = None
        for idx, token in enumerate(parts[:-1]):
            if token == "wtime":
                try:
                    wtime = int(parts[idx + 1])
                except ValueError:
                    pass
            elif token == "btime":
                try:
                    btime = int(parts[idx + 1])
                except ValueError:
                    pass
        return wtime, btime

    def apply_threads(target_threads: int) -> None:
        nonlocal current_threads
        if target_threads == current_threads:
            return
        proc.stdin.write(f"setoption name Threads value {target_threads}\n")
        current_threads = target_threads

    def level_from_remaining(remaining: int) -> int:
        # 0=normal, 1=low, 2=panic, 3=critical
        if remaining <= critical_time_ms:
            return 3
        if remaining <= panic_time_ms:
            return 2
        if remaining <= low_time_ms:
            return 1
        return 0

    def choose_level(go_line: str, stm: str) -> int:
        nonlocal current_level
        remaining = choose_remaining_ms(go_line, stm)
        if remaining is None:
            return current_level
        target = level_from_remaining(remaining)
        if target >= current_level:
            return target
        # Relax only with hysteresis to avoid churn around boundaries.
        if current_level == 3 and remaining >= critical_time_ms + profile_hysteresis_ms:
            return target
        if current_level == 2 and remaining >= panic_time_ms + profile_hysteresis_ms:
            return target
        if current_level == 1 and remaining >= low_time_ms + profile_hysteresis_ms:
            return target
        return current_level

    def choose_profile(go_line: str, stm: str) -> tuple[int, int]:
        remaining = choose_remaining_ms(go_line, stm)
        if remaining is None:
            return move_overhead, slow_mover

        if remaining <= critical_time_ms:
            return critical_overhead, critical_slow
        if remaining <= panic_time_ms:
            return panic_overhead, panic_slow
        if remaining <= low_time_ms:
            return low_time_overhead, low_time_slow
        return move_overhead, slow_mover

    def choose_threads_for_level(level: int) -> int:
        if level >= 3:
            return critical_threads
        if level == 2:
            return panic_threads
        if level == 1:
            return low_threads
        return threads

    for raw in sys.stdin:
        if raw.strip() == "ucinewgame":
            current_level = 0
        if raw.startswith("position "):
            side_to_move = side_to_move_from_position(raw, side_to_move)
        if raw.startswith("go ") and options_sent:
            current_level = choose_level(raw, side_to_move)
            apply_threads(choose_threads_for_level(current_level))
            profile_overhead, profile_slow = choose_profile(raw, side_to_move)
            apply_time_profile(profile_overhead, profile_slow)
        proc.stdin.write(raw)
        if raw.strip() == "uci" and not options_sent:
            proc.stdin.write(f"setoption name Threads value {current_threads}\n")
            proc.stdin.write(f"setoption name Hash value {hash_mb}\n")
            proc.stdin.write("setoption name Skill Level value 20\n")
            proc.stdin.write("setoption name UCI_LimitStrength value false\n")
            proc.stdin.write("setoption name Ponder value false\n")
            proc.stdin.write("setoption name UCI_AnalyseMode value false\n")
            proc.stdin.write("setoption name MultiPV value 1\n")
            proc.stdin.write("setoption name UCI_ShowWDL value false\n")
            proc.stdin.write(f"setoption name Move Overhead value {current_overhead}\n")
            proc.stdin.write(f"setoption name Slow Mover value {current_slow}\n")
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
