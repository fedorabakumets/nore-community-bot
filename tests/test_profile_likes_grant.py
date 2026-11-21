import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from community_bot import profile_likes_grant as grant
from community_bot import social_likes
from community_bot.database import Database


async def test_owner_likes_grant_verifies_backup_and_never_replays(tmp_path, monkeypatch):
    db = Database(tmp_path / 'likes.sqlite3')
    await db.initialize()
    uid = grant.RETAINED_OWNER_ID
    settings = SimpleNamespace(is_owner=lambda user_id: user_id == uid)
    await db.ensure_user(uid, telegram_name='Ромочка')
    await db.ensure_user(7, telegram_name='Участник')
    assert await social_likes.give(db, 7, uid) is None
    daily = await db.get_bot_state(social_likes.DAY_PREFIX + '7')

    monkeypatch.setenv('RAILWAY_GIT_BRANCH', 'cursor/nora-2-update-d133')
    monkeypatch.setenv('RAILWAY_VOLUME_MOUNT_PATH', str(tmp_path))
    monkeypatch.setenv('RAILWAY_ENVIRONMENT_NAME', 'preview')
    await grant.apply_profile_likes_grant(db, settings)
    assert await social_likes.count(db, uid) == 1

    monkeypatch.setenv('RAILWAY_ENVIRONMENT_NAME', 'production')
    with monkeypatch.context() as patch:
        patch.setattr(grant, 'verify_requested_release_backup', AsyncMock(side_effect=OSError))
        await grant.apply_profile_likes_grant(db, settings)
    assert await social_likes.count(db, uid) == 1
    assert not await db.get_bot_state(grant.MARKER)

    await grant.apply_profile_likes_grant(db, settings)
    assert await social_likes.count(db, uid) == 50
    assert await db.get_bot_state(social_likes.DAY_PREFIX + '7') == daily
    marker = json.loads(await db.get_bot_state(grant.MARKER))
    backup = Database(tmp_path / '.nora-backups' / f"before-{marker['backup']}.sqlite3")
    assert await social_likes.count(backup, uid) == 1
    await db.set_bot_state(social_likes.COUNT_PREFIX + str(uid), '51')
    await grant.apply_profile_likes_grant(db, settings)
    assert await social_likes.count(db, uid) == 51
