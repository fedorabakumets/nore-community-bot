import json
import sqlite3
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from community_bot.access import miniapp_allowed
from community_bot.admin_workspace import button_meta
from community_bot.community_api import directory
from community_bot.community_reset import MARKER, apply_reset, prepare_reset, reset_settings
from community_bot.database import Database
from community_bot.friends_api import snapshot
from community_bot.role_prefixes import EMOJI_LABELS, EMOJIS, decorate_game_people, prefix_for
from community_bot.social_profiles import heartbeat


@dataclass
class Settings:
    owner_id: int = 1
    owner_ids: frozenset = field(default_factory=lambda: frozenset({1, 2}))
    moderator_ids: frozenset = field(default_factory=lambda: frozenset({3}))
    community_chat_id: int = -100

    def is_owner(self, uid):
        return uid in self.owner_ids


@pytest.fixture
async def env(tmp_path, monkeypatch):
    monkeypatch.setattr('community_bot.community_reset.RETAINED_OWNER_ID', 1)
    db = Database(tmp_path / 'community.sqlite3')
    await db.initialize()
    for uid in range(1, 7):
        await db.ensure_user(uid, telegram_name=f'Person {uid}')
        await db.add_cookies(uid, 100, 'test')
        await db.record_activity(uid, -100, False)
    return SimpleNamespace(db=db, settings=Settings())


async def test_access_threshold_current_future_and_revocation(env):
    db, settings = env.db, env.settings
    for rank in (29, 30, 31, 40):
        slug = f'future_{rank}'
        await db.create_staff_role(slug, slug, rank)
        await db.set_role(4, slug)
        assert await miniapp_allowed(db, settings, 4) == (rank >= 30)
    await db.update_staff_role('future_40', rank=29)
    assert not await miniapp_allowed(db, settings, 4)


async def test_prefix_survives_initialization_and_updates_all_views(env):
    db = env.db
    await db.create_staff_role('custom', 'Stars <team>', 30, prefix_color='blue', prefix_emoji='⭐')
    await db.set_role(4, 'custom')
    await db.initialize()
    assert await prefix_for(db, env.settings, 4) == {
        'text': 'Stars <team>', 'color': 'blue', 'emoji': '⭐'}
    await db.update_staff_role('custom', name='New name', rank=35)
    view = await decorate_game_people(db, env.settings, {
        'players': [{'id': 4, 'name': 'Old cached name'}],
        'messages': [{'user_id': 4, 'name': 'Old name'}], 'host_id': 4, 'host_name': 'Cached'})
    assert view['players'][0]['prefix']['text'] == 'New name'
    assert view['messages'][0]['prefix'] == view['host_prefix']
    await db.set_role(4, 'member')
    assert await prefix_for(db, env.settings, 4) is None
    with pytest.raises(ValueError):
        await db.update_staff_role('custom', prefix_color='red" onclick="bad')
    with pytest.raises(ValueError):
        await db.create_staff_role('bad', 'Bad', 30, prefix_emoji='<img>')


@pytest.mark.parametrize('emoji', EMOJIS)
async def test_symbol_choices_survive_save_and_match_admin_controls(env, emoji):
    from community_bot.routers.private import _prefix_keyboard

    db = env.db
    await db.create_staff_role('symbols', 'Команда', 30, prefix_color='purple', prefix_emoji=emoji)
    await db.set_role(4, 'symbols')
    await db.initialize()
    assert (await prefix_for(db, env.settings, 4))['emoji'] == emoji
    buttons = [button for row in _prefix_keyboard('purple', emoji).inline_keyboard for button in row
               if button.callback_data.startswith('admin:prefix:emoji:')]
    selected = [button for button in buttons if button.text.startswith('✓')]
    assert len(buttons) == len(EMOJIS) and len(selected) == 1
    meta = button_meta(selected[0].callback_data, selected[0].text)
    assert meta['checked'] and meta['prefix_emoji'] == emoji
    assert meta['label'] == EMOJI_LABELS[emoji]


