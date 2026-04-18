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
