"""Exercise the real Mini App scripts with isolated browser and API doubles."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for Mini App regression tests")
def test_miniapp_stability_in_node():
    root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [shutil.which("node"), "--test", "tests/web_stability.test.cjs"],
        cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
