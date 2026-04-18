from __future__ import annotations

import argparse
import datetime as dt
import math
import os
import random
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from engine.chess_state import Position
from engine.search import SearchLimits, Searcher


@dataclass
class MatchResult:
    wins_white: int = 0
    wins_black: int = 0
    draws: int = 0

    def games(self) -> int:
        return self.wins_white + self.wins_black + self.draws


def play_one_game(
    depth_white: int,
    depth_black: int,
    max_plies: int,
    seed: int,
    nodes_per_move: int,
    movetime_ms: int,
) -> int:
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

        if (
            position.halfmove_clock >= 100
            or position.is_threefold_repetition()
            or position.is_insufficient_material()
        ):
            return 0

        if position.side_to_move == 0:
            move, _, _ = search_white.search(
                position,
                SearchLimits(depth=depth_white, nodes=nodes_per_move, movetime_ms=movetime_ms),
            )
        else:
            move, _, _ = search_black.search(
                position,
                SearchLimits(depth=depth_black, nodes=nodes_per_move, movetime_ms=movetime_ms),
            )

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


def run_matches(
    games: int,
    depth_a: int,
    depth_b: int,
    max_plies: int,
    nodes_per_move: int,
    movetime_ms: int,
) -> MatchResult:
    result = MatchResult()
    for game in range(games):
        # Alternate colors each game.
        if game % 2 == 0:
            outcome = play_one_game(depth_a, depth_b, max_plies, seed=game + 11, nodes_per_move=nodes_per_move, movetime_ms=movetime_ms)
            if outcome > 0:
                result.wins_white += 1
            elif outcome < 0:
                result.wins_black += 1
            else:
                result.draws += 1
        else:
            outcome = play_one_game(depth_b, depth_a, max_plies, seed=game + 11, nodes_per_move=nodes_per_move, movetime_ms=movetime_ms)
            if outcome > 0:
                result.wins_black += 1
            elif outcome < 0:
                result.wins_white += 1
            else:
                result.draws += 1

        print(
            f"progress game={game + 1}/{games} wins={result.wins_white} losses={result.wins_black} draws={result.draws}",
            flush=True,
        )

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
    parser.add_argument("--nodes-per-move", type=int, default=1500)
    parser.add_argument("--movetime-ms", type=int, default=0)
    parser.add_argument("--output", default="/workspace/game_data/selfplay_results.csv")
    args = parser.parse_args()

    result = run_matches(
        args.games,
        args.depth_a,
        args.depth_b,
        args.max_plies,
        args.nodes_per_move,
        args.movetime_ms,
    )
    total = result.games()
    score = (result.wins_white + 0.5 * result.draws) / max(1, total)
    elo = elo_from_score(score)

    summary = (
        f"matches games={total} wins={result.wins_white} losses={result.wins_black} "
        f"draws={result.draws} score={score:.3f} elo~{elo:.1f} "
        f"nodes_per_move={args.nodes_per_move} movetime_ms={args.movetime_ms}"
    )
    print(summary)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not output_path.exists()
    with output_path.open("a", encoding="ascii") as f:
        if is_new:
            f.write("timestamp,games,depth_a,depth_b,max_plies,nodes_per_move,movetime_ms,wins,losses,draws,score,elo\n")
        f.write(
            f"{dt.datetime.now(dt.UTC).isoformat()},{total},{args.depth_a},{args.depth_b},{args.max_plies},"
            f"{args.nodes_per_move},{args.movetime_ms},{result.wins_white},{result.wins_black},{result.draws},"
            f"{score:.3f},{elo:.1f}\n"
        )


if __name__ == "__main__":
    main()
