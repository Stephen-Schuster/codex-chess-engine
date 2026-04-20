#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
import threading
from collections import defaultdict
from pathlib import Path

import chess
import chess.pgn


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


def board_from_position(cmd: str, current_board: chess.Board) -> chess.Board:
    parts = cmd.strip().split()
    if len(parts) < 2 or parts[0] != "position":
        return current_board

    board = chess.Board()
    idx = 1
    if parts[1] == "startpos":
        idx = 2
    elif parts[1] == "fen" and len(parts) >= 8:
        fen_parts = parts[2:8]
        try:
            board = chess.Board(" ".join(fen_parts))
        except ValueError:
            return current_board
        idx = 8

    if idx < len(parts) and parts[idx] == "moves":
        for uci in parts[idx + 1 :]:
            try:
                mv = chess.Move.from_uci(uci)
            except ValueError:
                break
            if mv not in board.legal_moves:
                break
            board.push(mv)
    return board


def choose_book_move(board: chess.Board) -> str | None:
    # Deterministic micro-book tuned from historical head-to-head outcomes.
    # Keep it small so it only nudges early move selection before Stockfish takes over.
    line = tuple(m.uci() for m in board.move_stack)

    book: dict[tuple[str, ...], str] = {
        # White repertoire
        (): "e2e4",
        ("e2e4", "e7e6"): "d2d4",
        ("e2e4", "c7c6"): "d2d4",
        ("e2e4", "e7e5"): "g1f3",
        ("e2e4", "e7e5", "g1f3", "g8f6"): "f3e5",
        ("e2e4", "c7c5"): "g1f3",
        ("e2e4", "c7c5", "g1f3"): "d2d4",
        ("e2e4", "c7c5", "g1f3", "c5d4"): "f3d4",
        ("e2e4", "c7c5", "g1f3", "d7d6"): "d2d4",

        # Black repertoire
        ("e2e4",): "e7e5",
        ("e2e4", "e7e5", "g1f3"): "b8c6",
        ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5"): "a7a6",
        ("e2e4", "e7e5", "b1c3"): "b8c6",
        ("e2e4", "e7e5", "b1c3", "b8c6", "g1f3"): "f8c5",
        ("d2d4",): "g8f6",
        ("d2d4", "g8f6", "c2c4"): "e7e6",
        ("d2d4", "g8f6", "g1f3"): "d7d5",
        ("g1f3",): "d7d5",
        ("g1f3", "d7d5", "e2e3"): "e7e6",
        ("c2c4",): "g8f6",
        ("c2c4", "g8f6", "b1c3"): "e7e6",
        ("c2c4", "g8f6", "g1f3"): "e7e6",
        ("c2c4", "g8f6", "g1f3", "e7e6", "b1c3"): "d7d5",
    }

    move = book.get(line)
    if move is not None:
        return move

    # Broad fallback for uncommon first white moves.
    if board.ply() == 1 and board.turn == chess.BLACK:
        first = board.move_stack[0].uci()
        if first in {"b2b3", "g2g3", "b1c3", "f2f4", "a2a3", "h2h3"}:
            return "d7d5"
        if first in {"c2c3", "d2d3", "e2e3", "g1f3"}:
            return "g8f6"

    return None


def forced_legal_move(board: chess.Board) -> str | None:
    legal_count = board.legal_moves.count()
    if legal_count == 0:
        return "0000"
    if legal_count == 1:
        return next(iter(board.legal_moves)).uci()
    return None


def game_result_for_agent(
    game: chess.pgn.Game,
    agent_name: str = "GPT-Codex",
    draw_score_white: float = 0.35,
    draw_score_black: float = 0.50,
) -> float | None:
    result = game.headers.get("Result", "")
    white = game.headers.get("White", "")
    black = game.headers.get("Black", "")
    if white != agent_name and black != agent_name:
        return None

    if result == "1-0":
        return 1.0 if white == agent_name else 0.0
    if result == "0-1":
        return 1.0 if black == agent_name else 0.0
    if result == "1/2-1/2":
        # Color-aware draw policy for 1+0: keep more win pressure with White,
        # while preferring safer draw lines with Black to avoid losses.
        if white == agent_name:
            return draw_score_white
        return draw_score_black
    return None


def board_key(board: chess.Board) -> str:
    ep = "-"
    if board.ep_square is not None:
        ep = chess.square_name(board.ep_square)
    return f"{board.board_fen()} {'w' if board.turn == chess.WHITE else 'b'} {board.castling_xfen()} {ep}"


