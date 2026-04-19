from engine.chess_state import Position
from engine.eval import evaluate


def test_open_file_rook_bonus_preferred() -> None:
    open_file = Position.from_fen("8/8/8/8/8/8/1P6/R3K3 w - - 0 1")
    blocked_file = Position.from_fen("8/8/8/8/8/8/P7/R3K3 w - - 0 1")
    assert evaluate(open_file) > evaluate(blocked_file)


def test_doubled_pawn_penalty() -> None:
    doubled = Position.from_fen("8/8/8/8/8/P7/P7/4K3 w - - 0 1")
    split = Position.from_fen("8/8/8/8/8/P7/1P6/4K3 w - - 0 1")
    assert evaluate(split) > evaluate(doubled)


def test_king_shelter_bonus() -> None:
    sheltered = Position.from_fen("8/8/8/8/8/5PPP/8/6K1 w - - 0 1")
    exposed = Position.from_fen("8/8/8/8/8/8/8/6K1 w - - 0 1")
    assert evaluate(sheltered) > evaluate(exposed)


def test_knight_outpost_bonus() -> None:
    # White knight on d5 supported by e4 pawn and no black c/e-pawn to challenge.
    outpost = Position.from_fen("4k3/8/8/3N4/4P3/8/8/4K3 w - - 0 1")
    no_support = Position.from_fen("4k3/8/8/3N4/8/8/8/4K3 w - - 0 1")
    assert evaluate(outpost) > evaluate(no_support)


def test_pawn_islands_penalty() -> None:
    # White has fewer islands in the first position.
    fewer_islands = Position.from_fen("4k3/8/8/8/8/8/PPPP4/4K3 w - - 0 1")
    more_islands = Position.from_fen("4k3/8/8/8/8/8/P1P1P3/4K3 w - - 0 1")
    assert evaluate(fewer_islands) > evaluate(more_islands)


def test_connected_pawn_bonus() -> None:
    connected = Position.from_fen("4k3/8/8/8/8/8/PP6/4K3 w - - 0 1")
    isolated = Position.from_fen("4k3/8/8/8/8/8/P1P5/4K3 w - - 0 1")
    assert evaluate(connected) > evaluate(isolated)


def test_rook_on_seventh_bonus() -> None:
    rook_seventh = Position.from_fen("4k3/3R4/8/8/8/8/8/4K3 w - - 0 1")
    rook_sixth = Position.from_fen("4k3/8/3R4/8/8/8/8/4K3 w - - 0 1")
    assert evaluate(rook_seventh) > evaluate(rook_sixth)


def test_king_only_is_draw_eval() -> None:
    pos = Position.from_fen("8/8/8/8/8/2k5/8/K7 w - - 0 1")
    assert evaluate(pos) == 0


def test_tempo_bonus_side_to_move() -> None:
    white_to_move = Position.from_fen("4k3/8/8/8/8/8/8/4K3 w - - 0 1")
    black_to_move = Position.from_fen("4k3/8/8/8/8/8/8/4K3 b - - 0 1")
    assert evaluate(white_to_move) >= evaluate(black_to_move)


def test_rook_behind_passed_pawn_bonus() -> None:
    behind = Position.from_fen("4k3/8/8/8/8/8/4P3/4R1K1 w - - 0 1")
    side = Position.from_fen("4k3/8/8/8/8/8/4P3/1R4K1 w - - 0 1")
    assert evaluate(behind) > evaluate(side)


def test_king_centralization_endgame_bonus() -> None:
    # Keep one pawn each so eval does not hit king-only fast path.
    centered = Position.from_fen("7k/p7/8/3K4/8/8/P7/8 w - - 0 1")
    not_centered = Position.from_fen("7k/p7/8/8/8/8/P7/3K4 w - - 0 1")
    assert evaluate(centered) > evaluate(not_centered)


def test_opening_development_bonus() -> None:
    developed = Position.from_fen("rnbqkbnr/pppppppp/8/8/8/5N2/PPPPPPPP/RNBQKB1R w KQkq - 0 1")
    undeveloped = Position.from_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    assert evaluate(developed) > evaluate(undeveloped)


def test_early_queen_move_penalty() -> None:
    early_queen = Position.from_fen("rnbqkbnr/pppppppp/8/8/8/7Q/PPPPPPPP/RNB1KBNR w KQkq - 0 1")
    normal = Position.from_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    # Queen excursion should not be rewarded over normal setup.
    assert evaluate(early_queen) <= evaluate(normal) + 20


def test_center_pawn_loss_with_queens_penalty() -> None:
    intact = Position.from_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    missing_center = Position.from_fen("rnbqkbnr/pppppppp/8/8/8/8/PPP2PPP/RNBQKBNR w KQkq - 0 1")
    assert evaluate(intact) > evaluate(missing_center)
