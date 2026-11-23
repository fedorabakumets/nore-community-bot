"""Check that the multipart story reconstructs the exact uploaded MP4."""
import hashlib

from community_bot import dedzytwo_story


def test_dedzytwo_video_integrity(tmp_path, monkeypatch):
    monkeypatch.setattr(dedzytwo_story, "TARGET", tmp_path / "dedzytwo.mp4")
    output = dedzytwo_story._assemble()
    assert output.stat().st_size == dedzytwo_story.EXPECTED_SIZE
    assert hashlib.sha256(output.read_bytes()).hexdigest() == dedzytwo_story.EXPECTED_SHA256
    assert dedzytwo_story._assemble() == output