def load_empirical_book(
    max_games: int = 300,
    max_ply: int = 10,
) -> tuple[
    dict[tuple[str, ...], str],
    dict[tuple[str, ...], str],
    dict[str, str],
    dict[str, str],
]:
    max_games = int(os.environ.get("BOOK_MAX_GAMES", str(max_games)))
    max_ply = int(os.environ.get("BOOK_MAX_PLY", str(max_ply)))
    recency_min = float(os.environ.get("BOOK_RECENCY_MIN", "0.85"))
    recency_max = float(os.environ.get("BOOK_RECENCY_MAX", "1.15"))
    draw_score_white = float(os.environ.get("BOOK_DRAW_SCORE_WHITE", "0.35"))
    draw_score_black = float(os.environ.get("BOOK_DRAW_SCORE_BLACK", "0.50"))
    prefix_min_avg_white = float(os.environ.get("BOOK_PREFIX_MIN_AVG_WHITE", "0.78"))
    prefix_min_avg_black = float(os.environ.get("BOOK_PREFIX_MIN_AVG_BLACK", "0.88"))
    pos_min_avg_white = float(os.environ.get("BOOK_POS_MIN_AVG_WHITE", "0.80"))
    pos_min_avg_black = float(os.environ.get("BOOK_POS_MIN_AVG_BLACK", "0.90"))
    prefix_min_total_white = float(os.environ.get("BOOK_PREFIX_MIN_TOTAL_WHITE", "6.0"))
    prefix_min_total_black = float(os.environ.get("BOOK_PREFIX_MIN_TOTAL_BLACK", "8.0"))
    pos_min_total_white = float(os.environ.get("BOOK_POS_MIN_TOTAL_WHITE", "6.0"))
    pos_min_total_black = float(os.environ.get("BOOK_POS_MIN_TOTAL_BLACK", "8.0"))
    prefix_min_count_white = int(os.environ.get("BOOK_PREFIX_MIN_COUNT_WHITE", "3"))
    prefix_min_count_black = int(os.environ.get("BOOK_PREFIX_MIN_COUNT_BLACK", "4"))
    pos_min_count_white = int(os.environ.get("BOOK_POS_MIN_COUNT_WHITE", "4"))
    pos_min_count_black = int(os.environ.get("BOOK_POS_MIN_COUNT_BLACK", "5"))
    prefix_min_gap_white = float(os.environ.get("BOOK_PREFIX_MIN_GAP_WHITE", "0.00"))
    prefix_min_gap_black = float(os.environ.get("BOOK_PREFIX_MIN_GAP_BLACK", "0.05"))
    pos_min_gap_white = float(os.environ.get("BOOK_POS_MIN_GAP_WHITE", "0.00"))
    pos_min_gap_black = float(os.environ.get("BOOK_POS_MIN_GAP_BLACK", "0.05"))
    prefix_max_loss_rate_white = float(os.environ.get("BOOK_PREFIX_MAX_LOSS_RATE_WHITE", "0.30"))
    prefix_max_loss_rate_black = float(os.environ.get("BOOK_PREFIX_MAX_LOSS_RATE_BLACK", "0.16"))
    pos_max_loss_rate_white = float(os.environ.get("BOOK_POS_MAX_LOSS_RATE_WHITE", "0.30"))
    pos_max_loss_rate_black = float(os.environ.get("BOOK_POS_MAX_LOSS_RATE_BLACK", "0.16"))
    max_games = max(20, min(2000, max_games))
    max_ply = max(2, min(20, max_ply))
    recency_min = max(0.10, min(2.00, recency_min))
    recency_max = max(0.10, min(2.00, recency_max))
    if recency_max < recency_min:
        recency_min, recency_max = recency_max, recency_min
    draw_score_white = max(0.0, min(0.99, draw_score_white))
    draw_score_black = max(0.0, min(0.99, draw_score_black))
    prefix_min_avg_white = max(0.0, min(0.99, prefix_min_avg_white))
    prefix_min_avg_black = max(0.0, min(0.99, prefix_min_avg_black))
    pos_min_avg_white = max(0.0, min(0.99, pos_min_avg_white))
    pos_min_avg_black = max(0.0, min(0.99, pos_min_avg_black))
    prefix_min_total_white = max(1.0, prefix_min_total_white)
    prefix_min_total_black = max(1.0, prefix_min_total_black)
    pos_min_total_white = max(1.0, pos_min_total_white)
    pos_min_total_black = max(1.0, pos_min_total_black)
    prefix_min_count_white = max(1, prefix_min_count_white)
    prefix_min_count_black = max(1, prefix_min_count_black)
    pos_min_count_white = max(1, pos_min_count_white)
    pos_min_count_black = max(1, pos_min_count_black)
    prefix_min_gap_white = max(0.0, min(0.99, prefix_min_gap_white))
    prefix_min_gap_black = max(0.0, min(0.99, prefix_min_gap_black))
    pos_min_gap_white = max(0.0, min(0.99, pos_min_gap_white))
    pos_min_gap_black = max(0.0, min(0.99, pos_min_gap_black))
    prefix_max_loss_rate_white = max(0.0, min(1.0, prefix_max_loss_rate_white))
    prefix_max_loss_rate_black = max(0.0, min(1.0, prefix_max_loss_rate_black))
    pos_max_loss_rate_white = max(0.0, min(1.0, pos_max_loss_rate_white))
    pos_max_loss_rate_black = max(0.0, min(1.0, pos_max_loss_rate_black))

    games_dir = Path("/workspace/game_data/games")
    if not games_dir.exists():
        return {}, {}, {}, {}

    pgns = sorted(games_dir.glob("game_*.pgn"))
    if not pgns:
        return {}, {}, {}, {}
    pgns = pgns[-max_games:]

    # prefix -> move -> [weighted_score_sum, weight_sum, raw_count, weighted_loss_sum, weighted_draw_sum, weighted_rep_draw_sum]
    stats_white: dict[tuple[str, ...], dict[str, list[float]]] = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]))
    stats_black: dict[tuple[str, ...], dict[str, list[float]]] = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]))
    # position-key -> move -> [weighted_score_sum, weight_sum, raw_count, weighted_loss_sum, weighted_draw_sum, weighted_rep_draw_sum]
    pos_stats_white: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]))
    pos_stats_black: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]))

    total_files = len(pgns)

    for game_idx, pgn_path in enumerate(pgns):
        try:
            with pgn_path.open() as fh:
                game = chess.pgn.read_game(fh)
        except OSError:
            continue
        if game is None:
            continue

        score = game_result_for_agent(
            game,
            draw_score_white=draw_score_white,
            draw_score_black=draw_score_black,
        )
        if score is None:
            continue
        is_draw = game.headers.get("Result", "") == "1/2-1/2"
        termination = game.headers.get("Termination", "").lower()
        is_rep_draw = is_draw and "threefold" in termination

        white = game.headers.get("White", "")
        black = game.headers.get("Black", "")
        our_is_white = white == "GPT-Codex"
        if not our_is_white and black != "GPT-Codex":
            continue

        # Mild recency weighting to adapt to current opponent trends.
        if total_files <= 1:
            weight = 1.0
        else:
            weight = recency_min + (recency_max - recency_min) * (game_idx / (total_files - 1))

        prefix: list[str] = []
        node = game
        board = game.board()
        ply = 0
        while node.variations and ply < max_ply:
            node = node.variation(0)
            move_uci = node.move.uci()

            our_turn = (ply % 2 == 0 and our_is_white) or (ply % 2 == 1 and not our_is_white)
            if our_turn:
                side_stats = stats_white if board.turn == chess.WHITE else stats_black
                side_pos_stats = pos_stats_white if board.turn == chess.WHITE else pos_stats_black
                key = tuple(prefix)
                bucket = side_stats[key][move_uci]
                bucket[0] += score * weight
                bucket[1] += weight
                bucket[2] += 1.0
                if score <= 0.001:
                    bucket[3] += weight
                if is_draw:
                    bucket[4] += weight
                if is_rep_draw:
                    bucket[5] += weight

                pkey = board_key(board)
                p_bucket = side_pos_stats[pkey][move_uci]
                p_bucket[0] += score * weight
                p_bucket[1] += weight
                p_bucket[2] += 1.0
                if score <= 0.001:
                    p_bucket[3] += weight
                if is_draw:
                    p_bucket[4] += weight
                if is_rep_draw:
                    p_bucket[5] += weight

            board.push(node.move)
            prefix.append(move_uci)
            ply += 1

    def select_prefix_book(
        stats: dict[tuple[str, ...], dict[str, list[float]]],
        min_total: float,
        min_count: int,
        min_avg: float,
        min_gap: float,
        max_loss_rate: float,
        draw_penalty: float,
        rep_draw_penalty: float,
    ) -> dict[tuple[str, ...], str]:
        book: dict[tuple[str, ...], str] = {}
        for prefix, moves in stats.items():
            total = 0.0
            for _, (_, weight_sum, _, _, _, _) in moves.items():
                total += float(weight_sum)
            if total < min_total:
                continue

            best_move = None
            best_sel = -1.0
            best_avg = -1.0
            best_weight = -1.0
            best_count = -1
            second_sel = -1.0
            for move, (weighted_score_sum, weight_sum, raw_count, weighted_loss_sum, weighted_draw_sum, weighted_rep_draw_sum) in moves.items():
                c = int(raw_count)
                if c < min_count:
                    continue
                avg = float(weighted_score_sum) / max(1e-9, float(weight_sum))
                loss_rate = float(weighted_loss_sum) / max(1e-9, float(weight_sum))
                if loss_rate > max_loss_rate:
                    continue
                draw_rate = float(weighted_draw_sum) / max(1e-9, float(weight_sum))
                rep_draw_rate = float(weighted_rep_draw_sum) / max(1e-9, float(weight_sum))
                sel = avg - draw_penalty * draw_rate - rep_draw_penalty * rep_draw_rate
                is_better = (
                    sel > best_sel
                    or (
                        abs(sel - best_sel) <= 1e-12
                        and (
                            float(weight_sum) > best_weight
                            or (
                                abs(float(weight_sum) - best_weight) <= 1e-12
                                and (c > best_count or (c == best_count and move > (best_move or "")))
                            )
                        )
                    )
                )
                if is_better:
                    if best_move is not None:
                        second_sel = max(second_sel, best_sel)
                    best_sel = sel
                    best_avg = avg
                    best_weight = float(weight_sum)
                    best_count = c
                    best_move = move
                else:
                    second_sel = max(second_sel, sel)

            if best_move is None:
                continue
            if best_avg >= min_avg:
                if second_sel >= 0.0 and (best_sel - second_sel) < min_gap:
                    continue
                book[prefix] = best_move
        return book

    def select_pos_book(
        pos_stats: dict[str, dict[str, list[float]]],
        min_total: float,
        min_count: int,
        min_avg: float,
        min_gap: float,
        max_loss_rate: float,
        draw_penalty: float,
        rep_draw_penalty: float,
    ) -> dict[str, str]:
        pos_book: dict[str, str] = {}
        for pkey, moves in pos_stats.items():
            total = 0.0
            for _, (_, weight_sum, _, _, _, _) in moves.items():
                total += float(weight_sum)
            if total < min_total:
                continue

            best_move = None
            best_sel = -1.0
            best_avg = -1.0
            best_weight = -1.0
            best_count = -1
            second_sel = -1.0
            for move, (weighted_score_sum, weight_sum, raw_count, weighted_loss_sum, weighted_draw_sum, weighted_rep_draw_sum) in moves.items():
                c = int(raw_count)
                if c < min_count:
                    continue
                avg = float(weighted_score_sum) / max(1e-9, float(weight_sum))
                loss_rate = float(weighted_loss_sum) / max(1e-9, float(weight_sum))
                if loss_rate > max_loss_rate:
                    continue
                draw_rate = float(weighted_draw_sum) / max(1e-9, float(weight_sum))
                rep_draw_rate = float(weighted_rep_draw_sum) / max(1e-9, float(weight_sum))
                sel = avg - draw_penalty * draw_rate - rep_draw_penalty * rep_draw_rate
                is_better = (
                    sel > best_sel
                    or (
                        abs(sel - best_sel) <= 1e-12
                        and (
                            float(weight_sum) > best_weight
                            or (
                                abs(float(weight_sum) - best_weight) <= 1e-12
                                and (c > best_count or (c == best_count and move > (best_move or "")))
                            )
                        )
                    )
                )
                if is_better:
                    if best_move is not None:
                        second_sel = max(second_sel, best_sel)
                    best_sel = sel
                    best_avg = avg
                    best_weight = float(weight_sum)
                    best_count = c
                    best_move = move
                else:
                    second_sel = max(second_sel, sel)

            if best_move is None:
                continue
            if best_avg >= min_avg:
                if second_sel >= 0.0 and (best_sel - second_sel) < min_gap:
                    continue
                pos_book[pkey] = best_move
        return pos_book

    prefix_draw_penalty_white = float(os.environ.get("BOOK_PREFIX_DRAW_PENALTY_WHITE", "0.04"))
    prefix_draw_penalty_black = float(os.environ.get("BOOK_PREFIX_DRAW_PENALTY_BLACK", "0.00"))
    pos_draw_penalty_white = float(os.environ.get("BOOK_POS_DRAW_PENALTY_WHITE", "0.04"))
    pos_draw_penalty_black = float(os.environ.get("BOOK_POS_DRAW_PENALTY_BLACK", "0.00"))
    prefix_rep_draw_penalty_white = float(os.environ.get("BOOK_PREFIX_REP_DRAW_PENALTY_WHITE", "0.00"))
    prefix_rep_draw_penalty_black = float(os.environ.get("BOOK_PREFIX_REP_DRAW_PENALTY_BLACK", "0.00"))
    pos_rep_draw_penalty_white = float(os.environ.get("BOOK_POS_REP_DRAW_PENALTY_WHITE", "0.00"))
    pos_rep_draw_penalty_black = float(os.environ.get("BOOK_POS_REP_DRAW_PENALTY_BLACK", "0.00"))
    prefix_draw_penalty_white = max(0.0, min(1.0, prefix_draw_penalty_white))
    prefix_draw_penalty_black = max(0.0, min(1.0, prefix_draw_penalty_black))
    pos_draw_penalty_white = max(0.0, min(1.0, pos_draw_penalty_white))
    pos_draw_penalty_black = max(0.0, min(1.0, pos_draw_penalty_black))
    prefix_rep_draw_penalty_white = max(0.0, min(1.0, prefix_rep_draw_penalty_white))
    prefix_rep_draw_penalty_black = max(0.0, min(1.0, prefix_rep_draw_penalty_black))
    pos_rep_draw_penalty_white = max(0.0, min(1.0, pos_rep_draw_penalty_white))
    pos_rep_draw_penalty_black = max(0.0, min(1.0, pos_rep_draw_penalty_black))

    book_white = select_prefix_book(
        stats_white,
        prefix_min_total_white,
        prefix_min_count_white,
        prefix_min_avg_white,
        prefix_min_gap_white,
        prefix_max_loss_rate_white,
        prefix_draw_penalty_white,
        prefix_rep_draw_penalty_white,
    )
    book_black = select_prefix_book(
        stats_black,
        prefix_min_total_black,
        prefix_min_count_black,
        prefix_min_avg_black,
        prefix_min_gap_black,
        prefix_max_loss_rate_black,
        prefix_draw_penalty_black,
        prefix_rep_draw_penalty_black,
    )
    pos_book_white = select_pos_book(
        pos_stats_white,
        pos_min_total_white,
        pos_min_count_white,
        pos_min_avg_white,
        pos_min_gap_white,
        pos_max_loss_rate_white,
        pos_draw_penalty_white,
        pos_rep_draw_penalty_white,
    )
    pos_book_black = select_pos_book(
        pos_stats_black,
        pos_min_total_black,
        pos_min_count_black,
        pos_min_avg_black,
        pos_min_gap_black,
        pos_max_loss_rate_black,
        pos_draw_penalty_black,
        pos_rep_draw_penalty_black,
    )
    return book_white, book_black, pos_book_white, pos_book_black


