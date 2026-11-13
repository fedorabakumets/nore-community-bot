"""One-time profile and role reset for the opening of the Mini App."""
from __future__ import annotations

import logging
from dataclasses import replace
from time import time

from community_bot.community_reset import RETAINED_OWNER_ID
from community_bot.database import utcnow
from community_bot.profile_fill import profile_is_complete
from community_bot.release_backup import verify_requested_release_backup
from community_bot.rsvp import event_lock

logger = logging.getLogger(__name__)
REQUEST = "profile-access-20261111"
MARKER = f"maintenance:{REQUEST}"
NOTICE = ("Вам открыт доступ к Норе! Заполните профиль и укажите дату рождения, "
          "чтобы открыть Комьюнити и другие разделы.")


async def prepare(db):
    if db.path.is_file():
        await verify_requested_release_backup(db, request=REQUEST)


async def apply(db, settings):
    if not settings.is_owner(RETAINED_OWNER_ID):
        raise RuntimeError("Profile rollout requires the confirmed community owner")
    restricted = replace(settings, owner_id=RETAINED_OWNER_ID,
                         owner_ids=frozenset({RETAINED_OWNER_ID}), moderator_ids=frozenset())
    if await db.get_bot_state(MARKER):
        return restricted

    # Also enforce the backup requirement when this operation is called directly.
    await prepare(db)
    now = utcnow()
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        done = await (await conn.execute("SELECT 1 FROM bot_state WHERE key=?", (MARKER,))).fetchone()
        if not done:
            await conn.execute(
                "UPDATE users SET age=NULL, birth_date=NULL, "
                "role=CASE WHEN user_id=? THEN 'owner' ELSE 'member' END",
                (RETAINED_OWNER_ID,),
            )
            await conn.execute(
                """INSERT INTO notify_inbox(user_id,channel,text,created_at)
                   SELECT user_id,?,?,? FROM users WHERE user_id>0
                   AND lower(COALESCE(username,'')) NOT LIKE '%bot'
                   AND NOT EXISTS (SELECT 1 FROM bot_state
                                   WHERE key='telegram_is_bot:' || users.user_id AND value='1')""",
                (REQUEST, NOTICE, now),
            )
            await conn.execute(
                "INSERT INTO admin_audit_log(actor_id,action,target,details,created_at) VALUES(?,?,?,?,?)",
                (RETAINED_OWNER_ID, "profile_access_reset", "all", REQUEST, now),
            )
            await conn.execute("INSERT INTO bot_state(key,value) VALUES(?, '1')", (MARKER,))
            await conn.commit()
            logger.info("Profile access rollout applied; participant notifications queued")
    return restricted


async def dismiss_profile_notice(db, uid):
    from community_bot.widget_inbox import UNREAD, schedule_after_read

    async with event_lock(db, f"widget-inbox:{uid}"):
        async with db.connect() as conn:
            await conn.execute("BEGIN IMMEDIATE")
            await conn.execute("DELETE FROM notify_inbox WHERE user_id=? AND channel=?", (uid, REQUEST))
            now = int(time())
            read = await conn.execute(
                "UPDATE widget_notifications SET read_at=?,next_action_at=NULL,"
                "delivery=CASE WHEN delivery='inbox_open' THEN delivery ELSE 'inbox_read' END "
                f"WHERE recipient_id=? AND category='widget_personal' AND event_key=? AND ({UNREAD}"
                " OR (delivery='inbox_unconfirmed' AND read_at IS NULL))",
                (now, uid, REQUEST),
            )
            if read.rowcount:
                anchor = await (await conn.execute(
                    "SELECT id FROM widget_notifications WHERE recipient_id=? AND delivery='inbox_open'", (uid,),
                )).fetchone()
                if anchor:
                    await schedule_after_read(conn, uid, anchor["id"], now, delay=0)
            await conn.commit()


async def clear_profile_notice_if_read(conn, uid):
    await conn.execute(
        "DELETE FROM notify_inbox WHERE user_id=? AND channel=? AND EXISTS ("
        "SELECT 1 FROM widget_notifications WHERE recipient_id=? AND category='widget_personal' "
        "AND event_key=? AND read_at IS NOT NULL)",
        (uid, REQUEST, uid, REQUEST),
    )


async def queue_notices(db):
    rows = await db.fetchall(
        "SELECT users.* FROM notify_inbox JOIN users USING(user_id) WHERE notify_inbox.channel=?", (REQUEST,),
    )
    if not rows:
        return
    await verify_requested_release_backup(db, request="profile-notice-widget-20261111")
    for user in rows:
        if profile_is_complete(user):
            await dismiss_profile_notice(db, user["user_id"])

    now = int(time())
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        # Upgrade only messages not already delivered by the previous release.
        await conn.execute(
            """INSERT INTO widget_notifications(
                   id,recipient_id,sender_type,sender_label,title,preview,details,
                   category,target,context,event_at,event_key,created_at,delivery,next_action_at)
               SELECT lower(hex(randomblob(16))),user_id,'nora','Нора','Вам открыт доступ к Норе',
                      text,text,'widget_personal','lk','',created_at,channel,?,'inbox_queued',?
               FROM notify_inbox WHERE channel=? AND delivered=0
               ON CONFLICT(recipient_id,category,event_key) DO NOTHING""",
            (now, now, REQUEST),
        )
        await conn.execute("UPDATE notify_inbox SET delivered=1 WHERE channel=? AND delivered=0", (REQUEST,))
        await conn.commit()
