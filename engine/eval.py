from __future__ import annotations

from .chess_state import (
    BLACK,
    BISHOP,
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
            else:
                pawns_black[sq % 8] = True
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
        elif ptype == QUEEN:
            mg += QUEEN_PST[psq]
            eg += QUEEN_PST[psq]
            phase += 4
        elif ptype == KING:
            mg += KING_MG_PST[psq]
            eg += KING_EG_PST[psq]

        mg_score += sign * mg
        eg_score += sign * eg

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

    phase = min(24, phase)
    score = (mg_score * phase + eg_score * (24 - phase)) // 24

    return score if position.side_to_move == WHITE else -score