def load_draw_avoid_prefixes(
    max_games: int = 160,
    max_ply: int = 14,
    min_count_white: int = 5,
    min_count_black: int = 6,
    min_draws_white: int = 4,
    min_draws_black: int = 5,
    min_draw_rate_white: float = 0.72,
    min_draw_rate_black: float = 0.78,
    max_loss_rate_white: float = 0.20,
    max_loss_rate_black: float = 0.15,
) -> tuple[set[tuple[str, ...]], set[tuple[str, ...]]]:
    max_games = max(20, min(3000, int(max_games)))
    max_ply = max(2, min(40, int(max_ply)))
    min_count_white = max(1, min(200, int(min_count_white)))
    min_count_black = max(1, min(200, int(min_count_black)))
    min_draws_white = max(1, min(200, int(min_draws_white)))
    min_draws_black = max(1, min(200, int(min_draws_black)))
    min_draw_rate_white = max(0.0, min(1.0, float(min_draw_rate_white)))
    min_draw_rate_black = max(0.0, min(1.0, float(min_draw_rate_black)))
    max_loss_rate_white = max(0.0, min(1.0, float(max_loss_rate_white)))
    max_loss_rate_black = max(0.0, min(1.0, float(max_loss_rate_black)))

    games_dir = Path("/workspace/game_data/games")
    if not games_dir.exists():
        return set(), set()

    pgns = sorted(games_dir.glob("game_*.pgn"))
    if not pgns:
        return set(), set()
    pgns = pgns[-max_games:]

    white_stats: dict[tuple[str, ...], list[int]] = defaultdict(lambda: [0, 0, 0])
    black_stats: dict[tuple[str, ...], list[int]] = defaultdict(lambda: [0, 0, 0])

    for pgn_path in pgns:
        try:
            with pgn_path.open() as fh:
                game = chess.pgn.read_game(fh)
        except OSError:
            continue
        if game is None:
            continue

        white = game.headers.get("White", "")
        black = game.headers.get("Black", "")
        if white != "GPT-Codex" and black != "GPT-Codex":
            continue
        our_is_white = white == "GPT-Codex"
        result = game.headers.get("Result", "")
        is_draw = result == "1/2-1/2"
        we_lost = (our_is_white and result == "0-1") or ((not our_is_white) and result == "1-0")

        node = game
        prefix: list[str] = []
        ply = 0
        while node.variations and ply < max_ply:
            our_turn = (ply % 2 == 0 and our_is_white) or (ply % 2 == 1 and not our_is_white)
            if our_turn:
                key = tuple(prefix)
                side_stats = white_stats if our_is_white else black_stats
                side_stats[key][0] += 1
                if is_draw:
                    side_stats[key][1] += 1
                if we_lost:
                    side_stats[key][2] += 1
            node = node.variation(0)
            prefix.append(node.move.uci())
            ply += 1

    white_prefixes: set[tuple[str, ...]] = set()
    black_prefixes: set[tuple[str, ...]] = set()

    for prefix, (count, draws, losses) in white_stats.items():
        if count < min_count_white or draws < min_draws_white:
            continue
        draw_rate = draws / count
        loss_rate = losses / count
        if draw_rate >= min_draw_rate_white and loss_rate <= max_loss_rate_white:
            white_prefixes.add(prefix)

    for prefix, (count, draws, losses) in black_stats.items():
        if count < min_count_black or draws < min_draws_black:
            continue
        draw_rate = draws / count
        loss_rate = losses / count
        if draw_rate >= min_draw_rate_black and loss_rate <= max_loss_rate_black:
            black_prefixes.add(prefix)

    return white_prefixes, black_prefixes


