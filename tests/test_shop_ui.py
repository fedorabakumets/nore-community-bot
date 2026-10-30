from community_bot.keyboards import FLOW_CANCEL, STYLE_CLOSE, STYLE_GO, shop_home_keyboard, start_apply_keyboard
from community_bot.pets_talk import aftercare_line
from community_bot.shop_catalog import IMMUNITY_HOURS, SHOP_CATEGORIES, shop_prices_for


def test_start_apply_button_is_green() -> None:
    button = start_apply_keyboard().inline_keyboard[0][0]
    assert button.text.startswith("📝")
    assert button.style == STYLE_GO
    assert button.callback_data == "start:apply"


def test_shop_is_split_into_pet_and_reputation_blocks() -> None:
    assert "cosmetics" not in SHOP_CATEGORIES
    assert "pets" in SHOP_CATEGORIES
    assert "reputation" in SHOP_CATEGORIES
    assert "season_pack" in SHOP_CATEGORIES["pets"]["items"]
    assert "tamagotchi" in SHOP_CATEGORIES["pets"]["items"]
    assert "pet_meal" in SHOP_CATEGORIES["pets"]["items"]
    assert "forgive" in SHOP_CATEGORIES["reputation"]["items"]
    assert "rep_shield" in SHOP_CATEGORIES["reputation"]["items"]
    assert "title_owl" not in SHOP_CATEGORIES["profile"]["items"]
    assert set(IMMUNITY_HOURS) <= set(SHOP_CATEGORIES["reputation"]["items"])
    assert IMMUNITY_HOURS["immunity_24h"] == 24


def test_shop_home_has_red_close_and_green_cookies() -> None:
    rows = shop_home_keyboard().inline_keyboard
    close = rows[-1][-1]
    assert rows[-1][0].callback_data == "menu:home"
    cookies = rows[-2][0]
    assert close.style == STYLE_CLOSE
    assert FLOW_CANCEL.split()[0] in close.text or "Закрыть" in close.text
    assert cookies.style == STYLE_GO


def test_shop_prices_apply_gold_discount() -> None:
    from community_bot.shop_catalog import SAMPLE_SHOP_PRICES

    prices = shop_prices_for({"reputation": 95}, 0, SAMPLE_SHOP_PRICES)
    assert prices["immunity_24h"] < 18
    assert prices["forgive"] == 45


def test_pet_aftercare_mentions_name() -> None:
    line = aftercare_line({"name": "Булочка", "species": "cat"}, "food")
    assert "Булочка" in line