async def test_prefix_is_public_even_when_profile_is_hidden(env):
    from community_bot.social_profiles import profile

    db = env.db
    await db.create_staff_role('symbols', 'Команда', 30, prefix_color='blue', prefix_emoji='👮')
    await db.set_role(4, 'symbols')
    await db.execute('UPDATE users SET profile_private=1 WHERE user_id=4')

    class Request(dict):
        app = {'db': db, 'settings': env.settings}
        match_info = {'user_id': '4'}

    result = json.loads((await profile(Request(actor={'id': 5}))).body)
    assert result['hidden']
    assert result['prefix'] == {'text': 'Команда', 'color': 'blue', 'emoji': '👮'}
    assert 'bio' not in result and 'cookies' not in result


async def test_online_sort_uses_visible_presence_before_pagination_and_friends(env):
    db, settings = env.db, env.settings
    for uid in range(7, 63):
        await db.ensure_user(uid, telegram_name=f'A Person {uid}')
        await db.record_activity(uid, -100, False)
    await heartbeat(db, 62, 'a' * 20, 1, True)
    await heartbeat(db, 61, 'b' * 20, 1, True)
    await heartbeat(db, 60, 'c' * 20, 1, True)
    await db.execute('INSERT INTO mini_presence_settings VALUES(61,1)')
    await db.execute('UPDATE users SET profile_private=1 WHERE user_id=60')
    req = SimpleNamespace(app={'db': db, 'settings': settings}, query={})

    class Request(dict):
        app = req.app
        query = req.query

    result = json.loads((await directory(Request(actor={'id': 4}))).body)
    assert len(result['items']) == 50 and result['items'][0]['id'] == 62
    assert result['next_offset'] == 50
    for uid in (60, 61):
        await db.execute("INSERT INTO mini_friendships VALUES(4,?,4,'accepted',?,'now','now',0,99999999999)",
                         (uid, str(uid)))
    await db.execute("INSERT INTO mini_friendships VALUES(4,62,4,'accepted','62','now','now',0,99999999999)")
    friends = (await snapshot(db, settings, 4))['friends']
    assert friends[0]['id'] == 62
    assert all(not p['presence']['online'] and not p['presence']['visible'] for p in friends[1:])
    # Hiding a currently online person returns them to their ordinary name order.
    await db.execute('INSERT INTO mini_presence_settings VALUES(62,1)')
    hidden = json.loads((await directory(Request(actor={'id': 4}))).body)
    assert hidden['items'][0]['id'] != 62
    await heartbeat(db, 62, 'a' * 20, 2, False)
    assert json.loads((await directory(Request(actor={'id': 4}))).body) == hidden


async def test_reset_is_backed_up_atomic_once_and_removes_configured_overrides(env):
    db, settings = env.db, env.settings
    await db.set_role(2, 'owner')
    await db.set_role(3, 'moderator')
    await db.set_role(4, 'admin')
    await db.execute("INSERT INTO pets(user_id,species,name,last_tick_at,created_at,updated_at) "
                     "VALUES(4,'cat','Pet','now','now','now')")
    await db.execute("INSERT INTO applications(user_id,answers_json,status,created_at) "
                     "VALUES(4,'{}','approved','now')")
    game, _ = await db.create_staked_game(-100, 'dice', 4, 5)
    await prepare_reset(db)
    backups = list((db.path.parent / '.nora-backups').glob('*.sqlite3'))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as original:
        assert original.execute('SELECT cookies,role FROM users WHERE user_id=4').fetchone() == (95, 'admin')
        assert original.execute('SELECT count(*) FROM pets').fetchone()[0] == 1
    assert await apply_reset(db, settings)
    restricted = await reset_settings(db, settings)
    assert restricted.owner_ids == {1} and not restricted.moderator_ids
    for uid in range(1, 7):
        user = await db.get_user(uid)
        assert user['cookies'] == 0
        assert user['role'] == ('owner' if uid == 1 else 'member')
        assert await miniapp_allowed(db, restricted, uid) == (uid == 1)
    assert not await db.list_pets()
    assert await db.has_approved_application(4)
    assert (await db.get_party_game(game))['status'] == 'cancelled'
    await db.payout_staked_game(game, {4: 10})
    assert (await db.get_user(4))['cookies'] == 0
    assert (await db.fetchone('SELECT sum(amount) balance FROM transactions WHERE user_id=4'))['balance'] == 0
    assert await db.get_bot_state(MARKER)
    await db.add_cookies(4, 7, 'after_reset')
    await db.set_role(4, 'moderator')
    assert not await apply_reset(db, settings)
    assert (await db.get_user(4))['cookies'] == 7
    assert (await db.get_user(4))['role'] == 'moderator'


