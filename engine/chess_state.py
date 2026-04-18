from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

WHITE = 0
BLACK = 1

PAWN = 1
KNIGHT = 2
BISHOP = 3
ROOK = 4
QUEEN = 5
KING = 6

EMPTY = 0

PIECE_VALUES = {
    PAWN: 100,
    KNIGHT: 320,
    BISHOP: 330,
    ROOK: 500,
    QUEEN: 900,
    KING: 20000,
}

PIECE_TO_CHAR = {
    PAWN: "p",
    KNIGHT: "n",
    BISHOP: "b",
    ROOK: "r",
    QUEEN: "q",
    KING: "k",
}


def encode_piece(color: int, piece_type: int) -> int:
    sign = 1 if color == WHITE else -1
    return sign * piece_type


def piece_color(piece: int) -> Optional[int]:
    if piece == EMPTY:
        return None
    return WHITE if piece > 0 else BLACK


def piece_type(piece: int) -> int:
    return abs(piece)


def square_to_index(square: str) -> int:
    file = ord(square[0]) - ord("a")
    rank = ord(square[1]) - ord("1")
    return rank * 8 + file


def index_to_square(index: int) -> str:
    file = index % 8
    rank = index // 8
    return f"{chr(ord('a') + file)}{chr(ord('1') + rank)}"


@dataclass(frozen=True)
class Move:
    from_sq: int
    to_sq: int
    promotion: int = EMPTY
    is_capture: bool = False
    is_en_passant: bool = False
    is_castle: bool = False

    def to_uci(self) -> str:
        uci = index_to_square(self.from_sq) + index_to_square(self.to_sq)
        if self.promotion:
            uci += PIECE_TO_CHAR[self.promotion]
        return uci


@dataclass
class UndoState:
    captured: int
    castling_rights: int
    en_passant: int
    halfmove_clock: int
    fullmove_number: int
    zobrist_key: int


class Zobrist:
    def __init__(self) -> None:
        # Deterministic pseudo-random values using xorshift-like generation
        self.piece = [[[0 for _ in range(64)] for _ in range(6)] for _ in range(2)]
        self.castling = [0 for _ in range(16)]
        self.en_passant = [0 for _ in range(9)]
        self.side = 0

        seed = 0x9E3779B97F4A7C15
        values: List[int] = []
        needed = 2 * 6 * 64 + 16 + 9 + 1
        for _ in range(needed):
            seed ^= (seed << 7) & 0xFFFFFFFFFFFFFFFF
            seed ^= (seed >> 9)
            seed ^= (seed << 8) & 0xFFFFFFFFFFFFFFFF
            values.append(seed & 0xFFFFFFFFFFFFFFFF)

        idx = 0
        for color in range(2):
            for p in range(6):
                for sq in range(64):
                    self.piece[color][p][sq] = values[idx]
                    idx += 1
        for i in range(16):
            self.castling[i] = values[idx]
            idx += 1
        for i in range(9):
            self.en_passant[i] = values[idx]
            idx += 1
        self.side = values[idx]


ZOBRIST = Zobrist()


