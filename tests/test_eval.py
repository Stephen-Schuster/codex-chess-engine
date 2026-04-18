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
