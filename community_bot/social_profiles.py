"""Public profile visits and foreground-only Mini App presence, never Telegram online status."""

from __future__ import annotations

import html
import json
import math
import re
import time
from io import BytesIO
from uuid import uuid4

from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiohttp import ClientError, web

from community_bot.friends_api import _recipient, accepted
from community_bot.helpers import can_view_profile, effective_role, role_title
from community_bot.music_library import (
    add_resolved_track,
    can_read_library,
    change_collection,
    get_collection,
    is_public,
    public_track,
    saved_track_summary,
    set_public,
    track_id,
)
from community_bot.profile_fields import profile_age
from community_bot.profile_track import get_track, track_key
from community_bot.track_disk_cache import TrackResponse

SCHEMA = """
CREATE TABLE IF NOT EXISTS mini_presence (
 user_id INTEGER NOT NULL REFERENCES users(user_id), session TEXT NOT NULL,
 seq INTEGER NOT NULL, active INTEGER NOT NULL CHECK(active IN (0,1)), seen_at REAL NOT NULL,
 PRIMARY KEY(user_id,session)
);
CREATE INDEX IF NOT EXISTS mini_presence_seen ON mini_presence(user_id,seen_at);
CREATE TABLE IF NOT EXISTS mini_presence_settings (
 user_id INTEGER PRIMARY KEY REFERENCES users(user_id), hidden INTEGER NOT NULL CHECK(hidden IN (0,1))
);
"""
TTL = 60


async def privacy(db, uid):
    row = await db.fetchone("SELECT hidden FROM mini_presence_settings WHERE user_id=?", (uid,))
    return bool(row and row["hidden"])