class Position:
    START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

    # Castling bit mask: WK=1, WQ=2, BK=4, BQ=8
    WK = 1
    WQ = 2
    BK = 4
    BQ = 8

    def __init__(self) -> None:
        self.board: List[int] = [EMPTY for _ in range(64)]
        self.side_to_move: int = WHITE
        self.castling_rights: int = 0
        self.en_passant: int = -1
        self.halfmove_clock: int = 0
        self.fullmove_number: int = 1
        self.zobrist_key: int = 0
        self.key_history: List[int] = []

    def copy(self) -> "Position":
        pos = Position()
        pos.board = self.board.copy()
        pos.side_to_move = self.side_to_move
        pos.castling_rights = self.castling_rights
        pos.en_passant = self.en_passant
        pos.halfmove_clock = self.halfmove_clock
        pos.fullmove_number = self.fullmove_number
        pos.zobrist_key = self.zobrist_key
        pos.key_history = self.key_history.copy()
        return pos

    @staticmethod
    def from_fen(fen: str) -> "Position":
        pos = Position()
        fields = fen.split()
        if len(fields) != 6:
            raise ValueError(f"invalid FEN: {fen}")

        ranks = fields[0].split("/")
        if len(ranks) != 8:
            raise ValueError(f"invalid board in FEN: {fen}")

        for rank_idx, rank_data in enumerate(ranks):
            file_idx = 0
            for ch in rank_data:
                if ch.isdigit():
                    file_idx += int(ch)
                    continue

                color = WHITE if ch.isupper() else BLACK
                pch = ch.lower()
                ptype = {
                    "p": PAWN,
                    "n": KNIGHT,
                    "b": BISHOP,
                    "r": ROOK,
                    "q": QUEEN,
                    "k": KING,
                }.get(pch)
                if ptype is None:
                    raise ValueError(f"invalid piece in FEN: {ch}")

                sq = (7 - rank_idx) * 8 + file_idx
                pos.board[sq] = encode_piece(color, ptype)
                file_idx += 1

            if file_idx != 8:
                raise ValueError(f"invalid rank in FEN: {rank_data}")

        pos.side_to_move = WHITE if fields[1] == "w" else BLACK

        castling = fields[2]
        rights = 0
        if castling != "-":
            if "K" in castling:
                rights |= Position.WK
            if "Q" in castling:
                rights |= Position.WQ
            if "k" in castling:
                rights |= Position.BK
            if "q" in castling:
                rights |= Position.BQ
        pos.castling_rights = rights

        pos.en_passant = -1 if fields[3] == "-" else square_to_index(fields[3])
        pos.halfmove_clock = int(fields[4])
        pos.fullmove_number = int(fields[5])
        pos.zobrist_key = pos.compute_zobrist()
        pos.key_history = [pos.zobrist_key]
        return pos

    def to_fen(self) -> str:
        rank_parts = []
        for rank in range(7, -1, -1):
            empties = 0
            out = ""
            for file in range(8):
                sq = rank * 8 + file
                p = self.board[sq]
                if p == EMPTY:
                    empties += 1
                    continue

                if empties:
                    out += str(empties)
                    empties = 0

                ch = PIECE_TO_CHAR[piece_type(p)]
                if piece_color(p) == WHITE:
                    ch = ch.upper()
                out += ch

            if empties:
                out += str(empties)
            rank_parts.append(out)

        board_fen = "/".join(rank_parts)
        side = "w" if self.side_to_move == WHITE else "b"
        castling = ""
        castling += "K" if self.castling_rights & Position.WK else ""
        castling += "Q" if self.castling_rights & Position.WQ else ""
        castling += "k" if self.castling_rights & Position.BK else ""
        castling += "q" if self.castling_rights & Position.BQ else ""
        if not castling:
            castling = "-"

        ep = "-" if self.en_passant == -1 else index_to_square(self.en_passant)

        return f"{board_fen} {side} {castling} {ep} {self.halfmove_clock} {self.fullmove_number}"

    def compute_zobrist(self) -> int:
        key = 0
        for sq, p in enumerate(self.board):
            if p == EMPTY:
                continue
            color = piece_color(p)
            ptype = piece_type(p)
            key ^= ZOBRIST.piece[color][ptype - 1][sq]

        key ^= ZOBRIST.castling[self.castling_rights]
        ep_file = 8 if self.en_passant == -1 else (self.en_passant % 8)
        key ^= ZOBRIST.en_passant[ep_file]
        if self.side_to_move == BLACK:
            key ^= ZOBRIST.side
        return key

    def king_square(self, color: int) -> int:
        target = encode_piece(color, KING)
        for sq, p in enumerate(self.board):
            if p == target:
                return sq
        raise ValueError("king not found")

    def is_square_attacked(self, sq: int, by_color: int) -> bool:
        rank = sq // 8
        file = sq % 8

        # Pawn attacks
        pawn = encode_piece(by_color, PAWN)
        if by_color == WHITE:
            for dr, df in [(-1, -1), (-1, 1)]:
                r, f = rank + dr, file + df
                if 0 <= r < 8 and 0 <= f < 8 and self.board[r * 8 + f] == pawn:
                    return True
        else:
            for dr, df in [(1, -1), (1, 1)]:
                r, f = rank + dr, file + df
                if 0 <= r < 8 and 0 <= f < 8 and self.board[r * 8 + f] == pawn:
                    return True

        # Knight attacks
        knight = encode_piece(by_color, KNIGHT)
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
            if 0 <= r < 8 and 0 <= f < 8 and self.board[r * 8 + f] == knight:
                return True

        # King attacks
        king = encode_piece(by_color, KING)
        for dr in (-1, 0, 1):
            for df in (-1, 0, 1):
                if dr == 0 and df == 0:
                    continue
                r, f = rank + dr, file + df
                if 0 <= r < 8 and 0 <= f < 8 and self.board[r * 8 + f] == king:
                    return True

        # Sliding attacks
        bishop = encode_piece(by_color, BISHOP)
        rook = encode_piece(by_color, ROOK)
        queen = encode_piece(by_color, QUEEN)

        for dr, df in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
            r, f = rank + dr, file + df
            while 0 <= r < 8 and 0 <= f < 8:
                p = self.board[r * 8 + f]
                if p != EMPTY:
                    if p in (bishop, queen):
                        return True
                    break
                r += dr
                f += df

        for dr, df in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            r, f = rank + dr, file + df
            while 0 <= r < 8 and 0 <= f < 8:
                p = self.board[r * 8 + f]
                if p != EMPTY:
                    if p in (rook, queen):
                        return True
                    break
                r += dr
                f += df

        return False

    def in_check(self, color: int) -> bool:
        king_sq = self.king_square(color)
        return self.is_square_attacked(king_sq, 1 - color)

    def generate_pseudo_legal_moves(self) -> Iterable[Move]:
        side = self.side_to_move
        forward = 1 if side == WHITE else -1
        start_rank = 1 if side == WHITE else 6
        promotion_rank = 7 if side == WHITE else 0

        for sq, p in enumerate(self.board):
            if p == EMPTY or piece_color(p) != side:
                continue

            ptype = piece_type(p)
            rank = sq // 8
            file = sq % 8

            if ptype == PAWN:
                one_rank = rank + forward
                if 0 <= one_rank < 8:
                    one_sq = one_rank * 8 + file
                    if self.board[one_sq] == EMPTY:
                        if one_rank == promotion_rank:
                            for promo in (QUEEN, ROOK, BISHOP, KNIGHT):
                                yield Move(sq, one_sq, promotion=promo)
                        else:
                            yield Move(sq, one_sq)
                            if rank == start_rank:
                                two_rank = rank + 2 * forward
                                two_sq = two_rank * 8 + file
                                if self.board[two_sq] == EMPTY:
                                    yield Move(sq, two_sq)

                for df in (-1, 1):
                    cf = file + df
                    cr = rank + forward
                    if not (0 <= cf < 8 and 0 <= cr < 8):
                        continue
                    tsq = cr * 8 + cf
                    tp = self.board[tsq]
                    if tp != EMPTY and piece_color(tp) != side:
                        if cr == promotion_rank:
                            for promo in (QUEEN, ROOK, BISHOP, KNIGHT):
                                yield Move(sq, tsq, promotion=promo, is_capture=True)
                        else:
                            yield Move(sq, tsq, is_capture=True)
                    elif tsq == self.en_passant:
                        yield Move(sq, tsq, is_capture=True, is_en_passant=True)

            elif ptype == KNIGHT:
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
                    tsq = r * 8 + f
                    tp = self.board[tsq]
                    if tp == EMPTY:
                        yield Move(sq, tsq)
                    elif piece_color(tp) != side:
                        yield Move(sq, tsq, is_capture=True)

            elif ptype in (BISHOP, ROOK, QUEEN):
                directions = []
                if ptype in (BISHOP, QUEEN):
                    directions.extend([(-1, -1), (-1, 1), (1, -1), (1, 1)])
                if ptype in (ROOK, QUEEN):
                    directions.extend([(-1, 0), (1, 0), (0, -1), (0, 1)])

                for dr, df in directions:
                    r, f = rank + dr, file + df
                    while 0 <= r < 8 and 0 <= f < 8:
                        tsq = r * 8 + f
                        tp = self.board[tsq]
                        if tp == EMPTY:
                            yield Move(sq, tsq)
                        else:
                            if piece_color(tp) != side:
                                yield Move(sq, tsq, is_capture=True)
                            break
                        r += dr
                        f += df

            elif ptype == KING:
                for dr in (-1, 0, 1):
                    for df in (-1, 0, 1):
                        if dr == 0 and df == 0:
                            continue
                        r, f = rank + dr, file + df
                        if not (0 <= r < 8 and 0 <= f < 8):
                            continue
                        tsq = r * 8 + f
                        tp = self.board[tsq]
                        if tp == EMPTY:
                            yield Move(sq, tsq)
                        elif piece_color(tp) != side:
                            yield Move(sq, tsq, is_capture=True)

                # Castling
                if side == WHITE and sq == 4:
                    if self.castling_rights & Position.WK:
                        if self.board[5] == EMPTY and self.board[6] == EMPTY:
                            if not self.is_square_attacked(4, BLACK) and not self.is_square_attacked(5, BLACK) and not self.is_square_attacked(6, BLACK):
                                yield Move(4, 6, is_castle=True)
                    if self.castling_rights & Position.WQ:
                        if self.board[1] == EMPTY and self.board[2] == EMPTY and self.board[3] == EMPTY:
                            if not self.is_square_attacked(4, BLACK) and not self.is_square_attacked(3, BLACK) and not self.is_square_attacked(2, BLACK):
                                yield Move(4, 2, is_castle=True)
                elif side == BLACK and sq == 60:
                    if self.castling_rights & Position.BK:
                        if self.board[61] == EMPTY and self.board[62] == EMPTY:
                            if not self.is_square_attacked(60, WHITE) and not self.is_square_attacked(61, WHITE) and not self.is_square_attacked(62, WHITE):
                                yield Move(60, 62, is_castle=True)
                    if self.castling_rights & Position.BQ:
                        if self.board[57] == EMPTY and self.board[58] == EMPTY and self.board[59] == EMPTY:
                            if not self.is_square_attacked(60, WHITE) and not self.is_square_attacked(59, WHITE) and not self.is_square_attacked(58, WHITE):
                                yield Move(60, 58, is_castle=True)

    def generate_legal_moves(self) -> List[Move]:
        legal: List[Move] = []
        for move in self.generate_pseudo_legal_moves():
            undo = self.make_move(move)
            if not self.in_check(1 - self.side_to_move):
                legal.append(move)
            self.unmake_move(move, undo)
        return legal

    def make_move(self, move: Move) -> UndoState:
        moving_piece = self.board[move.from_sq]
        captured_piece = self.board[move.to_sq]
        side = self.side_to_move

        undo = UndoState(
            captured=captured_piece,
            castling_rights=self.castling_rights,
            en_passant=self.en_passant,
            halfmove_clock=self.halfmove_clock,
            fullmove_number=self.fullmove_number,
            zobrist_key=self.zobrist_key,
        )

        self.en_passant = -1

        moved_type = piece_type(moving_piece)
        if moved_type == PAWN or captured_piece != EMPTY or move.is_en_passant:
            self.halfmove_clock = 0
        else:
            self.halfmove_clock += 1

        # Remove moving piece from source
        self.board[move.from_sq] = EMPTY

        # Handle en passant capture
        if move.is_en_passant:
            if side == WHITE:
                cap_sq = move.to_sq - 8
            else:
                cap_sq = move.to_sq + 8
            undo.captured = self.board[cap_sq]
            self.board[cap_sq] = EMPTY

        # Handle castling rook movement
        if move.is_castle and moved_type == KING:
            if move.to_sq == 6:  # white king side
                self.board[5] = self.board[7]
                self.board[7] = EMPTY
            elif move.to_sq == 2:  # white queen side
                self.board[3] = self.board[0]
                self.board[0] = EMPTY
            elif move.to_sq == 62:  # black king side
                self.board[61] = self.board[63]
                self.board[63] = EMPTY
            elif move.to_sq == 58:  # black queen side
                self.board[59] = self.board[56]
                self.board[56] = EMPTY

        # Promotion or regular placement
        if move.promotion:
            self.board[move.to_sq] = encode_piece(side, move.promotion)
        else:
            self.board[move.to_sq] = moving_piece

        # Update castling rights due to king/rook moves
        if moving_piece == encode_piece(WHITE, KING):
            self.castling_rights &= ~(Position.WK | Position.WQ)
        elif moving_piece == encode_piece(BLACK, KING):
            self.castling_rights &= ~(Position.BK | Position.BQ)
        elif moving_piece == encode_piece(WHITE, ROOK):
            if move.from_sq == 0:
                self.castling_rights &= ~Position.WQ
            elif move.from_sq == 7:
                self.castling_rights &= ~Position.WK
        elif moving_piece == encode_piece(BLACK, ROOK):
            if move.from_sq == 56:
                self.castling_rights &= ~Position.BQ
            elif move.from_sq == 63:
                self.castling_rights &= ~Position.BK

        # Update castling rights due to rook capture
        if undo.captured == encode_piece(WHITE, ROOK):
            if move.to_sq == 0:
                self.castling_rights &= ~Position.WQ
            elif move.to_sq == 7:
                self.castling_rights &= ~Position.WK
        elif undo.captured == encode_piece(BLACK, ROOK):
            if move.to_sq == 56:
                self.castling_rights &= ~Position.BQ
            elif move.to_sq == 63:
                self.castling_rights &= ~Position.BK

        # Set en passant target on double pawn push
        if moved_type == PAWN:
            delta = move.to_sq - move.from_sq
            if delta == 16 or delta == -16:
                self.en_passant = (move.from_sq + move.to_sq) // 2

        self.side_to_move = 1 - self.side_to_move
        if self.side_to_move == WHITE:
            self.fullmove_number += 1

        self.zobrist_key = self.compute_zobrist()
        self.key_history.append(self.zobrist_key)
        return undo

    def unmake_move(self, move: Move, undo: UndoState) -> None:
        self.side_to_move = 1 - self.side_to_move
        self.castling_rights = undo.castling_rights
        self.en_passant = undo.en_passant
        self.halfmove_clock = undo.halfmove_clock
        self.fullmove_number = undo.fullmove_number

        moving_piece = self.board[move.to_sq]
        side = self.side_to_move

        if move.promotion:
            moving_piece = encode_piece(side, PAWN)

        self.board[move.from_sq] = moving_piece

        if move.is_en_passant:
            self.board[move.to_sq] = EMPTY
            if side == WHITE:
                self.board[move.to_sq - 8] = undo.captured
            else:
                self.board[move.to_sq + 8] = undo.captured
        else:
            self.board[move.to_sq] = undo.captured

        if move.is_castle and piece_type(moving_piece) == KING:
            if move.to_sq == 6:
                self.board[7] = self.board[5]
                self.board[5] = EMPTY
            elif move.to_sq == 2:
                self.board[0] = self.board[3]
                self.board[3] = EMPTY
            elif move.to_sq == 62:
                self.board[63] = self.board[61]
                self.board[61] = EMPTY
            elif move.to_sq == 58:
                self.board[56] = self.board[59]
                self.board[59] = EMPTY

        self.zobrist_key = undo.zobrist_key
        if self.key_history:
            self.key_history.pop()

    def is_threefold_repetition(self) -> bool:
        if len(self.key_history) < 3:
            return False

        current = self.zobrist_key
        count = 0
        max_back = min(self.halfmove_clock + 1, len(self.key_history) - 1)
        idx = len(self.key_history) - 3
        scanned = 0
        while idx >= 0 and scanned < max_back:
            if self.key_history[idx] == current:
                count += 1
                if count >= 2:
                    return True
            idx -= 2
            scanned += 2
        return False

    def parse_uci_move(self, uci: str) -> Optional[Move]:
        if len(uci) < 4:
            return None
        from_sq = square_to_index(uci[:2])
        to_sq = square_to_index(uci[2:4])
        promotion = EMPTY
        if len(uci) == 5:
            promo_ch = uci[4].lower()
            promotion = {
                "q": QUEEN,
                "r": ROOK,
                "b": BISHOP,
                "n": KNIGHT,
            }.get(promo_ch, EMPTY)

        for move in self.generate_legal_moves():
            if move.from_sq == from_sq and move.to_sq == to_sq:
                if (move.promotion or EMPTY) == promotion:
                    return move
        return None

    def is_checkmate(self) -> bool:
        return self.in_check(self.side_to_move) and not self.generate_legal_moves()

    def is_stalemate(self) -> bool:
        return not self.in_check(self.side_to_move) and not self.generate_legal_moves()
