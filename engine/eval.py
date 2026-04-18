from __future__ import annotations

from .chess_state import (
    BLACK,
    BISHOP,
    EMPTY,
    KING,
    KNIGHT,
    PAWN,
    PIECE_VALUES,
    QUEEN,
    ROOK,
    WHITE,
    Position,
    piece_color,
    piece_type,
)

# Piece-square tables indexed by square a1=0..h8=63, from White perspective.
PAWN_PST = [
    0, 0, 0, 0, 0, 0, 0, 0,
    5, 10, 10, -20, -20, 10, 10, 5,
    5, -5, -10, 0, 0, -10, -5, 5,
    0, 0, 0, 20, 20, 0, 0, 0,
    5, 5, 10, 25, 25, 10, 5, 5,
    10, 10, 20, 30, 30, 20, 10, 10,
    50, 50, 50, 50, 50, 50, 50, 50,
    0, 0, 0, 0, 0, 0, 0, 0,
]

KNIGHT_PST = [
    -50, -40, -30, -30, -30, -30, -40, -50,
    -40, -20, 0, 0, 0, 0, -20, -40,
    -30, 0, 10, 15, 15, 10, 0, -30,
    -30, 5, 15, 20, 20, 15, 5, -30,
    -30, 0, 15, 20, 20, 15, 0, -30,
    -30, 5, 10, 15, 15, 10, 5, -30,
    -40, -20, 0, 5, 5, 0, -20, -40,
    -50, -40, -30, -30, -30, -30, -40, -50,
]

BISHOP_PST = [
    -20, -10, -10, -10, -10, -10, -10, -20,
    -10, 0, 0, 0, 0, 0, 0, -10,
    -10, 0, 5, 10, 10, 5, 0, -10,
    -10, 5, 5, 10, 10, 5, 5, -10,
    -10, 0, 10, 10, 10, 10, 0, -10,
    -10, 10, 10, 10, 10, 10, 10, -10,
    -10, 5, 0, 0, 0, 0, 5, -10,
    -20, -10, -10, -10, -10, -10, -10, -20,
]

ROOK_PST = [
    0, 0, 0, 0, 0, 0, 0, 0,
    5, 10, 10, 10, 10, 10, 10, 5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    0, 0, 0, 5, 5, 0, 0, 0,
]

QUEEN_PST = [
    -20, -10, -10, -5, -5, -10, -10, -20,
    -10, 0, 0, 0, 0, 0, 0, -10,
    -10, 0, 5, 5, 5, 5, 0, -10,
    -5, 0, 5, 5, 5, 5, 0, -5,
    0, 0, 5, 5, 5, 5, 0, -5,
    -10, 5, 5, 5, 5, 5, 0, -10,
    -10, 0, 5, 0, 0, 0, 0, -10,
    -20, -10, -10, -5, -5, -10, -10, -20,
]

KING_MG_PST = [
    20, 30, 10, 0, 0, 10, 30, 20,
    20, 20, 0, 0, 0, 0, 20, 20,
    -10, -20, -20, -20, -20, -20, -20, -10,
    -20, -30, -30, -40, -40, -30, -30, -20,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
]

KING_EG_PST = [
    -50, -30, -30, -30, -30, -30, -30, -50,
    -30, -30, 0, 0, 0, 0, -30, -30,
    -30, -10, 20, 30, 30, 20, -10, -30,
    -30, -10, 30, 40, 40, 30, -10, -30,
    -30, -10, 30, 40, 40, 30, -10, -30,
    -30, -10, 20, 30, 30, 20, -10, -30,
    -30, -20, -10, 0, 0, -10, -20, -30,
    -50, -40, -30, -20, -20, -30, -40, -50,
]


def mirror_square(sq: int) -> int:
    rank = sq // 8
    file = sq % 8
    return (7 - rank) * 8 + file


