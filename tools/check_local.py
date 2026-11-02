"""Run existing lint and Python tests without outbound Python network access."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUARD = '''import socket
import sys
import threading

_original_connect = socket.socket.connect
_original_pair = socket.socketpair
_pair_state = threading.local()

def _blocked(*args, **kwargs):
    raise OSError("Network disabled for isolated Nora tests")

socket.socket.connect = _blocked
socket.socket.connect_ex = _blocked
socket.create_connection = _blocked
socket.getaddrinfo = _blocked

if sys.platform == "win32":
    def _pair_connect(sock, address):
        if getattr(_pair_state, "active", False) and address[0] in ("127.0.0.1", "::1"):
            return _original_connect(sock, address)
        return _blocked()

    def _local_socketpair(*args, **kwargs):
        _pair_state.active = True
        try:
            return _original_pair(*args, **kwargs)
        finally:
            _pair_state.active = False

    socket.socket.connect = _pair_connect
    socket.socketpair = _local_socketpair
'''


def main() -> int:
    lint = subprocess.run([sys.executable, "-m", "ruff", "check", "."], cwd=ROOT, check=False)
    if lint.returncode:
        return lint.returncode
    with tempfile.TemporaryDirectory(prefix="nora-offline-") as directory:
        Path(directory, "sitecustomize.py").write_text(GUARD, encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join((directory, str(ROOT)))
        env.pop("BOT_TOKEN", None)
        env["PYTHON_DOTENV_DISABLED"] = "1"
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"], cwd=ROOT, env=env, check=False,
        )
        return result.returncode


if __name__ == "__main__":
    sys.exit(main())
