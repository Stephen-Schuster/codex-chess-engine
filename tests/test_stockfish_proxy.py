import os
import subprocess
import sys


def test_proxy_handshake() -> None:
    env = os.environ.copy()
    env["STOCKFISH_BIN"] = "/usr/games/stockfish"
    proc = subprocess.Popen(
        [sys.executable, "engine/stockfish_proxy.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    assert proc.stdin is not None
    out, _err = proc.communicate("uci\nisready\nquit\n", timeout=20)
    assert "uciok" in out
    assert "readyok" in out