def evaluate(position: Position) -> int:
    mg_score = 0
    eg_score = 0
    phase = 0

    pawns_white = [False for _ in range(8)]
    pawns_black = [False for _ in range(8)]

    bishops_white = 0
    bishops_black = 0

    mobility_white = 0
    mobility_black = 0

    rooks_white = 0
    rooks_black = 0

    pawns_by_file_white = [0 for _ in range(8)]
    pawns_by_file_black = [0 for _ in range(8)]

    for sq, p in enumerate(position.board):
        if p == 0:
            continue

        color = piece_color(p)
        ptype = piece_type(p)
        sign = 1 if color == WHITE else -1
        psq = sq if color == WHITE else mirror_square(sq)

        mg = PIECE_VALUES[ptype]
        eg = PIECE_VALUES[ptype]

        if ptype == PAWN:
            mg += PAWN_PST[psq]
            eg += PAWN_PST[psq]
            if color == WHITE:
                pawns_white[sq % 8] = True
                pawns_by_file_white[sq % 8] += 1
            else:
                pawns_black[sq % 8] = True
                pawns_by_file_black[sq % 8] += 1
        elif ptype == KNIGHT:
            mg += KNIGHT_PST[psq]
            eg += KNIGHT_PST[psq]
            phase += 1
        elif ptype == BISHOP:
            mg += BISHOP_PST[psq]
            eg += BISHOP_PST[psq]
            phase += 1
            if color == WHITE:
                bishops_white += 1
            else:
                bishops_black += 1
        elif ptype == ROOK:
            mg += ROOK_PST[psq]
            eg += ROOK_PST[psq]
            phase += 2
            if color == WHITE:
                rooks_white += 1
            else:
                rooks_black += 1
        elif ptype == QUEEN:
            mg += QUEEN_PST[psq]
            eg += QUEEN_PST[psq]
            phase += 4
        elif ptype == KING:
            mg += KING_MG_PST[psq]
            eg += KING_EG_PST[psq]

        mg_score += sign * mg
        eg_score += sign * eg

        # Lightweight mobility by piece reach
        rank = sq // 8
        file = sq % 8
        if ptype == KNIGHT:
            for dr, df in [
                (-2, -1),
                (-2, 1),
                (-1, -2),
                (-1, 2),
                (1, -2),
                (1, 2),
                (2, -1),
                (2, 1),
            ]:
                r, f = rank + dr, file + df
                if not (0 <= r < 8 and 0 <= f < 8):
                    continue
                tp = position.board[r * 8 + f]
                if tp == EMPTY or piece_color(tp) != color:
                    if color == WHITE:
                        mobility_white += 1
                    else:
                        mobility_black += 1
        elif ptype in (BISHOP, ROOK, QUEEN):
            directions = []
            if ptype in (BISHOP, QUEEN):
                directions.extend([(-1, -1), (-1, 1), (1, -1), (1, 1)])
            if ptype in (ROOK, QUEEN):
                directions.extend([(-1, 0), (1, 0), (0, -1), (0, 1)])
            for dr, df in directions:
                r, f = rank + dr, file + df
                while 0 <= r < 8 and 0 <= f < 8:
                    tp = position.board[r * 8 + f]
                    if tp == EMPTY:
                        if color == WHITE:
                            mobility_white += 1
                        else:
                            mobility_black += 1
                    else:
                        if piece_color(tp) != color:
                            if color == WHITE:
                                mobility_white += 1
                            else:
                                mobility_black += 1
                        break
                    r += dr
                    f += df

    # Bishop pair bonus
    if bishops_white >= 2:
        mg_score += 35
        eg_score += 45
    if bishops_black >= 2:
        mg_score -= 35
        eg_score -= 45

    # Simple pawn structure terms
    for file in range(8):
        if pawns_white[file] and ((file > 0 and pawns_white[file - 1]) or (file < 7 and pawns_white[file + 1])):
            mg_score += 5
        elif pawns_white[file]:
            mg_score -= 8

        if pawns_black[file] and ((file > 0 and pawns_black[file - 1]) or (file < 7 and pawns_black[file + 1])):
            mg_score -= 5
        elif pawns_black[file]:
            mg_score += 8

        if pawns_by_file_white[file] > 1:
            mg_score -= 10 * (pawns_by_file_white[file] - 1)
        if pawns_by_file_black[file] > 1:
            mg_score += 10 * (pawns_by_file_black[file] - 1)

        # Rook file bonuses
        if rooks_white > 0:
            if pawns_by_file_white[file] == 0 and pawns_by_file_black[file] == 0:
                mg_score += 8 * rooks_white
            elif pawns_by_file_white[file] == 0:
                mg_score += 4 * rooks_white
        if rooks_black > 0:
            if pawns_by_file_black[file] == 0 and pawns_by_file_white[file] == 0:
                mg_score -= 8 * rooks_black
            elif pawns_by_file_black[file] == 0:
                mg_score -= 4 * rooks_black

    # Passed pawn bonuses
    for sq, p in enumerate(position.board):
        if p == EMPTY or piece_type(p) != PAWN:
            continue
        color = piece_color(p)
        rank = sq // 8
        file = sq % 8
        is_passed = True
        if color == WHITE:
            for r in range(rank + 1, 8):
                for f in range(max(0, file - 1), min(7, file + 1) + 1):
                    tp = position.board[r * 8 + f]
                    if tp != EMPTY and piece_color(tp) == BLACK and piece_type(tp) == PAWN:
                        is_passed = False
                        break
                if not is_passed:
                    break
            if is_passed:
                bonus = 12 + rank * 10
                mg_score += bonus
                eg_score += bonus * 2
        else:
            for r in range(rank - 1, -1, -1):
                for f in range(max(0, file - 1), min(7, file + 1) + 1):
                    tp = position.board[r * 8 + f]
                    if tp != EMPTY and piece_color(tp) == WHITE and piece_type(tp) == PAWN:
                        is_passed = False
                        break
                if not is_passed:
                    break
            if is_passed:
                bonus = 12 + (7 - rank) * 10
                mg_score -= bonus
                eg_score -= bonus * 2

    # Knight outpost bonus (very lightweight): supported by pawn and not attacked by enemy pawn.
    for sq, p in enumerate(position.board):
        if p == EMPTY or piece_type(p) != KNIGHT:
            continue
        color = piece_color(p)
        rank = sq // 8
        file = sq % 8

        if color == WHITE:
            if rank < 3:
                continue
            supported = False
            for df in (-1, 1):
                f = file + df
                r = rank - 1
                if 0 <= f < 8 and 0 <= r < 8:
                    tp = position.board[r * 8 + f]
                    if tp != EMPTY and piece_color(tp) == WHITE and piece_type(tp) == PAWN:
                        supported = True
                        break
            attacked_by_pawn = False
            for df in (-1, 1):
                f = file + df
                for r in range(rank + 1, 8):
                    if 0 <= f < 8:
                        tp = position.board[r * 8 + f]
                        if tp != EMPTY and piece_color(tp) == BLACK:
                            if piece_type(tp) == PAWN:
                                attacked_by_pawn = True
                            break
                if attacked_by_pawn:
                    break
            if supported and not attacked_by_pawn:
                mg_score += 24
                eg_score += 10
        else:
            if rank > 4:
                continue
            supported = False
            for df in (-1, 1):
                f = file + df
                r = rank + 1
                if 0 <= f < 8 and 0 <= r < 8:
                    tp = position.board[r * 8 + f]
                    if tp != EMPTY and piece_color(tp) == BLACK and piece_type(tp) == PAWN:
                        supported = True
                        break
            attacked_by_pawn = False
            for df in (-1, 1):
                f = file + df
                for r in range(rank - 1, -1, -1):
                    if 0 <= f < 8:
                        tp = position.board[r * 8 + f]
                        if tp != EMPTY and piece_color(tp) == WHITE:
                            if piece_type(tp) == PAWN:
                                attacked_by_pawn = True
                            break
                if attacked_by_pawn:
                    break
            if supported and not attacked_by_pawn:
                mg_score -= 24
                eg_score -= 10

    # King shelter (simple): count friendly pawns near king file/rank in middlegame.
    try:
        white_king = position.king_square(WHITE)
        black_king = position.king_square(BLACK)
    except ValueError:
        phase = min(24, phase)
        score = (mg_score * phase + eg_score * (24 - phase)) // 24
        return score if position.side_to_move == WHITE else -score
    wk_rank = white_king // 8
    wk_file = white_king % 8
    bk_rank = black_king // 8
    bk_file = black_king % 8

    white_shelter = 0
    black_shelter = 0
    for df in (-1, 0, 1):
        f = wk_file + df
        if 0 <= f < 8:
            for dr in (1, 2):
                r = wk_rank + dr
                if 0 <= r < 8:
                    tp = position.board[r * 8 + f]
                    if tp != EMPTY and piece_color(tp) == WHITE and piece_type(tp) == PAWN:
                        white_shelter += 1
        f = bk_file + df
        if 0 <= f < 8:
            for dr in (-1, -2):
                r = bk_rank + dr
                if 0 <= r < 8:
                    tp = position.board[r * 8 + f]
                    if tp != EMPTY and piece_color(tp) == BLACK and piece_type(tp) == PAWN:
                        black_shelter += 1

    mg_score += (white_shelter - black_shelter) * 9

    mg_score += (mobility_white - mobility_black) * 2
    eg_score += (mobility_white - mobility_black)

    phase = min(24, phase)
    score = (mg_score * phase + eg_score * (24 - phase)) // 24

    return score if position.side_to_move == WHITE else -score