async def test_backup_failure_aborts_before_any_reset(env, monkeypatch):
    def fail(*args):
        raise OSError('backup unavailable')

    monkeypatch.setattr('community_bot.community_reset.checked_backup', fail)
    with pytest.raises(OSError):
        await apply_reset(env.db, env.settings)
    assert (await env.db.get_user(4))['cookies'] == 100
    assert not await env.db.get_bot_state(MARKER)


async def test_retained_account_can_be_secondary_owner_and_unconfirmed_reset_is_blocked(env, monkeypatch):
    monkeypatch.setattr('community_bot.community_reset.RETAINED_OWNER_ID', 0)
    with pytest.raises(RuntimeError):
        await prepare_reset(env.db)
    with pytest.raises(ValueError):
        await apply_reset(env.db, env.settings)
    with pytest.raises(ValueError):
        await apply_reset(env.db, env.settings, owner_id=4)
    assert (await env.db.get_user(1))['cookies'] == 100
    assert await apply_reset(env.db, env.settings, owner_id=2)
    effective = await reset_settings(env.db, env.settings)
    assert effective.is_owner(2) and not effective.is_owner(1)
    assert (await env.db.get_user(1))['role'] == 'member'


async def test_reset_prevents_old_games_and_quotes_restoring_balances(env):
    from community_bot import rocket_api as rocket
    from community_bot import sea_api as sea

    db = env.db
    await db.execute("UPDATE users SET profile_name='Player',age=25,hobbies='Games',profile_bio='Hi',"
                     "avatar_file_id='photo',role='moderator'")
    room, _, _ = await sea.apply_action(db, env.settings, 4, {
        'action': 'create', 'vs_bot': False, 'stake': 10}, now=1000)
    quote = await rocket.prepare_round(db, 5, 10, None, now=1000)
    launched = await rocket.launch_round(db, 5, quote['token'], now=1000)
    pending = await rocket.prepare_round(db, 6, 10, None, now=1000)
    await apply_reset(db, env.settings)
    assert (await db.fetchone('SELECT status FROM mini_sea_rooms WHERE id=?', (room,)))['status'] == 'cancelled'
    assert not await db.fetchall('SELECT 1 FROM mini_sea_members WHERE active=1')
    assert (await db.fetchone('SELECT status FROM mini_rocket_rounds WHERE id=?',
                              (launched['round']['id'],)))['status'] == 'crashed'
    assert (await db.fetchone('SELECT status FROM mini_rocket_quotes WHERE token=?',
                              (pending['token'],)))['status'] == 'superseded'
    await sea.tick(db, now=99999999999)
    assert all(row['cookies'] == 0 for row in await db.list_all_users())


async def test_prefix_migration_preserves_existing_roles_and_backup_precedes_schema(env):
    db = env.db
    await db.create_staff_role('old', 'Existing', 30, ['admin.panel'])
    await db.execute('ALTER TABLE staff_roles DROP COLUMN prefix_color')
    await db.execute('ALTER TABLE staff_roles DROP COLUMN prefix_emoji')
    await prepare_reset(db)
    backup = next((db.path.parent / '.nora-backups').glob('*.sqlite3'))
    with sqlite3.connect(backup) as original:
        assert 'prefix_color' not in {r[1] for r in original.execute('PRAGMA table_info(staff_roles)')}
    await db.initialize()
    role = await db.get_staff_role('old')
    assert role['rank'] == 30 and role['permissions'] == ['admin.panel']
    assert role['prefix_color'] == role['prefix_emoji'] == ''
