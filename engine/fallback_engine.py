#!/usr/bin/env python3
"""
fallback_engine.py — Minimal UCI engine used as a placeholder.

Opens with 1.e4 (or 1...e5), then plays random legal moves.
Agents are expected to replace this with their own engine.
"""

import random
import sys

import chess


def main() -> None:
    board = chess.Board()

    for raw in sys.stdin:
        line = raw.strip()

        if line == "uci":
            print("id name FallbackEngine")
            print("id author orchestrator")
            print("uciok")
            sys.stdout.flush()

        elif line == "isready":
            print("readyok")
            sys.stdout.flush()

        elif line.startswith("position"):
            board = chess.Board()
            parts = line.split()
            if "fen" in parts:
                fen_idx = parts.index("fen")
                fen_parts = []
                for p in parts[fen_idx + 1 :]:
                    if p == "moves":
                        break
                    fen_parts.append(p)
                board = chess.Board(" ".join(fen_parts))
            if "moves" in parts:
                moves_idx = parts.index("moves")
                for uci in parts[moves_idx + 1 :]:
                    board.push(chess.Move.from_uci(uci))

        elif line.startswith("go"):
            legal = list(board.legal_moves)
            if not legal:
                print("bestmove 0000")
                sys.stdout.flush()
                continue
            # Try e2e4 or e7e5 as opening moves
            for opening in ("e2e4", "e7e5"):
                try:
                    m = chess.Move.from_uci(opening)
                    if m in legal:
                        print(f"bestmove {m.uci()}")
                        sys.stdout.flush()
                        break
                except Exception:
                    pass
            else:
                move = random.choice(legal)
                print(f"bestmove {move.uci()}")
                sys.stdout.flush()

        elif line == "stop":
            legal = list(board.legal_moves)
            if legal:
                print(f"bestmove {random.choice(legal).uci()}")
            else:
                print("bestmove 0000")
            sys.stdout.flush()

        elif line == "quit":
            break

        elif line in ("ucinewgame", ""):
            pass


if __name__ == "__main__":
    main()
