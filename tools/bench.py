from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from engine.chess_state import Position
from engine.search import SearchLimits, Searcher


def run_bench(epd_path: str, depth: int, limit: int) -> None:
    searcher = Searcher()
    searcher.print_info = False
    total_nodes = 0
    total_ms = 0
    tested = 0

    with open(epd_path, "r", encoding="ascii") as f:
        for line in f:
            fen = line.strip()
            if not fen:
                continue
            pos = Position.from_fen(fen)
            limits = SearchLimits(depth=depth)
            _, _, elapsed = searcher.search(pos, limits)
            total_nodes += searcher.nodes
            total_ms += elapsed
            tested += 1
            if tested >= limit:
                break

    nps = int(total_nodes * 1000 / max(1, total_ms))
    print(f"bench positions={tested} depth={depth} nodes={total_nodes} time_ms={total_ms} nps={nps}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run engine benchmark")
    parser.add_argument("--epd", default="tests/bench_positions.epd")
    parser.add_argument("--depth", type=int, default=4)
    parser.add_argument("--limit", type=int, default=60)
    args = parser.parse_args()

    start = time.time()
    run_bench(args.epd, args.depth, args.limit)
    elapsed = int((time.time() - start) * 1000)
    print(f"bench_total_time_ms={elapsed}")


if __name__ == "__main__":
    main()
