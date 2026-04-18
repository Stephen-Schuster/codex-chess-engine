from __future__ import annotations

import argparse
import math
import os
import random
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from engine.chess_state import Position
from engine.search import SearchLimits, Searcher


@dataclass
class MatchResult:
    wins_white: int = 0
    wins_black: int = 0
    draws: int = 0


def play_one_game(depth_white: int, depth_black: int, max_plies: int, seed: int) -> int:
    random.seed(seed)
    position = Position.from_fen(Position.START_FEN)
    search_white = Searcher()
    search_black = Searcher()
    search_white.print_info = False
    search_black.print_info = False

    for _ply in range(max_plies):
        legal = position.generate_legal_moves()
        if not legal:
            if position.in_check(position.side_to_move):
                return -1 if position.side_to_move == 0 else 1
            return 0

        if position.halfmove_clock >= 100 or position.is_threefold_repetition():
            return 0

        if position.side_to_move == 0:
            move, _, _ = search_white.search(position, SearchLimits(depth=depth_white))
        else:
            move, _, _ = search_black.search(position, SearchLimits(depth=depth_black))

        if move is None:
            move = random.choice(legal)

        position.make_move(move)

    # Fallback to static evaluation at move limit.
    white_material = 0
    black_material = 0
    for p in position.board:
        if p > 0:
            white_material += abs(p)
        elif p < 0:
            black_material += abs(p)
    if white_material > black_material:
        return 1
    if black_material > white_material:
        return -1
    return 0


def run_matches(games: int, depth_a: int, depth_b: int, max_plies: int) -> MatchResult:
    result = MatchResult()
    for game in range(games):
        # Alternate colors each game.
        if game % 2 == 0:
            outcome = play_one_game(depth_a, depth_b, max_plies, seed=game + 11)
            if outcome > 0:
                result.wins_white += 1
            elif outcome < 0:
                result.wins_black += 1
            else:
                result.draws += 1
        else:
            outcome = play_one_game(depth_b, depth_a, max_plies, seed=game + 11)
            if outcome > 0:
                result.wins_black += 1
            elif outcome < 0:
                result.wins_white += 1
            else:
                result.draws += 1

    return result


def elo_from_score(score: float) -> float:
    if score <= 0.0:
        return -999.0
    if score >= 1.0:
        return 999.0
    return -400.0 * math.log10((1.0 / score) - 1.0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run quick engine self-matches")
    parser.add_argument("--games", type=int, default=8)
    parser.add_argument("--depth-a", type=int, default=3)
    parser.add_argument("--depth-b", type=int, default=2)
    parser.add_argument("--max-plies", type=int, default=140)
    args = parser.parse_args()

    result = run_matches(args.games, args.depth_a, args.depth_b, args.max_plies)
    total = result.wins_white + result.wins_black + result.draws
    score = (result.wins_white + 0.5 * result.draws) / max(1, total)
    elo = elo_from_score(score)

    print(
        f"matches games={total} wins={result.wins_white} losses={result.wins_black} draws={result.draws} score={score:.3f} elo~{elo:.1f}"
    )


if __name__ == "__main__":
    main()
