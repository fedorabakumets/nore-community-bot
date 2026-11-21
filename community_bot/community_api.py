"""Read-only community directory and completed-day boards; existing balances stay authoritative."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiohttp import web

from community_bot.helpers import can_view_profile
from community_bot.role_prefixes import prefix_for
from community_bot.social_likes import COUNT_PREFIX
from community_bot.social_profiles import presence_map


def day_window(now=None):
    now = now or datetime.now(ZoneInfo('Europe/Moscow'))
    today = now.astimezone(ZoneInfo('Europe/Moscow')).date()
    return today, today - timedelta(days=1)


async def people(db, settings, viewer):
    chat = int(getattr(settings, 'community_chat_id', 0) or 0)
    rows = await db.fetchall(
        "SELECT u.*,r.name role_name,COALESCE(r.rank,0) rank,"
        "CASE WHEN u.profile_private=0 THEN COALESCE(CAST(l.value AS INTEGER),0) END likes,"
        "EXISTS(SELECT 1 FROM applications a WHERE a.user_id=u.user_id AND a.status='approved') approved,"
        "(EXISTS(SELECT 1 FROM user_activity a WHERE a.user_id=u.user_id AND a.chat_id=?) OR "
        "EXISTS(SELECT 1 FROM daily_scores a WHERE a.user_id=u.user_id AND a.chat_id=?)) active_member "
        "FROM users u LEFT JOIN staff_roles r ON r.slug=u.role "
        "LEFT JOIN bot_state l ON l.key=(? || u.user_id) WHERE u.user_id>0 AND NOT EXISTS("
        "SELECT 1 FROM mini_friend_blocks b WHERE (b.blocker_id=? AND b.blocked_id=u.user_id) "
        "OR (b.blocked_id=? AND b.blocker_id=u.user_id))",
        (chat, chat, COUNT_PREFIX, viewer, viewer),
    )
    from community_bot.bot_identity import likely_bot, marked_bots

    known_bots = await marked_bots(db)
    result = []
    for row in rows:
        if likely_bot(row) or str(row['user_id']) in known_bots:
            continue
        if settings.is_owner(row['user_id']):
            row.update(role='owner', role_name='Владелец', rank=1000)
        elif row['user_id'] in settings.moderator_ids and row['role'] == 'member':
            row.update(role='moderator', role_name='Модератор', rank=40)
        if row['approved'] or row['active_member'] or row['rank'] > 0:
            result.append(row)
    return result


async def card(db, settings, viewer, row):
    return {
        'id': row['user_id'],
        'prefix': await prefix_for(db, settings, row['user_id']),
        'name': row['profile_name'] or row['telegram_name'] or row['username'] or 'Участник',
        'username': row['username'],
        'has_avatar': bool(row['avatar_file_id'] and row['avatar_media_type'] == 'photo'
                           and await can_view_profile(db, settings, viewer, row)),
    }


async def directory(request):
    db, settings, viewer = request.app['db'], request.app['settings'], request['actor']['id']
    query = request.query.get('q', '').strip()
    try:
        offset = int(request.query.get('offset', '0'))
        limit = int(request.query.get('limit', '50'))
    except ValueError:
        raise web.HTTPBadRequest() from None
    if len(query) > 80 or not 0 <= offset <= 1_000_000 or not 1 <= limit <= 500:
        raise web.HTTPBadRequest()
    normalized = lambda s: str(s or '').casefold().replace('ё', 'е')  # noqa: E731
    needle = normalized(query.lstrip('@'))
    rows = [r for r in await people(db, settings, viewer) if not needle or any(
        needle in normalized(r[k]) for k in ('profile_name', 'telegram_name', 'username', 'user_id'))]
    statuses = await presence_map(db, [r['user_id'] for r in rows])
    rows.sort(key=lambda r: (not statuses.get(r['user_id'], {}).get('online', False),
                             normalized(r['profile_name'] or r['telegram_name'] or r['username']), r['user_id']))
    items = [await card(db, settings, viewer, r) for r in rows[offset:offset + limit]]
    for item in items:
        item['presence'] = statuses.get(item['id'])
    return web.json_response({'items': items, 'total': len(rows),
                              'next_offset': offset + limit if offset + limit < len(rows) else None})


async def status(request):
    db, settings, viewer = request.app['db'], request.app['settings'], request['actor']['id']
    now = datetime.now(ZoneInfo('Europe/Moscow'))
    today, day = day_window(now)
    chat = int(getattr(settings, 'community_chat_id', 0) or 0)
    rows = await people(db, settings, viewer)
    by_id = {r['user_id']: r for r in rows}
    board = await db.daily_message_board(today.isoformat(), chat, limit=-1)
    boards = {}
    for metric, ranking in (
        ('messages', board),
        ('likes', await db.public_profile_board(chat, 'likes')),
        ('cookies', await db.public_profile_board(chat, 'cookies')),
    ):
        visible = [row for row in ranking if row['user_id'] in by_id][:5]
        boards[metric] = [
            {**await card(db, settings, viewer, by_id[row['user_id']]),
             'likes': by_id[row['user_id']]['likes'], metric: row[metric]}
            for row in visible
        ]
    from community_bot.referral_campaign import END as referral_end, START as referral_start, leaderboard

    invited = await leaderboard(db, limit=10)
    boards['invites'] = [
        {**await card(db, settings, viewer, by_id[row['user_id']]),
         'likes': by_id[row['user_id']]['likes'], 'invites': int(row['invites'])}
        for row in invited if row['user_id'] in by_id
    ][:3]
    # Show the recipient actually credited by the existing midnight job, never guess or issue another reward.
    winner = await db.fetchone(
        "SELECT user_id FROM transactions WHERE kind='daily_chat' AND details=? AND amount>0 ORDER BY id LIMIT 1",
        (day.isoformat(),),
    )
    winner_card = None
    if winner and winner['user_id'] in by_id:
        winner_card = await card(db, settings, viewer, by_id[winner['user_id']])
    staff = []
    ordered = sorted(rows, key=lambda r: (-r['rank'],
                                          str(r['profile_name'] or r['telegram_name'] or '').casefold(),
                                          r['user_id']))
    for row in ordered:
        if row['rank'] > 0:
            staff.append({**await card(db, settings, viewer, row),
                          'role': row['role_name'] or row['role'], 'rank': row['rank']})
    from community_bot.helpers import has_permission
    from community_bot.permissions import PERM_GAMES
    from community_bot.sea_api import public_lobbies
    from community_bot.sea_api import read_status as read_sea_status
    sea_invites = (await read_sea_status(db, viewer))["invites"]
    sea_admin = await has_permission(db, settings, viewer, PERM_GAMES)
    sea_lobbies = await public_lobbies(db, viewer, admin=sea_admin)
    return web.json_response({'day': today.isoformat(), 'winner_day': day.isoformat(),
                              'revision_day': today.isoformat(),
                              'timezone': 'Europe/Moscow', 'leaders': boards['messages'],
                              'boards': boards, 'staff': staff,
                               'referral_contest': {'starts_at': referral_start.isoformat(),
                                                    'ends_at': referral_end.isoformat()},
                              'winner': winner_card, 'awarded': bool(winner), 'sea_invites': sea_invites,
                              'sea_lobbies': sea_lobbies, 'sea_admin': sea_admin,
                              'updated_at': now.isoformat(timespec='seconds')})


async def presence(request):
    rows = await people(request.app['db'], request.app['settings'], request['actor']['id'])
    ids = [r['user_id'] for r in rows if r['rank'] > 0]
    return web.json_response(await presence_map(request.app['db'], ids))


async def lobbies(request):
    from community_bot import durak_api, mafia_api, sea_api
    from community_bot.helpers import has_permission
    from community_bot.permissions import PERM_GAMES

    db, settings, uid = request.app['db'], request.app['settings'], request['actor']['id']
    sea_admin = await has_permission(db, settings, uid, PERM_GAMES)
    sea = await sea_api.read_status(db, uid, lobby_details=True)
    mafia = await mafia_api.read_status(db, uid, lobby_details=True)
    sea_rooms = {
        r['id']: dict(id=r['id'], title=r['title'], players=r['players'],
                      locked=r['locked'] or not r['public'], stake=r['stake'], admin=sea_admin,
                      action='join' if r['public'] and not r['bot'] and r['players'] < 2 else '')
        for r in await sea_api.public_lobbies(db, uid, admin=sea_admin, include_full=True)
    }
    mafia_rooms = {
        r['id']: dict(id=r['id'], title=r['title'], players=r['players'], locked=False,
                      action='join' if r['players'] < mafia_api.RULES['max_players'] else '')
        for r in await mafia_api.public_lobbies(db, uid)
    }
    for game, status, entries, capacity in (
        ('sea', sea, sea_rooms, 2),
        ('mafia', mafia, mafia_rooms, mafia_api.RULES['max_players']),
    ):
        for invite in status['invites']:
            rid = invite['room_id']
            entries[rid] = {**entries.get(rid, {}), 'id': rid, 'title': invite['title'],
                            'players': invite['players_count'], 'stake': invite.get('stake', 0),
                            'locked': invite['locked'] if game == 'sea' else not invite['public'],
                            'action': 'invite'}
        room = status['room']
        if room and room['status'] == 'lobby':
            rid = room['id']
            entries[rid] = {**entries.get(rid, {}), 'id': rid, 'title': room['title'],
                            'players': sum(not player['left'] for player in room['players']),
                            'locked': room.get('locked', False) or not room['public'],
                            'stake': room.get('stake', 0), 'action': 'resume'}
        for entry in entries.values():
            entry.update(game=game, capacity=capacity)

    cards = [
        dict(id=r['id'], title=r['host_name'], game='durak', players=r['count'], capacity=r['config']['players'],
             locked=r['config']['private'], stake=r['config']['stake'], action='resume' if r['own'] else 'preview',
             config=r['config'])
        for r in await durak_api.lobbies(db, uid)
    ]
    barricades = [
        dict(id=r['id'], title=r['host_name'], game='barricade', players=r['count'], capacity=2,
             locked=r['config']['private'], stake=r['config']['stake'], action='resume' if r['own'] else 'invite')
        for r in await durak_api.lobbies(db, uid, game='barricade')
    ]
    result = [*sea_rooms.values(), *mafia_rooms.values(), *cards, *barricades]
    result.sort(key=lambda r: {'resume': 0, 'invite': 1}.get(r['action'], 2))
    return web.json_response({'rooms': result})
