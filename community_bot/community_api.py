"""Read-only community directory and completed-day boards; existing balances stay authoritative."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiohttp import web

from community_bot.helpers import can_view_profile
from community_bot.social_profiles import presence_map


def day_window(now=None):
    now = now or datetime.now(ZoneInfo('Europe/Moscow'))
    today = now.astimezone(ZoneInfo('Europe/Moscow')).date()
    return today, today - timedelta(days=1)


async def people(db, settings, viewer):
    chat = int(getattr(settings, 'community_chat_id', 0) or 0)
    rows = await db.fetchall(
        "SELECT u.*,r.name role_name,COALESCE(r.rank,0) rank,"
        "EXISTS(SELECT 1 FROM applications a WHERE a.user_id=u.user_id AND a.status='approved') approved,"
        "(EXISTS(SELECT 1 FROM user_activity a WHERE a.user_id=u.user_id AND a.chat_id=?) OR "
        "EXISTS(SELECT 1 FROM daily_scores a WHERE a.user_id=u.user_id AND a.chat_id=?)) active_member "
        "FROM users u LEFT JOIN staff_roles r ON r.slug=u.role WHERE u.user_id>0 AND NOT EXISTS("
        "SELECT 1 FROM mini_friend_blocks b WHERE (b.blocker_id=? AND b.blocked_id=u.user_id) "
        "OR (b.blocked_id=? AND b.blocker_id=u.user_id))",
        (chat, chat, viewer, viewer),
    )
    result = []
    for row in rows:
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
    except ValueError:
        raise web.HTTPBadRequest() from None
    if len(query) > 80 or not 0 <= offset <= 1_000_000:
        raise web.HTTPBadRequest()
    normalized = lambda s: str(s or '').casefold().replace('ё', 'е')  # noqa: E731
    needle = normalized(query.lstrip('@'))
    rows = [r for r in await people(db, settings, viewer) if not needle or any(
        needle in normalized(r[k]) for k in ('profile_name', 'telegram_name', 'username', 'user_id'))]
    rows.sort(key=lambda r: (normalized(r['profile_name'] or r['telegram_name'] or r['username']), r['user_id']))
    items = [await card(db, settings, viewer, r) for r in rows[offset:offset + 50]]
    return web.json_response({'items': items, 'total': len(rows),
                              'next_offset': offset + 50 if offset + 50 < len(rows) else None})


async def status(request):
    db, settings, viewer = request.app['db'], request.app['settings'], request['actor']['id']
    today, day = day_window()
    chat = int(getattr(settings, 'community_chat_id', 0) or 0)
    rows = await people(db, settings, viewer)
    by_id = {r['user_id']: r for r in rows}
    board = await db.daily_message_board(day.isoformat(), chat, limit=-1)
    leaders = []
    for row in board:
        if row['user_id'] in by_id:
            leaders.append({**await card(db, settings, viewer, by_id[row['user_id']]), 'messages': row['messages']})
    # Show the recipient actually credited by the existing midnight job, never guess or issue another reward.
    winner = await db.fetchone(
        "SELECT user_id FROM transactions WHERE kind='daily_chat' AND details=? AND amount>0 ORDER BY id LIMIT 1",
        (day.isoformat(),),
    )
    winner_card = None
    if winner and winner['user_id'] in by_id:
        winner_card = await card(db, settings, viewer, by_id[winner['user_id']])
    staff = []
    for row in sorted(rows, key=lambda r: (-r['rank'], str(r['profile_name'] or r['telegram_name']).casefold())):
        if row['rank'] > 0:
            staff.append({**await card(db, settings, viewer, row), 'role': row['role_name'] or row['role']})
    return web.json_response({'day': day.isoformat(), 'revision_day': today.isoformat(),
                              'timezone': 'Europe/Moscow', 'leaders': leaders, 'staff': staff,
                              'winner': winner_card, 'awarded': bool(winner)})


async def presence(request):
    rows = await people(request.app['db'], request.app['settings'], request['actor']['id'])
    ids = [r['user_id'] for r in rows if r['rank'] > 0]
    return web.json_response(await presence_map(request.app['db'], ids))
