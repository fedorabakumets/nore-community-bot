"""Run existing lint and Python tests without outbound Python network access."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUARD = '''import socket
def _blocked(*args, **kwargs):
    raise OSError("Network disabled for isolated Nora tests")
socket.socket.connect = _blocked
socket.socket.connect_ex = _blocked
socket.create_connection = _blocked
socket.getaddrinfo = _blocked
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
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"], cwd=ROOT, env=env, check=False,
        )
        return result.returncode


if __name__ == "__main__":
    sys.exit(main())
