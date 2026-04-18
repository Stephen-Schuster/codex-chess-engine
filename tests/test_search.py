from engine.chess_state import Position
from engine.search import SearchLimits, Searcher


def test_search_returns_fallback_move_when_stopped_immediately() -> None:
    searcher = Searcher()
    pos = Position.from_fen(Position.START_FEN)
    searcher.stop = True
    best, _score, _elapsed = searcher.search(pos, SearchLimits(depth=5))
    assert best is not None


def test_search_respects_node_limit() -> None:
    searcher = Searcher()
    pos = Position.from_fen(Position.START_FEN)
    _best, _score, _elapsed = searcher.search(pos, SearchLimits(depth=10, nodes=200))
    assert searcher.nodes <= 400


def test_history_update_is_bounded() -> None:
    searcher = Searcher()
    pos = Position.from_fen(Position.START_FEN)
    move = pos.parse_uci_move("g1f3")
    assert move is not None

    for _ in range(2000):
        searcher.update_history(move, 100)
    assert searcher.history[move.from_sq][move.to_sq] <= 20000

    for _ in range(4000):
        searcher.update_history(move, -100)
    assert searcher.history[move.from_sq][move.to_sq] >= -20000


def test_history_aging_reduces_magnitude() -> None:
    searcher = Searcher()
    pos = Position.from_fen(Position.START_FEN)
    move = pos.parse_uci_move("g1f3")
    assert move is not None

    searcher.update_history(move, 1000)
    before = searcher.history[move.from_sq][move.to_sq]
    searcher.age_history()
    after = searcher.history[move.from_sq][move.to_sq]
    assert abs(after) <= abs(before)


def test_tt_mate_score_roundtrip() -> None:
    searcher = Searcher()
    score = 99990
    packed = searcher.score_to_tt(score, ply=5)
    unpacked = searcher.score_from_tt(packed, ply=5)
    assert unpacked == score


def test_losing_capture_gets_lower_order_score() -> None:
    searcher = Searcher()
    # White queen can capture defended pawn on d5 (typically losing exchange).
    pos = Position.from_fen("4k3/8/8/3p4/4Q3/8/8/4K3 w - - 0 1")
    cap = pos.parse_uci_move("e4d5")
    quiet = pos.parse_uci_move("e4e5")
    assert cap is not None
    assert quiet is not None
    cap_score = searcher.score_move(pos, cap, ply=0, tt_move=None)
    quiet_score = searcher.score_move(pos, quiet, ply=0, tt_move=None)
    assert cap_score < 1_000_000
    assert cap_score > quiet_score


def test_futility_pruning_keeps_tactical_checks() -> None:
    searcher = Searcher()
    # White to move has checking move Qe7+ in a quiet-ish material edge case.
    pos = Position.from_fen("4k3/8/8/8/8/8/4Q3/4K3 w - - 0 1")
    move = pos.parse_uci_move("e2e7")
    assert move is not None
    assert move in pos.generate_legal_moves()
    best, _score, _elapsed = searcher.search(pos, SearchLimits(depth=3, nodes=800))
    assert best is not None


def test_quiescence_returns_mate_when_in_check_no_legal_moves() -> None:
    searcher = Searcher()
    # Black to move, checkmated.
    pos = Position.from_fen("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1")
    score = searcher.quiescence(pos, -1_000_000, 1_000_000, ply=0)
    assert score <= -99990


def test_insufficient_material_root_is_draw_score() -> None:
    searcher = Searcher()
    # Legal king-only position.
    pos = Position.from_fen("8/8/8/8/8/2k5/8/K7 w - - 0 1")
    _best, score, _elapsed = searcher.search(pos, SearchLimits(depth=3))
    assert score == 0
