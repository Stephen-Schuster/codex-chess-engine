from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .chess_state import (
    EMPTY,
    KING,
    PAWN,
    Position,
    Move,
    piece_type,
)
from .eval import evaluate

MATE_SCORE = 100000
INFINITY = 1_000_000
MAX_PLY = 256


@dataclass
class SearchLimits:
    depth: int = 0
    movetime_ms: int = 0
    wtime_ms: int = 0
    btime_ms: int = 0
    winc_ms: int = 0
    binc_ms: int = 0
    movestogo: int = 0
    nodes: int = 0
    infinite: bool = False


@dataclass
class TTEntry:
    depth: int
    score: int
    flag: int
    move: Optional[Move]


TT_EXACT = 0
TT_ALPHA = 1
TT_BETA = 2


class Searcher:
    def __init__(self) -> None:
        self.nodes = 0
        self.start_time = 0.0
        self.stop_time = 0.0
        self.stop = False
        self.node_limit = 0
        self.print_info = True
        self.tt: Dict[int, TTEntry] = {}
        self.max_tt_size = 1_000_000
        self.killers: List[List[Optional[Move]]] = [[None, None] for _ in range(MAX_PLY)]
        self.history = [[0 for _ in range(64)] for _ in range(64)]
        self.pv_table: List[List[Optional[Move]]] = [[None for _ in range(MAX_PLY)] for _ in range(MAX_PLY)]
        self.pv_length: List[int] = [0 for _ in range(MAX_PLY)]

    def clear(self) -> None:
        self.tt.clear()
        self.killers = [[None, None] for _ in range(MAX_PLY)]
        self.history = [[0 for _ in range(64)] for _ in range(64)]

    def should_stop(self) -> bool:
        if self.stop:
            return True
        if self.node_limit > 0 and self.nodes >= self.node_limit:
            self.stop = True
            return True
        if self.stop_time and time.time() >= self.stop_time:
            self.stop = True
            return True
        return False

    def allocate_time_ms(self, position: Position, limits: SearchLimits) -> int:
        if limits.movetime_ms > 0:
            return max(10, limits.movetime_ms)
        if limits.infinite:
            return 0
        if limits.depth > 0 and limits.wtime_ms == 0 and limits.btime_ms == 0 and limits.nodes == 0:
            return 0

        remaining = limits.wtime_ms if position.side_to_move == 0 else limits.btime_ms
        inc = limits.winc_ms if position.side_to_move == 0 else limits.binc_ms
        if remaining <= 0:
            return 100

        moves_left = limits.movestogo if limits.movestogo > 0 else 30
        base = remaining // moves_left
        budget = base + (inc // 2)
        budget = max(20, min(budget, remaining // 2))
        return budget

    def search(self, position: Position, limits: SearchLimits) -> Tuple[Optional[Move], int, int]:
        self.nodes = 0
        self.stop = False
        self.start_time = time.time()

        time_ms = self.allocate_time_ms(position, limits)
        self.stop_time = 0.0 if time_ms == 0 else (self.start_time + time_ms / 1000.0)
        self.node_limit = limits.nodes

        max_depth = limits.depth if limits.depth > 0 else 64
        best_move: Optional[Move] = None
        best_score = -INFINITY
        fallback_moves = position.generate_legal_moves()
        if not fallback_moves:
            return None, 0, 1

        prev_score = 0

        for depth in range(1, max_depth + 1):
            if self.should_stop():
                break

            alpha = -INFINITY
            beta = INFINITY
            aspiration = 35

            if depth >= 4:
                alpha = prev_score - aspiration
                beta = prev_score + aspiration

            while True:
                score = self.alphabeta(position, depth, alpha, beta, 0, True)
                if self.should_stop():
                    break

                if score <= alpha:
                    alpha -= aspiration
                    aspiration *= 2
                    continue
                if score >= beta:
                    beta += aspiration
                    aspiration *= 2
                    continue
                break

            if self.should_stop():
                break

            prev_score = score
            best_score = score
            best_move = self.pv_table[0][0]

            elapsed_ms = max(1, int((time.time() - self.start_time) * 1000))
            nps = int(self.nodes * 1000 / elapsed_ms)
            pv_moves = []
            for i in range(self.pv_length[0]):
                mv = self.pv_table[0][i]
                if mv is None:
                    break
                pv_moves.append(mv.to_uci())
            pv = " ".join(pv_moves)
            if self.print_info:
                print(
                    f"info depth {depth} score cp {best_score} nodes {self.nodes} nps {nps} time {elapsed_ms} pv {pv}",
                    flush=True,
                )

            if abs(best_score) > MATE_SCORE - 1000:
                break

        elapsed = max(1, int((time.time() - self.start_time) * 1000))
        if best_move is None:
            best_move = fallback_moves[0]
        return best_move, best_score, elapsed

    def score_move(self, position: Position, move: Move, ply: int, tt_move: Optional[Move]) -> int:
        if tt_move and move == tt_move:
            return 2_000_000

        score = 0
        if move.is_capture:
            victim = position.board[move.to_sq]
            if move.is_en_passant:
                victim_value = 100
            else:
                victim_value = 0 if victim == EMPTY else evaluate_capture_value(piece_type(victim))
            attacker_value = evaluate_capture_value(piece_type(position.board[move.from_sq]))
            score = 1_000_000 + 10 * victim_value - attacker_value
        else:
            k0, k1 = self.killers[ply]
            if k0 and move == k0:
                score = 900_000
            elif k1 and move == k1:
                score = 800_000
            else:
                score = self.history[move.from_sq][move.to_sq]

        if move.promotion:
            score += 50_000 + evaluate_capture_value(move.promotion)

        return score

    def ordered_moves(self, position: Position, moves: List[Move], ply: int, tt_move: Optional[Move]) -> List[Move]:
        return sorted(moves, key=lambda m: self.score_move(position, m, ply, tt_move), reverse=True)

    def store_tt(self, key: int, depth: int, score: int, flag: int, move: Optional[Move]) -> None:
        if len(self.tt) >= self.max_tt_size and key not in self.tt:
            # Simple replacement strategy: clear table on overflow
            self.tt.clear()
        self.tt[key] = TTEntry(depth=depth, score=score, flag=flag, move=move)

    def quiescence(self, position: Position, alpha: int, beta: int, ply: int) -> int:
        if ply >= MAX_PLY - 1:
            return evaluate(position)
        if self.should_stop():
            return 0

        self.nodes += 1
        in_check = position.in_check(position.side_to_move)
        if in_check:
            stand_pat = -INFINITY
        else:
            stand_pat = evaluate(position)
            if stand_pat >= beta:
                return beta
            if stand_pat > alpha:
                alpha = stand_pat

        if in_check:
            moves = position.generate_legal_moves()
        else:
            moves = [m for m in position.generate_pseudo_legal_moves() if m.is_capture or m.promotion]
            moves = self.ordered_moves(position, moves, ply, None)

        for move in moves:
            if not in_check and move.is_capture and not move.promotion:
                victim = position.board[move.to_sq]
                victim_value = 100 if move.is_en_passant else (0 if victim == EMPTY else evaluate_capture_value(piece_type(victim)))
                if stand_pat + victim_value + 90 < alpha:
                    continue

            undo = position.make_move(move)
            if position.in_check(1 - position.side_to_move):
                position.unmake_move(move, undo)
                continue

            score = -self.quiescence(position, -beta, -alpha, ply + 1)
            position.unmake_move(move, undo)

            if self.should_stop():
                return 0

            if score >= beta:
                return beta
            if score > alpha:
                alpha = score

        return alpha

    def alphabeta(self, position: Position, depth: int, alpha: int, beta: int, ply: int, allow_null: bool) -> int:
        if ply >= MAX_PLY - 1:
            return evaluate(position)
        self.pv_length[ply] = ply
        if self.should_stop():
            return 0

        if depth <= 0:
            return self.quiescence(position, alpha, beta, ply)

        self.nodes += 1
        in_check = position.in_check(position.side_to_move)
        if in_check:
            depth += 1

        if ply > 0:
            if position.halfmove_clock >= 100:
                return 0
            if position.is_threefold_repetition():
                return 0

        static_eval = evaluate(position)

        tt_entry = self.tt.get(position.zobrist_key)
        tt_move: Optional[Move] = None
        if tt_entry:
            tt_move = tt_entry.move
            if ply > 0 and tt_entry.depth >= depth:
                if tt_entry.flag == TT_EXACT:
                    return tt_entry.score
                if tt_entry.flag == TT_ALPHA and tt_entry.score <= alpha:
                    return tt_entry.score
                if tt_entry.flag == TT_BETA and tt_entry.score >= beta:
                    return tt_entry.score

        # Null move pruning
        if allow_null and depth >= 3 and not in_check and static_eval >= beta - 75:
            has_non_pawn = any(
                p != 0 and (p > 0) == (position.side_to_move == 0) and piece_type(p) not in (PAWN, KING)
                for p in position.board
            )
            if has_non_pawn:
                saved_ep = position.en_passant
                saved_side = position.side_to_move
                saved_key = position.zobrist_key
                position.side_to_move = 1 - position.side_to_move
                position.en_passant = -1
                position.zobrist_key = position.compute_zobrist()
                score = -self.alphabeta(position, depth - 1 - 2, -beta, -beta + 1, ply + 1, False)
                position.side_to_move = saved_side
                position.en_passant = saved_ep
                position.zobrist_key = saved_key
                if self.should_stop():
                    return 0
                if score >= beta:
                    return beta

        # Reverse futility pruning in quiet positions
        if depth <= 3 and not in_check and static_eval - 90 * depth >= beta:
            return static_eval

        if depth <= 2 and not in_check and static_eval + 80 * depth <= alpha:
            return static_eval

        legal_moves = position.generate_legal_moves()
        if not legal_moves:
            if in_check:
                return -MATE_SCORE + ply
            return 0

        ordered = self.ordered_moves(position, legal_moves, ply, tt_move)

        orig_alpha = alpha
        best_move = None
        best_score = -INFINITY

        move_count = 0
        for move in ordered:
            move_count += 1
            undo = position.make_move(move)

            if position.in_check(1 - position.side_to_move):
                position.unmake_move(move, undo)
                continue

            extension = 0
            # Simple check extension for forcing lines
            if depth >= 3 and position.in_check(position.side_to_move) and ply < MAX_PLY - 4:
                extension = 1

            reduction = 0
            if move_count > 4 and depth >= 3 and not in_check and not move.is_capture and not move.promotion and extension == 0:
                reduction = 1

            if move_count > 10 and depth <= 3 and not in_check and not move.is_capture and not move.promotion:
                position.unmake_move(move, undo)
                continue

            if move_count == 1:
                score = -self.alphabeta(position, depth - 1 + extension, -beta, -alpha, ply + 1, True)
            else:
                score = -self.alphabeta(position, depth - 1 - reduction + extension, -alpha - 1, -alpha, ply + 1, True)
                if score > alpha and score < beta:
                    score = -self.alphabeta(position, depth - 1 + extension, -beta, -alpha, ply + 1, True)

            position.unmake_move(move, undo)

            if self.should_stop():
                return 0

            if score > best_score:
                best_score = score
                best_move = move

            if score > alpha:
                alpha = score
                self.pv_table[ply][ply] = move
                for next_ply in range(ply + 1, self.pv_length[ply + 1]):
                    self.pv_table[ply][next_ply] = self.pv_table[ply + 1][next_ply]
                self.pv_length[ply] = self.pv_length[ply + 1]

            if alpha >= beta:
                if not move.is_capture:
                    k0, k1 = self.killers[ply]
                    if k0 != move:
                        self.killers[ply][1] = k0
                        self.killers[ply][0] = move
                    self.history[move.from_sq][move.to_sq] += depth * depth
                self.store_tt(position.zobrist_key, depth, beta, TT_BETA, move)
                return beta

        flag = TT_EXACT
        if best_score <= orig_alpha:
            flag = TT_ALPHA
        elif best_score >= beta:
            flag = TT_BETA
        self.store_tt(position.zobrist_key, depth, best_score, flag, best_move)
        return best_score


def evaluate_capture_value(ptype: int) -> int:
    if ptype == PAWN:
        return 100
    if ptype == 2:
        return 320
    if ptype == 3:
        return 330
    if ptype == 4:
        return 500
    if ptype == 5:
        return 900
    if ptype == KING:
        return 20000
    return 0
