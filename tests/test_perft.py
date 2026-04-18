from engine.chess_state import Position


def perft(pos: Position, depth: int) -> int:
    if depth == 0:
        return 1
    nodes = 0
    for mv in pos.generate_legal_moves():
        undo = pos.make_move(mv)
        nodes += perft(pos, depth - 1)
        pos.unmake_move(mv, undo)
    return nodes


def test_startpos_perft_depth_1() -> None:
    pos = Position.from_fen(Position.START_FEN)
    assert perft(pos, 1) == 20


def test_startpos_perft_depth_2() -> None:
    pos = Position.from_fen(Position.START_FEN)
    assert perft(pos, 2) == 400


def test_startpos_perft_depth_3() -> None:
    pos = Position.from_fen(Position.START_FEN)
    assert perft(pos, 3) == 8902


def test_kiwipete_perft_depth_3() -> None:
    # Position from CPW perft suite.
    fen = "r3k2r/p1ppqpb1/bn2pnp1/2P5/1p2P3/2N2N2/PPQ1BPPP/R1B1K2R w KQkq - 0 1"
    pos = Position.from_fen(fen)
    assert perft(pos, 3) == 86279


def test_no_king_capture_moves_generated() -> None:
    # White queen attacks black king along e-file.
    fen = "4k3/8/8/8/4Q3/8/8/4K3 b - - 0 1"
    pos = Position.from_fen(fen)
    moves = [m.to_uci() for m in pos.generate_legal_moves()]
    assert "e8e4" not in moves


def test_insufficient_material_detection() -> None:
    assert Position.from_fen("8/8/8/8/8/8/k7/K7 w - - 0 1").is_insufficient_material()
    assert Position.from_fen("8/8/8/8/8/8/k7/KN6 w - - 0 1").is_insufficient_material()
    assert Position.from_fen("8/8/8/8/8/8/k7/KB6 w - - 0 1").is_insufficient_material()
    assert Position.from_fen("8/8/8/8/8/8/k5b1/KB6 w - - 0 1").is_insufficient_material()
    assert not Position.from_fen("8/8/8/8/8/8/k7/KP6 w - - 0 1").is_insufficient_material()
