import os
import subprocess
import sys
from pathlib import Path

from tools.check_local import GUARD


def test_network_guard_allows_asyncio_but_blocks_connections(tmp_path: Path) -> None:
    (tmp_path / "sitecustomize.py").write_text(GUARD, encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(tmp_path))
    env.pop("BOT_TOKEN", None)
    code = """import asyncio, socket
loop = asyncio.new_event_loop()
loop.close()
for address in (('127.0.0.1', 443), ('192.0.2.1', 443)):
    with socket.socket() as sock:
        try:
            sock.connect(address)
        except OSError as error:
            assert str(error) == 'Network disabled for isolated Nora tests'
        else:
            raise AssertionError('connection was not blocked')
try:
    socket.getaddrinfo('example.com', 443)
except OSError as error:
    assert str(error) == 'Network disabled for isolated Nora tests'
else:
    raise AssertionError('DNS was not blocked')
"""
    subprocess.run([sys.executable, "-c", code], env=env, check=True)
