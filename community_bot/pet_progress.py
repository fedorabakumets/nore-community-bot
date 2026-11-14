"""Persistent pet development. Write helpers run inside the caller's SQLite transaction."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta, timezone

MSK = timezone(timedelta(hours=3), "МСК")
QUEST_XP = 50
STAGE_XP = 100
DAILY_XP = 100
TEXT_INTERVAL = 5
TEXT_MIN_LENGTH = 3
LEVELS = ("Компаньон", "Собеседник", "Помощник")
AI_STAGE = 5
VIDEO_STAGE = 10
VIDEO_DAILY_LIMIT = 5
VIDEO_MAX_MB = 45
REWARDS = (
    ("unlock", 1, "Базовый уход и походы"),
    ("cookies", 5, "5 печенек"),
    ("meal", 1, "Бесплатный обед"),
    ("cookies", 10, "10 печенек"),
    ("unlock", 2, "Доступ к ИИ Норе"),
    ("drink", 1, "Бесплатная поилка"),
    ("reputation", 10, "+10 репутации"),
    ("mood", 100, "Настроение до 100"),
    ("cookies", 10, "10 печенек"),
    ("unlock", 3, "Загрузка видео"),
)
CONSUMABLES = {"meal": "hunger", "drink": "thirst", "mood": "mood"}
MEDIA_LABELS = {
    "voice": "Отправь голосовое", "circle": "Отправь кружок", "photo": "Отправь фото",
    "video": "Отправь видео", "media": "Отправь аудио, GIF или документ",
}
ACTIVITY_MILESTONES = (50, 100)
TEXT_TARGET = 10
SCHEMA = """
CREATE TABLE IF NOT EXISTS pet_development (
    user_id INTEGER PRIMARY KEY REFERENCES pets(user_id) ON DELETE CASCADE,
    level INTEGER NOT NULL DEFAULT 1,
    stage INTEGER NOT NULL DEFAULT 1,
    xp INTEGER NOT NULL DEFAULT 0,
    advanced_on TEXT,
    messages INTEGER NOT NULL DEFAULT 0,
    last_text_hash TEXT,
    last_text_at INTEGER
);
CREATE TABLE IF NOT EXISTS pet_quest_days (
    user_id INTEGER NOT NULL REFERENCES pet_development(user_id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    xp INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
);
CREATE TABLE IF NOT EXISTS pet_quests (
    user_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    slot INTEGER NOT NULL,
    label TEXT NOT NULL,
    events TEXT NOT NULL,
    target INTEGER NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    xp INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day, slot),
    FOREIGN KEY (user_id, day) REFERENCES pet_quest_days(user_id, day) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS pet_quest_events (
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL REFERENCES pet_development(user_id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    PRIMARY KEY (chat_id, message_id)
);
CREATE INDEX IF NOT EXISTS pet_quest_events_day ON pet_quest_events(day);
CREATE TABLE IF NOT EXISTS pet_stage_rewards (
    user_id INTEGER NOT NULL REFERENCES pet_development(user_id) ON DELETE CASCADE,
    stage INTEGER NOT NULL,
    kind TEXT NOT NULL,
    amount INTEGER NOT NULL,
    awarded_at TEXT NOT NULL,
    used_at TEXT,
    PRIMARY KEY (user_id, stage)
);
"""


async def one(db, sql, args=()):
    return await (await db.execute(sql, args)).fetchone()


def moscow_now(now=None):
    return (now or datetime.now(UTC)).astimezone(MSK)


def level_for(stage):
    return 3 if stage >= VIDEO_STAGE else 2 if stage >= AI_STAGE else 1


async def level(db, user_id):
    row = await db.fetchone("SELECT level FROM pet_development WHERE user_id=?", (user_id,))
    return row["level"] if row else 0


async def ensure_pet(db, user_id, stamp):
    await db.execute(
        "INSERT OR IGNORE INTO pet_development(user_id) SELECT user_id FROM pets WHERE user_id=?",
        (user_id,),
    )
    await db.execute(
        "INSERT OR IGNORE INTO pet_stage_rewards SELECT user_id,1,'unlock',1,?,? "
        "FROM pet_development WHERE user_id=?",
        (stamp, stamp, user_id),
    )
    return await one(db, "SELECT * FROM pet_development WHERE user_id=?", (user_id,))


async def ensure_day(db, user_id, now):
    day = now.date().isoformat()
    inserted = await db.execute("INSERT OR IGNORE INTO pet_quest_days VALUES (?,?,0)", (user_id, day))
    if not inserted.rowcount:
        return day

    # Telegram retry windows are shorter than this retention window. Reject stale deliveries too.
    await db.execute("DELETE FROM pet_quest_events WHERE day < ?", ((now.date() - timedelta(days=2)).isoformat(),))
    flags = dict(await (await db.execute(
        "SELECT key,enabled FROM feature_flags WHERE key IN ('media_filter')"
    )).fetchall())
    cycle = now.date().toordinal() + user_id
    activity = (f"Общайся в основном чате · {TEXT_TARGET} сообщений", "text", TEXT_TARGET)
    if not flags.get("media_filter") and cycle % 3:
        media = list(MEDIA_LABELS)[(cycle - cycle // 3) % len(MEDIA_LABELS)]
        activity = (f"{MEDIA_LABELS[media]} в основном чате", media, 1)

    # Either action in a pair can complete it. A single event counts only once.
    care = (
        ("Погладь питомца или отправь в поход", "stroke,expedition"),
        ("Покорми или напои питомца", "food,water"),
        ("Отправь питомца в поход или напои его", "expedition,water"),
        ("Покорми или погладь питомца", "food,stroke"),
    )[cycle % 4]
    if activity[1] != "text":
        extra = (f"Поддержи участника или напиши {TEXT_TARGET} сообщений", "text,plus,minus,transfer", TEXT_TARGET)
    else:
        media = ("voice,circle,photo,video,media" if not flags.get("media_filter") else "")
        extra = (
            "Поддержи участника, переведи печеньку или отправь медиа"
            if media else "Поддержи участника, переведи печеньку или позаботься о питомце",
            f"plus,minus,transfer,{media or 'food,water,stroke,expedition'}", 1,
        )
    rows = (activity, (*care, 1), extra)
    await db.executemany(
        "INSERT INTO pet_quests(user_id,day,slot,label,events,target) VALUES (?,?,?,?,?,?)",
        ((user_id, day, slot, label, events, target) for slot, (label, events, target) in enumerate(rows, 1)),
    )
    return day


async def award(db, user_id, stage, stamp):
    from community_bot.database import Database

    kind, value, _ = REWARDS[stage - 1]
    used = None if kind in CONSUMABLES else stamp
    inserted = await db.execute(
        "INSERT OR IGNORE INTO pet_stage_rewards VALUES (?,?,?,?,?,?)",
        (user_id, stage, kind, value, stamp, used),
    )
    if not inserted.rowcount:
        return
    if kind == "cookies":
        await Database._add_cookies(db, user_id, value, "pet_stage", str(stage), stamp)
    if kind == "reputation":
        applied = await Database._change_reputation_value(db, user_id, value, stamp)
        await db.execute(
            "UPDATE pet_stage_rewards SET amount=? WHERE user_id=? AND stage=?", (applied, user_id, stage),
        )


async def record(db, user_id, event, *, now=None, message=None):
    """Record a successful action or a moderated Telegram message. No client event input."""
    now = moscow_now(now)
    stamp = now.astimezone(UTC).isoformat()
    if not await one(db, "SELECT 1 FROM feature_flags WHERE key='tamagotchi' AND enabled=1"):
        return
    state = await ensure_pet(db, user_id, stamp)
    if not state:
        return
    day = await ensure_day(db, user_id, now)
    if message:
        chat_id, message_id, sent_at, text = message
        if sent_at.astimezone(MSK).date() != now.date():
            return
        event_row = await db.execute(
            "INSERT OR IGNORE INTO pet_quest_events VALUES (?,?,?,?)", (chat_id, message_id, user_id, day),
        )
        if not event_row.rowcount:
            return
        if event == "text":
            digest = hashlib.sha256(text.encode()).hexdigest()
            timestamp = int(sent_at.timestamp())
            if state["last_text_hash"] == digest or timestamp - (state["last_text_at"] or 0) < TEXT_INTERVAL:
                return
            await db.execute(
                "UPDATE pet_development SET last_text_hash=?, last_text_at=?, messages=messages+1 WHERE user_id=?",
                (digest, timestamp, user_id),
            )

    daily = await one(db, "SELECT xp FROM pet_quest_days WHERE user_id=? AND day=?", (user_id, day))
    quests = await (await db.execute(
        "SELECT * FROM pet_quests WHERE user_id=? AND day=? AND progress<target ORDER BY slot", (user_id, day),
    )).fetchall()
    for quest in quests:
        if event not in quest["events"].split(","):
            continue
        progress = quest["progress"] + 1 if event == "text" else quest["target"]
        xp = min(QUEST_XP, DAILY_XP - daily["xp"]) if progress == quest["target"] else 0
        if state["stage"] == len(REWARDS):
            xp = 0
        await db.execute(
            "UPDATE pet_quests SET progress=?,xp=? WHERE user_id=? AND day=? AND slot=?",
            (progress, xp, user_id, day, quest["slot"]),
        )
        if xp:
            await db.execute("UPDATE pet_quest_days SET xp=xp+? WHERE user_id=? AND day=?", (xp, user_id, day))
            stage, total = state["stage"], state["xp"] + xp
            advanced = state["advanced_on"]
            if total >= STAGE_XP and advanced != day:
                stage += 1
                total = 0 if stage == len(REWARDS) else total - STAGE_XP
                advanced = day
                await award(db, user_id, stage, stamp)
            await db.execute(
                "UPDATE pet_development SET level=?,stage=?,xp=?,advanced_on=? WHERE user_id=?",
                (level_for(stage), stage, total, advanced, user_id),
            )
        break


async def record_message(database, message):
    from community_bot.aliases import is_command_message
    from community_bot.nora import strip_address

    user = message.from_user
    if not user or user.is_bot or message.sender_chat or message.via_bot or message.forward_origin:
        return
    text = " ".join((message.text or "").casefold().split())
    if message.text:
        if (len(text) < TEXT_MIN_LENGTH or text.startswith(("/", "+", "-", "−"))
                or is_command_message(text, include_disabled=True) or strip_address(text) is not None):
            return
        event = "text"
    else:
        event = next((kind for kind, value in (
            ("voice", message.voice), ("circle", message.video_note), ("photo", message.photo),
            ("video", message.video), ("media", message.document or message.audio or message.animation),
        ) if value), None)
        if not event:
            return
    # Fast path for participants without a pet.
    if not await database.get_pet(user.id, settle=False):
        return
    async with database.connect() as db:
        await db.execute("BEGIN IMMEDIATE")
        await record(db, user.id, event, message=(message.chat.id, message.message_id, message.date, text))
        await db.commit()


async def redeem(database, user_id, kind, token):
    stat = CONSUMABLES[kind]
    await database.settle_pet(user_id)
    now = datetime.now(UTC)
    stamp = now.isoformat()
    async with database.connect() as db:
        await db.execute("BEGIN IMMEDIATE")
        error = await database._consume_wallet_intent(db, token, user_id, "pet_action", 1, user_id)
        if error:
            return False, error
        reward = await one(
            db, "SELECT stage FROM pet_stage_rewards WHERE user_id=? AND kind=? AND used_at IS NULL",
            (user_id, kind),
        )
        if not reward:
            return False, "Награда ещё закрыта или уже использована."
        pet = await one(db, f"SELECT {stat} FROM pets WHERE user_id=?", (user_id,))
        if pet[stat] >= 100:
            return False, "Показатель уже на максимуме. Награда сохранена."
        if kind == "mood":
            await db.execute("UPDATE pets SET mood=100, updated_at=? WHERE user_id=?", (stamp, user_id))
        else:
            await database._apply_shop_effect(db, user_id, "pet_meal" if kind == "meal" else "pet_drink", stamp)
        await db.execute(
            "UPDATE pet_stage_rewards SET used_at=? WHERE user_id=? AND stage=?", (stamp, user_id, reward["stage"]),
        )
        await db.commit()
    return True, "Награда использована."


async def dashboard(database, user_id):
    now = moscow_now()
    async with database.connect() as db:
        await db.execute("BEGIN IMMEDIATE")
        state = await ensure_pet(db, user_id, now.astimezone(UTC).isoformat())
        if not state:
            return None
        day = await ensure_day(db, user_id, now)
        daily = await one(db, "SELECT xp FROM pet_quest_days WHERE user_id=? AND day=?", (user_id, day))
        quests = await (await db.execute(
            "SELECT label,target,progress,xp FROM pet_quests WHERE user_id=? AND day=? ORDER BY slot", (user_id, day),
        )).fetchall()
        rewards = await (await db.execute(
            "SELECT stage,used_at,amount FROM pet_stage_rewards WHERE user_id=?", (user_id,),
        )).fetchall()
        await db.commit()
    earned = {r["stage"]: r for r in rewards}
    return {
        "level": state["level"], "stage": state["stage"], "xp": state["xp"],
        "level_name": LEVELS[state["level"] - 1], "daily_xp": daily["xp"],
        "reset_at": (now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).isoformat(),
        "quests": [dict(q) for q in quests],
        "stages": [
            {
                "stage": stage, "level": level_for(stage), "kind": kind, "label": label,
                "status": ("locked" if stage not in earned else "open" if kind == "unlock"
                           else "received" if earned[stage]["used_at"] else "available"),
                "amount": earned[stage]["amount"] if stage in earned else amount,
                "level_name": LEVELS[level_for(stage) - 1],
            }
            for stage, (kind, amount, label) in enumerate(REWARDS, 1)
        ],
        "messages": state["messages"], "milestones": ACTIVITY_MILESTONES,
        "rules": {
            "quest_xp": QUEST_XP, "daily_xp": DAILY_XP, "stage_xp": STAGE_XP,
            "text_interval": TEXT_INTERVAL, "text_min_length": TEXT_MIN_LENGTH,
            "ai_stage": AI_STAGE, "video_stage": VIDEO_STAGE, "video_daily_limit": VIDEO_DAILY_LIMIT,
            "video_max_mb": VIDEO_MAX_MB, "timezone": "МСК", "reset_hour": "00:00",
        },
    }
