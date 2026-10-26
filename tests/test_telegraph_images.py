from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from community_bot import telegraph
from community_bot.database import Database
from community_bot.updates import UPDATES, BotUpdate, UpdateSection


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "articles.db")
    await database.initialize()
    return database


@pytest.fixture
def artwork(tmp_path, monkeypatch):
    updates = tmp_path / "updates"
    covers = tmp_path / "covers"
    updates.mkdir()
    covers.mkdir()
    monkeypatch.setattr(telegraph, "_ASSETS", updates)
    monkeypatch.setattr(telegraph, "_COVERS", covers)
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "a" * 40)
    return updates, covers


def item():
    return BotUpdate(
        number=20, slug="article", title="Статья", summary="Вступление", details=(),
        sections=(UpdateSection(heading="Стикеры", body="Текст статьи", image="20-stickers.png"),),
    )


def test_public_artwork_is_pinned_to_deployed_commit_and_cannot_expose_other_files(artwork, tmp_path):
    updates, _ = artwork
    image = updates / "20-stickers.png"
    image.write_bytes(b"test")
    assert telegraph.public_image_url(image) == (
        "https://raw.githubusercontent.com/fedorabakumets/nore-community-bot/"
        + "a" * 40 + "/assets/updates/20-stickers.png"
    )
    private_image = tmp_path / "private.png"
    private_image.write_bytes(b"private")
    assert telegraph.public_image_url(private_image) is None
    linked_image = updates / "linked.png"
    linked_image.symlink_to(private_image)
    assert telegraph.public_image_url(linked_image) is None
    secret = updates / "private.txt"
    secret.write_text("private")
    assert telegraph.public_image_url(secret) is None


def test_missing_or_invalid_revision_falls_back_to_known_production_ref(artwork, monkeypatch):
    image = artwork[0] / "20-stickers.png"
    image.write_bytes(b"test")
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "not-a-commit")
    assert "/refs/heads/cursor/nora-2-update-d133/" in telegraph.public_image_url(image)


async def test_section_images_use_committed_illustrations_and_deduplicate_without_upload(artwork):
    updates, _ = artwork
    (updates / "18-profile.jpg").write_bytes(b"test")
    article = replace(item(), sections=(
        UpdateSection(heading="Первый", body="Текст", image="profile.jpg"),
        UpdateSection(heading="Второй", body="Текст", image="profile.jpg"),
    ))
    images = await telegraph._section_images(article)
    assert list(images) == ["profile.jpg"]
    assert images["profile.jpg"].endswith("/assets/updates/18-profile.jpg")


async def test_publish_verifies_returned_image_nodes_and_logs_public_article_url(db, monkeypatch, caplog):
    monkeypatch.setattr(telegraph, "ensure_token", AsyncMock(return_value="test-only-token"))
    monkeypatch.setattr(telegraph, "_section_images", AsyncMock(return_value={"20-stickers.png": "https://example.com/a.png"}))

    async def api(method, payload):
        assert method == "createPage"
        assert payload["return_content"] is True
        return {"path": "Article-10-26", "url": "https://telegra.ph/Article-10-26", "content": payload["content"]}

    monkeypatch.setattr(telegraph, "_call", api)
    with caplog.at_level("INFO", logger="community_bot.telegraph"):
        assert await telegraph.publish_member_update(db, item()) == "https://telegra.ph/Article-10-26"
    assert await db.get_bot_state("telegraph_path_20") == "Article-10-26"
    assert "illustrations=1 url=https://telegra.ph/Article-10-26" in caplog.text
    assert "test-only-token" not in caplog.text


async def test_publish_does_not_report_success_when_telegraph_strips_requested_images(db, monkeypatch):
    monkeypatch.setattr(telegraph, "ensure_token", AsyncMock(return_value="test-only-token"))
    monkeypatch.setattr(telegraph, "_section_images", AsyncMock(return_value={"20-stickers.png": "https://example.com/a.png"}))
    monkeypatch.setattr(telegraph, "_call", AsyncMock(return_value={
        "path": "Article-10-26", "url": "https://telegra.ph/Article-10-26",
        "content": [{"tag": "p", "children": ["Text"]}],
    }))
    assert await telegraph.publish_member_update(db, item()) is None
    assert await db.get_bot_state("telegraph_url") is None


async def test_missing_artwork_does_not_silently_publish_another_text_only_article(db, monkeypatch):
    monkeypatch.setattr(telegraph, "ensure_token", AsyncMock(return_value="test-only-token"))
    monkeypatch.setattr(telegraph, "_section_images", AsyncMock(return_value={}))
    api = AsyncMock()
    monkeypatch.setattr(telegraph, "_call", api)
    assert await telegraph.publish_member_update(db, item()) is None
    api.assert_not_awaited()


async def test_existing_article_repair_is_verified_once_and_preserves_current_announcement(db, monkeypatch):
    await db.set_bot_state("telegraph_path_18", "Existing-10-26")
    await db.set_bot_state("telegraph_url", "https://telegra.ph/Current-10-26")
    await db.set_bot_state("last_announced_update", "19:photo-v2")
    article = next(entry for entry in UPDATES if entry.number == 18)
    images = {section.image: f"https://example.com/{section.image}" for section in article.sections if section.image}
    monkeypatch.setattr(telegraph, "ensure_token", AsyncMock(return_value="test-only-token"))
    monkeypatch.setattr(telegraph, "_section_images", AsyncMock(return_value=images))
    calls = []

    async def api(method, payload):
        calls.append(method)
        assert method == "editPage" and payload["path"] == "Existing-10-26"
        return {"url": "https://telegra.ph/Existing-10-26", "path": "Existing-10-26", "content": payload["content"]}

    monkeypatch.setattr(telegraph, "_call", api)
    await telegraph.repair_member_images(db)
    await telegraph.repair_member_images(db)
    assert calls == ["editPage"]
    assert await db.get_bot_state("telegraph_url") == "https://telegra.ph/Current-10-26"
    assert await db.get_bot_state("last_announced_update") == "19:photo-v2"
    assert await db.get_bot_state("telegraph_images_repaired_v1") == "1"


async def test_failed_existing_article_repair_never_creates_a_replacement_page_or_success_marker(db, monkeypatch):
    await db.set_bot_state("telegraph_path_18", "Existing-10-26")
    monkeypatch.setattr(telegraph, "ensure_token", AsyncMock(return_value="test-only-token"))
    monkeypatch.setattr(telegraph, "_section_images", AsyncMock(return_value={
        "profile.jpg": "https://example.com/profile.jpg", "wallet.jpg": "https://example.com/wallet.jpg",
    }))
    api = AsyncMock(return_value=None)
    monkeypatch.setattr(telegraph, "_call", api)
    await telegraph.repair_member_images(db)
    assert [call.args[0] for call in api.await_args_list] == ["editPage"]
    assert await db.get_bot_state("telegraph_images_repaired_v1") is None