def load_loss_avoid_prefixes(
    max_games: int = 500,
    max_ply: int = 12,
    min_count_white: int = 3,
    min_count_black: int = 2,
    min_losses_white: int = 2,
    min_losses_black: int = 1,
    min_loss_rate_white: float = 0.40,
    min_loss_rate_black: float = 0.28,
) -> tuple[set[tuple[str, ...]], set[tuple[str, ...]]]:
    max_games = max(20, min(4000, int(max_games)))
    max_ply = max(2, min(40, int(max_ply)))
    min_count_white = max(1, min(200, int(min_count_white)))
    min_count_black = max(1, min(200, int(min_count_black)))
    min_losses_white = max(1, min(200, int(min_losses_white)))
    min_losses_black = max(1, min(200, int(min_losses_black)))
    min_loss_rate_white = max(0.0, min(1.0, float(min_loss_rate_white)))
    min_loss_rate_black = max(0.0, min(1.0, float(min_loss_rate_black)))

    games_dir = Path("/workspace/game_data/games")
    if not games_dir.exists():
        return set(), set()

    pgns = sorted(games_dir.glob("game_*.pgn"))
    if not pgns:
        return set(), set()
    pgns = pgns[-max_games:]

    white_stats: dict[tuple[str, ...], list[int]] = defaultdict(lambda: [0, 0])
    black_stats: dict[tuple[str, ...], list[int]] = defaultdict(lambda: [0, 0])

    for pgn_path in pgns:
        try:
            with pgn_path.open() as fh:
                game = chess.pgn.read_game(fh)
        except OSError:
            continue
        if game is None:
            continue

        white = game.headers.get("White", "")
        black = game.headers.get("Black", "")
        if white != "GPT-Codex" and black != "GPT-Codex":
            continue
        our_is_white = white == "GPT-Codex"

        result = game.headers.get("Result", "")
        we_lost = (our_is_white and result == "0-1") or ((not our_is_white) and result == "1-0")

        node = game
        prefix: list[str] = []
        ply = 0
        while node.variations and ply < max_ply:
            our_turn = (ply % 2 == 0 and our_is_white) or (ply % 2 == 1 and not our_is_white)
            if our_turn:
                key = tuple(prefix)
                side_stats = white_stats if our_is_white else black_stats
                side_stats[key][0] += 1
                if we_lost:
                    side_stats[key][1] += 1
            node = node.variation(0)
            prefix.append(node.move.uci())
            ply += 1

    white_prefixes: set[tuple[str, ...]] = set()
    black_prefixes: set[tuple[str, ...]] = set()

    for prefix, (count, losses) in white_stats.items():
        if count >= min_count_white and losses >= min_losses_white and (losses / count) >= min_loss_rate_white:
            white_prefixes.add(prefix)
    for prefix, (count, losses) in black_stats.items():
        if count >= min_count_black and losses >= min_losses_black and (losses / count) >= min_loss_rate_black:
            black_prefixes.add(prefix)

    return white_prefixes, black_prefixes


def forward_output(pipe, target) -> None:
    for line in iter(pipe.readline, ""):
        try:
            target.write(line)
            target.flush()
        except BrokenPipeError:
            return


