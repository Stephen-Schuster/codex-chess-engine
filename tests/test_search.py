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
