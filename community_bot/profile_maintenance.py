"""Operator-requested, one-shot profile/onboarding reset; no public reset endpoint."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
from contextlib import closing

from community_bot.access import miniapp_allowed, private_allowed, sync_menu
from community_bot.audit import SYSTEM_ACTOR_ID
from community_bot.database import utcnow
from community_bot.profile_fill import profile_fill_percent
from community_bot.release_backup import _snapshot

logger = logging.getLogger(__name__)
REQUEST_VARIABLE = 'NORA_RESET_PROFILE_ONCE'
DEFAULTS = {
    'profile_name': None, 'age': None, 'hobbies': None, 'profile_bio': '',
    'avatar_file_id': None, 'avatar_media_type': 'photo', 'role': 'member',
    'custom_status': None, 'reputation': 69, 'warnings': 0, 'hate_immunity_until': None,
    'profile_private': 0, 'profile_ornate': 0, 'profile_title': '', 'hate_shields': 0,
    'bio_warning': 0, 'bio_auto_warn': 0,
}


def request_data(raw):
    data = json.loads(raw)
    if not isinstance(data, dict) or set(data) != {'username', 'nonce'}:
        raise ValueError('Expected username and one-shot nonce')
    username = str(data['username']).removeprefix('@').lower()
    nonce = str(data['nonce'])
    if not re.fullmatch('[a-z0-9_]{5,32}', username) or not re.fullmatch('[a-z0-9-]{8,64}', nonce):
        raise ValueError('Invalid profile reset selector')
    return username, nonce


def checked_backup(database, nonce):
    folder = database.parent / '.nora-backups'
    folder.mkdir(mode=0o700, exist_ok=True)
    folder.chmod(0o700)
    backup = folder / f'before-profile-reset-{nonce}.sqlite3'
    if not backup.exists():
        _snapshot(database, backup)
    # Verify both SQLite integrity and the requested backup's ability to restore.
    with closing(sqlite3.connect(backup)) as source, closing(sqlite3.connect(':memory:')) as restored:
        if source.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('Profile reset backup integrity check failed')
        source.backup(restored)
        if restored.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('Profile reset backup restore check failed')
    return backup


async def reset_profile(db, settings, bot, raw):
    username, nonce = request_data(raw)
    marker = 'profile_reset:'+username+':'+nonce
    if await db.get_bot_state(marker):
        return {'status': 'already_done'}
    rows = await db.fetchall('SELECT user_id FROM users WHERE lower(username)=?', (username,))
    # Configured staff may have their cached username cleared by ordinary startup.
    ids = {row['user_id'] for row in rows}
    if not ids:
        ids.update(getattr(settings, 'owner_ids', ()))
        ids.update(settings.moderator_ids)
    verified = []
    for uid in sorted(ids):
        try:
            chat = await asyncio.wait_for(bot.get_chat(uid), timeout=10)
        except Exception:
            continue
        if str(chat.username or '').lower() == username:
            verified.append(uid)
    if len(verified) != 1:
        raise ValueError('Target not uniquely verified against current Telegram username')
    uid = verified[0]
    if settings.is_owner(uid) or uid in settings.moderator_ids:
        raise ValueError('Target has a configured owner/moderator override; reset was not applied')
    backup = await asyncio.to_thread(checked_backup, db.path, nonce)
    async with db.connect() as conn:
        await conn.execute('BEGIN IMMEDIATE')
        done = await (await conn.execute('SELECT 1 FROM bot_state WHERE key=?', (marker,))).fetchone()
        if done:
            return {'status': 'already_done'}
        old = await (await conn.execute('SELECT * FROM users WHERE user_id=?', (uid,))).fetchone()
        if not old or str(old['username'] or '').lower() != username:
            raise ValueError('Target identity changed before reset; nothing changed')
        balances = (old['cookies'], old['cookie_debt'])
        now = utcnow()
        await conn.execute(
            'UPDATE users SET '+', '.join(f'{key}=?' for key in DEFAULTS)+', updated_at=? WHERE user_id=?',
            (*DEFAULTS.values(), now, uid),
        )
        archived = await conn.execute(
            "UPDATE applications SET status='reset', decision_reason=COALESCE(decision_reason,'')||? "
            "WHERE user_id=? AND status IN ('pending','approved')",
            (' | Повторное анкетирование по запросу владельца; '+nonce, uid),
        )
        await conn.execute('DELETE FROM mini_presence WHERE user_id=?', (uid,))
        result = {'status': 'done', 'user_id': uid, 'role': 'member', 'fill_percent': 0,
                  'archived_applications': archived.rowcount, 'backup': backup.name,
                  'balances_preserved': True, 'history_preserved': True}
        await conn.execute('INSERT INTO bot_state(key,value) VALUES(?,?)',
                           (marker, json.dumps(result, ensure_ascii=False)))
        await conn.execute(
            'INSERT INTO admin_audit_log('
            'actor_id,action,target,details,reason,status,actor_name,target_name,created_at) '
            'VALUES(?,?,?,?,?,?,?,?,?)',
            (SYSTEM_ACTOR_ID, 'profile_onboarding_reset', str(uid), json.dumps({'nonce': nonce, 'backup': backup.name}),
             'Сброс профиля и анкеты по запросу владельца через ChatGPT', 'yellow', 'Система', '@'+username, now),
        )
        after = await (await conn.execute('SELECT * FROM users WHERE user_id=?', (uid,))).fetchone()
        if any(after[key] != value for key, value in DEFAULTS.items()):
            raise ValueError('Profile defaults verification failed')
        if balances != (after['cookies'], after['cookie_debt']):
            raise ValueError('Profile reset must not change balances')
        await conn.commit()
    if await private_allowed(db, settings, uid) or await miniapp_allowed(db, settings, uid):
        raise ValueError('Profile reset access verification failed')
    if profile_fill_percent(await db.get_user(uid)) != 0:
        raise ValueError('Profile reset fill verification failed')
    try:
        await sync_menu(bot, db, settings, uid)
    except Exception:
        logger.warning('Profile reset menu refresh deferred until the next private interaction')
    return result


async def run_requested_reset(db, settings, bot):
    raw = os.getenv(REQUEST_VARIABLE, '').strip()
    if not raw:
        return
    try:
        result = await reset_profile(db, settings, bot, raw)
        logger.info('Requested profile reset: status=%s role=%s fill=%s balances_preserved=%s history_preserved=%s',
                    result['status'], result.get('role'), result.get('fill_percent'),
                    result.get('balances_preserved'), result.get('history_preserved'))
    except Exception as error:
        # A failed maintenance request must not interrupt the working bot. Never log credentials or rows.
        logger.error('Requested profile reset aborted: %s',
                     str(error) if isinstance(error, ValueError) else type(error).__name__)
