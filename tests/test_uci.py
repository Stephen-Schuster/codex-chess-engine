import subprocess
import sys


def run_engine(commands: str) -> str:
    proc = subprocess.Popen(
        [sys.executable, "main.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    out, _ = proc.communicate(commands, timeout=20)
    return out


def test_uci_handshake() -> None:
    output = run_engine("uci\nisready\nquit\n")
    assert "uciok" in output
    assert "readyok" in output


def test_go_depth_returns_move() -> None:
    output = run_engine("uci\nposition startpos\ngo depth 2\nquit\n")
    assert "bestmove " in output


def test_go_nodes_returns_move() -> None:
    output = run_engine("uci\nposition startpos\ngo nodes 500\nquit\n")
    assert "bestmove " in output


def test_go_infinite_stop_returns_move() -> None:
    output = run_engine("uci\nposition startpos\ngo infinite\nstop\nquit\n")
    assert "bestmove " in output


def test_go_movetime_returns_move() -> None:
    output = run_engine("uci\nposition startpos\ngo movetime 50\nquit\n")
    assert "bestmove " in output
