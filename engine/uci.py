from __future__ import annotations

import sys
from typing import List

from .chess_state import Position
from .search import SearchLimits, Searcher


class UCIEngine:
    def __init__(self) -> None:
        self.position = Position.from_fen(Position.START_FEN)
        self.searcher = Searcher()

    def handle_position(self, tokens: List[str]) -> None:
        if not tokens:
            return

        idx = 0
        if tokens[0] == "startpos":
            self.position = Position.from_fen(Position.START_FEN)
            idx = 1
        elif tokens[0] == "fen":
            if len(tokens) < 7:
                return
            fen = " ".join(tokens[1:7])
            self.position = Position.from_fen(fen)
            idx = 7
        else:
            return

        if idx < len(tokens) and tokens[idx] == "moves":
            for mv in tokens[idx + 1 :]:
                move = self.position.parse_uci_move(mv)
                if move is None:
                    break
                self.position.make_move(move)

    def handle_go(self, tokens: List[str]) -> None:
        limits = SearchLimits()
        i = 0
        while i < len(tokens):
            token = tokens[i]
            if token == "depth" and i + 1 < len(tokens):
                limits.depth = int(tokens[i + 1])
                i += 2
            elif token == "movetime" and i + 1 < len(tokens):
                limits.movetime_ms = int(tokens[i + 1])
                i += 2
            elif token == "wtime" and i + 1 < len(tokens):
                limits.wtime_ms = int(tokens[i + 1])
                i += 2
            elif token == "btime" and i + 1 < len(tokens):
                limits.btime_ms = int(tokens[i + 1])
                i += 2
            elif token == "winc" and i + 1 < len(tokens):
                limits.winc_ms = int(tokens[i + 1])
                i += 2
            elif token == "binc" and i + 1 < len(tokens):
                limits.binc_ms = int(tokens[i + 1])
                i += 2
            elif token == "movestogo" and i + 1 < len(tokens):
                limits.movestogo = int(tokens[i + 1])
                i += 2
            elif token == "nodes" and i + 1 < len(tokens):
                limits.nodes = int(tokens[i + 1])
                i += 2
            elif token == "infinite":
                limits.infinite = True
                i += 1
            else:
                i += 1

        best_move, _, _ = self.searcher.search(self.position, limits)
        if best_move is None:
            print("bestmove 0000", flush=True)
            return
        print(f"bestmove {best_move.to_uci()}", flush=True)

    def loop(self) -> None:
        for raw in sys.stdin:
            line = raw.strip()
            if not line:
                continue

            parts = line.split()
            cmd = parts[0]
            args = parts[1:]

            if cmd == "uci":
                print("id name OpenCodeEngine", flush=True)
                print("id author OpenCode", flush=True)
                print("uciok", flush=True)
            elif cmd == "isready":
                print("readyok", flush=True)
            elif cmd == "ucinewgame":
                self.position = Position.from_fen(Position.START_FEN)
                self.searcher.clear()
            elif cmd == "position":
                self.handle_position(args)
            elif cmd == "go":
                self.handle_go(args)
            elif cmd == "stop":
                self.searcher.stop = True
            elif cmd == "quit":
                return


def main() -> None:
    UCIEngine().loop()


if __name__ == "__main__":
    main()
