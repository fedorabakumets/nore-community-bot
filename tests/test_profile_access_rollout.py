import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date

import pytest

from community_bot import profile_access_rollout as rollout
from community_bot.database import Database
from community_bot.helpers import has_permission
from community_bot.profile_fields import profile_age
from community_bot.profile_fill import profile_is_complete


@dataclass(frozen=True)
class Settings:
    owner_id: int = rollout.RETAINED_OWNER_ID
    owner_ids: frozenset[int] = frozenset({rollout.RETAINED_OWNER_ID, 8})
    moderator_ids: frozenset[int] = frozenset({9})

    def is_owner(self, uid):
        return uid in self.owner_ids


def test_age_changes_on_birthday_and_accepts_leap_day():
    person = {"birth_date": "2000-02-29"}
    assert profile_age(person, date(2024, 2, 28)) == 23
    assert profile_age(person, date(2024, 2, 29)) == 24
    assert profile_age(person, date(2025, 2, 28)) == 24
    assert profile_age(person, date(2025, 3, 1)) == 25
    assert profile_age({"age": 25}) is None


async def test_reset_keeps_only_confirmed_owner_and_queues_each_notice_once(tmp_path):
    db = Database(tmp_path / "community.sqlite3")
    await db.initialize()
    for uid, role in ((rollout.RETAINED_OWNER_ID, "owner"), (8, "owner"), (9, "admin"), (10, "member")):
        await db.ensure_user(uid, username="examplebot" if uid == 10 else None)
        await db.set_role(uid, role)
        await db.execute(
            "UPDATE users SET age=30,birth_date='1996-01-01',profile_name='Имя',hobbies='Кино',"
            "profile_bio='Описание',avatar_file_id='photo' WHERE user_id=?",
            (uid,),
        )
    await db.ensure_user(9)
    await db.add_cookies(9, 50, "test")
    before = await db.get_user(9)
    assert before["cookies"] == 60

    with pytest.raises(RuntimeError, match="confirmed community owner"):
        await rollout.apply(db, Settings(owner_ids=frozenset({8})))
    assert await db.get_user(9) == before

    await rollout.prepare(db)
    settings = await rollout.apply(db, Settings())
    assert settings.owner_ids == {rollout.RETAINED_OWNER_ID} and not settings.moderator_ids
    assert await has_permission(db, settings, rollout.RETAINED_OWNER_ID, "admin.panel")
    for uid in (8, 9, 10, rollout.RETAINED_OWNER_ID):
        user = await db.get_user(uid)
        assert user["age"] is user["birth_date"] is None
        assert not profile_is_complete(user)
        assert user["role"] == ("owner" if uid == rollout.RETAINED_OWNER_ID else "member")
    assert not await has_permission(db, settings, 8, "admin.panel")
    assert not await has_permission(db, settings, 9, "admin.panel")
    assert (await db.get_user(9))["cookies"] == before["cookies"]

    backup = tmp_path / ".nora-backups" / f"before-{rollout.REQUEST}.sqlite3"
    with closing(sqlite3.connect(backup)) as saved:
        original = saved.execute("SELECT age,role FROM users WHERE user_id=9").fetchone()
    assert original == (30, "admin")

    await db.update_profile(9, "birth_date", "1996-01-01")
    await rollout.apply(db, Settings())
    assert profile_is_complete(await db.get_user(9))
    assert (await db.get_user(9))["cookies"] == before["cookies"]

    # One recipient already received the previous plain message. Do not send a second invitation.
    await db.execute("UPDATE notify_inbox SET delivered=1 WHERE user_id=8 AND channel=?", (rollout.REQUEST,))
    await rollout.queue_notices(db)
    await rollout.queue_notices(db)
    queued = await db.fetchall("SELECT recipient_id,target,details,delivery FROM widget_notifications")
    assert queued == [{
        "recipient_id": rollout.RETAINED_OWNER_ID, "target": "lk", "details": rollout.NOTICE,
        "delivery": "inbox_queued",
    }]
    rows = await db.fetchall("SELECT user_id FROM notify_inbox WHERE channel=?", (rollout.REQUEST,))
    assert {row["user_id"] for row in rows} == {8, rollout.RETAINED_OWNER_ID}
