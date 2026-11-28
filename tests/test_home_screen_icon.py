"""Regression: the install story must use the standalone NORA burrow icon."""
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def test_install_story_and_tile_share_transparent_logo():
    story = (ROOT / "community_bot/web/home-screen.js").read_text(encoding="utf-8")
    viewer = (ROOT / "community_bot/web/home-stories.js").read_text(encoding="utf-8")
    assert "const icon = '/intro/nora-home-icon.svg';" in story
    assert "cover: NoraHomeScreen.icon," in viewer
    assert "nora-logo-ru.jpg" not in story


def test_burrow_icon_is_svg_without_background_rectangle():
    path = ROOT / "assets/branding/nora-home-icon.svg"
    root = ET.parse(path).getroot()
    namespace = "{http://www.w3.org/2000/svg}"
    assert root.tag == namespace + "svg"
    assert root.attrib["viewBox"] == "0 0 512 512"
    assert len(root.findall(namespace + "path")) == 1
    assert not root.findall(namespace + "rect")