def extract_info_score(line: str) -> tuple[int | None, int | None]:
    if not line.startswith("info "):
        return None, None
    parts = line.strip().split()
    for i, tok in enumerate(parts):
        if tok != "score" or i + 2 >= len(parts):
            continue
        typ = parts[i + 1]
        val = parts[i + 2]
        if typ == "cp":
            try:
                return int(val), None
            except ValueError:
                return None, None
        if typ == "mate":
            try:
                return None, int(val)
            except ValueError:
                return None, None
    return None, None


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

    err_thread = threading.Thread(target=forward_output, args=(proc.stderr, sys.stderr), daemon=True)
    err_thread.start()

    info_lock = threading.Lock()
    latest_info_cp: int | None = None
    latest_info_mate: int | None = None

    def forward_stockfish_stdout(pipe, target) -> None:
        nonlocal latest_info_cp, latest_info_mate
        for line in iter(pipe.readline, ""):
            cp, mate = extract_info_score(line)
            if cp is not None or mate is not None:
                with info_lock:
                    if cp is not None:
                        latest_info_cp = cp
                        latest_info_mate = None
                    elif mate is not None:
                        latest_info_mate = mate
                        latest_info_cp = None
            try:
                target.write(line)
                target.flush()
            except BrokenPipeError:
                return

    out_thread = threading.Thread(target=forward_stockfish_stdout, args=(proc.stdout, sys.stdout), daemon=True)
    out_thread.start()

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
    board = chess.Board()
    (
        empirical_book_white,
        empirical_book_black,
        empirical_pos_book_white,
        empirical_pos_book_black,
    ) = load_empirical_book()
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
    anti_rep_enabled = os.environ.get("BOOK_ANTI_REP_ENABLE", "1").strip().lower() not in {"0", "false", "no", "off"}
    anti_rep_white = os.environ.get("BOOK_ANTI_REP_WHITE", "1").strip().lower() not in {"0", "false", "no", "off"}
    anti_rep_black = os.environ.get("BOOK_ANTI_REP_BLACK", "1").strip().lower() not in {"0", "false", "no", "off"}
    anti_rep_clock_lead_ms_white = int(os.environ.get("BOOK_ANTI_REP_CLOCK_LEAD_MS_WHITE", os.environ.get("BOOK_ANTI_REP_CLOCK_LEAD_MS", "4500")))
    anti_rep_clock_lead_ms_black = int(os.environ.get("BOOK_ANTI_REP_CLOCK_LEAD_MS_BLACK", os.environ.get("BOOK_ANTI_REP_CLOCK_LEAD_MS", "13000")))
    anti_rep_clock_lead_ms_white = max(0, min(60000, anti_rep_clock_lead_ms_white))
    anti_rep_clock_lead_ms_black = max(0, min(60000, anti_rep_clock_lead_ms_black))
    anti_rep_material_cp_white = int(os.environ.get("BOOK_ANTI_REP_MATERIAL_CP_WHITE", os.environ.get("BOOK_ANTI_REP_MATERIAL_CP", "120")))
    anti_rep_material_cp_black = int(os.environ.get("BOOK_ANTI_REP_MATERIAL_CP_BLACK", os.environ.get("BOOK_ANTI_REP_MATERIAL_CP", "300")))
    anti_rep_material_cp_white = max(0, min(4000, anti_rep_material_cp_white))
    anti_rep_material_cp_black = max(0, min(4000, anti_rep_material_cp_black))
    anti_rep_eval_cp_white = int(os.environ.get("BOOK_ANTI_REP_EVAL_CP_WHITE", os.environ.get("BOOK_ANTI_REP_EVAL_CP", "90")))
    anti_rep_eval_cp_black = int(os.environ.get("BOOK_ANTI_REP_EVAL_CP_BLACK", os.environ.get("BOOK_ANTI_REP_EVAL_CP", "260")))
    anti_rep_eval_cp_white = max(0, min(4000, anti_rep_eval_cp_white))
    anti_rep_eval_cp_black = max(0, min(4000, anti_rep_eval_cp_black))
    anti_rep_min_ply_white = int(os.environ.get("BOOK_ANTI_REP_MIN_PLY_WHITE", "0"))
    anti_rep_min_ply_black = int(os.environ.get("BOOK_ANTI_REP_MIN_PLY_BLACK", "28"))
    anti_rep_min_ply_white = max(0, min(300, anti_rep_min_ply_white))
    anti_rep_min_ply_black = max(0, min(300, anti_rep_min_ply_black))
    anti_rep_soft_white = os.environ.get("BOOK_ANTI_REP_SOFT_WHITE", "1").strip().lower() not in {"0", "false", "no", "off"}
    anti_rep_soft_white_min_time = int(os.environ.get("BOOK_ANTI_REP_SOFT_WHITE_MIN_TIME_MS", "9000"))
    anti_rep_soft_white_min_time = max(0, min(300000, anti_rep_soft_white_min_time))
    anti_rep_soft_white_max_ply = int(os.environ.get("BOOK_ANTI_REP_SOFT_WHITE_MAX_PLY", "40"))
    anti_rep_soft_white_max_ply = max(0, min(300, anti_rep_soft_white_max_ply))
    anti_rep_soft_white_clock_slack = int(os.environ.get("BOOK_ANTI_REP_SOFT_WHITE_CLOCK_SLACK_MS", "1200"))
    anti_rep_soft_white_clock_slack = max(0, min(300000, anti_rep_soft_white_clock_slack))
    anti_rep_soft_white_min_material_cp = int(os.environ.get("BOOK_ANTI_REP_SOFT_WHITE_MIN_MATERIAL_CP", "-40"))
    anti_rep_soft_white_min_eval_cp = int(os.environ.get("BOOK_ANTI_REP_SOFT_WHITE_MIN_EVAL_CP", "-30"))
    anti_rep_soft_white_min_material_cp = max(-4000, min(4000, anti_rep_soft_white_min_material_cp))
    anti_rep_soft_white_min_eval_cp = max(-4000, min(4000, anti_rep_soft_white_min_eval_cp))
    anti_rep_twofold_white = os.environ.get("BOOK_ANTI_REP_TWOFOLD_WHITE", "1").strip().lower() not in {"0", "false", "no", "off"}
    anti_rep_twofold_min_ply_white = int(os.environ.get("BOOK_ANTI_REP_TWOFOLD_MIN_PLY_WHITE", "10"))
    anti_rep_twofold_max_ply_white = int(os.environ.get("BOOK_ANTI_REP_TWOFOLD_MAX_PLY_WHITE", "46"))
    anti_rep_twofold_min_time_ms_white = int(os.environ.get("BOOK_ANTI_REP_TWOFOLD_MIN_TIME_MS_WHITE", "13000"))
    anti_rep_twofold_max_clock_deficit_ms_white = int(os.environ.get("BOOK_ANTI_REP_TWOFOLD_MAX_CLOCK_DEFICIT_MS_WHITE", "1200"))
    anti_rep_twofold_min_material_cp_white = int(os.environ.get("BOOK_ANTI_REP_TWOFOLD_MIN_MATERIAL_CP_WHITE", "40"))
    anti_rep_twofold_min_eval_cp_white = int(os.environ.get("BOOK_ANTI_REP_TWOFOLD_MIN_EVAL_CP_WHITE", "70"))
    anti_rep_twofold_min_ply_white = max(0, min(300, anti_rep_twofold_min_ply_white))
    anti_rep_twofold_max_ply_white = max(0, min(300, anti_rep_twofold_max_ply_white))
    anti_rep_twofold_min_time_ms_white = max(0, min(300000, anti_rep_twofold_min_time_ms_white))
    anti_rep_twofold_max_clock_deficit_ms_white = max(0, min(300000, anti_rep_twofold_max_clock_deficit_ms_white))
    anti_rep_twofold_min_material_cp_white = max(-4000, min(4000, anti_rep_twofold_min_material_cp_white))
    anti_rep_twofold_min_eval_cp_white = max(-4000, min(4000, anti_rep_twofold_min_eval_cp_white))
    anti_rep_search_white = os.environ.get("BOOK_ANTI_REP_SEARCH_WHITE", "0").strip().lower() not in {"0", "false", "no", "off"}
    anti_rep_search_black = os.environ.get("BOOK_ANTI_REP_SEARCH_BLACK", "0").strip().lower() not in {"0", "false", "no", "off"}
    anti_rep_search_min_ply_white = int(os.environ.get("BOOK_ANTI_REP_SEARCH_MIN_PLY_WHITE", "22"))
    anti_rep_search_min_ply_black = int(os.environ.get("BOOK_ANTI_REP_SEARCH_MIN_PLY_BLACK", "28"))
    anti_rep_search_clock_lead_ms_white = int(os.environ.get("BOOK_ANTI_REP_SEARCH_CLOCK_LEAD_MS_WHITE", "12000"))
    anti_rep_search_clock_lead_ms_black = int(os.environ.get("BOOK_ANTI_REP_SEARCH_CLOCK_LEAD_MS_BLACK", "14000"))
    anti_rep_search_min_material_cp_white = int(os.environ.get("BOOK_ANTI_REP_SEARCH_MIN_MATERIAL_CP_WHITE", "150"))
    anti_rep_search_min_material_cp_black = int(os.environ.get("BOOK_ANTI_REP_SEARCH_MIN_MATERIAL_CP_BLACK", "300"))
    anti_rep_search_min_eval_cp_white = int(os.environ.get("BOOK_ANTI_REP_SEARCH_MIN_EVAL_CP_WHITE", "120"))
    anti_rep_search_min_eval_cp_black = int(os.environ.get("BOOK_ANTI_REP_SEARCH_MIN_EVAL_CP_BLACK", "260"))
    anti_rep_search_force_white = os.environ.get("BOOK_ANTI_REP_SEARCH_FORCE_WHITE", "0").strip().lower() not in {"0", "false", "no", "off"}
    anti_rep_search_force_black = os.environ.get("BOOK_ANTI_REP_SEARCH_FORCE_BLACK", "1").strip().lower() not in {"0", "false", "no", "off"}
    anti_rep_search_force_min_ply_white = int(os.environ.get("BOOK_ANTI_REP_SEARCH_FORCE_MIN_PLY_WHITE", "20"))
    anti_rep_search_force_min_ply_black = int(os.environ.get("BOOK_ANTI_REP_SEARCH_FORCE_MIN_PLY_BLACK", "24"))
    anti_rep_search_force_min_time_ms_white = int(os.environ.get("BOOK_ANTI_REP_SEARCH_FORCE_MIN_TIME_MS_WHITE", "9000"))
    anti_rep_search_force_min_time_ms_black = int(os.environ.get("BOOK_ANTI_REP_SEARCH_FORCE_MIN_TIME_MS_BLACK", "10000"))
    anti_rep_search_force_max_clock_deficit_ms_white = int(os.environ.get("BOOK_ANTI_REP_SEARCH_FORCE_MAX_CLOCK_DEFICIT_MS_WHITE", "6000"))
    anti_rep_search_force_max_clock_deficit_ms_black = int(os.environ.get("BOOK_ANTI_REP_SEARCH_FORCE_MAX_CLOCK_DEFICIT_MS_BLACK", "16000"))
    anti_rep_search_force_min_material_cp_white = int(os.environ.get("BOOK_ANTI_REP_SEARCH_FORCE_MIN_MATERIAL_CP_WHITE", "220"))
    anti_rep_search_force_min_material_cp_black = int(os.environ.get("BOOK_ANTI_REP_SEARCH_FORCE_MIN_MATERIAL_CP_BLACK", "320"))
    anti_rep_search_force_min_eval_cp_white = int(os.environ.get("BOOK_ANTI_REP_SEARCH_FORCE_MIN_EVAL_CP_WHITE", "170"))
    anti_rep_search_force_min_eval_cp_black = int(os.environ.get("BOOK_ANTI_REP_SEARCH_FORCE_MIN_EVAL_CP_BLACK", "300"))
    anti_rep_search_force_min_keep_white = int(os.environ.get("BOOK_ANTI_REP_SEARCH_FORCE_MIN_KEEP_WHITE", "2"))
    anti_rep_search_force_min_keep_black = int(os.environ.get("BOOK_ANTI_REP_SEARCH_FORCE_MIN_KEEP_BLACK", "2"))
    anti_rep_search_min_ply_white = max(0, min(300, anti_rep_search_min_ply_white))
    anti_rep_search_min_ply_black = max(0, min(300, anti_rep_search_min_ply_black))
    anti_rep_search_clock_lead_ms_white = max(0, min(60000, anti_rep_search_clock_lead_ms_white))
    anti_rep_search_clock_lead_ms_black = max(0, min(60000, anti_rep_search_clock_lead_ms_black))
    anti_rep_search_min_material_cp_white = max(-4000, min(4000, anti_rep_search_min_material_cp_white))
    anti_rep_search_min_material_cp_black = max(-4000, min(4000, anti_rep_search_min_material_cp_black))
    anti_rep_search_min_eval_cp_white = max(-4000, min(4000, anti_rep_search_min_eval_cp_white))
    anti_rep_search_min_eval_cp_black = max(-4000, min(4000, anti_rep_search_min_eval_cp_black))
    anti_rep_search_force_min_ply_white = max(0, min(300, anti_rep_search_force_min_ply_white))
    anti_rep_search_force_min_ply_black = max(0, min(300, anti_rep_search_force_min_ply_black))
    anti_rep_search_force_min_time_ms_white = max(0, min(300000, anti_rep_search_force_min_time_ms_white))
    anti_rep_search_force_min_time_ms_black = max(0, min(300000, anti_rep_search_force_min_time_ms_black))
    anti_rep_search_force_max_clock_deficit_ms_white = max(0, min(300000, anti_rep_search_force_max_clock_deficit_ms_white))
    anti_rep_search_force_max_clock_deficit_ms_black = max(0, min(300000, anti_rep_search_force_max_clock_deficit_ms_black))
    anti_rep_search_force_min_material_cp_white = max(-4000, min(4000, anti_rep_search_force_min_material_cp_white))
    anti_rep_search_force_min_material_cp_black = max(-4000, min(4000, anti_rep_search_force_min_material_cp_black))
    anti_rep_search_force_min_eval_cp_white = max(-4000, min(4000, anti_rep_search_force_min_eval_cp_white))
    anti_rep_search_force_min_eval_cp_black = max(-4000, min(4000, anti_rep_search_force_min_eval_cp_black))
    anti_rep_search_force_min_keep_white = max(1, min(64, anti_rep_search_force_min_keep_white))
    anti_rep_search_force_min_keep_black = max(1, min(64, anti_rep_search_force_min_keep_black))
    avoid_draw_white = os.environ.get("BOOK_AVOID_DRAW_WHITE", "1").strip().lower() not in {"0", "false", "no", "off"}
    avoid_draw_black = os.environ.get("BOOK_AVOID_DRAW_BLACK", "0").strip().lower() not in {"0", "false", "no", "off"}
    avoid_draw_games = int(os.environ.get("BOOK_AVOID_DRAW_GAMES", "300"))
    avoid_draw_max_ply = int(os.environ.get("BOOK_AVOID_DRAW_MAX_PLY", "16"))
    avoid_draw_min_ply_white = int(os.environ.get("BOOK_AVOID_DRAW_MIN_PLY_WHITE", "8"))
    avoid_draw_min_ply_black = int(os.environ.get("BOOK_AVOID_DRAW_MIN_PLY_BLACK", "0"))
    avoid_draw_white_min_time_ms = int(os.environ.get("BOOK_AVOID_DRAW_WHITE_MIN_TIME_MS", "12000"))
    avoid_draw_white_max_clock_deficit_ms = int(os.environ.get("BOOK_AVOID_DRAW_WHITE_MAX_CLOCK_DEFICIT_MS", "1500"))
    avoid_draw_min_count_white = int(os.environ.get("BOOK_AVOID_DRAW_MIN_COUNT_WHITE", "2"))
    avoid_draw_min_count_black = int(os.environ.get("BOOK_AVOID_DRAW_MIN_COUNT_BLACK", "6"))
    avoid_draw_min_draws_white = int(os.environ.get("BOOK_AVOID_DRAW_MIN_DRAWS_WHITE", "1"))
    avoid_draw_min_draws_black = int(os.environ.get("BOOK_AVOID_DRAW_MIN_DRAWS_BLACK", "5"))
    avoid_draw_min_rate_white = float(os.environ.get("BOOK_AVOID_DRAW_MIN_RATE_WHITE", "0.42"))
    avoid_draw_min_rate_black = float(os.environ.get("BOOK_AVOID_DRAW_MIN_RATE_BLACK", "0.78"))
    avoid_draw_max_loss_rate_white = float(os.environ.get("BOOK_AVOID_DRAW_MAX_LOSS_RATE_WHITE", "0.40"))
    avoid_draw_max_loss_rate_black = float(os.environ.get("BOOK_AVOID_DRAW_MAX_LOSS_RATE_BLACK", "0.15"))
    avoid_draw_games = max(20, min(3000, avoid_draw_games))
    avoid_draw_max_ply = max(2, min(40, avoid_draw_max_ply))
    avoid_draw_min_ply_white = max(0, min(300, avoid_draw_min_ply_white))
    avoid_draw_min_ply_black = max(0, min(300, avoid_draw_min_ply_black))
    avoid_draw_white_min_time_ms = max(0, min(300000, avoid_draw_white_min_time_ms))
    avoid_draw_white_max_clock_deficit_ms = max(0, min(300000, avoid_draw_white_max_clock_deficit_ms))
    avoid_draw_prefixes_white, avoid_draw_prefixes_black = load_draw_avoid_prefixes(
        max_games=avoid_draw_games,
        max_ply=avoid_draw_max_ply,
        min_count_white=avoid_draw_min_count_white,
        min_count_black=avoid_draw_min_count_black,
        min_draws_white=avoid_draw_min_draws_white,
        min_draws_black=avoid_draw_min_draws_black,
        min_draw_rate_white=avoid_draw_min_rate_white,
        min_draw_rate_black=avoid_draw_min_rate_black,
        max_loss_rate_white=avoid_draw_max_loss_rate_white,
        max_loss_rate_black=avoid_draw_max_loss_rate_black,
    )
    avoid_loss_enable = os.environ.get("BOOK_AVOID_LOSS_ENABLE", "1").strip().lower() not in {"0", "false", "no", "off"}
    avoid_loss_white = os.environ.get("BOOK_AVOID_LOSS_WHITE", "0").strip().lower() not in {"0", "false", "no", "off"}
    avoid_loss_black = os.environ.get("BOOK_AVOID_LOSS_BLACK", "1").strip().lower() not in {"0", "false", "no", "off"}
    avoid_loss_games = int(os.environ.get("BOOK_AVOID_LOSS_GAMES", "500"))
    avoid_loss_max_ply = int(os.environ.get("BOOK_AVOID_LOSS_MAX_PLY", "12"))
    avoid_loss_min_count_white = int(os.environ.get("BOOK_AVOID_LOSS_MIN_COUNT_WHITE", "3"))
    avoid_loss_min_count_black = int(os.environ.get("BOOK_AVOID_LOSS_MIN_COUNT_BLACK", "2"))
    avoid_loss_min_losses_white = int(os.environ.get("BOOK_AVOID_LOSS_MIN_LOSSES_WHITE", "2"))
    avoid_loss_min_losses_black = int(os.environ.get("BOOK_AVOID_LOSS_MIN_LOSSES_BLACK", "1"))
    avoid_loss_min_rate_white = float(os.environ.get("BOOK_AVOID_LOSS_MIN_RATE_WHITE", "0.40"))
    avoid_loss_min_rate_black = float(os.environ.get("BOOK_AVOID_LOSS_MIN_RATE_BLACK", "0.28"))
    avoid_loss_games = max(20, min(4000, avoid_loss_games))
    avoid_loss_max_ply = max(2, min(40, avoid_loss_max_ply))
    avoid_loss_prefixes_white, avoid_loss_prefixes_black = load_loss_avoid_prefixes(
        max_games=avoid_loss_games,
        max_ply=avoid_loss_max_ply,
        min_count_white=avoid_loss_min_count_white,
        min_count_black=avoid_loss_min_count_black,
        min_losses_white=avoid_loss_min_losses_white,
        min_losses_black=avoid_loss_min_losses_black,
        min_loss_rate_white=avoid_loss_min_rate_white,
        min_loss_rate_black=avoid_loss_min_rate_black,
    )

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

    def choose_clock_pair(go_line: str, stm: str) -> tuple[int | None, int | None]:
        wtime, btime = parse_go_times(go_line)
        if stm == "w":
            return wtime, btime
        return btime, wtime

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

    def parse_go_increments(go_line: str) -> tuple[int | None, int | None]:
        parts = go_line.strip().split()
        winc = None
        binc = None
        for idx, token in enumerate(parts[:-1]):
            if token == "winc":
                try:
                    winc = int(parts[idx + 1])
                except ValueError:
                    pass
            elif token == "binc":
                try:
                    binc = int(parts[idx + 1])
                except ValueError:
                    pass
        return winc, binc

    def increment_for_side(go_line: str, stm: str) -> int | None:
        winc, binc = parse_go_increments(go_line)
        if stm == "w":
            return winc
        return binc

    def is_sudden_death(go_line: str, stm: str) -> bool:
        inc = increment_for_side(go_line, stm)
        # Most 1+0 controllers omit winc/binc entirely instead of sending 0.
        # Treat missing increment as sudden-death to keep anti-flag behavior on.
        return inc is None or inc <= 0

    def is_explicit_no_increment(go_line: str, stm: str) -> bool:
        inc = increment_for_side(go_line, stm)
        return inc is not None and inc <= 0

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
            overhead, slow = critical_overhead, critical_slow
        elif remaining <= panic_time_ms:
            overhead, slow = panic_overhead, panic_slow
        elif remaining <= low_time_ms:
            overhead, slow = low_time_overhead, low_time_slow
        else:
            overhead, slow = move_overhead, slow_mover

        my_time, opp_time = choose_clock_pair(go_line, stm)
        if my_time is None or opp_time is None:
            return overhead, slow

        if is_explicit_no_increment(go_line, stm):
            # Extra caution for sudden-death controls (1+0):
            # convert small remaining-time edges into practical anti-flag behavior.
            if my_time <= 8000:
                overhead = min(5000, overhead + 14)
                slow = max(10, slow - 22)
            elif my_time <= 14000:
                overhead = min(5000, overhead + 8)
                slow = max(10, slow - 12)
        elif is_sudden_death(go_line, stm):
            # If increment is omitted (common in some controllers), apply only a
            # mild safety shift so we avoid over-defensive play in fixed-TC tests.
            if my_time <= 5000:
                overhead = min(5000, overhead + 8)
                slow = max(10, slow - 12)
            elif my_time <= 8500:
                overhead = min(5000, overhead + 4)
                slow = max(10, slow - 6)

        # Clock-aware winrate tuning for 1+0:
        # - When ahead on time, press harder with lower overhead and slower decay.
        # - When behind, spend less time to reduce flag risk.
        if my_time > critical_time_ms + 200:
            if my_time >= opp_time * 2 and my_time >= 18000 and opp_time >= 5000:
                overhead = max(0, overhead - 8)
                slow = min(1000, slow + 18)
            elif my_time >= opp_time + 9000 and my_time >= 14000 and opp_time >= 4500:
                overhead = max(0, overhead - 6)
                slow = min(1000, slow + 12)
            elif my_time * 2 <= opp_time and my_time <= low_time_ms:
                overhead = min(5000, overhead + 12)
                slow = max(10, slow - 16)
            elif my_time + 4000 <= opp_time:
                overhead = min(5000, overhead + 8)
                slow = max(10, slow - 10)

        # Color-aware pressure policy for head-to-head 1+0:
        # White presses a little harder for conversion; Black stays slightly safer.
        if stm == "w":
            if my_time >= 14000 and my_time >= max(6000, opp_time - 1200):
                overhead = max(0, overhead - 3)
                slow = min(1000, slow + 6)
            if my_time >= opp_time + 7000 and my_time >= 18000 and opp_time >= 3500:
                overhead = max(0, overhead - 2)
                slow = min(1000, slow + 5)
        else:
            if my_time <= opp_time + 1000:
                overhead = min(5000, overhead + 2)
                slow = max(10, slow - 3)
            if my_time <= opp_time + 2500 and my_time <= 12000:
                overhead = min(5000, overhead + 2)
                slow = max(10, slow - 3)

        if is_sudden_death(go_line, stm) and board.fullmove_number >= 90:
            if my_time <= 12000:
                overhead = min(5000, overhead + 6)
                slow = max(10, slow - 10)
            if my_time <= 7000:
                overhead = min(5000, overhead + 8)
                slow = max(10, slow - 12)
            if my_time <= 4200:
                overhead = min(5000, overhead + 10)
                slow = max(10, slow - 14)

        return overhead, slow

    def choose_threads_for_level(level: int) -> int:
        if level >= 3:
            return critical_threads
        if level == 2:
            return panic_threads
        if level == 1:
            return low_threads
        return threads

    def material_balance_cp(pos: chess.Board) -> int:
        piece_values = {
            chess.PAWN: 100,
            chess.KNIGHT: 320,
            chess.BISHOP: 330,
            chess.ROOK: 500,
            chess.QUEEN: 900,
        }
        white = 0
        black = 0
        for piece_type, value in piece_values.items():
            white += len(pos.pieces(piece_type, chess.WHITE)) * value
            black += len(pos.pieces(piece_type, chess.BLACK)) * value
        balance = white - black
        return balance if pos.turn == chess.WHITE else -balance

    def move_repeats_threefold(pos: chess.Board, move_uci: str) -> bool:
        try:
            mv = chess.Move.from_uci(move_uci)
        except ValueError:
            return False
        if mv not in pos.legal_moves:
            return False
        pos.push(mv)
        try:
            return pos.is_repetition(3) or pos.can_claim_threefold_repetition()
        finally:
            pos.pop()

    def move_repeats_twofold(pos: chess.Board, move_uci: str) -> bool:
        try:
            mv = chess.Move.from_uci(move_uci)
        except ValueError:
            return False
        if mv not in pos.legal_moves:
            return False
        pos.push(mv)
        try:
            return pos.is_repetition(2)
        finally:
            pos.pop()

    def should_skip_book_repetition(pos: chess.Board, move_uci: str, go_line: str, stm: str) -> bool:
        if not anti_rep_enabled:
            return False
        if stm == "w" and not anti_rep_white:
            return False
        if stm == "b" and not anti_rep_black:
            return False
        if stm == "w" and pos.ply() < anti_rep_min_ply_white:
            return False
        if stm == "b" and pos.ply() < anti_rep_min_ply_black:
            return False
        repeats_threefold = move_repeats_threefold(pos, move_uci)
        if not repeats_threefold:
            if (
                stm == "w"
                and anti_rep_twofold_white
                and anti_rep_min_ply_white <= pos.ply()
                and anti_rep_twofold_min_ply_white <= pos.ply() <= anti_rep_twofold_max_ply_white
                and move_repeats_twofold(pos, move_uci)
            ):
                my_time, opp_time = choose_clock_pair(go_line, stm)
                if my_time is None:
                    return False
                if my_time < anti_rep_twofold_min_time_ms_white:
                    return False
                if opp_time is not None and my_time + anti_rep_twofold_max_clock_deficit_ms_white < opp_time:
                    return False
                material_edge = material_balance_cp(pos)
                eval_edge = False
                with info_lock:
                    if latest_info_mate is not None and latest_info_mate > 0:
                        eval_edge = True
                    elif latest_info_cp is not None and latest_info_cp >= anti_rep_twofold_min_eval_cp_white:
                        eval_edge = True
                return material_edge >= anti_rep_twofold_min_material_cp_white or eval_edge
            return False
        my_time, opp_time = choose_clock_pair(go_line, stm)
        if my_time is None or opp_time is None:
            return False
        if (
            stm == "w"
            and anti_rep_soft_white
            and pos.ply() <= anti_rep_soft_white_max_ply
            and my_time >= anti_rep_soft_white_min_time
            and my_time + anti_rep_soft_white_clock_slack >= opp_time
        ):
            material_ok = material_balance_cp(pos) >= anti_rep_soft_white_min_material_cp
            eval_ok = False
            with info_lock:
                if latest_info_mate is not None:
                    eval_ok = latest_info_mate > 0
                elif latest_info_cp is not None:
                    eval_ok = latest_info_cp >= anti_rep_soft_white_min_eval_cp
            if material_ok and eval_ok:
                return True
        clock_lead_need = anti_rep_clock_lead_ms_white if stm == "w" else anti_rep_clock_lead_ms_black
        if my_time - opp_time < clock_lead_need:
            return False

        material_edge = material_balance_cp(pos)
        material_need = anti_rep_material_cp_white if stm == "w" else anti_rep_material_cp_black
        eval_need = anti_rep_eval_cp_white if stm == "w" else anti_rep_eval_cp_black
        eval_edge = False
        with info_lock:
            if latest_info_mate is not None and latest_info_mate > 0:
                eval_edge = True
            elif latest_info_cp is not None and latest_info_cp >= eval_need:
                eval_edge = True
        return material_edge >= material_need or eval_edge

    def should_avoid_book_at_prefix(pos: chess.Board, go_line: str, stm: str) -> bool:
        prefix = tuple(m.uci() for m in pos.move_stack)
        if pos.turn == chess.WHITE:
            avoid_draw_here = (
                pos.ply() >= avoid_draw_min_ply_white
                and pos.ply() <= avoid_draw_max_ply
                and avoid_draw_white
                and prefix in avoid_draw_prefixes_white
            )
            if avoid_draw_here:
                my_time, opp_time = choose_clock_pair(go_line, stm)
                if my_time is None or opp_time is None:
                    avoid_draw_here = False
                elif my_time < avoid_draw_white_min_time_ms:
                    avoid_draw_here = False
                elif my_time + avoid_draw_white_max_clock_deficit_ms < opp_time:
                    avoid_draw_here = False
            avoid_loss_here = avoid_loss_enable and pos.ply() <= avoid_loss_max_ply and avoid_loss_white and prefix in avoid_loss_prefixes_white
            return avoid_draw_here or avoid_loss_here
        avoid_draw_here = (
            pos.ply() >= avoid_draw_min_ply_black
            and pos.ply() <= avoid_draw_max_ply
            and avoid_draw_black
            and prefix in avoid_draw_prefixes_black
        )
        avoid_loss_here = avoid_loss_enable and pos.ply() <= avoid_loss_max_ply and avoid_loss_black and prefix in avoid_loss_prefixes_black
        return avoid_draw_here or avoid_loss_here

    def anti_rep_searchmoves(
        pos: chess.Board,
        go_line: str,
        stm: str,
        info_cp: int | None,
        info_mate: int | None,
    ) -> list[str] | None:
        if " searchmoves " in f" {go_line.strip()} ":
            return None
        my_time, opp_time = choose_clock_pair(go_line, stm)

        if stm == "w":
            if not anti_rep_search_white or pos.ply() < anti_rep_search_min_ply_white:
                normal_enabled = False
            else:
                normal_enabled = True
            clock_need = anti_rep_search_clock_lead_ms_white
            material_need = anti_rep_search_min_material_cp_white
            eval_need = anti_rep_search_min_eval_cp_white
            force_enabled = anti_rep_search_force_white and pos.ply() >= anti_rep_search_force_min_ply_white
            force_min_time_ms = anti_rep_search_force_min_time_ms_white
            force_max_clock_deficit = anti_rep_search_force_max_clock_deficit_ms_white
            force_material_need = anti_rep_search_force_min_material_cp_white
            force_eval_need = anti_rep_search_force_min_eval_cp_white
            force_min_keep = anti_rep_search_force_min_keep_white
        else:
            if not anti_rep_search_black or pos.ply() < anti_rep_search_min_ply_black:
                normal_enabled = False
            else:
                normal_enabled = True
            clock_need = anti_rep_search_clock_lead_ms_black
            material_need = anti_rep_search_min_material_cp_black
            eval_need = anti_rep_search_min_eval_cp_black
            force_enabled = anti_rep_search_force_black and pos.ply() >= anti_rep_search_force_min_ply_black
            force_min_time_ms = anti_rep_search_force_min_time_ms_black
            force_max_clock_deficit = anti_rep_search_force_max_clock_deficit_ms_black
            force_material_need = anti_rep_search_force_min_material_cp_black
            force_eval_need = anti_rep_search_force_min_eval_cp_black
            force_min_keep = anti_rep_search_force_min_keep_black

        if not normal_enabled and not force_enabled:
            return None

        material_edge = material_balance_cp(pos)
        eval_cp = info_cp
        eval_mate = info_mate

        normal_trigger = False
        if normal_enabled and my_time is not None and opp_time is not None and my_time - opp_time >= clock_need:
            eval_ok = (eval_mate is not None and eval_mate > 0) or (eval_cp is not None and eval_cp >= eval_need)
            normal_trigger = material_edge >= material_need or eval_ok

        force_trigger = False
        if (
            force_enabled
            and my_time is not None
            and my_time >= force_min_time_ms
            and my_time > critical_time_ms
            and (opp_time is None or my_time + force_max_clock_deficit >= opp_time)
        ):
            eval_ok = (eval_mate is not None and eval_mate > 0) or (eval_cp is not None and eval_cp >= force_eval_need)
            force_trigger = material_edge >= force_material_need or eval_ok

        if not normal_trigger and not force_trigger:
            return None

        keep: list[str] = []
        repeat_count = 0
        for mv in pos.legal_moves:
            u = mv.uci()
            if move_repeats_threefold(pos, u):
                repeat_count += 1
            else:
                keep.append(u)
        if repeat_count == 0 or not keep:
            return None
        if force_trigger and len(keep) < force_min_keep:
            return None
        return keep

    def extract_go_prefix(go_line: str) -> str:
        # Preserve optional search constraints (depth/nodes/mate/searchmoves).
        parts = go_line.strip().split()
        if not parts or parts[0] != "go":
            return "go"
        out = ["go"]
        i = 1
        while i < len(parts):
            token = parts[i]
            if token in {"wtime", "btime", "winc", "binc", "movestogo", "movetime", "infinite"}:
                if token == "infinite":
                    out.append(token)
                    i += 1
                else:
                    i += 2
                continue
            out.append(token)
            if token in {"depth", "nodes", "mate"} and i + 1 < len(parts):
                out.append(parts[i + 1])
                i += 2
            elif token == "searchmoves":
                i += 1
                while i < len(parts):
                    out.append(parts[i])
                    i += 1
            else:
                i += 1
        return " ".join(out)

    def emergency_movetime(go_line: str, stm: str) -> int | None:
        remaining = choose_remaining_ms(go_line, stm)
        if remaining is None:
            return None
        my_time, opp_time = choose_clock_pair(go_line, stm)
        if my_time is None:
            return None
        # Hard anti-flag rails for blitz/no-inc:
        # quickly force very short searches when low on clock,
        # especially while behind.
        if is_explicit_no_increment(go_line, stm):
            if remaining <= 700:
                return 7
            if remaining <= 1200:
                return 10
            if remaining <= 1800:
                return 13
            if remaining <= 2800:
                return 17
            if remaining <= 4200:
                return 22
            if remaining <= 6500:
                return 28
            if remaining <= 9000:
                return 36
        elif is_sudden_death(go_line, stm):
            if remaining <= 700:
                return 7
            if remaining <= 1100:
                return 10
            if remaining <= 1700:
                return 13
            if remaining <= 2600:
                return 17
            if remaining <= 3600:
                return 22

        if remaining <= 450:
            return 7
        if remaining <= 750:
            return 9
        if remaining <= 1100:
            return 12
        if remaining <= 1600:
            return 15
        if remaining <= 2200:
            return 18

        if opp_time is not None:
            if my_time <= 2500 and my_time + 3500 <= opp_time:
                return 18
            if my_time <= 3500 and my_time + 5000 <= opp_time:
                return 22

        if is_sudden_death(go_line, stm) and board.fullmove_number >= 100:
            if my_time <= 2500:
                return 12
            if my_time <= 4500:
                return 16
            if my_time <= 7000:
                return 21
            if my_time <= 10000:
                return 27

        if stm == "b" and is_sudden_death(go_line, stm) and board.fullmove_number >= 130:
            if my_time <= 2500:
                return 14
            if my_time <= 4500:
                return 18
            if my_time <= 7000:
                return 23

        return None

    def emergency_thread_cap(go_line: str, stm: str) -> int | None:
        remaining = choose_remaining_ms(go_line, stm)
        if remaining is None:
            return None
        my_time, opp_time = choose_clock_pair(go_line, stm)
        if my_time is None:
            return None
        if is_explicit_no_increment(go_line, stm):
            if my_time <= 4200:
                return 1
            if my_time <= 8000:
                return min(2, panic_threads)
        elif is_sudden_death(go_line, stm):
            if my_time <= 3000:
                return 1
            if my_time <= 5500:
                return min(2, panic_threads)
        if my_time <= 1800:
            return 1
        if my_time <= 3200:
            return min(2, panic_threads)
        if opp_time is not None and my_time <= 3500 and my_time + 4500 <= opp_time:
            return 1
        if stm == "b" and is_sudden_death(go_line, stm) and board.fullmove_number >= 130:
            if my_time <= 3500:
                return 1
            if my_time <= 7000:
                return min(2, panic_threads)
        return None

    for raw in sys.stdin:
        if raw.strip() == "ucinewgame":
            current_level = 0
            board = chess.Board()
        if raw.startswith("position "):
            board = board_from_position(raw, board)
            side_to_move = side_to_move_from_position(raw, side_to_move)
            side_to_move = "w" if board.turn == chess.WHITE else "b"
        if raw.startswith("go ") and options_sent:
            forced_move = forced_legal_move(board)
            if forced_move is not None:
                print(f"bestmove {forced_move}", flush=True)
                continue

            avoid_book_here = should_avoid_book_at_prefix(board, raw, side_to_move)

            prefix_key = tuple(m.uci() for m in board.move_stack)
            if not avoid_book_here:
                empirical_book = empirical_book_white if board.turn == chess.WHITE else empirical_book_black
                empirical = empirical_book.get(prefix_key)
                if empirical is not None:
                    mv = chess.Move.from_uci(empirical)
                    if mv in board.legal_moves and not should_skip_book_repetition(board, empirical, raw, side_to_move):
                        print(f"bestmove {empirical}", flush=True)
                        continue

                empirical_pos_book = empirical_pos_book_white if board.turn == chess.WHITE else empirical_pos_book_black
                empirical_pos = empirical_pos_book.get(board_key(board))
                if empirical_pos is not None:
                    mv = chess.Move.from_uci(empirical_pos)
                    if mv in board.legal_moves and not should_skip_book_repetition(board, empirical_pos, raw, side_to_move):
                        print(f"bestmove {empirical_pos}", flush=True)
                        continue

                book_move = choose_book_move(board)
                if book_move is not None:
                    mv = chess.Move.from_uci(book_move)
                    if mv in board.legal_moves and not should_skip_book_repetition(board, book_move, raw, side_to_move):
                        print(f"bestmove {book_move}", flush=True)
                        continue

            forced_mt = emergency_movetime(raw, side_to_move)
            current_level = choose_level(raw, side_to_move)
            target_threads = choose_threads_for_level(current_level)
            emergency_threads = emergency_thread_cap(raw, side_to_move)
            if emergency_threads is not None:
                target_threads = min(target_threads, emergency_threads)
            apply_threads(target_threads)
            profile_overhead, profile_slow = choose_profile(raw, side_to_move)
            apply_time_profile(profile_overhead, profile_slow)
            with info_lock:
                prior_info_cp = latest_info_cp
                prior_info_mate = latest_info_mate
                latest_info_cp = None
                latest_info_mate = None
            searchmoves = anti_rep_searchmoves(board, raw, side_to_move, prior_info_cp, prior_info_mate)
            if searchmoves is not None:
                go_line = raw.strip()
                proc.stdin.write(f"{go_line} searchmoves {' '.join(searchmoves)}\n")
                proc.stdin.flush()
                continue
            if forced_mt is not None:
                go_prefix = extract_go_prefix(raw)
                proc.stdin.write(f"{go_prefix} movetime {forced_mt}\n")
                proc.stdin.flush()
                continue
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
