import asyncio
from unittest.mock import AsyncMock

import pytest

from community_bot import wallet_reset
from community_bot.database import Database


@pytest.fixture
async def db(tmp_path):
    db = Database(tmp_path / "wallet.sqlite3")
    await db.initialize()
    for user_id, amount in ((7, 4), (8, 30), (9, 10), (10, 0)):
        await db.ensure_user(user_id, telegram_name="Участник")
        await db.set_cookies(user_id, amount, 8)
    for user_id in (7, 9):
        await db.execute("INSERT INTO profile_completion_rewards VALUES (?,?)", (user_id, "2026-11-10"))
    await db.execute("UPDATE users SET cookie_debt=17 WHERE user_id=7")
    return db


async def test_reset_keeps_profile_bonus_and_audit_trail_and_never_replays(db):
    old_rows = await db.fetchall("SELECT * FROM transactions ORDER BY id")
    results = await asyncio.gather(wallet_reset.reset_wallet_balances(db), wallet_reset.reset_wallet_balances(db))
    assert sorted(results) == [False, True]
    assert [
        (row["cookies"], row["cookie_debt"])
        for row in await db.fetchall("SELECT cookies, cookie_debt FROM users ORDER BY user_id")
    ] == [(10, 17), (0, 0), (10, 0), (0, 0)]
    assert len(await db.fetchall("SELECT * FROM profile_completion_rewards")) == 2
    rows = await db.fetchall("SELECT * FROM transactions ORDER BY id")
    assert rows[:len(old_rows)] == old_rows
    assert [(row["user_id"], row["amount"], row["kind"]) for row in rows[len(old_rows):]] == [
        (7, 6, "wallet_reset"), (8, -30, "wallet_reset"),
    ]
    backup_id = await db.get_bot_state(wallet_reset.MARKER)
    backup = Database(db.path.parent / ".nora-backups" / f"before-{backup_id}.sqlite3")
    assert (await backup.get_user(7))["cookies"] == 4
    assert (await backup.get_user(8))["cookies"] == 30
    assert await backup.fetchall("SELECT * FROM transactions ORDER BY id") == old_rows
    await db.add_cookies(8, 3, "test")
    assert not await wallet_reset.reset_wallet_balances(Database(db.path))
    assert (await db.get_user(8))["cookies"] == 3


async def test_release_requires_production_and_backup_before_reset(db, monkeypatch):
    backup = AsyncMock(side_effect=OSError)
    monkeypatch.setattr(wallet_reset, "verify_requested_release_backup", backup)
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_MESSAGE", wallet_reset.RELEASE_SUBJECT)
    monkeypatch.setenv("RAILWAY_GIT_BRANCH", "cursor/nora-2-update-d133")
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", str(db.path.parent))
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "preview")
    await wallet_reset.apply_wallet_reset_release(db)
    backup.assert_not_awaited()
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    await wallet_reset.apply_wallet_reset_release(db)
    backup.assert_awaited_once()
    assert (await db.get_user(7))["cookies"] == 4
    assert (await db.get_user(8))["cookies"] == 30
    assert not await db.get_bot_state(wallet_reset.MARKER)
    assert not await db.fetchall("SELECT id FROM transactions WHERE kind='wallet_reset'")
