from PIL import Image

from community_bot.december_house_vote import BASE, HOUSES, ROOT, build_rich


def test_house_vote_rich_structure():
    rich = build_rich(["one", "two", "three"], {"1": 1, "2": 2, "3": 2})
    blocks = rich.model_dump(exclude_none=True)["blocks"]
    assert sum(b["type"] == "photo" for b in blocks) == 3
    assert sum(b["type"] == "details" for b in blocks) == 4
    buttons = [button for block in blocks if block["type"] == "buttons" for button in block["buttons"]]
    assert [b["url"] for b in buttons if b.get("url")] == [BASE + h[-1] for h in HOUSES]
    assert [b["text"] for b in buttons if b.get("callback_data")] == [
        "Дом 1 · 33% (1)", "Дом 2 · 67% (2)", "Дом 3 · 0% (0)",
    ]
    closed = build_rich(["one", "two", "three"], {"1": 1}, closed=True)
    assert not any(
        b.callback_data for block in closed.blocks if block.type == "buttons" for b in block.buttons
    )


def test_house_photos_are_square():
    for index in range(1, 4):
        with Image.open(ROOT / f"house-{index}.jpg") as photo:
            assert photo.width == photo.height
            photo.verify()
