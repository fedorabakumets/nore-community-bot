import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from community_bot.access import miniapp_allowed, private_allowed
from community_bot.database import Database
from community_bot.profile_fill import profile_fill_percent
from community_bot.profile_maintenance import reset_profile

USERNAME = 'test_reset_user'


@pytest.fixture
async def env(tmp_path):
    db = Database(tmp_path / 'profiles.sqlite3')
    await db.initialize()
    for uid in (7, 8):
        await db.ensure_user(uid, USERNAME if uid == 7 else 'another_user', 'Друг')
        await db.execute("UPDATE users SET profile_name='Анкета',age=25,hobbies='Город',profile_bio='Привет',"
                         "avatar_file_id='photo',role='admin',cookies=123,cookie_debt=4 WHERE user_id=?", (uid,))
    await db.execute("INSERT INTO transactions(user_id,amount,kind,created_at) VALUES(7,123,'test','now')")
    await db.execute("INSERT INTO applications(user_id,answers_json,status,created_at) VALUES(7,'{}','approved','now')")
    await db.execute("INSERT INTO profile_completion_rewards VALUES(7,'now')")
    await db.execute("INSERT INTO seasonal_entries VALUES('season1-crimson-guardian',7,'now')")
    await db.execute("INSERT INTO mini_presence VALUES(7,'abcdefghijklmnop',1,1,1000)")
    settings = SimpleNamespace(is_owner=lambda uid: uid == 99, owner_ids={99}, moderator_ids=set())
    bot = SimpleNamespace(get_chat=AsyncMock(return_value=SimpleNamespace(username=USERNAME)),
                          set_chat_menu_button=AsyncMock())
    return SimpleNamespace(db=db, settings=settings, bot=bot,
                           request=json.dumps({'username': USERNAME, 'nonce': 'test-reset-20261028'}))


async def test_one_profile_reset_restores_onboarding_and_preserves_finances_history_and_other_users(env):
    db = env.db
    other = await db.get_user(8)
    ledger = await db.fetchall('SELECT * FROM transactions ORDER BY id')
    reward = await db.fetchall('SELECT * FROM profile_completion_rewards')
    seasonal = await db.fetchall('SELECT * FROM seasonal_entries')
    result = await reset_profile(db, env.settings, env.bot, env.request)
    assert result['status'] == 'done' and result['role'] == 'member' and result['archived_applications'] == 1
    user = await db.get_user(7)
    assert user['role'] == 'member' and profile_fill_percent(user) == 0
    assert not await private_allowed(db, env.settings, 7)
    assert not await miniapp_allowed(db, env.settings, 7)
    assert not await db.has_approved_application(7) and not await db.has_pending_application(7)
    assert (user['cookies'], user['cookie_debt']) == (123, 4)
    assert await db.fetchall('SELECT * FROM transactions ORDER BY id') == ledger
    assert await db.fetchall('SELECT * FROM profile_completion_rewards') == reward
    assert await db.fetchall('SELECT * FROM seasonal_entries') == seasonal
    assert await db.get_user(8) == other
    assert not await db.fetchall('SELECT * FROM mini_presence WHERE user_id=7')
    backups = list((db.path.parent / '.nora-backups').glob('*.sqlite3'))
    assert len(backups) == 1 and backups[0].stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(backups[0]) as original:
        assert original.execute('SELECT role FROM users WHERE user_id=7').fetchone() == ('admin',)
        assert original.execute('SELECT status FROM applications WHERE user_id=7').fetchone() == ('approved',)
    assert await db.create_application(7, {'name': 'Новая анкета'})
    assert await db.has_pending_application(7)
    await db.update_profile(7, 'profile_name', 'Заполняется заново')
    assert (await reset_profile(db, env.settings, env.bot, env.request))['status'] == 'already_done'
    assert (await db.get_user(7))['profile_name'] == 'Заполняется заново'
    assert await db.has_pending_application(7)
    assert len(await db.fetchall("SELECT * FROM admin_audit_log WHERE action='profile_onboarding_reset'")) == 1


@pytest.mark.parametrize('protected', ['owner', 'moderator', 'renamed'])
async def test_unverified_or_configured_staff_reset_is_rejected_without_mutation(env, protected):
    before = await env.db.get_user(7)
    if protected == 'owner':
        env.settings.is_owner = lambda uid: uid == 7
    elif protected == 'moderator':
        env.settings.moderator_ids = {7}
    else:
        env.bot.get_chat.return_value.username = 'renamed_user'
    with pytest.raises(ValueError):
        await reset_profile(env.db, env.settings, env.bot, env.request)
    assert await env.db.get_user(7) == before
    assert await env.db.has_approved_application(7)
    assert not (env.db.path.parent / '.nora-backups').exists()


async def test_failed_backup_aborts_reset(env, monkeypatch):
    from community_bot import profile_maintenance

    def fail(*args):
        raise OSError('Backup storage unavailable')

    before = await env.db.get_user(7)
    monkeypatch.setattr(profile_maintenance, 'checked_backup', fail)
    with pytest.raises(OSError):
        await reset_profile(env.db, env.settings, env.bot, env.request)
    assert await env.db.get_user(7) == before
    assert await env.db.has_approved_application(7)