async def heartbeat(db, uid, session, seq, active, now=None):
    if (
        not isinstance(session, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", session)
        or type(seq) is not int
        or not 0 <= seq <= 2**31 - 1
        or type(active) is not bool
    ):
        raise ValueError("Некорректный статус активности")
    now = time.time() if now is None else now
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        if not await (await conn.execute("SELECT 1 FROM users WHERE user_id=?", (uid,))).fetchone():
            raise ValueError("Сначала открой личный кабинет")
        row = await (
            await conn.execute("SELECT seq FROM mini_presence WHERE user_id=? AND session=?", (uid, session))
        ).fetchone()
        if row and row["seq"] >= seq:
            return
        if not row and not active:
            return
        if not row:
            # A user cannot grow the presence table by opening arbitrary session IDs.
            await conn.execute(
                "DELETE FROM mini_presence WHERE user_id=? AND session NOT IN "
                "(SELECT session FROM mini_presence WHERE user_id=? ORDER BY seen_at DESC LIMIT 4)",
                (uid, uid),
            )
        await conn.execute(
            "INSERT INTO mini_presence VALUES(?,?,?,?,?) ON CONFLICT(user_id,session) DO UPDATE SET "
            "seq=excluded.seq,active=excluded.active,seen_at=excluded.seen_at",
            (uid, session, seq, int(active), now),
        )
        await conn.commit()


async def presence_map(db, ids, now=None):
    if not ids:
        return {}
    now = time.time() if now is None else now
    marks = ",".join("?" for _ in ids)
    rows = await db.fetchall(
        "SELECT u.user_id,u.profile_private,COALESCE(s.hidden,0) hidden,MAX(p.seen_at) last_seen,"
        "MAX(CASE WHEN p.active=0 THEN p.seen_at END) last_exit,"
        "MAX(CASE WHEN p.active=1 AND p.seen_at>? THEN 1 ELSE 0 END) online "
        "FROM users u LEFT JOIN mini_presence p ON p.user_id=u.user_id "
        "LEFT JOIN mini_presence_settings s ON s.user_id=u.user_id "
        f"WHERE u.user_id IN ({marks}) GROUP BY u.user_id",
        (now - TTL, *ids),
    )
    return {
        row["user_id"]: {
            "visible": not bool(row["hidden"] or row["profile_private"]),
            "online": bool(row["online"]) if not row["hidden"] and not row["profile_private"] else False,
            "last_seen": row["last_seen"] if not row["hidden"] and not row["profile_private"] else None,
            "last_exit": row["last_exit"] if not row["hidden"] and not row["profile_private"] else None,
        }
        for row in rows
    }


async def status(request):
    return web.json_response({"hidden": await privacy(request.app["db"], request["actor"]["id"]), "ttl": TTL})


async def update(request):
    body = await request.json()
    if not isinstance(body, dict):
        raise ValueError("Некорректный запрос активности")
    db, uid = request.app["db"], request["actor"]["id"]
    if not await db.get_user(uid):
        from community_bot.miniapp import actor

        await actor(request)
    if set(body) == {"hidden"} and type(body["hidden"]) is bool:
        await db.execute(
            "INSERT INTO mini_presence_settings VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET hidden=excluded.hidden",
            (uid, int(body["hidden"])),
        )
    elif set(body) == {"session", "seq", "active"}:
        await heartbeat(db, uid, body["session"], body["seq"], body["active"])
    else:
        raise ValueError("Некорректные поля активности")
    return web.json_response({"ok": True})


async def target_for(request):
    db, uid = request.app["db"], request["actor"]["id"]
    raw = request.match_info.get("user_id")
    if raw is None:
        target = await _recipient(db, request.query.get("recipient"))
    elif not raw.isdigit() or len(raw) > 16 or int(raw) <= 0:
        raise web.HTTPNotFound()
    else:
        target = int(raw)
    row = await db.get_user(target)
    from community_bot.bot_identity import is_bot

    bot = request.app.get('bot')
    if not row or await is_bot(db, row, getattr(bot, 'id', None)):
        raise web.HTTPNotFound()
    block = await db.fetchone(
        "SELECT 1 FROM mini_friend_blocks WHERE (blocker_id=? AND blocked_id=?) OR (blocker_id=? AND blocked_id=?)",
        (uid, target, target, uid),
    )
    if block and uid != target:
        raise web.HTTPNotFound()
    return row


async def profile(request):
    from community_bot.domain import reputation_tier

    db, uid, settings = request.app["db"], request["actor"]["id"], request.app["settings"]
    target = await target_for(request)
    from community_bot.role_prefixes import prefix_for

    friend = await accepted(db, uid, target["user_id"])
    result = {
        "id": target["user_id"],
        "prefix": await prefix_for(db, settings, target["user_id"]),
        "name": target["profile_name"] or target["telegram_name"] or "Участник",
        "username": target["username"],
        "friend": friend,
        "hidden": True,
        "private": bool(target["profile_private"]),
    }
    if not await can_view_profile(db, settings, uid, target):
        return web.json_response(result)
    # Public presence is visible to every viewer, but per-user settings and
    # profile_private are enforced by presence_map before any timestamps leave the server.
    presence = (await presence_map(db, [target["user_id"]]))[target["user_id"]]
    result.update(
        hidden=False,
        private=bool(target["profile_private"]),
        age=profile_age(target),
        city=target.get('city'),
        tg_channel_url=target.get('tg_channel_url') or '',
        role=await role_title(db, await effective_role(db, settings, target["user_id"])),
        has_avatar=bool(target["avatar_file_id"] and target["avatar_media_type"] == "photo"),
        presence=presence,
    )
    if not target["profile_private"] or uid == target["user_id"]:
        from community_bot.profile_theme import appearance

        likes, theme = await appearance(db, target["user_id"])
        tier = reputation_tier(target["reputation"], settings.restricted_reputation_threshold)
        result.update(bio=target["profile_bio"], hobbies=target["hobbies"],
                      reputation=target["reputation"], tier=tier.label, cookies=target["cookies"],
                      likes=likes, theme=theme,
                      track=await saved_track_summary(db, uid, await get_track(db, target["user_id"])),
                      music_library_public=await can_read_library(db, settings, uid, target["user_id"]))
    return web.json_response(result)


def thumbnail(photo):
    from PIL import Image

    with Image.open(BytesIO(photo)) as source:
        source.thumbnail((96, 96))
        output = BytesIO()
        source.save(output, format="JPEG", quality=82)
        return output.getvalue()


async def avatar(request):
    from community_bot.media_cache import images

    target = await target_for(request)
    if not await can_view_profile(request.app["db"], request.app["settings"], request["actor"]["id"], target):
        raise web.HTTPForbidden()
    if not target["avatar_file_id"] or target["avatar_media_type"] != "photo":
        raise web.HTTPNotFound()
    try:
        photo = await images(request).avatar(target["avatar_file_id"], thumb=request.query.get("size") == "thumb")
        fresh = await target_for(request)
        if not await can_view_profile(request.app["db"], request.app["settings"], request["actor"]["id"], fresh):
            raise web.HTTPForbidden()
        if fresh["avatar_file_id"] != target["avatar_file_id"] or fresh["avatar_media_type"] != "photo":
            raise web.HTTPNotFound()
    except (TelegramAPIError, ValueError):
        raise web.HTTPNotFound() from None
    return web.Response(body=photo, content_type="image/jpeg")


async def _profile_track_target(request):
    if request.path == "/api/profile/track":
        target = await request.app["db"].get_user(request["actor"]["id"])
        if not target:
            raise web.HTTPNotFound()
        return target
    target = await target_for(request)
    if target["profile_private"] and target["user_id"] != request["actor"]["id"]:
        raise web.HTTPNotFound()
    return target


async def track_audio(request):
    db, bot = request.app["db"], request.app.get("bot")
    target = await _profile_track_target(request)
    track = await get_track(db, target["user_id"])
    if not bot or not track or track["revision"] != request.query.get("v"):
        raise web.HTTPNotFound()
    if request.query.get("check") == "1":
        return web.Response(status=204)
    try:
        lease = await request.app["track_disk_cache"].open_track(bot, track)
    except (TelegramAPIError, ClientError, OSError, ValueError):
        raise web.HTTPBadGateway() from None
    try:
        fresh = await _profile_track_target(request)
        latest = await get_track(db, fresh["user_id"])
        if not latest or latest["revision"] != track["revision"] or latest["file_id"] != track["file_id"]:
            raise web.HTTPNotFound()
        return TrackResponse(lease, track["mime"], request.headers)
    except BaseException:
        lease.close()
        raise


async def save_profile_track(request):
    db, settings, uid = request.app["db"], request.app["settings"], request["actor"]["id"]
    target = await db.get_user(uid) if request.path == "/api/profile/track/save" else await target_for(request)
    if not target or (uid != target["user_id"] and (
        target["profile_private"] or not await can_view_profile(db, settings, uid, target)
    )):
        raise web.HTTPNotFound()
    payload = await request.json()
    if (not isinstance(payload, dict) or type(payload.get("saved")) is not bool
            or not isinstance(payload.get("revision"), str)):
        raise web.HTTPBadRequest()
    try:
        result = await change_collection(
            db, uid, target_id=target["user_id"], revision=payload["revision"], saved=payload["saved"],
        )
    except ValueError as error:
        return web.json_response({"error": str(error)}, status=409)
    return web.json_response(result)


async def music_library(request):
    from community_bot.music_discovery import SOCIAL_PREFIX

    db, uid = request.app["db"], request["actor"]["id"]
    if request.method == "POST":
        payload = await request.json()
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest()
        try:
            result = await change_collection(db, uid, key=payload.get("id"), saved=False)
        except ValueError as error:
            return web.json_response({"error": str(error)}, status=400)
        return web.json_response(result)
    entries = await get_collection(db, uid)
    return web.json_response({
        "public": await is_public(db, uid),
        "activity_public": await db.get_bot_state(SOCIAL_PREFIX + str(uid)) == "1",
        "tracks": [public_track(key, track) for key, track in reversed(list(entries.items()))],
    })


async def library_audio(request):
    db, bot, uid = request.app["db"], request.app.get("bot"), request["actor"]["id"]
    key = request.match_info["track_id"]
    owner = uid
    if "user_id" in request.match_info:
        owner = (await target_for(request))["user_id"]
        if not await can_read_library(db, request.app["settings"], uid, owner):
            raise web.HTTPNotFound()
    track = (await get_collection(db, owner)).get(key)
    if not bot or not track or track["revision"] != request.query.get("v"):
        raise web.HTTPNotFound()
    if request.query.get("check") == "1":
        return web.Response(status=204)
    try:
        lease = await request.app["track_disk_cache"].open_track(bot, track)
    except (TelegramAPIError, ClientError, OSError, ValueError):
        raise web.HTTPBadGateway() from None
    try:
        latest = (await get_collection(db, owner)).get(key)
        if (not latest or latest["revision"] != track["revision"] or latest["file_id"] != track["file_id"]
                or not await can_read_library(db, request.app["settings"], uid, owner)):
            raise web.HTTPNotFound()
        return TrackResponse(lease, track["mime"], request.headers)
    except BaseException:
        lease.close()
        raise


async def library_visibility(request):
    db, uid = request.app["db"], request["actor"]["id"]
    payload = await request.json()
    if not isinstance(payload, dict) or type(payload.get("public")) is not bool:
        raise web.HTTPBadRequest()
    await set_public(db, uid, payload["public"])
    return web.json_response({"public": payload["public"]})


async def public_music_library(request):
    db, uid = request.app["db"], request["actor"]["id"]
    target = await target_for(request)
    owner = target["user_id"]
    if not await can_read_library(db, request.app["settings"], uid, owner):
        raise web.HTTPNotFound()
    entries = await get_collection(db, owner)
    return web.json_response({"tracks": [
        public_track(key, track) for key, track in reversed(list(entries.items()))
    ]})


async def _share_track_source(db, settings, uid, source, revision):
    """Resolve only an authorized, current audio reference; never accept a file ID from the client."""
    from community_bot import music_artist

    if isinstance(source, str) and source.startswith(music_artist.SOURCE):
        return music_artist.resolve(source, revision)
    if isinstance(source, str) and source.startswith(("/api/music-library/history/", "/api/music-library/social/")):
        from community_bot.music_discovery import resolve

        return await resolve(db, uid, source, revision)
    match = re.fullmatch(
        r"/api/(?:(?:people/([1-9][0-9]{0,15})/)?(track|music-library/[a-f0-9]{64})|profile/track)",
        source,
    ) if isinstance(source, str) else None
    if not match or not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{32}", revision):
        raise web.HTTPBadRequest()
    owner = int(match.group(1)) if match.group(1) else uid
    target = await db.get_user(owner)
    if not target:
        return None
    library = (match.group(2) or "").startswith("music-library/")
    if owner != uid:
        if target["profile_private"] or not await can_view_profile(db, settings, uid, target):
            return None
        if await db.fetchone(
            "SELECT 1 FROM mini_friend_blocks WHERE (blocker_id=? AND blocked_id=?) "
            "OR (blocker_id=? AND blocked_id=?)",
            (uid, owner, owner, uid),
        ):
            return None
    if library:
        if not await can_read_library(db, settings, uid, owner):
            return None
        track = (await get_collection(db, owner)).get(match.group(2).split("/")[1])
    else:
        track = await get_track(db, owner)
    return track if track and track["revision"] == revision else None


# Only the caller's recently unliked library audio can remain actionable in
# the in-memory player. It is never returned by the library or audio routes.
_PLAYER_UNDO = {}
_PLAYER_UNDO_TTL = 7200
_PLAYER_UNDO_LIMIT = 1024


async def _player_track_source(db, settings, uid, source, revision):
    track = await _share_track_source(db, settings, uid, source, revision)
    if track:
        return track
    if isinstance(source, str) and re.fullmatch(r"/api/music-library/[a-f0-9]{64}", source):
        cached = _PLAYER_UNDO.get((uid, source, revision))
        if cached and cached[0] > time.monotonic():
            return cached[1]
    return None


def _remember_unliked(uid, source, revision, track):
    if source != "/api/music-library/" + track_id(track):
        return
    now = time.monotonic()
    for key, entry in list(_PLAYER_UNDO.items()):
        if entry[0] <= now:
            _PLAYER_UNDO.pop(key, None)
    key = (uid, source, revision)
    _PLAYER_UNDO.pop(key, None)
    _PLAYER_UNDO[key] = (now + _PLAYER_UNDO_TTL, track)
    while len(_PLAYER_UNDO) > _PLAYER_UNDO_LIMIT:
        _PLAYER_UNDO.pop(next(iter(_PLAYER_UNDO)))


async def current_track_collection(request):
    """Check, like/unlike, or independently pin an authorized playable track."""
    db, settings, uid = request.app["db"], request.app["settings"], request["actor"]["id"]
    payload = await request.json() if request.method == "POST" else request.query
    if request.method == "POST" and not isinstance(payload, dict):
        raise web.HTTPBadRequest()
    source, revision = payload.get("source"), payload.get("revision")
    track = await _player_track_source(db, settings, uid, source, revision)
    if not track:
        return web.json_response({"error": "Трек изменился или больше недоступен"}, status=404)
    key = track_id(track)
    profile = await get_track(db, uid)
    result = {"id": key, "in_profile": bool(profile and track_id(profile) == key)}
    if request.method == "POST":
        action = payload.get("action", "like")
        if action == "profile":
            if not result["in_profile"]:
                profile = {**track, "revision": uuid4().hex}
                await db.set_bot_state(track_key(uid), json.dumps(profile, ensure_ascii=False))
            result["in_profile"] = True
            result["profile_track"] = await saved_track_summary(db, uid, profile)
        elif action == "like":
            saved = payload.get("saved", True)
            if type(saved) is not bool:
                raise web.HTTPBadRequest()
            if saved:
                await add_resolved_track(db, uid, track)
                _PLAYER_UNDO.pop((uid, source, revision), None)
                result["track"] = public_track(key, track)
            else:
                await change_collection(db, uid, key=key, saved=False)
                _remember_unliked(uid, source, revision, track)
        else:
            raise web.HTTPBadRequest()
    result["saved"] = key in await get_collection(db, uid)
    return web.json_response(result)


async def share_track(request):
    """Send the selected track as a native Telegram audio in the configured community."""
    from aiogram.types import FSInputFile

    from community_bot.group_message_close import without_group_close
    from community_bot.music_api import CHAT_COOLDOWN, COOLDOWN, save
    from community_bot.reply_rich import bot_publication

    db, settings, uid = request.app["db"], request.app["settings"], request["actor"]["id"]
    bot = request.app.get("bot")
    chat = getattr(settings, "community_chat_id", 0)
    user = await db.get_user(uid)
    if not bot or not chat:
        return web.json_response({"error": "Чат Норы пока недоступен"}, status=503)
    if not user or int(user["reputation"]) < getattr(settings, "restricted_reputation_threshold", 50):
        return web.json_response({"error": "Репутация ниже бронзы: писать в чат нельзя"}, status=403)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise web.HTTPBadRequest()
    source, revision = payload.get("source"), payload.get("revision")
    track = await _player_track_source(db, settings, uid, source, revision)
    if not track:
        return web.json_response({"error": "Трек изменился или больше недоступен"}, status=404)
    try:
        member = await bot.get_chat_member(chat, uid)
        if member.status not in {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR,
                                 ChatMemberStatus.CREATOR, ChatMemberStatus.RESTRICTED} or (
            member.status == ChatMemberStatus.RESTRICTED and not (
                member.is_member and member.can_send_messages and member.can_send_audios
            )
        ):
            return web.json_response({"error": "Сейчас отправлять музыку в чат нельзя"}, status=403)
        if member.status == ChatMemberStatus.MEMBER:
            group = await bot.get_chat(chat)
            permissions = getattr(group, "permissions", None)
            if permissions and (permissions.can_send_audios is False or permissions.can_send_messages is False):
                return web.json_response({"error": "В чате отключена отправка музыки"}, status=403)
    except TelegramAPIError:
        return web.json_response({"error": "Не удалось проверить доступ к чату"}, status=503)
    # Recheck privacy/revision after the Telegram membership request.
    track = await _player_track_source(db, settings, uid, source, revision)
    if not track:
        return web.json_response({"error": "Трек изменился или больше недоступен"}, status=404)
    # Use the existing music-send limits, shared with the seasonal music feature.
    now = time.time()
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        for key, cooldown in ((f"nora_music_send:{uid}", COOLDOWN), ("nora_music_chat", CHAT_COOLDOWN)):
            row = await (await conn.execute("SELECT value FROM bot_state WHERE key=?", (key,))).fetchone()
            remaining = math.ceil(float(row["value"]) + cooldown - now) if row else 0
            if remaining > 0:
                return web.json_response(
                    {"error": f"Подожди {remaining} сек. перед отправкой музыки", "retry_after": remaining},
                    status=429,
                )
        await save(conn, f"nora_music_send:{uid}", now)
        await save(conn, "nora_music_chat", now)
        await conn.commit()
    name = html.escape(str(user.get("profile_name") or user.get("telegram_name") or "Участник")[:80])
    lease = None
    try:
        media = track["file_id"]
        from community_bot.music_artist import release_paths

        local = release_paths().get(media)
        if local:
            media = FSInputFile(local)
        elif media.startswith("catalog:"):
            lease = await request.app["track_disk_cache"].open_track(bot, track)
            # Recheck source after a possible external download.
            if not await _player_track_source(db, settings, uid, source, revision):
                return web.json_response({"error": "Трек больше недоступен"}, status=404)
            media = FSInputFile(lease.file.name, filename="track.mp3")
        with bot_publication(), without_group_close():
            await bot.send_audio(
                chat_id=chat, audio=media, title=track["title"],
                performer=track["artist"] or None, duration=track["duration"],
                caption=f'🎧 <b><a href="tg://user?id={uid}">{name}</a></b> поделился треком',
                parse_mode="HTML",
            )
    except (TelegramAPIError, OSError, TimeoutError, ValueError):
        # Keep the reservation: Telegram may have accepted a timed-out request.
        return web.json_response(
            {"error": "Отправка не подтверждена. Проверь чат перед повтором"}, status=502,
        )
    finally:
        if lease:
            lease.close()
    return web.json_response({"sent": True, "message": "Трек отправлен в чат", "retry_after": COOLDOWN})
