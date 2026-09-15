from pathlib import Path

from community_bot.config import DEFAULT_SBP_PAYMENT_URL, load_settings


def test_owner_ids_and_group_id_fallback(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:abc")
    monkeypatch.setenv("OWNER_ID", "406719727")
    monkeypatch.setenv("OWNER_IDS", "406719727,1612141295")
    monkeypatch.setenv("MODERATOR_IDS", "1612141295")
    monkeypatch.setenv("COMMUNITY_CHAT_ID", "0")
    monkeypatch.setenv("GROUP_ID", "-1004331642093")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "community.db"))
    monkeypatch.setenv("EVENT_PASS_PRICE", "0")
    monkeypatch.setenv("SUPPORT_PRICE", "0")
    monkeypatch.delenv("SBP_PAYMENT_URL", raising=False)
    monkeypatch.delenv("FREEBIE_CHANNEL_URL", raising=False)
    monkeypatch.delenv("WELCOME_COVER", raising=False)

    settings = load_settings()

    assert settings.owner_id == 406719727
    assert settings.owner_ids == frozenset({406719727, 1612141295})
    assert settings.is_owner(1612141295)
    assert settings.community_chat_id == -1004331642093
    assert settings.community_invite_url == "https://t.me/+MfMowwQUlZlkMDIy"
    assert settings.sbp_payment_url == DEFAULT_SBP_PAYMENT_URL
    assert "79533571508" in settings.sbp_payment_url
    assert 406719727 in settings.reviewers
    assert 1612141295 in settings.reviewers
