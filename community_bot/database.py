from __future__ import annotations

import json
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, AsyncIterator
from zoneinfo import ZoneInfo

import aiosqlite

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    telegram_name TEXT NOT NULL DEFAULT '',
    profile_name TEXT,
    age INTEGER,
    hobbies TEXT,
    avatar_file_id TEXT,
    avatar_media_type TEXT NOT NULL DEFAULT 'photo',
    role TEXT NOT NULL DEFAULT 'member',
    custom_status TEXT,
    cookies INTEGER NOT NULL DEFAULT 0 CHECK(cookies >= 0),
    cookie_debt INTEGER NOT NULL DEFAULT 0 CHECK(cookie_debt >= 0),
    reputation INTEGER NOT NULL DEFAULT 69,
    warnings INTEGER NOT NULL DEFAULT 0 CHECK(warnings >= 0),
    hate_immunity_until TEXT,
    profile_private INTEGER NOT NULL DEFAULT 0 CHECK(profile_private IN (0, 1)),
    profile_ornate INTEGER NOT NULL DEFAULT 0 CHECK(profile_ornate IN (0, 1)),
    profile_title TEXT NOT NULL DEFAULT '',
    hate_shields INTEGER NOT NULL DEFAULT 0 CHECK(hate_shields >= 0),
    moderator_note TEXT NOT NULL DEFAULT '',
    profile_bio TEXT NOT NULL DEFAULT '',
    bio_warning INTEGER NOT NULL DEFAULT 0,
    bio_auto_warn INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    answers_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    moderator_id INTEGER,
    decision_reason TEXT,
    created_at TEXT NOT NULL,
    reviewed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status, created_at);

CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status, updated_at);

CREATE TABLE IF NOT EXISTS ticket_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id),
    sender_id INTEGER NOT NULL,
    sender_kind TEXT NOT NULL,
    text TEXT,
    media_type TEXT,
    media_file_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reputation_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id INTEGER NOT NULL REFERENCES users(user_id),
    target_id INTEGER NOT NULL REFERENCES users(user_id),
    delta INTEGER NOT NULL,
    action_date TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rep_actor_date ON reputation_actions(actor_id, action_date);

CREATE TABLE IF NOT EXISTS pending_transfers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id INTEGER NOT NULL REFERENCES users(user_id),
    receiver_id INTEGER NOT NULL REFERENCES users(user_id),
    amount INTEGER NOT NULL CHECK(amount > 0),
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    amount INTEGER NOT NULL,
    kind TEXT NOT NULL,
    details TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id, created_at);

CREATE TABLE IF NOT EXISTS wallet_intents (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    target_id INTEGER NOT NULL REFERENCES users(user_id),
    item TEXT NOT NULL,
    price INTEGER NOT NULL CHECK(price > 0),
    payload_json TEXT NOT NULL DEFAULT '{}',
    catalog_version TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'completed', 'cancelled')),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS cookie_loans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    principal INTEGER NOT NULL,
    interest_percent INTEGER NOT NULL,
    due_amount INTEGER NOT NULL,
    due_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    collected_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_cookie_loans_status ON cookie_loans(status, due_at);

CREATE TABLE IF NOT EXISTS bot_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notify_prefs (
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    channel TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0, 1)),
    digest INTEGER NOT NULL DEFAULT 0 CHECK(digest IN (0, 1)),
    PRIMARY KEY (user_id, channel)
);

CREATE TABLE IF NOT EXISTS notify_inbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    channel TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    read INTEGER NOT NULL DEFAULT 0 CHECK(read IN (0, 1)),
    delivered INTEGER NOT NULL DEFAULT 0 CHECK(delivered IN (0, 1))
);
CREATE INDEX IF NOT EXISTS idx_notify_inbox_user ON notify_inbox(user_id, read, delivered, id);

CREATE TABLE IF NOT EXISTS cookie_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    amount INTEGER NOT NULL CHECK(amount > 0),
    rubles INTEGER NOT NULL CHECK(rubles > 0),
    receipt_media_type TEXT NOT NULL,
    receipt_file_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    reviewer_id INTEGER,
    created_at TEXT NOT NULL,
    reviewed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_cookie_orders_status ON cookie_orders(status, created_at);

CREATE TABLE IF NOT EXISTS scheduled_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target TEXT NOT NULL CHECK(target IN ('community', 'private_all')),
    text TEXT,
    media_type TEXT,
    media_file_id TEXT,
    interval_minutes INTEGER NOT NULL CHECK(interval_minutes >= 5),
    next_run_at TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scheduled_due ON scheduled_messages(enabled, next_run_at);

CREATE TABLE IF NOT EXISTS roulette_games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    challenger_id INTEGER NOT NULL REFERENCES users(user_id),
    opponent_id INTEGER NOT NULL REFERENCES users(user_id),
    stake INTEGER NOT NULL DEFAULT 10,
    status TEXT NOT NULL DEFAULT 'pending',
    winner_id INTEGER,
    payout INTEGER,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS freebie_claims (
    user_id INTEGER PRIMARY KEY REFERENCES users(user_id),
    amount INTEGER NOT NULL,
    claimed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feature_flags (
    key TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
    updated_by INTEGER,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    target TEXT,
    details TEXT,
    reason TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    actor_name TEXT NOT NULL DEFAULT '',
    target_name TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_admin_audit_created ON admin_audit_log(created_at DESC);

CREATE TABLE IF NOT EXISTS user_activity (
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    chat_id INTEGER NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    reward_checkpoint INTEGER NOT NULL DEFAULT 0,
    last_message_at TEXT NOT NULL,
    PRIMARY KEY(user_id, chat_id)
);

CREATE TABLE IF NOT EXISTS pets (
    user_id INTEGER PRIMARY KEY REFERENCES users(user_id),
    species TEXT NOT NULL,
    name TEXT NOT NULL,
    hunger INTEGER NOT NULL DEFAULT 80 CHECK(hunger BETWEEN 0 AND 100),
    thirst INTEGER NOT NULL DEFAULT 80 CHECK(thirst BETWEEN 0 AND 100),
    mood INTEGER NOT NULL DEFAULT 80 CHECK(mood BETWEEN 0 AND 100),
    food_units INTEGER NOT NULL DEFAULT 0 CHECK(food_units >= 0),
    water_units INTEGER NOT NULL DEFAULT 0 CHECK(water_units >= 0),
    farm_milli INTEGER NOT NULL DEFAULT 0 CHECK(farm_milli >= 0),
    sleeping INTEGER NOT NULL DEFAULT 0 CHECK(sleeping IN (0, 1)),
    last_tick_at TEXT NOT NULL,
    last_notice_at TEXT,
    last_talk_at TEXT,
    guard_used_on TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS staff_roles (
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    rank INTEGER NOT NULL DEFAULT 0,
    permissions_json TEXT NOT NULL DEFAULT '[]',
    is_system INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS party_games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    game_type TEXT NOT NULL,
    creator_id INTEGER NOT NULL REFERENCES users(user_id),
    status TEXT NOT NULL DEFAULT 'lobby',
    state_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_party_games_chat_status ON party_games(chat_id, status, created_at);

CREATE TABLE IF NOT EXISTS party_game_players (
    game_id INTEGER NOT NULL REFERENCES party_games(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    secret_json TEXT NOT NULL DEFAULT '{}',
    joined_at TEXT NOT NULL,
    PRIMARY KEY(game_id, user_id)
);

CREATE TABLE IF NOT EXISTS party_game_votes (
    game_id INTEGER NOT NULL REFERENCES party_games(id) ON DELETE CASCADE,
    voter_id INTEGER NOT NULL REFERENCES users(user_id),
    target_id INTEGER NOT NULL REFERENCES users(user_id),
    created_at TEXT NOT NULL,
    PRIMARY KEY(game_id, voter_id)
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reporter_id INTEGER NOT NULL REFERENCES users(user_id),
    target_id INTEGER NOT NULL REFERENCES users(user_id),
    chat_id INTEGER,
    message_id INTEGER,
    text TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    moderator_id INTEGER,
    created_at TEXT NOT NULL,
    reviewed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status, created_at);

CREATE TABLE IF NOT EXISTS mailbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    moderator_id INTEGER,
    created_at TEXT NOT NULL,
    reviewed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_mailbox_status ON mailbox(status, created_at);

CREATE TABLE IF NOT EXISTS stop_words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word TEXT NOT NULL UNIQUE,
    created_by INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_rsvps (
    event_id TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    stake INTEGER NOT NULL DEFAULT 0,
    kind TEXT NOT NULL DEFAULT 'legacy',
    created_at TEXT NOT NULL,
    PRIMARY KEY(event_id, user_id)
);

CREATE TABLE IF NOT EXISTS studio_events (
    event_id TEXT PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    buttons_json TEXT NOT NULL DEFAULT '[]',
    rsvp_enabled INTEGER NOT NULL DEFAULT 1,
    stake INTEGER NOT NULL DEFAULT 0 CHECK(stake >= 0),
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    markup_dirty INTEGER NOT NULL DEFAULT 0,
    description TEXT NOT NULL DEFAULT '',
    starts_at TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    revision INTEGER NOT NULL DEFAULT 0,
    media_type TEXT NOT NULL DEFAULT '',
    content_dirty INTEGER NOT NULL DEFAULT 0,
    UNIQUE(chat_id, message_id)
);

CREATE TABLE IF NOT EXISTS achievements (
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    slug TEXT NOT NULL,
    unlocked_at TEXT NOT NULL,
    PRIMARY KEY(user_id, slug)
);

CREATE TABLE IF NOT EXISTS weekly_scores (
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    week_id TEXT NOT NULL,
    messages INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(user_id, week_id)
);

CREATE TABLE IF NOT EXISTS daily_scores (
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    day TEXT NOT NULL,
    chat_id INTEGER NOT NULL,
    messages INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(user_id, day, chat_id)
);

CREATE TABLE IF NOT EXISTS command_overrides (
    slug TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'builtin',
    enabled INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    aliases_json TEXT NOT NULL DEFAULT '[]',
    ttl_seconds INTEGER,
    scope TEXT NOT NULL DEFAULT 'both',
    reply_text TEXT NOT NULL DEFAULT '',
    options_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS lotteries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    creator_id INTEGER NOT NULL REFERENCES users(user_id),
    entry_fee INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    winner_id INTEGER,
    created_at TEXT NOT NULL,
    drawn_at TEXT
);

CREATE TABLE IF NOT EXISTS lottery_entries (
    lottery_id INTEGER NOT NULL REFERENCES lotteries(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    created_at TEXT NOT NULL,
    PRIMARY KEY(lottery_id, user_id)
);

CREATE TABLE IF NOT EXISTS cookie_contests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    creator_id INTEGER NOT NULL REFERENCES users(user_id),
    prize INTEGER NOT NULL,
    body TEXT NOT NULL,
    extra_text TEXT NOT NULL DEFAULT '',
    media_type TEXT,
    media_file_id TEXT,
    message_id INTEGER,
    status TEXT NOT NULL DEFAULT 'open',
    winner_id INTEGER,
    created_at TEXT NOT NULL,
    drawn_at TEXT
);

CREATE TABLE IF NOT EXISTS cookie_contest_entries (
    contest_id INTEGER NOT NULL REFERENCES cookie_contests(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    created_at TEXT NOT NULL,
    PRIMARY KEY(contest_id, user_id)
);

CREATE TABLE IF NOT EXISTS captcha_pending (
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(user_id, chat_id)
);

CREATE TABLE IF NOT EXISTS bot_chat_messages (
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(chat_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_bot_chat_messages_created ON bot_chat_messages(chat_id, created_at);

CREATE TABLE IF NOT EXISTS shop_categories (
    slug TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS shop_items (
    sku TEXT PRIMARY KEY,
    category_slug TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    price INTEGER,
    image TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
    extra_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shop_items_category ON shop_items(category_slug, sort_order, sku);

CREATE TABLE IF NOT EXISTS ui_owners (
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL DEFAULT 'ui',
    created_at TEXT NOT NULL,
    PRIMARY KEY(chat_id, message_id)
);

CREATE TABLE IF NOT EXISTS event_offers (
    event_id TEXT PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    button_text TEXT NOT NULL,
    price INTEGER NOT NULL CHECK(price >= 0),
    title TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
"""

DEFAULT_FEATURE_FLAGS = {
    "games": 1,
    "tamagotchi": 1,
    "profile_video": 1,
    "activity_rewards": 1,
    "anti_flood": 0,
    "link_filter": 0,
    "media_filter": 0,
    "sticker_filter": 0,
    "quiet_hours": 0,
    "raid_mode": 0,
    "word_filter": 0,
    "join_captcha": 0,
    "morning_digest": 1,
}


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


logger = logging.getLogger(__name__)


SCHEMA += """
CREATE TABLE IF NOT EXISTS profile_completion_rewards (
    user_id INTEGER PRIMARY KEY REFERENCES users(user_id), awarded_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[aiosqlite.Connection]:
        connection = await aiosqlite.connect(self.path)
        connection.row_factory = aiosqlite.Row
        await connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            await connection.close()

    async def initialize(self) -> None:
        from community_bot.friends_api import SCHEMA as friends_schema
        from community_bot.mafia_api import SCHEMA as mafia_schema
        from community_bot.rocket_api import SCHEMA as rocket_schema

        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with self.connect() as db:
            await db.executescript(SCHEMA)
            # Additive, independent game tables: existing balances, party games and pets stay shared.
            await db.executescript(friends_schema + mafia_schema + rocket_schema)
            event_columns = {
                str(row[1]) for row in await (await db.execute("PRAGMA table_info(studio_events)")).fetchall()
            }
            for name, definition in (
                ('description', "TEXT NOT NULL DEFAULT ''"), ('starts_at', 'TEXT'),
                ('status', "TEXT NOT NULL DEFAULT 'active'"), ('revision', 'INTEGER NOT NULL DEFAULT 0'),
                ('media_type', "TEXT NOT NULL DEFAULT ''"), ('content_dirty', 'INTEGER NOT NULL DEFAULT 0'),
            ):
                if name not in event_columns:
                    await db.execute(f'ALTER TABLE studio_events ADD COLUMN {name} {definition}')
            columns = {str(row[1]) for row in await (await db.execute("PRAGMA table_info(users)")).fetchall()}
            if "avatar_media_type" not in columns:
                await db.execute("ALTER TABLE users ADD COLUMN avatar_media_type TEXT NOT NULL DEFAULT 'photo'")
            pet_columns = {str(row[1]) for row in await (await db.execute("PRAGMA table_info(pets)")).fetchall()}
            rsvp_columns = {
                str(row[1]) for row in await (await db.execute("PRAGMA table_info(event_rsvps)")).fetchall()
            }
            if "kind" not in rsvp_columns:
                await db.execute("ALTER TABLE event_rsvps ADD COLUMN kind TEXT NOT NULL DEFAULT 'legacy'")
            if "last_talk_at" not in pet_columns:
                await db.execute("ALTER TABLE pets ADD COLUMN last_talk_at TEXT")
            if "profile_private" not in columns:
                await db.execute("ALTER TABLE users ADD COLUMN profile_private INTEGER NOT NULL DEFAULT 0")
            if "profile_ornate" not in columns:
                await db.execute("ALTER TABLE users ADD COLUMN profile_ornate INTEGER NOT NULL DEFAULT 0")
            if "cookie_debt" not in columns:
                await db.execute("ALTER TABLE users ADD COLUMN cookie_debt INTEGER NOT NULL DEFAULT 0")
            if "profile_title" not in columns:
                await db.execute("ALTER TABLE users ADD COLUMN profile_title TEXT NOT NULL DEFAULT ''")
            if "hate_shields" not in columns:
                await db.execute("ALTER TABLE users ADD COLUMN hate_shields INTEGER NOT NULL DEFAULT 0")
            if "moderator_note" not in columns:
                await db.execute("ALTER TABLE users ADD COLUMN moderator_note TEXT NOT NULL DEFAULT ''")
            if "profile_bio" not in columns:
                await db.execute("ALTER TABLE users ADD COLUMN profile_bio TEXT NOT NULL DEFAULT ''")
            if "bio_warning" not in columns:
                await db.execute("ALTER TABLE users ADD COLUMN bio_warning INTEGER NOT NULL DEFAULT 0")
            if "bio_auto_warn" not in columns:
                await db.execute("ALTER TABLE users ADD COLUMN bio_auto_warn INTEGER NOT NULL DEFAULT 0")
            if "guard_used_on" not in pet_columns:
                await db.execute("ALTER TABLE pets ADD COLUMN guard_used_on TEXT")
            if "expedition_until" not in pet_columns:
                await db.execute("ALTER TABLE pets ADD COLUMN expedition_until TEXT")
            if "expedition_reward" not in pet_columns:
                await db.execute("ALTER TABLE pets ADD COLUMN expedition_reward INTEGER NOT NULL DEFAULT 0")
            if "expedition_loot" not in pet_columns:
                await db.execute("ALTER TABLE pets ADD COLUMN expedition_loot TEXT")
            if "expedition_notice_sent" not in pet_columns:
                await db.execute("ALTER TABLE pets ADD COLUMN expedition_notice_sent INTEGER NOT NULL DEFAULT 1")
            audit_columns = {
                str(row[1]) for row in await (await db.execute("PRAGMA table_info(admin_audit_log)")).fetchall()
            }
            for column, definition in (
                ("reason", "TEXT NOT NULL DEFAULT ''"),
                ("status", "TEXT NOT NULL DEFAULT ''"),
                ("actor_name", "TEXT NOT NULL DEFAULT ''"),
                ("target_name", "TEXT NOT NULL DEFAULT ''"),
            ):
                if column not in audit_columns:
                    await db.execute(f"ALTER TABLE admin_audit_log ADD COLUMN {column} {definition}")
            await db.commit()
        await self._seed_staff_roles()
        async with self.connect() as db:
            now = utcnow()
            for key, enabled in DEFAULT_FEATURE_FLAGS.items():
                await db.execute(
                    "INSERT OR IGNORE INTO feature_flags(key, enabled, updated_at) VALUES (?, ?, ?)",
                    (key, enabled, now),
                )
            await db.commit()
        await self._seed_shop_catalog()
        await self.reset_incomplete_reputation_to_bronze()
        await self.sync_all_bio_auto_warns()

    async def fetchone(self, query: str, parameters: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        async with self.connect() as db:
            cursor = await db.execute(query, parameters)
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def fetchall(self, query: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        async with self.connect() as db:
            cursor = await db.execute(query, parameters)
            return [dict(row) for row in await cursor.fetchall()]

    async def execute(self, query: str, parameters: tuple[Any, ...] = ()) -> int:
        async with self.connect() as db:
            cursor = await db.execute(query, parameters)
            await db.commit()
            return cursor.lastrowid or 0

    async def get_bot_state(self, key: str) -> str | None:
        row = await self.fetchone("SELECT value FROM bot_state WHERE key = ?", (key,))
        return str(row["value"]) if row else None

    async def set_bot_state(self, key: str, value: str) -> None:
        await self.execute(
            "INSERT INTO bot_state(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    async def feature_enabled(self, key: str) -> bool:
        row = await self.fetchone("SELECT enabled FROM feature_flags WHERE key = ?", (key,))
        return bool(row and int(row["enabled"]))

    async def list_feature_flags(self) -> list[dict[str, Any]]:
        rows = await self.fetchall("SELECT * FROM feature_flags")
        order = {key: index for index, key in enumerate(DEFAULT_FEATURE_FLAGS)}
        rows.sort(key=lambda row: (order.get(str(row["key"]), 1000), str(row["key"])))
        return rows

    async def reset_feature_flags(self, actor_id: int) -> None:
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            for key, enabled in DEFAULT_FEATURE_FLAGS.items():
                await db.execute(
                    """
                    INSERT INTO feature_flags(key, enabled, updated_by, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        enabled=excluded.enabled,
                        updated_by=excluded.updated_by,
                        updated_at=excluded.updated_at
                    """,
                    (key, enabled, actor_id, now),
                )
            await db.execute(
                """
                INSERT INTO admin_audit_log(
                    actor_id, action, target, details, reason, status, actor_name, target_name, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (actor_id, "feature_reset", "features", "factory_defaults", "сброс функций", "yellow", "", "", now),
            )
            await db.commit()

    async def toggle_feature(self, key: str, actor_id: int) -> bool | None:
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT enabled FROM feature_flags WHERE key = ?", (key,))
            row = await cursor.fetchone()
            if not row:
                await db.rollback()
                return None
            enabled = 0 if int(row["enabled"]) else 1
            await db.execute(
                "UPDATE feature_flags SET enabled = ?, updated_by = ?, updated_at = ? WHERE key = ?",
                (enabled, actor_id, now, key),
            )
            await db.execute(
                """
                INSERT INTO admin_audit_log(
                    actor_id, action, target, details, reason, status, actor_name, target_name, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (actor_id, "feature_toggle", key, f"enabled:{enabled}", "", "green", "", key, now),
            )
            await db.commit()
            return bool(enabled)

    async def log_admin_action(
        self,
        actor_id: int,
        action: str,
        target: str = "",
        details: str = "",
        *,
        reason: str = "",
        status: str = "",
        actor_name: str = "",
        target_name: str = "",
        default_duration: bool = False,
    ) -> None:
        from community_bot.audit import SYSTEM_ACTOR_ID, classify_status, person_label

        if not actor_name:
            if actor_id == SYSTEM_ACTOR_ID:
                actor_name = "Система"
            else:
                actor = await self.get_user(actor_id)
                actor_name = person_label(actor, str(actor_id))
        if not target_name and str(target).lstrip("-").isdigit():
            target_user = await self.get_user(int(target))
            if target_user:
                target_name = person_label(target_user, str(target))
        if not status:
            status = classify_status(
                action,
                reason=reason,
                details=details,
                target=str(target or ""),
                target_name=target_name,
                default_duration=default_duration,
            )
        await self.execute(
            """
            INSERT INTO admin_audit_log(
                actor_id, action, target, details, reason, status, actor_name, target_name, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (actor_id, action, target, details, reason, status, actor_name, target_name, utcnow()),
        )

    async def recent_admin_actions(self, limit: int = 20) -> list[dict[str, Any]]:
        return await self.fetchall(
            """
            SELECT
                a.*,
                COALESCE(NULLIF(a.actor_name, ''), ua.profile_name, ua.telegram_name, ua.username) AS actor_display,
                COALESCE(NULLIF(a.target_name, ''), ut.profile_name, ut.telegram_name, ut.username) AS target_display
            FROM admin_audit_log a
            LEFT JOIN users ua ON ua.user_id = a.actor_id
            LEFT JOIN users ut ON CAST(ut.user_id AS TEXT) = a.target
            ORDER BY a.id DESC
            LIMIT ?
            """,
            (limit,),
        )

    async def dashboard_stats(self) -> dict[str, int]:
        queries = {
            "users": "SELECT COUNT(*) AS count FROM users",
            "pets": "SELECT COUNT(*) AS count FROM pets",
            "active_games": "SELECT COUNT(*) AS count FROM party_games WHERE status IN ('lobby', 'active')",
            "pending_orders": "SELECT COUNT(*) AS count FROM cookie_orders WHERE status = 'pending'",
            "pending_applications": "SELECT COUNT(*) AS count FROM applications WHERE status = 'pending'",
            "open_tickets": "SELECT COUNT(*) AS count FROM tickets WHERE status = 'open'",
            "pending_reports": "SELECT COUNT(*) AS count FROM reports WHERE status = 'pending'",
            "pending_mail": "SELECT COUNT(*) AS count FROM mailbox WHERE status = 'pending'",
        }
        result: dict[str, int] = {}
        for key, query in queries.items():
            row = await self.fetchone(query)
            result[key] = int(row["count"]) if row else 0
        return result

    async def inactive_users(self, days: int = 7, limit: int = 50) -> list[dict[str, Any]]:
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        return await self.fetchall(
            """
            SELECT u.user_id, u.username, u.telegram_name, u.profile_name, u.role,
                   MAX(a.last_message_at) AS last_message_at,
                   COALESCE(SUM(a.message_count), 0) AS message_count
            FROM users u
            LEFT JOIN user_activity a ON a.user_id = u.user_id
            GROUP BY u.user_id
            HAVING MAX(a.last_message_at) IS NULL OR MAX(a.last_message_at) < ?
            ORDER BY last_message_at ASC
            LIMIT ?
            """,
            (cutoff, limit),
        )

    async def ensure_user(self, user_id: int, username: str | None = None, telegram_name: str = "") -> dict[str, Any]:
        from community_bot.domain import STARTING_REPUTATION

        now = utcnow()
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO users(user_id, username, telegram_name, reputation, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username=excluded.username,
                    telegram_name=excluded.telegram_name,
                    updated_at=excluded.updated_at
                """,
                (user_id, username, telegram_name, STARTING_REPUTATION, now, now),
            )
            await db.commit()
        user = await self.get_user(user_id)
        assert user is not None
        await self.sync_bio_auto_warn(user_id)
        await self.reward_complete_profile(user_id)
        user = await self.get_user(user_id)
        assert user is not None
        return user

    async def get_user(self, user_id: int) -> dict[str, Any] | None:
        return await self.fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))

    async def set_role(self, user_id: int, role: str) -> None:
        await self.execute(
            "UPDATE users SET role = ?, updated_at = ? WHERE user_id = ?",
            (role, utcnow(), user_id),
        )

    async def reset_incomplete_reputation_to_bronze(self) -> int:
        from community_bot.domain import AUTO_REPUTATION_CAP

        now = utcnow()
        async with self.connect() as db:
            cursor = await db.execute(
                """
                UPDATE users SET reputation = ?, updated_at = ?
                WHERE reputation > ?
                  AND (
                    TRIM(COALESCE(profile_name, '')) = ''
                    OR age IS NULL OR age < 14 OR age > 120
                    OR TRIM(COALESCE(hobbies, '')) = ''
                    OR TRIM(COALESCE(profile_bio, '')) = ''
                    OR TRIM(COALESCE(avatar_file_id, '')) = ''
                  )
                """,
                (AUTO_REPUTATION_CAP, now, AUTO_REPUTATION_CAP),
            )
            await db.commit()
            return int(cursor.rowcount or 0)

    async def sync_all_bio_auto_warns(self) -> None:
        for user in await self.list_all_users():
            await self.sync_bio_auto_warn(int(user["user_id"]))

    async def sync_bio_auto_warn(self, user_id: int) -> str | None:
        from community_bot.audit import SYSTEM_ACTOR_ID
        from community_bot.profile_fill import bio_is_filled

        user = await self.get_user(user_id)
        if not user:
            return None
        state = int(user.get("bio_auto_warn") or 0)
        filled = bio_is_filled(user)
        now = utcnow()
        if filled and state == 0:
            await self.execute(
                "UPDATE users SET bio_auto_warn = 2, updated_at = ? WHERE user_id = ?",
                (now, user_id),
            )
            return None
        if filled and state == 1:
            await self.remove_warning(user_id)
            await self.execute(
                "UPDATE users SET bio_auto_warn = 2, updated_at = ? WHERE user_id = ?",
                (now, user_id),
            )
            await self.log_admin_action(
                SYSTEM_ACTOR_ID,
                "unwarn",
                str(user_id),
                "bio_filled",
                reason="Описание профиля заполнено",
                actor_name="Система",
            )
            return "cleared"
        if (not filled) and state == 0:
            await self.add_warning(user_id)
            await self.execute(
                "UPDATE users SET bio_auto_warn = 1, updated_at = ? WHERE user_id = ?",
                (now, user_id),
            )
            await self.log_admin_action(
                SYSTEM_ACTOR_ID,
                "warn",
                str(user_id),
                "bio_empty",
                reason="Не заполнено описание профиля",
                actor_name="Система",
            )
            return "issued"
        return None

    async def list_user_warns(self, user_id: int) -> list[dict[str, Any]]:
        return await self.fetchall(
            """
            SELECT * FROM admin_audit_log
            WHERE action = 'warn' AND target = ?
            ORDER BY id DESC
            """,
            (str(user_id),),
        )

    async def bind_ui_owner(self, chat_id: int, message_id: int, user_id: int, kind: str = "ui") -> None:
        await self.execute(
            """
            INSERT INTO ui_owners(chat_id, message_id, user_id, kind, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, message_id) DO UPDATE SET user_id=excluded.user_id, kind=excluded.kind
            """,
            (chat_id, message_id, user_id, kind, utcnow()),
        )

    async def get_ui_owner(self, chat_id: int, message_id: int) -> int | None:
        row = await self.fetchone(
            "SELECT user_id FROM ui_owners WHERE chat_id = ? AND message_id = ?",
            (chat_id, message_id),
        )
        return int(row["user_id"]) if row else None

    async def _seed_shop_catalog(self) -> None:
        from community_bot.shop_catalog import (
            DEFAULT_COOKIE_SHOP,
            DEFAULT_SHOP_HEADER,
            REMOVED_COSMETIC_SKUS,
            SEED_CATEGORIES,
            SEED_ITEMS,
        )

        now = utcnow()
        async with self.connect() as db:
            for row in SEED_CATEGORIES:
                await db.execute(
                    """
                    INSERT OR IGNORE INTO shop_categories(slug, title, description, sort_order, enabled, created_at)
                    VALUES (?, ?, ?, ?, 1, ?)
                    """,
                    (row["slug"], row["title"], row["description"], row["sort_order"], now),
                )
            for row in SEED_ITEMS:
                await db.execute(
                    """
                    INSERT OR IGNORE INTO shop_items(
                        sku, category_slug, title, description, price, image, sort_order, enabled, extra_json,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, '', NULL, '', ?, 1, '{}', ?, ?)
                    """,
                    (row["sku"], row["category_slug"], row["title"], row["sort_order"], now, now),
                )
            await db.execute(
                f"DELETE FROM shop_items WHERE sku IN ({','.join('?' * len(REMOVED_COSMETIC_SKUS))})",
                REMOVED_COSMETIC_SKUS,
            )
            await db.execute("DELETE FROM shop_categories WHERE slug = 'cosmetics'")
            await db.execute("DROP TABLE IF EXISTS pet_cosmetics")
            cleared = await db.execute("SELECT value FROM bot_state WHERE key = 'shop_prices_cleared'")
            flag = await cleared.fetchone()
            if not flag:
                await db.execute("UPDATE shop_items SET price = NULL, updated_at = ?", (now,))
                await db.execute(
                    "INSERT INTO bot_state(key, value) VALUES ('shop_prices_cleared', '1') ON CONFLICT(key) DO NOTHING"
                )
            header = await db.execute("SELECT value FROM bot_state WHERE key = 'shop_header'")
            if not await header.fetchone():
                await db.execute(
                    "INSERT INTO bot_state(key, value) VALUES (?, ?)",
                    ("shop_header", json.dumps(DEFAULT_SHOP_HEADER, ensure_ascii=False)),
                )
            cookies = await db.execute("SELECT value FROM bot_state WHERE key = 'cookie_shop'")
            if not await cookies.fetchone():
                await db.execute(
                    "INSERT INTO bot_state(key, value) VALUES (?, ?)",
                    ("cookie_shop", json.dumps(DEFAULT_COOKIE_SHOP, ensure_ascii=False)),
                )
            await db.commit()

    async def list_shop_categories(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        from community_bot.shop_text import catalogue_row

        where = 'WHERE enabled = 1' if enabled_only else ''
        rows = await self.fetchall(f'SELECT * FROM shop_categories {where} ORDER BY sort_order, title')
        return [catalogue_row(row) for row in rows]

    async def get_shop_category(self, slug: str) -> dict[str, Any] | None:
        from community_bot.shop_text import catalogue_row

        return catalogue_row(await self.fetchone('SELECT * FROM shop_categories WHERE slug = ?', (slug,)))

    async def upsert_shop_category(
        self,
        slug: str,
        title: str,
        description: str = "",
        *,
        sort_order: int | None = None,
        enabled: int | None = None,
    ) -> None:
        now = utcnow()
        existing = await self.get_shop_category(slug)
        if existing is None:
            order = 10 if sort_order is None else sort_order
            max_row = await self.fetchone("SELECT MAX(sort_order) AS m FROM shop_categories")
            if sort_order is None:
                order = int((max_row or {}).get("m") or 0) + 10
            await self.execute(
                """
                INSERT INTO shop_categories(slug, title, description, sort_order, enabled, created_at)
                VALUES (?, ?, ?, ?, 1, ?)
                """,
                (slug, title, description, order, now),
            )
            return
        fields = ["title = ?", "description = ?"]
        values: list[Any] = [title, description]
        if sort_order is not None:
            fields.append("sort_order = ?")
            values.append(sort_order)
        if enabled is not None:
            fields.append("enabled = ?")
            values.append(enabled)
        values.append(slug)
        await self.execute(f"UPDATE shop_categories SET {', '.join(fields)} WHERE slug = ?", tuple(values))

    async def delete_shop_category(self, slug: str) -> bool:
        if slug in {"pets", "reputation", "profile"}:
            return False
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute("DELETE FROM shop_items WHERE category_slug = ?", (slug,))
            cursor = await db.execute("DELETE FROM shop_categories WHERE slug = ?", (slug,))
            await db.commit()
            return cursor.rowcount == 1

    async def list_shop_items(
        self,
        category_slug: str | None = None,
        *,
        enabled_only: bool = False,
        priced_only: bool = False,
    ) -> list[dict[str, Any]]:
        clauses = []
        params: list[Any] = []
        from community_bot.shop_catalog import RETIRED_PROFILE_SKUS

        clauses.append(f"sku NOT IN ({','.join('?' * len(RETIRED_PROFILE_SKUS))})")
        params.extend(sorted(RETIRED_PROFILE_SKUS))
        if category_slug:
            clauses.append("category_slug = ?")
            params.append(category_slug)
        if enabled_only:
            clauses.append("enabled = 1")
        if priced_only:
            clauses.append("price IS NOT NULL AND price > 0")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        from community_bot.shop_text import catalogue_row

        rows = await self.fetchall(
            f"SELECT * FROM shop_items {where} ORDER BY sort_order, title",
            tuple(params),
        )
        return [catalogue_row(row) for row in rows]

    async def get_shop_item(self, sku: str) -> dict[str, Any] | None:
        from community_bot.shop_catalog import RETIRED_PROFILE_SKUS

        if sku in RETIRED_PROFILE_SKUS:
            return None
        from community_bot.shop_text import catalogue_row

        return catalogue_row(await self.fetchone("SELECT * FROM shop_items WHERE sku = ?", (sku,)))

    async def upsert_shop_item(
        self,
        sku: str,
        *,
        category_slug: str | None = None,
        title: str | None = None,
        description: str | None = None,
        price: int | None | object = ...,
        image: str | None = None,
        sort_order: int | None = None,
        enabled: int | None = None,
        extra_json: str | None = None,
    ) -> dict[str, Any] | None:
        from community_bot.shop_catalog import RETIRED_PROFILE_SKUS

        if sku in RETIRED_PROFILE_SKUS:
            return None
        now = utcnow()
        existing = await self.get_shop_item(sku)
        if existing is None:
            if not category_slug or not title:
                return None
            order = sort_order
            if order is None:
                max_row = await self.fetchone(
                    "SELECT MAX(sort_order) AS m FROM shop_items WHERE category_slug = ?",
                    (category_slug,),
                )
                order = int((max_row or {}).get("m") or 0) + 10
            stored_price = None if price is ... else price
            stored_extra = extra_json if extra_json is not None else "{}"
            await self.execute(
                """
                INSERT INTO shop_items(
                    sku, category_slug, title, description, price, image, sort_order, enabled, extra_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sku,
                    category_slug,
                    title,
                    description or "",
                    stored_price,
                    image or "",
                    order,
                    1 if enabled is None else enabled,
                    stored_extra,
                    now,
                    now,
                ),
            )
            return await self.get_shop_item(sku)
        fields = ["updated_at = ?"]
        values: list[Any] = [now]
        if category_slug is not None:
            fields.append("category_slug = ?")
            values.append(category_slug)
        if title is not None:
            fields.append("title = ?")
            values.append(title)
        if description is not None:
            fields.append("description = ?")
            values.append(description)
        if price is not ...:
            fields.append("price = ?")
            values.append(price)
        if image is not None:
            fields.append("image = ?")
            values.append(image)
        if sort_order is not None:
            fields.append("sort_order = ?")
            values.append(sort_order)
        if enabled is not None:
            fields.append("enabled = ?")
            values.append(enabled)
        if extra_json is not None:
            fields.append("extra_json = ?")
            values.append(extra_json)
        values.append(sku)
        await self.execute(f"UPDATE shop_items SET {', '.join(fields)} WHERE sku = ?", tuple(values))
        return await self.get_shop_item(sku)

    async def delete_shop_item(self, sku: str) -> bool:
        async with self.connect() as db:
            cursor = await db.execute("DELETE FROM shop_items WHERE sku = ?", (sku,))
            await db.commit()
            return cursor.rowcount == 1

    async def shift_shop_item(self, sku: str, direction: int) -> bool:
        item = await self.get_shop_item(sku)
        if not item:
            return False
        neighbors = await self.list_shop_items(str(item["category_slug"]))
        index = next((i for i, row in enumerate(neighbors) if row["sku"] == sku), None)
        if index is None:
            return False
        target = index + direction
        if target < 0 or target >= len(neighbors):
            return False
        other = neighbors[target]
        await self.execute(
            "UPDATE shop_items SET sort_order = ? WHERE sku = ?",
            (int(other["sort_order"]), sku),
        )
        await self.execute(
            "UPDATE shop_items SET sort_order = ? WHERE sku = ?",
            (int(item["sort_order"]), other["sku"]),
        )
        return True

    async def shift_shop_category(self, slug: str, direction: int) -> bool:
        rows = await self.list_shop_categories()
        index = next((i for i, row in enumerate(rows) if row["slug"] == slug), None)
        if index is None:
            return False
        target = index + direction
        if target < 0 or target >= len(rows):
            return False
        other = rows[target]
        current = rows[index]
        await self.execute("UPDATE shop_categories SET sort_order = ? WHERE slug = ?", (int(other["sort_order"]), slug))
        await self.execute(
            "UPDATE shop_categories SET sort_order = ? WHERE slug = ?",
            (int(current["sort_order"]), other["slug"]),
        )
        return True

    async def shop_header(self) -> dict[str, Any]:
        from community_bot.shop_catalog import DEFAULT_SHOP_HEADER

        raw = await self.get_bot_state("shop_header")
        if not raw:
            return dict(DEFAULT_SHOP_HEADER)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return dict(DEFAULT_SHOP_HEADER)
        if not isinstance(data, dict):
            return dict(DEFAULT_SHOP_HEADER)
        header = dict(DEFAULT_SHOP_HEADER)
        header.update({key: data.get(key, header[key]) for key in header})
        header["enabled"] = bool(data.get("enabled"))
        return header

    async def set_shop_header(self, **fields: Any) -> dict[str, Any]:
        header = await self.shop_header()
        header.update(fields)
        header["enabled"] = bool(header.get("enabled"))
        header["title"] = str(header.get("title") or "")
        header["text"] = str(header.get("text") or "")
        await self.set_bot_state("shop_header", json.dumps(header, ensure_ascii=False))
        return header

    async def cookie_shop(self) -> dict[str, Any]:
        from community_bot.shop_catalog import DEFAULT_COOKIE_SHOP, normalize_cookie_shop

        raw = await self.get_bot_state("cookie_shop")
        if not raw:
            return normalize_cookie_shop(dict(DEFAULT_COOKIE_SHOP))
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return normalize_cookie_shop(dict(DEFAULT_COOKIE_SHOP))
        if not isinstance(data, dict):
            return normalize_cookie_shop(dict(DEFAULT_COOKIE_SHOP))
        return normalize_cookie_shop(data)

    async def set_cookie_shop(self, **fields: Any) -> dict[str, Any]:
        from community_bot.shop_catalog import normalize_cookie_shop

        shop = await self.cookie_shop()
        shop.update(fields)
        shop = normalize_cookie_shop(shop)
        await self.set_bot_state("cookie_shop", json.dumps(shop, ensure_ascii=False))
        return shop

    async def priced_shop_map(self) -> dict[str, int]:
        items = await self.list_shop_items(enabled_only=True, priced_only=True)
        return {str(row["sku"]): int(row["price"]) for row in items if row.get("price") is not None}

    async def save_event_offer(
        self,
        event_id: str,
        chat_id: int,
        message_id: int,
        button_text: str,
        price: int,
        created_by: int,
        title: str = "",
        body: str = "",
    ) -> None:
        await self.execute(
            """
            INSERT INTO event_offers(
                event_id, chat_id, message_id, button_text, price, title, body, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                chat_id=excluded.chat_id,
                message_id=excluded.message_id,
                button_text=excluded.button_text,
                price=excluded.price,
                title=excluded.title,
                body=excluded.body
            """,
            (event_id, chat_id, message_id, button_text, price, title, body, created_by, utcnow()),
        )

    async def get_event_offer(self, event_id: str) -> dict[str, Any] | None:
        return await self.fetchone("SELECT * FROM event_offers WHERE event_id = ?", (event_id,))

    async def has_event_rsvp(self, event_id: str, user_id: int) -> bool:
        row = await self.fetchone(
            "SELECT 1 AS ok FROM event_rsvps WHERE event_id = ? AND user_id = ?",
            (event_id, user_id),
        )
        return bool(row)

    async def _seed_staff_roles(self) -> None:
        from community_bot.permissions import DEFAULT_STAFF_ROLES, dump_permissions

        now = utcnow()
        async with self.connect() as db:
            for slug, name, rank, perms, is_system in DEFAULT_STAFF_ROLES:
                await db.execute(
                    """
                    INSERT OR IGNORE INTO staff_roles(slug, name, rank, permissions_json, is_system, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (slug, name, rank, dump_permissions(perms), is_system, now),
                )
                if is_system:
                    await db.execute(
                        """
                        UPDATE staff_roles SET name = ?, rank = ?, permissions_json = ?
                        WHERE slug = ? AND is_system = 1
                        """,
                        (name, rank, dump_permissions(perms), slug),
                    )
            await db.commit()

    async def list_staff_roles(self) -> list[dict[str, Any]]:
        from community_bot.permissions import parse_permissions

        rows = await self.fetchall("SELECT * FROM staff_roles ORDER BY rank DESC, name")
        for row in rows:
            row["permissions"] = parse_permissions(str(row.get("permissions_json") or "[]"))
        return rows

    async def get_staff_role(self, slug: str) -> dict[str, Any] | None:
        from community_bot.permissions import parse_permissions

        row = await self.fetchone("SELECT * FROM staff_roles WHERE slug = ?", (slug,))
        if not row:
            return None
        row["permissions"] = parse_permissions(str(row.get("permissions_json") or "[]"))
        return row

    async def create_staff_role(self, slug: str, name: str, rank: int, permissions: list[str] | None = None) -> bool:
        from community_bot.permissions import dump_permissions

        try:
            await self.execute(
                """
                INSERT INTO staff_roles(slug, name, rank, permissions_json, is_system, created_at)
                VALUES (?, ?, ?, ?, 0, ?)
                """,
                (slug, name, rank, dump_permissions(permissions or []), utcnow()),
            )
        except Exception:
            return False
        return True

    async def update_staff_role(
        self,
        slug: str,
        *,
        name: str | None = None,
        rank: int | None = None,
        permissions: list[str] | None = None,
    ) -> bool:
        from community_bot.permissions import dump_permissions

        role = await self.get_staff_role(slug)
        if not role:
            return False
        new_name = name if name is not None else str(role["name"])
        new_rank = rank if rank is not None else int(role["rank"])
        new_perms = dump_permissions(permissions if permissions is not None else list(role["permissions"]))
        await self.execute(
            "UPDATE staff_roles SET name = ?, rank = ?, permissions_json = ? WHERE slug = ?",
            (new_name, new_rank, new_perms, slug),
        )
        return True

    async def delete_staff_role(self, slug: str) -> bool:
        role = await self.get_staff_role(slug)
        if not role or int(role["is_system"]):
            return False
        async with self.connect() as db:
            await db.execute("UPDATE users SET role = 'member', updated_at = ? WHERE role = ?", (utcnow(), slug))
            cursor = await db.execute("DELETE FROM staff_roles WHERE slug = ? AND is_system = 0", (slug,))
            await db.commit()
            return cursor.rowcount == 1

    async def list_users(self, limit: int = 30) -> list[dict[str, Any]]:
        return await self.fetchall(
            """
            SELECT u.user_id, u.username, u.telegram_name, u.profile_name, u.role
            FROM users u
            LEFT JOIN staff_roles r ON r.slug = u.role
            ORDER BY COALESCE(r.rank, 0) DESC, u.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )

    async def list_all_users(self) -> list[dict[str, Any]]:
        return await self.fetchall(
            """
            SELECT * FROM users
            ORDER BY updated_at DESC
            """
        )

    async def update_profile(self, user_id: int, field: str, value: Any) -> None:
        allowed = {
            "profile_name",
            "age",
            "hobbies",
            "avatar_file_id",
            "avatar_media_type",
            "profile_private",
            "profile_ornate",
            "moderator_note",
            "profile_bio",
        }
        if field not in allowed:
            raise ValueError("Недопустимое поле профиля")
        await self.execute(
            f"UPDATE users SET {field} = ?, updated_at = ? WHERE user_id = ?",
            (value, utcnow(), user_id),
        )
        if field in {"profile_bio", "profile_name", "age", "hobbies", "avatar_file_id"}:
            if field == "profile_bio":
                await self.sync_bio_auto_warn(user_id)
            user = await self.get_user(user_id)
            if user:
                from community_bot.domain import AUTO_REPUTATION_CAP
                from community_bot.profile_fill import profile_is_complete

                if not profile_is_complete(user) and int(user["reputation"]) > AUTO_REPUTATION_CAP:
                    await self.execute(
                        "UPDATE users SET reputation = ?, updated_at = ? WHERE user_id = ?",
                        (AUTO_REPUTATION_CAP, utcnow(), user_id),
                    )

        await self.reward_complete_profile(user_id)

    async def save_self_profile(self, user_id: int, values: dict, revision: str, *, avatar: bool = False) -> bool:
        from community_bot.profile_fields import profile_revision, validate_profile_fields
        from community_bot.profile_fill import reputation_cap

        if avatar:
            if set(values) != {"avatar_file_id", "avatar_media_type"} or values["avatar_media_type"] != "photo":
                raise ValueError("Некорректный аватар")
        else:
            values = validate_profile_fields(values)
        async with self.connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            row = await (await connection.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))).fetchone()
            if not row or profile_revision(dict(row)) != revision:
                await connection.rollback()
                return False
            updated = dict(row) | values
            reputation = min(int(row["reputation"]), reputation_cap(updated))
            assignments = ", ".join(f"{key} = ?" for key in values)
            await connection.execute(
                f"UPDATE users SET {assignments}, reputation = ?, updated_at = ? WHERE user_id = ?",
                (*values.values(), reputation, utcnow(), user_id),
            )
            await connection.commit()
        if "profile_bio" in values:
            await self.sync_bio_auto_warn(user_id)
        await self.reward_complete_profile(user_id)
        return True

    async def reward_complete_profile(self, user_id: int) -> bool:
        from community_bot.profile_fill import profile_is_complete

        async with self.connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            row = await (await connection.execute("SELECT * FROM users WHERE user_id=?", (user_id,))).fetchone()
            if not row or not profile_is_complete(dict(row)):
                await connection.rollback()
                return False
            now = utcnow()
            inserted = await connection.execute(
                "INSERT OR IGNORE INTO profile_completion_rewards(user_id, awarded_at) VALUES (?, ?)", (user_id, now),
            )
            if inserted.rowcount != 1:
                await connection.rollback()
                return False
            await connection.execute(
                "UPDATE users SET cookies=cookies+10, updated_at=? WHERE user_id=?", (now, user_id),
            )
            await connection.execute(
                "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?,10,?,?,?)",
                (user_id, "profile_complete", "first_100_percent", now),
            )
            await connection.commit()
            return True

    async def create_application(self, user_id: int, answers: dict[str, Any]) -> int:
        if await self.has_approved_application(user_id):
            return 0
        if await self.has_pending_application(user_id):
            return 0
        return await self.execute(
            "INSERT INTO applications(user_id, answers_json, created_at) VALUES (?, ?, ?)",
            (user_id, json.dumps(answers, ensure_ascii=False), utcnow()),
        )

    async def has_approved_application(self, user_id: int) -> bool:
        row = await self.fetchone(
            "SELECT 1 AS ok FROM applications WHERE user_id = ? AND status = 'approved' LIMIT 1",
            (user_id,),
        )
        return bool(row)

    async def has_pending_application(self, user_id: int) -> bool:
        row = await self.fetchone(
            "SELECT 1 AS ok FROM applications WHERE user_id = ? AND status = 'pending' LIMIT 1",
            (user_id,),
        )
        return bool(row)

    async def get_application(self, application_id: int) -> dict[str, Any] | None:
        row = await self.fetchone(
            """
            SELECT a.*, u.username, u.telegram_name
            FROM applications a JOIN users u ON u.user_id = a.user_id
            WHERE a.id = ?
            """,
            (application_id,),
        )
        if row:
            row["answers"] = json.loads(row.pop("answers_json"))
        return row

    async def pending_applications(self, limit: int = 10) -> list[dict[str, Any]]:
        return await self.fetchall(
            """
            SELECT a.id, a.user_id, a.created_at, u.username, u.telegram_name
            FROM applications a JOIN users u ON u.user_id = a.user_id
            WHERE a.status = 'pending' ORDER BY a.created_at LIMIT ?
            """,
            (limit,),
        )

    async def decide_application(self, application_id: int, moderator_id: int, status: str, reason: str | None) -> bool:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                UPDATE applications
                SET status = ?, moderator_id = ?, decision_reason = ?, reviewed_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (status, moderator_id, reason, utcnow(), application_id),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def get_or_create_ticket(self, user_id: int) -> tuple[int, bool]:
        existing = await self.fetchone(
            "SELECT id FROM tickets WHERE user_id = ? AND status = 'open' ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        if existing:
            return int(existing["id"]), False
        now = utcnow()
        ticket_id = await self.execute(
            "INSERT INTO tickets(user_id, created_at, updated_at) VALUES (?, ?, ?)",
            (user_id, now, now),
        )
        return ticket_id, True

    async def get_ticket(self, ticket_id: int) -> dict[str, Any] | None:
        return await self.fetchone(
            """
            SELECT t.*, u.username, u.telegram_name
            FROM tickets t JOIN users u ON u.user_id = t.user_id WHERE t.id = ?
            """,
            (ticket_id,),
        )

    async def add_ticket_message(
        self,
        ticket_id: int,
        sender_id: int,
        sender_kind: str,
        text: str | None,
        media_type: str | None = None,
        media_file_id: str | None = None,
    ) -> None:
        now = utcnow()
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO ticket_messages(
                    ticket_id, sender_id, sender_kind, text, media_type, media_file_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (ticket_id, sender_id, sender_kind, text, media_type, media_file_id, now),
            )
            await db.execute("UPDATE tickets SET updated_at = ? WHERE id = ?", (now, ticket_id))
            await db.commit()

    async def close_ticket(self, ticket_id: int) -> None:
        await self.execute(
            "UPDATE tickets SET status = 'closed', updated_at = ? WHERE id = ?",
            (utcnow(), ticket_id),
        )

    async def reputation_actions_today(self, actor_id: int, action_date: date) -> int:
        row = await self.fetchone(
            "SELECT COUNT(*) AS count FROM reputation_actions WHERE actor_id = ? AND action_date = ?",
            (actor_id, action_date.isoformat()),
        )
        return int(row["count"]) if row else 0

    async def reputation_action_today_for_target(self, actor_id: int, target_id: int, action_date: date) -> bool:
        row = await self.fetchone(
            """
            SELECT 1 AS ok FROM reputation_actions
            WHERE actor_id = ? AND target_id = ? AND action_date = ?
            LIMIT 1
            """,
            (actor_id, target_id, action_date.isoformat()),
        )
        return bool(row)

    async def consume_hate_shield(self, user_id: int) -> bool:
        now = utcnow()
        async with self.connect() as db:
            cursor = await db.execute(
                "UPDATE users SET hate_shields = hate_shields - 1, updated_at = ? "
                "WHERE user_id = ? AND hate_shields > 0",
                (now, user_id),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def apply_reputation(self, actor_id: int, target_id: int, delta: int, action_date: date) -> int:
        from community_bot.profile_fill import reputation_cap

        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (target_id,))
            target_row = await cursor.fetchone()
            if not target_row:
                await db.rollback()
                raise ValueError("Пользователь не найден")
            current = int(target_row["reputation"])
            if delta > 0:
                cap = reputation_cap(dict(target_row))
                nxt = current if current >= cap else min(cap, current + delta)
            else:
                nxt = max(-20, current + delta)
            await db.execute(
                "UPDATE users SET reputation = ?, updated_at = ? WHERE user_id = ?",
                (nxt, now, target_id),
            )
            await db.execute(
                """
                INSERT INTO reputation_actions(actor_id, target_id, delta, action_date, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (actor_id, target_id, delta, action_date.isoformat(), now),
            )
            await db.commit()
            return nxt

    async def create_transfer(self, sender_id: int, receiver_id: int, amount: int) -> int:
        return await self.execute(
            """
            INSERT INTO pending_transfers(sender_id, receiver_id, amount, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (sender_id, receiver_id, amount, utcnow()),
        )

    async def complete_transfer(
        self,
        transfer_id: int,
        sender_id: int,
        restricted_threshold: int = 0,
        *, intent_id: str | None = None,
    ) -> tuple[bool, str, int]:
        from community_bot.domain import transfer_commission_percent

        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT * FROM pending_transfers WHERE id = ? AND sender_id = ?",
                (transfer_id, sender_id),
            )
            transfer = await cursor.fetchone()
            if not transfer or transfer["status"] != "pending":
                await db.rollback()
                return False, "Перевод уже обработан или не найден.", 0
            amount = int(transfer["amount"])
            cursor = await db.execute("SELECT reputation FROM users WHERE user_id = ?", (sender_id,))
            sender = await cursor.fetchone()
            if not sender:
                await db.rollback()
                return False, "Отправитель не найден.", 0
            percent = transfer_commission_percent(int(sender["reputation"]), restricted_threshold)
            if intent_id:
                error = await self._consume_wallet_intent(
                    db, intent_id, sender_id, 'transfer', amount, int(transfer['receiver_id']),
                )
                if error:
                    await db.rollback()
                    return False, error, 0
                cursor = await db.execute('SELECT payload_json FROM wallet_intents WHERE token=?', (intent_id,))
                payload = json.loads((await cursor.fetchone())['payload_json'])
                if payload.get('percent') != percent or payload.get('transfer_id') != transfer_id:
                    await db.rollback()
                    return False, 'Комиссия изменилась. Подтвердите перевод заново.', 0
            receiver_amount = amount * (100 - percent) // 100
            if receiver_amount <= 0:
                await db.rollback()
                return False, "После комиссии получателю ничего не останется.", 0
            debit = await db.execute(
                """
                UPDATE users SET cookies = cookies - ?, updated_at = ?
                WHERE user_id = ? AND cookies >= ?
                """,
                (amount, now, sender_id, amount),
            )
            if debit.rowcount != 1:
                await db.rollback()
                return False, "Недостаточно печенек.", 0
            await db.execute(
                "UPDATE users SET cookies = cookies + ?, updated_at = ? WHERE user_id = ?",
                (receiver_amount, now, int(transfer["receiver_id"])),
            )
            await db.execute(
                "UPDATE pending_transfers SET status = 'completed', completed_at = ? WHERE id = ?",
                (now, transfer_id),
            )
            await db.execute(
                "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
                (sender_id, -amount, "transfer", f"to:{transfer['receiver_id']}", now),
            )
            await db.execute(
                "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
                (int(transfer["receiver_id"]), receiver_amount, "transfer", f"from:{sender_id}", now),
            )
            await db.commit()
            return True, "ok", receiver_amount

    async def list_transactions(self, user_id: int, limit: int = 12, *, offset: int = 0) -> list[dict[str, Any]]:
        return await self.fetchall(
            "SELECT * FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT ? OFFSET ?",
            (user_id, limit, max(0, offset)),
        )

    async def create_wallet_intent(
        self,
        user_id: int,
        item: str,
        price: int,
        *,
        target_id: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        """Persist a short-lived confirmation; no balance changes until it is consumed."""
        if price <= 0:
            raise ValueError("The confirmed amount must be positive")
        now = datetime.now(UTC)
        token = secrets.token_urlsafe(12)
        catalog = await self.get_shop_item(item)
        await self.execute(
            """
            INSERT INTO wallet_intents(
                token, user_id, target_id, item, price, payload_json, catalog_version, created_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                token, user_id, target_id if target_id is not None else user_id, item, price,
                json.dumps(payload or {}, ensure_ascii=False),
                catalog["updated_at"] if catalog else None,
                now.isoformat(), (now + timedelta(minutes=15)).isoformat(),
            ),
        )
        return token

    async def get_wallet_intent(self, user_id: int, token: str) -> dict[str, Any] | None:
        row = await self.fetchone(
            "SELECT * FROM wallet_intents WHERE token = ? AND user_id = ? AND status = 'pending' AND expires_at > ?",
            (token, user_id, utcnow()),
        )
        if row:
            row["payload"] = json.loads(row["payload_json"])
        return row

    async def cancel_wallet_intent(self, user_id: int, token: str) -> None:
        await self.execute(
            "UPDATE wallet_intents SET status = 'cancelled' WHERE token = ? AND user_id = ? AND status = 'pending'",
            (token, user_id),
        )

    async def _consume_wallet_intent(
        self,
        db: aiosqlite.Connection,
        token: str | None,
        user_id: int,
        item: str,
        price: int,
        target_id: int,
    ) -> str | None:
        """Called inside the same write transaction as debit, delivery and ledger entry."""
        if token is None:  # Trusted internal operations; Telegram handlers always supply a token.
            return None
        cursor = await db.execute("SELECT * FROM wallet_intents WHERE token = ?", (token,))
        row = await cursor.fetchone()
        if not row or (row["user_id"], row["target_id"], row["item"], row["price"]) != (
            user_id, target_id, item, price,
        ):
            return "Подтверждение не найдено. Откройте операцию заново."
        if row["status"] == "cancelled":
            return "Операция отменена. Откройте её заново, если хотите повторить."
        if row["status"] != "pending":
            return "Эта операция уже выполнена. Повторного списания не было."
        if row["expires_at"] <= utcnow():
            return "Подтверждение устарело. Откройте операцию заново."
        if row["catalog_version"] is not None:
            cursor = await db.execute(
                """SELECT i.enabled, i.updated_at, c.enabled AS category_enabled
                FROM shop_items i JOIN shop_categories c ON c.slug = i.category_slug WHERE i.sku = ?""",
                (item,),
            )
            catalog = await cursor.fetchone()
            if not catalog or not catalog["enabled"] or not catalog["category_enabled"]:
                return "Товар больше недоступен."
            if catalog["updated_at"] != row["catalog_version"]:
                return "Условия товара изменились. Откройте товар и подтвердите покупку заново."
        payload = json.loads(row["payload_json"])
        if payload.get("shop_quote"):
            from community_bot.domain import discounted_price, reputation_tier
            from community_bot.shop_catalog import item_discount

            cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            payer = dict(await cursor.fetchone())
            discount = reputation_tier(payer["reputation"], int(payload["restricted_threshold"])).discount
            cursor = await db.execute("SELECT price FROM shop_items WHERE sku = ?", (item,))
            current_item = await cursor.fetchone()
            base = payload.get("base_amount") if item == "support" else (
                current_item["price"] if current_item else None
            )
            if not base or discounted_price(int(base), item_discount(item, discount)) != price:
                return "Цена или скидка изменились. Откройте товар и подтвердите покупку заново."
            feature = payload.get("feature")
            if feature:
                cursor = await db.execute("SELECT enabled FROM feature_flags WHERE key = ?", (feature,))
                flag = await cursor.fetchone()
                if not flag or not flag["enabled"]:
                    return "Эта функция временно выключена. Списания не было."
        elif item == 'pet_action':
            cursor = await db.execute("SELECT enabled FROM feature_flags WHERE key='tamagotchi'")
            flag = await cursor.fetchone()
            if not flag or not flag['enabled']:
                return 'Тамагочи временно выключены.'
        elif item == "cookie_topup":
            from community_bot.shop_catalog import normalize_cookie_shop

            cursor = await db.execute("SELECT value FROM bot_state WHERE key='cookie_shop'")
            config_row = await cursor.fetchone()
            config = normalize_cookie_shop(json.loads(config_row["value"]) if config_row else None)
            if not config["enabled"] or payload.get("amount") not in config["packs"] or (
                payload.get("rate") != config["rate_rub"] or payload["amount"] * config["rate_rub"] != price
            ):
                return "Условия пакета изменились. Откройте оплату заново."
        await db.execute(
            "UPDATE wallet_intents SET status = 'completed', completed_at = ? WHERE token = ?",
            (utcnow(), token),
        )
        return None

    async def get_active_loan(self, user_id: int) -> dict[str, Any] | None:
        return await self.fetchone(
            "SELECT * FROM cookie_loans WHERE user_id = ? AND status = 'active' ORDER BY id DESC LIMIT 1",
            (user_id,),
        )

    async def take_cookie_loan(
        self,
        user_id: int,
        restricted_threshold: int = 0,
        *,
        intent_id: str | None = None,
    ) -> tuple[bool, str, dict[str, Any] | None]:
        from community_bot.economy import LOAN_DAYS, LOAN_PRINCIPAL, loan_interest_percent, loan_repay_amount

        now_dt = datetime.now(UTC)
        now = now_dt.isoformat()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            error = await self._consume_wallet_intent(db, intent_id, user_id, "loan", LOAN_PRINCIPAL, user_id)
            if error:
                await db.rollback()
                return False, error, None
            cursor = await db.execute(
                "SELECT cookies, reputation, cookie_debt FROM users WHERE user_id = ?",
                (user_id,),
            )
            user = await cursor.fetchone()
            if not user:
                await db.rollback()
                return False, "Пользователь не найден.", None
            if int(user["cookie_debt"] or 0) > 0:
                await db.rollback()
                return False, "Сначала закройте текущий долг кошелька.", None
            cursor = await db.execute(
                "SELECT 1 FROM cookie_loans WHERE user_id = ? AND status = 'active'",
                (user_id,),
            )
            if await cursor.fetchone():
                await db.rollback()
                return False, "У вас уже есть открытый кредит.", None
            percent = loan_interest_percent(int(user["reputation"]), restricted_threshold)
            if intent_id is not None:
                cursor = await db.execute("SELECT payload_json FROM wallet_intents WHERE token = ?", (intent_id,))
                intent = await cursor.fetchone()
                if json.loads(intent["payload_json"]).get("interest_percent") != percent:
                    await db.rollback()
                    return False, "Ставка изменилась. Подтвердите новые условия кредита.", None
            due_amount = loan_repay_amount(LOAN_PRINCIPAL, percent)
            due_at = (now_dt + timedelta(days=LOAN_DAYS)).isoformat()
            await db.execute(
                "UPDATE users SET cookies = cookies + ?, updated_at = ? WHERE user_id = ?",
                (LOAN_PRINCIPAL, now, user_id),
            )
            cursor = await db.execute(
                """
                INSERT INTO cookie_loans(
                    user_id, principal, interest_percent, due_amount, due_at, status, created_at
                ) VALUES (?, ?, ?, ?, ?, 'active', ?)
                """,
                (user_id, LOAN_PRINCIPAL, percent, due_amount, due_at, now),
            )
            await db.execute(
                "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, LOAN_PRINCIPAL, "loan", f"due:{due_amount}", now),
            )
            await db.commit()
            return True, "ok", {
                "principal": LOAN_PRINCIPAL,
                "interest_percent": percent,
                "due_amount": due_amount,
                "due_at": due_at,
                "id": int(cursor.lastrowid or 0),
            }

    async def collect_due_loans(self) -> list[dict[str, Any]]:
        now = utcnow()
        collected: list[dict[str, Any]] = []
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT * FROM cookie_loans WHERE status = 'active' AND due_at <= ?",
                (now,),
            )
            rows = [dict(row) for row in await cursor.fetchall()]
            for loan in rows:
                user_id = int(loan["user_id"])
                due_amount = int(loan["due_amount"])
                cursor = await db.execute("SELECT cookies FROM users WHERE user_id = ?", (user_id,))
                user = await cursor.fetchone()
                if not user:
                    continue
                cookies = int(user["cookies"])
                pay = min(cookies, due_amount)
                remainder = due_amount - pay
                await db.execute(
                    """
                    UPDATE users SET cookies = cookies - ?, cookie_debt = cookie_debt + ?, updated_at = ?
                    WHERE user_id = ?
                    """,
                    (pay, remainder, now, user_id),
                )
                await db.execute(
                    "UPDATE cookie_loans SET status = 'collected', collected_at = ? WHERE id = ?",
                    (now, int(loan["id"])),
                )
                await db.execute(
                    "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
                    (user_id, -pay, "loan_repay", f"loan:{loan['id']};debt:{remainder}", now),
                )
                collected.append({**loan, "paid": pay, "debt_added": remainder})
            await db.commit()
        return collected

    async def repay_cookie_debt(
        self, user_id: int, amount: int, *, intent_id: str | None = None,
    ) -> tuple[bool, str]:
        if amount <= 0:
            return False, "Сумма погашения должна быть больше нуля."
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            error = await self._consume_wallet_intent(db, intent_id, user_id, "debt_repay", amount, user_id)
            if error:
                await db.rollback()
                return False, error
            cursor = await db.execute(
                """UPDATE users SET cookies = cookies - ?, cookie_debt = cookie_debt - ?, updated_at = ?
                WHERE user_id = ? AND cookies >= ? AND cookie_debt >= ?""",
                (amount, amount, now, user_id, amount, amount),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                return False, "Баланс или долг изменился. Откройте кошелёк и подтвердите сумму заново."
            await db.execute(
                "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, -amount, "debt_repay", "overdue", now),
            )
            await db.commit()
            return True, "ok"

    async def cancel_transfer(self, transfer_id: int, sender_id: int) -> bool:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                UPDATE pending_transfers SET status = 'cancelled', completed_at = ?
                WHERE id = ? AND sender_id = ? AND status = 'pending'
                """,
                (utcnow(), transfer_id, sender_id),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def add_cookies(self, user_id: int, amount: int, kind: str, details: str = "") -> None:
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                "UPDATE users SET cookies = cookies + ?, updated_at = ? WHERE user_id = ?",
                (amount, now, user_id),
            )
            await db.execute(
                "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, amount, kind, details, now),
            )
            await db.commit()

    async def set_cookies(self, user_id: int, amount: int, actor_id: int) -> tuple[bool, int]:
        if amount < 0:
            return False, 0
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT cookies FROM users WHERE user_id = ?", (user_id,))
            user = await cursor.fetchone()
            if not user:
                await db.rollback()
                return False, 0
            difference = amount - int(user["cookies"])
            await db.execute(
                "UPDATE users SET cookies = ?, updated_at = ? WHERE user_id = ?",
                (amount, now, user_id),
            )
            await db.execute(
                "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, difference, "admin_set", f"by:{actor_id}", now),
            )
            await db.commit()
            return True, difference

    async def buy_item(
        self, user_id: int, item: str, price: int, target_id: int | None = None,
        *, intent_id: str | None = None, profile_value: str | None = None,
    ) -> tuple[bool, str]:
        from community_bot.shop_catalog import ITEM_LABELS

        if price <= 0:
            return False, "Некорректная цена."
        if item not in ITEM_LABELS and item not in {"event_pass", "support", "immunity"}:
            return False, "Для этого товара ещё не настроена выдача."
        if item == "tamagotchi":
            return False, "Сначала выберите питомца и его имя."
        if item == "video_avatar" and not profile_value:
            return False, "Сначала отправьте видео."
        now = utcnow()
        beneficiary = target_id if target_id is not None else user_id
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            error = await self._consume_wallet_intent(db, intent_id, user_id, item, price, beneficiary)
            if error:
                await db.rollback()
                return False, error
            cursor = await db.execute("SELECT 1 FROM users WHERE user_id = ?", (beneficiary,))
            if not await cursor.fetchone():
                await db.rollback()
                return False, "Получатель не найден."
            cursor = await db.execute(
                "UPDATE users SET cookies = cookies - ?, updated_at = ? WHERE user_id = ? AND cookies >= ?",
                (price, now, user_id, price),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                return False, "Недостаточно печенек."
            error = await self._apply_shop_effect(db, beneficiary, item, now)
            if error:
                await db.rollback()
                return False, error
            if item == "video_avatar":
                await db.execute(
                    "UPDATE users SET avatar_file_id = ?, avatar_media_type = 'video' WHERE user_id = ?",
                    (profile_value, beneficiary),
                )
            await db.execute(
                "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, -price, "shop", item if beneficiary == user_id else f"{item}->{beneficiary}", now),
            )
            await db.commit()
            return True, "ok"

    async def _apply_shop_effect(
        self, db: aiosqlite.Connection, user_id: int, item: str, now: str,
    ) -> str | None:
        from community_bot.shop_catalog import IMMUNITY_HOURS

        if item == "restore_rep":
            from community_bot.profile_fill import reputation_cap

            cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            current = int(row["reputation"]) if row else 0
            cap = reputation_cap(dict(row) if row else {})
            if current >= cap:
                return "Репутация уже на доступном максимуме. Для роста заполните профиль, если он ещё не заполнен."
            nxt = current if current >= cap else min(cap, current + 10)
            await db.execute(
                "UPDATE users SET reputation = ? WHERE user_id = ?",
                (nxt, user_id),
            )
        elif item == "reset_limits":
            await db.execute(
                "DELETE FROM reputation_actions WHERE actor_id = ? AND action_date = ?",
                (user_id, datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat()),
            )
        elif item == "forgive":
            await db.execute("UPDATE users SET warnings = 0 WHERE user_id = ?", (user_id,))
        elif item == "rep_shield":
            await db.execute(
                "UPDATE users SET hate_shields = hate_shields + 1, updated_at = ? WHERE user_id = ?",
                (now, user_id),
            )
        elif item == "private_profile":
            cursor = await db.execute("SELECT profile_private FROM users WHERE user_id = ?", (user_id,))
            if (await cursor.fetchone())["profile_private"]:
                return "Профиль уже скрыт."
            await db.execute(
                "UPDATE users SET profile_private = 1, updated_at = ? WHERE user_id = ?",
                (now, user_id),
            )
        elif item == "ornate_profile":
            cursor = await db.execute("SELECT profile_ornate FROM users WHERE user_id = ?", (user_id,))
            if (await cursor.fetchone())["profile_ornate"]:
                return "Оформление профиля уже куплено."
            await db.execute(
                "UPDATE users SET profile_ornate = 1, updated_at = ? WHERE user_id = ?",
                (now, user_id),
            )
        elif item == "season_pack":
            cursor = await db.execute("SELECT 1 FROM pets WHERE user_id = ?", (user_id,))
            if not await cursor.fetchone():
                return "Для сезонного набора сначала заведите питомца."
            for part in ("rep_shield", "pet_meal"):
                await self._apply_shop_effect(db, user_id, part, now)
        elif item == "pet_meal":
            await db.execute(
                "UPDATE pets SET hunger = MIN(100, hunger + 40), sleeping = 0, updated_at = ? WHERE user_id = ?",
                (now, user_id),
            )
        elif item == "pet_drink":
            await db.execute(
                "UPDATE pets SET thirst = MIN(100, thirst + 50), sleeping = 0, updated_at = ? WHERE user_id = ?",
                (now, user_id),
            )
        elif item in IMMUNITY_HOURS or item == "immunity":
            cursor = await db.execute("SELECT hate_immunity_until FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            start = datetime.fromisoformat(now)
            if row["hate_immunity_until"]:
                current_until = datetime.fromisoformat(row["hate_immunity_until"])
                start = max(start, current_until if current_until.tzinfo else current_until.replace(tzinfo=UTC))
            until = start + timedelta(hours=IMMUNITY_HOURS.get(item, 24))
            await db.execute(
                "UPDATE users SET hate_immunity_until = ?, updated_at = ? WHERE user_id = ?",
                (until.isoformat(), now, user_id),
            )
        return None

    async def set_immunity(self, user_id: int, until: datetime) -> None:
        await self.execute(
            "UPDATE users SET hate_immunity_until = ?, updated_at = ? WHERE user_id = ?",
            (until.astimezone(UTC).isoformat(), utcnow(), user_id),
        )

    async def add_warning(self, user_id: int) -> int:
        async with self.connect() as db:
            await db.execute(
                "UPDATE users SET warnings = warnings + 1, updated_at = ? WHERE user_id = ?",
                (utcnow(), user_id),
            )
            cursor = await db.execute("SELECT warnings FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            await db.commit()
            return int(row["warnings"]) if row else 0

    async def remove_warning(self, user_id: int) -> int:
        async with self.connect() as db:
            await db.execute(
                "UPDATE users SET warnings = MAX(0, warnings - 1), updated_at = ? WHERE user_id = ?",
                (utcnow(), user_id),
            )
            cursor = await db.execute("SELECT warnings FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            await db.commit()
            return int(row["warnings"]) if row else 0

    async def set_warnings(self, user_id: int, warnings: int) -> bool:
        if warnings < 0:
            return False
        async with self.connect() as db:
            cursor = await db.execute(
                "UPDATE users SET warnings = ?, updated_at = ? WHERE user_id = ?",
                (warnings, utcnow(), user_id),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def create_cookie_order(
        self,
        user_id: int,
        amount: int,
        rubles: int,
        receipt_media_type: str,
        receipt_file_id: str,
    ) -> int:
        return await self.execute(
            """
            INSERT INTO cookie_orders(
                user_id, amount, rubles, receipt_media_type, receipt_file_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, amount, rubles, receipt_media_type, receipt_file_id, utcnow()),
        )

    async def get_cookie_order(self, order_id: int) -> dict[str, Any] | None:
        return await self.fetchone(
            """
            SELECT o.*, u.username, u.telegram_name, u.profile_name
            FROM cookie_orders o JOIN users u ON u.user_id = o.user_id
            WHERE o.id = ?
            """,
            (order_id,),
        )

    async def pending_cookie_orders(self, limit: int = 20) -> list[dict[str, Any]]:
        return await self.fetchall(
            """
            SELECT o.*, u.username, u.telegram_name, u.profile_name
            FROM cookie_orders o JOIN users u ON u.user_id = o.user_id
            WHERE o.status = 'pending'
            ORDER BY o.created_at
            LIMIT ?
            """,
            (limit,),
        )

    async def review_cookie_order(self, order_id: int, reviewer_id: int, approved: bool) -> dict[str, Any] | None:
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT * FROM cookie_orders WHERE id = ?", (order_id,))
            order = await cursor.fetchone()
            if not order or order["status"] != "pending":
                await db.rollback()
                return None
            status = "approved" if approved else "rejected"
            await db.execute(
                "UPDATE cookie_orders SET status = ?, reviewer_id = ?, reviewed_at = ? WHERE id = ?",
                (status, reviewer_id, now, order_id),
            )
            if approved:
                await db.execute(
                    "UPDATE users SET cookies = cookies + ?, updated_at = ? WHERE user_id = ?",
                    (int(order["amount"]), now, int(order["user_id"])),
                )
                await db.execute(
                    "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
                    (int(order["user_id"]), int(order["amount"]), "sbp_payment", f"order:{order_id}", now),
                )
            await db.commit()
            return dict(order)

    async def create_scheduled_message(
        self,
        target: str,
        text: str | None,
        media_type: str | None,
        media_file_id: str | None,
        interval_minutes: int,
        created_by: int,
    ) -> int:
        if target not in {"community", "private_all"} or interval_minutes < 5:
            raise ValueError("Некорректные параметры автосообщения")
        now = datetime.now(UTC)
        return await self.execute(
            """
            INSERT INTO scheduled_messages(
                target, text, media_type, media_file_id, interval_minutes,
                next_run_at, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                target,
                text,
                media_type,
                media_file_id,
                interval_minutes,
                (now + timedelta(minutes=interval_minutes)).isoformat(),
                created_by,
                now.isoformat(),
                now.isoformat(),
            ),
        )

    async def list_scheduled_messages(self) -> list[dict[str, Any]]:
        return await self.fetchall("SELECT * FROM scheduled_messages ORDER BY id DESC")

    async def due_scheduled_messages(self, now: datetime) -> list[dict[str, Any]]:
        return await self.fetchall(
            "SELECT * FROM scheduled_messages WHERE enabled = 1 AND next_run_at <= ? ORDER BY next_run_at",
            (now.astimezone(UTC).isoformat(),),
        )

    async def mark_scheduled_sent(self, schedule_id: int, interval_minutes: int) -> None:
        now = datetime.now(UTC)
        await self.execute(
            "UPDATE scheduled_messages SET next_run_at = ?, updated_at = ? WHERE id = ?",
            ((now + timedelta(minutes=interval_minutes)).isoformat(), now.isoformat(), schedule_id),
        )

    async def toggle_scheduled_message(self, schedule_id: int) -> bool:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                UPDATE scheduled_messages
                SET enabled = CASE enabled WHEN 1 THEN 0 ELSE 1 END, updated_at = ?
                WHERE id = ?
                """,
                (utcnow(), schedule_id),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def delete_scheduled_message(self, schedule_id: int) -> bool:
        async with self.connect() as db:
            cursor = await db.execute("DELETE FROM scheduled_messages WHERE id = ?", (schedule_id,))
            await db.commit()
            return cursor.rowcount == 1

    async def create_roulette(self, chat_id: int, challenger_id: int, opponent_id: int, stake: int = 10) -> int:
        return await self.execute(
            """
            INSERT INTO roulette_games(chat_id, challenger_id, opponent_id, stake, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (chat_id, challenger_id, opponent_id, stake, utcnow()),
        )

    async def get_roulette(self, game_id: int) -> dict[str, Any] | None:
        return await self.fetchone("SELECT * FROM roulette_games WHERE id = ?", (game_id,))

    async def cancel_roulette(self, game_id: int, opponent_id: int) -> bool:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                UPDATE roulette_games SET status = 'declined', completed_at = ?
                WHERE id = ? AND opponent_id = ? AND status = 'pending'
                """,
                (utcnow(), game_id, opponent_id),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def settle_roulette(
        self,
        game_id: int,
        opponent_id: int,
        winner_id: int,
    ) -> tuple[bool, str, dict[str, Any] | None]:
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT * FROM roulette_games WHERE id = ?", (game_id,))
            game = await cursor.fetchone()
            if not game or game["status"] != "pending" or int(game["opponent_id"]) != opponent_id:
                await db.rollback()
                return False, "Игра уже завершена или приглашение недействительно.", None
            players = (int(game["challenger_id"]), int(game["opponent_id"]))
            if winner_id not in players:
                await db.rollback()
                return False, "Некорректный победитель.", None
            loser_id = players[1] if winner_id == players[0] else players[0]
            await db.execute(
                """
                UPDATE roulette_games
                SET status = 'completed', winner_id = ?, payout = 0, completed_at = ?
                WHERE id = ?
                """,
                (winner_id, now, game_id),
            )
            await db.commit()
            result = dict(game)
            result.update({"winner_id": winner_id, "loser_id": loser_id, "payout": 0})
            return True, "ok", result

    async def remember_bot_message(self, chat_id: int, message_id: int) -> None:
        await self.execute(
            "INSERT OR REPLACE INTO bot_chat_messages(chat_id, message_id, created_at) VALUES (?, ?, ?)",
            (chat_id, message_id, utcnow()),
        )

    async def recent_bot_message_ids(self, chat_id: int, limit: int = 50) -> list[int]:
        rows = await self.fetchall(
            "SELECT message_id FROM bot_chat_messages WHERE chat_id = ? ORDER BY created_at DESC LIMIT ?",
            (chat_id, limit),
        )
        return [int(row["message_id"]) for row in rows]

    async def forget_bot_messages(self, chat_id: int, message_ids: list[int]) -> None:
        if not message_ids:
            return
        placeholders = ",".join("?" for _ in message_ids)
        await self.execute(
            f"DELETE FROM bot_chat_messages WHERE chat_id = ? AND message_id IN ({placeholders})",
            (chat_id, *message_ids),
        )

    async def claim_freebie(self, user_id: int, amount: int) -> bool:
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "INSERT OR IGNORE INTO freebie_claims(user_id, amount, claimed_at) VALUES (?, ?, ?)",
                (user_id, amount, now),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                return False
            await db.execute(
                "UPDATE users SET cookies = cookies + ?, updated_at = ? WHERE user_id = ?",
                (amount, now, user_id),
            )
            await db.execute(
                "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, amount, "subscription_freebie", "channel", now),
            )
            await db.commit()
            return True

    async def record_activity(self, user_id: int, chat_id: int, rewards_enabled: bool = True) -> tuple[int, bool]:
        """Count one community message and grant pet supplies every 120 messages."""
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                """
                INSERT INTO user_activity(user_id, chat_id, message_count, last_message_at)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(user_id, chat_id) DO UPDATE SET
                    message_count = message_count + 1,
                    last_message_at = excluded.last_message_at
                """,
                (user_id, chat_id, now),
            )
            cursor = await db.execute(
                "SELECT message_count, reward_checkpoint FROM user_activity WHERE user_id = ? AND chat_id = ?",
                (user_id, chat_id),
            )
            activity = await cursor.fetchone()
            assert activity is not None
            count = int(activity["message_count"])
            checkpoint = count // 120
            rewarded = False
            if checkpoint > int(activity["reward_checkpoint"]):
                pet_cursor = await db.execute("SELECT 1 FROM pets WHERE user_id = ?", (user_id,))
                if rewards_enabled and await pet_cursor.fetchone():
                    await db.execute(
                        "UPDATE pets SET food_units = food_units + 1, water_units = water_units + 1, updated_at = ? "
                        "WHERE user_id = ?",
                        (now, user_id),
                    )
                    rewarded = True
                await db.execute(
                    "UPDATE user_activity SET reward_checkpoint = ? WHERE user_id = ? AND chat_id = ?",
                    (checkpoint, user_id, chat_id),
                )
            week_id = datetime.now(UTC).strftime("%G-W%V")
            await db.execute(
                """
                INSERT INTO weekly_scores(user_id, week_id, messages) VALUES (?, ?, 1)
                ON CONFLICT(user_id, week_id) DO UPDATE SET messages = messages + 1
                """,
                (user_id, week_id),
            )
            day = datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat()
            await db.execute(
                """
                INSERT INTO daily_scores(user_id, day, chat_id, messages) VALUES (?, ?, ?, 1)
                ON CONFLICT(user_id, day, chat_id) DO UPDATE SET messages = messages + 1
                """,
                (user_id, day, chat_id),
            )
            await db.commit()
            return count, rewarded

    async def get_activity(self, user_id: int, chat_id: int) -> dict[str, Any] | None:
        return await self.fetchone(
            "SELECT * FROM user_activity WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id),
        )

    async def purchase_pet(
        self, user_id: int, species: str, name: str, price: int, *, intent_id: str | None = None,
    ) -> tuple[bool, str]:
        from community_bot.pets_talk import SPECIES

        if price <= 0 or species not in SPECIES or not 1 <= len(name.strip()) <= 24:
            return False, "Некорректная покупка питомца."
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            error = await self._consume_wallet_intent(db, intent_id, user_id, "tamagotchi", price, user_id)
            if error:
                await db.rollback()
                return False, error
            cursor = await db.execute("SELECT cookies FROM users WHERE user_id = ?", (user_id,))
            user = await cursor.fetchone()
            if not user:
                await db.rollback()
                return False, "Пользователь не найден."
            cursor = await db.execute("SELECT 1 FROM pets WHERE user_id = ?", (user_id,))
            if await cursor.fetchone():
                await db.rollback()
                return False, "У вас уже есть питомец."
            if int(user["cookies"]) < price:
                await db.rollback()
                return False, "Недостаточно печенек."
            await db.execute(
                "UPDATE users SET cookies = cookies - ?, updated_at = ? WHERE user_id = ?",
                (price, now, user_id),
            )
            await db.execute(
                """
                INSERT INTO pets(user_id, species, name, last_tick_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, species, name, now, now, now),
            )
            await db.execute(
                "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, -price, "shop", "tamagotchi", now),
            )
            await db.commit()
            return True, "ok"

    async def settle_pet(self, user_id: int) -> dict[str, Any] | None:
        from community_bot.expedition import parse_loot, roll_expedition_loot

        now_dt = datetime.now(UTC)
        now = now_dt.isoformat()
        loot_payload: dict[str, object] | None = None
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT * FROM pets WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            if not row:
                await db.rollback()
                return None
            pet = dict(row)
            try:
                last_tick = datetime.fromisoformat(str(pet["last_tick_at"])).astimezone(UTC)
            except ValueError:
                last_tick = now_dt
            hours = max(0, int((now_dt - last_tick).total_seconds() // 3600))
            expedition_until = str(pet.get("expedition_until") or "")
            on_expedition = False
            expedition_due = False
            if expedition_until:
                try:
                    until_dt = datetime.fromisoformat(expedition_until)
                    if until_dt.tzinfo is None:
                        until_dt = until_dt.replace(tzinfo=UTC)
                    on_expedition = until_dt > now_dt
                    expedition_due = until_dt <= now_dt
                except ValueError:
                    expedition_due = True
            if hours and not on_expedition:
                hunger = max(0, int(pet["hunger"]) - hours * 2)
                thirst = max(0, int(pet["thirst"]) - hours * 3)
                sleeping = int(hunger == 0 or thirst == 0)
                mood = max(0, min(100, (hunger + thirst) // 2 - (20 if sleeping else 0)))
                new_tick = (last_tick + timedelta(hours=hours)).isoformat()
                await db.execute(
                    """
                    UPDATE pets SET hunger = ?, thirst = ?, mood = ?, sleeping = ?,
                        last_tick_at = ?, updated_at = ? WHERE user_id = ?
                    """,
                    (hunger, thirst, mood, sleeping, new_tick, now, user_id),
                )
            if expedition_due:
                loot = parse_loot(str(pet.get("expedition_loot") or "")) or roll_expedition_loot()
                loot_payload = loot.to_json()
                reward = int(loot.amount) if loot.kind == "cookies" else 0
                if reward:
                    await db.execute(
                        "UPDATE users SET cookies = cookies + ?, updated_at = ? WHERE user_id = ?",
                        (reward, now, user_id),
                    )
                    await db.execute(
                        "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
                        (user_id, reward, "pet_expedition", json.dumps(loot_payload, ensure_ascii=False), now),
                    )
                await db.execute(
                    """
                    UPDATE pets SET expedition_until = NULL, expedition_reward = ?, expedition_loot = ?,
                        expedition_notice_sent = 0, updated_at = ? WHERE user_id = ?
                    """,
                    (reward, json.dumps(loot_payload, ensure_ascii=False), now, user_id),
                )
            await db.commit()
        result = await self.fetchone("SELECT * FROM pets WHERE user_id = ?", (user_id,))
        if result is None:
            return None
        result["payout"] = 0
        result["earned_milli"] = 0
        if loot_payload:
            result["expedition_done"] = True
            result["expedition_loot"] = loot_payload
            result["payout"] = int(loot_payload.get("amount") or 0) if loot_payload.get("kind") == "cookies" else 0
        return result

    async def get_pet(self, user_id: int, settle: bool = True) -> dict[str, Any] | None:
        if settle:
            try:
                settled = await self.settle_pet(user_id)
                if settled is not None:
                    return settled
            except Exception:
                logger.exception("Не удалось обновить состояние питомца %s", user_id)
        return await self.fetchone("SELECT * FROM pets WHERE user_id = ?", (user_id,))

    async def list_pets(self) -> list[dict[str, Any]]:
        return await self.fetchall("SELECT * FROM pets ORDER BY updated_at")

    async def use_pet_supply(
        self, user_id: int, kind: str, *, intent_id: str | None = None,
    ) -> tuple[bool, str, dict[str, Any] | None]:
        if kind not in {"food", "water"}:
            return False, "Неизвестный припас.", None
        await self.settle_pet(user_id)
        column = "food_units" if kind == "food" else "water_units"
        stat = "hunger" if kind == "food" else "thirst"
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            error = await self._consume_wallet_intent(db, intent_id, user_id, 'pet_action', 1, user_id)
            if error:
                await db.rollback()
                return False, error, None

            cursor = await db.execute(
                f"UPDATE pets SET {column} = {column} - 1, {stat} = MIN(100, {stat} + 20), "
                "sleeping = 0, updated_at = ? WHERE user_id = ? AND " + column + " > 0 AND " + stat + " < 100",
                (now, user_id),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                return False, "Нет подходящих припасов. Их дают за каждые 120 сообщений.", None
            await db.commit()
        return True, "ok", await self.get_pet(user_id, settle=False)

    async def purchase_pet_supply(
        self,
        user_id: int,
        kind: str,
        gain: int,
        price: int,
        item: str,
        payer_id: int | None = None,
        *,
        intent_id: str | None = None,
    ) -> tuple[bool, str, dict[str, Any] | None]:
        if kind not in {"food", "water"} or gain <= 0 or price <= 0:
            return False, "Некорректный товар.", None
        payer = payer_id or user_id
        await self.settle_pet(user_id)
        stat = "hunger" if kind == "food" else "thirst"
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            error = await self._consume_wallet_intent(db, intent_id, payer, item, price, user_id)
            if error:
                await db.rollback()
                return False, error, None
            cursor = await db.execute(f"SELECT {stat} FROM pets WHERE user_id = ?", (user_id,))
            pet = await cursor.fetchone()
            if not pet:
                await db.rollback()
                return False, "Сначала заведите тамагочи.", None
            if int(pet[stat]) >= 100:
                await db.rollback()
                return False, "Этот показатель питомца уже на максимуме. Списания не было.", None
            cursor = await db.execute(
                "UPDATE users SET cookies = cookies - ?, updated_at = ? WHERE user_id = ? AND cookies >= ?",
                (price, now, payer, price),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                return False, "Недостаточно печенек.", None
            await db.execute(
                f"UPDATE pets SET {stat} = MIN(100, {stat} + ?), sleeping = 0, updated_at = ? WHERE user_id = ?",
                (gain, now, user_id),
            )
            await db.execute(
                "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
                (payer, -price, "pet_shop", item, now),
            )
            await db.commit()
        return True, "ok", await self.get_pet(user_id, settle=False)

    async def rename_pet(self, user_id: int, name: str) -> bool:
        async with self.connect() as db:
            cursor = await db.execute(
                "UPDATE pets SET name = ?, updated_at = ? WHERE user_id = ?",
                (name, utcnow(), user_id),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def mark_pet_guard(self, user_id: int, used_on: str) -> None:
        await self.execute(
            "UPDATE pets SET guard_used_on = ?, updated_at = ? WHERE user_id = ?",
            (used_on, utcnow(), user_id),
        )

    async def search_users(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        needle = f"%{query.strip()}%"
        if query.strip().isdigit():
            by_id = await self.fetchone("SELECT * FROM users WHERE user_id = ?", (int(query.strip()),))
            if by_id:
                return [by_id]
        return await self.fetchall(
            """
            SELECT * FROM users
            WHERE telegram_name LIKE ? OR profile_name LIKE ? OR IFNULL(username, '') LIKE ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (needle, needle, needle, limit),
        )

    async def list_open_tickets(self, limit: int = 15) -> list[dict[str, Any]]:
        return await self.fetchall(
            """
            SELECT t.*, u.profile_name, u.telegram_name, u.username
            FROM tickets t
            JOIN users u ON u.user_id = t.user_id
            WHERE t.status = 'open'
            ORDER BY t.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )

    async def set_weekly_star(self, user_id: int) -> None:
        await self.set_bot_state("weekly_star_user_id", str(user_id))

    async def mark_pet_talk(self, user_id: int) -> None:
        now = utcnow()
        await self.execute(
            "UPDATE pets SET last_talk_at = ?, mood = MIN(100, mood + 4), updated_at = ? WHERE user_id = ?",
            (now, now, user_id),
        )

    async def create_party_game(
        self,
        chat_id: int,
        game_type: str,
        creator_id: int,
        state: dict[str, Any] | None = None,
    ) -> tuple[int, bool]:
        now = utcnow()
        payload = json.dumps(state or {}, ensure_ascii=False)
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT id FROM party_games WHERE chat_id = ? AND status IN ('lobby', 'active') "
                "ORDER BY id DESC LIMIT 1",
                (chat_id,),
            )
            existing = await cursor.fetchone()
            if existing:
                await db.rollback()
                return int(existing["id"]), False
            cursor = await db.execute(
                "INSERT INTO party_games(chat_id, game_type, creator_id, state_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (chat_id, game_type, creator_id, payload, now, now),
            )
            game_id = int(cursor.lastrowid)
            await db.execute(
                "INSERT INTO party_game_players(game_id, user_id, joined_at) VALUES (?, ?, ?)",
                (game_id, creator_id, now),
            )
            await db.commit()
            return game_id, True

    async def create_staked_game(
        self,
        chat_id: int,
        game_type: str,
        creator_id: int,
        stake: int,
    ) -> tuple[int | None, str]:
        if stake <= 0:
            return None, "Ставка должна быть больше нуля."
        now = utcnow()
        state = {"stake": stake, "phase": "lobby"}
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT id FROM party_games WHERE chat_id = ? AND status IN ('lobby', 'active') "
                "ORDER BY id DESC LIMIT 1",
                (chat_id,),
            )
            existing = await cursor.fetchone()
            if existing:
                await db.rollback()
                return int(existing["id"]), "В чате уже идёт другая игра."
            cursor = await db.execute(
                "UPDATE users SET cookies = cookies - ?, updated_at = ? WHERE user_id = ? AND cookies >= ?",
                (stake, now, creator_id, stake),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                return None, "Недостаточно печенек для этой ставки."
            await db.execute(
                "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
                (creator_id, -stake, "cookie_game_stake", game_type, now),
            )
            cursor = await db.execute(
                "INSERT INTO party_games(chat_id, game_type, creator_id, state_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (chat_id, game_type, creator_id, json.dumps(state, ensure_ascii=False), now, now),
            )
            game_id = int(cursor.lastrowid)
            await db.execute(
                "INSERT INTO party_game_players(game_id, user_id, secret_json, joined_at) VALUES (?, ?, ?, ?)",
                (game_id, creator_id, json.dumps({"stake": stake}), now),
            )
            await db.commit()
            return game_id, "ok"

    async def join_staked_game(self, game_id: int, user_id: int, maximum: int = 4) -> tuple[bool, str]:
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT * FROM party_games WHERE id = ?", (game_id,))
            game = await cursor.fetchone()
            if not game or game["status"] != "lobby":
                await db.rollback()
                return False, "Набор в эту игру уже закрыт."
            state = json.loads(str(game["state_json"]) or "{}")
            stake = int(state.get("stake") or 0)
            if stake <= 0:
                await db.rollback()
                return False, "У этой игры нет ставки."
            cursor = await db.execute("SELECT COUNT(*) AS count FROM party_game_players WHERE game_id = ?", (game_id,))
            count = int((await cursor.fetchone())["count"])
            if count >= maximum:
                await db.rollback()
                return False, "В лобби уже нет мест."
            cursor = await db.execute(
                "SELECT 1 FROM party_game_players WHERE game_id = ? AND user_id = ?",
                (game_id, user_id),
            )
            if await cursor.fetchone():
                await db.rollback()
                return False, "Вы уже присоединились."
            cursor = await db.execute(
                "UPDATE users SET cookies = cookies - ?, updated_at = ? WHERE user_id = ? AND cookies >= ?",
                (stake, now, user_id, stake),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                return False, "Недостаточно печенек для этой ставки."
            await db.execute(
                "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, -stake, "cookie_game_stake", str(game["game_type"]), now),
            )
            await db.execute(
                "INSERT INTO party_game_players(game_id, user_id, secret_json, joined_at) VALUES (?, ?, ?, ?)",
                (game_id, user_id, json.dumps({"stake": stake}), now),
            )
            await db.commit()
            return True, "Вы в игре. Ставка списана."

    async def update_staked_game_stake(self, game_id: int, actor_id: int, new_stake: int) -> tuple[bool, str]:
        if not 1 <= new_stake <= 500:
            return False, "Ставка — целое число от 1 до 500 🍪."
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT * FROM party_games WHERE id = ?", (game_id,))
            game = await cursor.fetchone()
            if not game or game["status"] != "lobby":
                await db.rollback()
                return False, "Менять ставку можно только в открытом лобби."
            if int(game["creator_id"]) != actor_id:
                await db.rollback()
                return False, "Ставку меняет только создатель лобби."
            state = json.loads(str(game["state_json"] or "{}"))
            old_stake = int(state.get("stake") or 0)
            if old_stake == new_stake:
                await db.rollback()
                return False, "Эта ставка уже стоит."
            delta = new_stake - old_stake
            cursor = await db.execute("SELECT user_id FROM party_game_players WHERE game_id = ?", (game_id,))
            players = [int(row["user_id"]) for row in await cursor.fetchall()]
            if delta > 0:
                for user_id in players:
                    cursor = await db.execute(
                        "UPDATE users SET cookies = cookies - ?, updated_at = ? WHERE user_id = ? AND cookies >= ?",
                        (delta, now, user_id, delta),
                    )
                    if cursor.rowcount != 1:
                        await db.rollback()
                        return False, "Не у всех игроков хватает печенек на новую ставку."
                    await db.execute(
                        "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
                        (user_id, -delta, "cookie_game_restake", f"{old_stake}->{new_stake}", now),
                    )
            elif delta < 0:
                refund = -delta
                for user_id in players:
                    await db.execute(
                        "UPDATE users SET cookies = cookies + ?, updated_at = ? WHERE user_id = ?",
                        (refund, now, user_id),
                    )
                    await db.execute(
                        "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
                        (user_id, refund, "cookie_game_restake", f"{old_stake}->{new_stake}", now),
                    )
            state["stake"] = new_stake
            await db.execute(
                "UPDATE party_games SET state_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(state, ensure_ascii=False), now, game_id),
            )
            for user_id in players:
                await db.execute(
                    "UPDATE party_game_players SET secret_json = ? WHERE game_id = ? AND user_id = ?",
                    (json.dumps({"stake": new_stake}), game_id, user_id),
                )
            await db.commit()
            return True, "ok"

    async def save_party_state(self, game_id: int, state: dict[str, Any]) -> None:
        await self.execute(
            "UPDATE party_games SET state_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(state, ensure_ascii=False), utcnow(), game_id),
        )

    async def save_player_secret(self, game_id: int, user_id: int, secret: dict[str, Any]) -> None:
        await self.execute(
            "UPDATE party_game_players SET secret_json = ? WHERE game_id = ? AND user_id = ?",
            (json.dumps(secret, ensure_ascii=False), game_id, user_id),
        )

    async def payout_staked_game(self, game_id: int, payouts: dict[int, int]) -> None:
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT status FROM party_games WHERE id = ?", (game_id,))
            game = await cursor.fetchone()
            if not game or game["status"] not in {"lobby", "active"}:
                await db.rollback()
                return
            for user_id, amount in payouts.items():
                if amount <= 0:
                    continue
                await db.execute(
                    "UPDATE users SET cookies = cookies + ?, updated_at = ? WHERE user_id = ?",
                    (amount, now, user_id),
                )
                await db.execute(
                    "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
                    (user_id, amount, "cookie_game_win", str(game_id), now),
                )
            await db.execute(
                "UPDATE party_games SET status = 'completed', updated_at = ?, completed_at = ? WHERE id = ?",
                (now, now, game_id),
            )
            await db.commit()

    async def crash_cashout(self, game_id: int, user_id: int) -> tuple[bool, str, dict[str, Any] | None]:
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT * FROM party_games WHERE id = ?", (game_id,))
            game = await cursor.fetchone()
            if not game or game["status"] != "active" or str(game["game_type"]) != "crash":
                await db.rollback()
                return False, "Рейс уже не в воздухе.", None
            cursor = await db.execute(
                "SELECT 1 FROM party_game_players WHERE game_id = ? AND user_id = ?",
                (game_id, user_id),
            )
            if not await cursor.fetchone():
                await db.rollback()
                return False, "Вы не в этом рейсе.", None
            state = json.loads(str(game["state_json"]) or "{}")
            if str(state.get("phase") or "") != "flight":
                await db.rollback()
                return False, "Рейс уже не в воздухе.", None
            cashed = dict(state.get("cashed") or {})
            if str(user_id) in cashed:
                await db.rollback()
                return False, "Уже забрали.", None
            multiplier = float(state.get("multiplier") or 1)
            stake = int(state.get("stake") or 0)
            gross = max(0, int(stake * multiplier))
            net = gross
            info = {"mult": multiplier, "gross": gross, "net": net, "percent": 0}
            cashed[str(user_id)] = info
            state["cashed"] = cashed
            await db.execute(
                "UPDATE party_games SET state_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(state, ensure_ascii=False), now, game_id),
            )
            await db.commit()
            return True, "ok", info

    async def set_nested_state(self, game_id: int, path: list[str], value: Any) -> dict[str, Any] | None:
        if not path:
            return None
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT * FROM party_games WHERE id = ?", (game_id,))
            game = await cursor.fetchone()
            if not game or game["status"] != "active":
                await db.rollback()
                return None
            state = json.loads(str(game["state_json"]) or "{}")
            cursor_obj: Any = state
            for key in path[:-1]:
                child = cursor_obj.get(key)
                if not isinstance(child, dict):
                    child = {}
                    cursor_obj[key] = child
                cursor_obj = child
            cursor_obj[path[-1]] = value
            await db.execute(
                "UPDATE party_games SET state_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(state, ensure_ascii=False), now, game_id),
            )
            await db.commit()
            return state

    async def complete_party_game(self, game_id: int) -> None:
        now = utcnow()
        await self.execute(
            "UPDATE party_games SET status = 'completed', updated_at = ?, completed_at = ? "
            "WHERE id = ? AND status IN ('lobby', 'active')",
            (now, now, game_id),
        )

    async def trap_pick(self, game_id: int, user_id: int, door: str) -> tuple[bool, str]:
        if door not in {"A", "B", "C"}:
            return False, "Нет такой двери."
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT * FROM party_games WHERE id = ?", (game_id,))
            game = await cursor.fetchone()
            if not game or game["status"] != "active" or str(game["game_type"]) != "trap":
                await db.rollback()
                return False, "Капкан уже закрылся."
            cursor = await db.execute(
                "SELECT 1 FROM party_game_players WHERE game_id = ? AND user_id = ?",
                (game_id, user_id),
            )
            if not await cursor.fetchone():
                await db.rollback()
                return False, "Вы не в этой партии."
            state = json.loads(str(game["state_json"]) or "{}")
            if str(state.get("phase") or "") != "pick":
                await db.rollback()
                return False, "Сейчас нельзя выбрать дверь."
            alive = [int(item) for item in state.get("alive") or []]
            if user_id not in alive:
                await db.rollback()
                return False, "Вы уже выбыли."
            picks = dict(state.get("picks") or {})
            picks[str(user_id)] = door
            state["picks"] = picks
            await db.execute(
                "UPDATE party_games SET state_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(state, ensure_ascii=False), now, game_id),
            )
            await db.commit()
            return True, "ok"

    async def trap_begin_resolve(self, game_id: int) -> dict[str, Any] | None:
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT * FROM party_games WHERE id = ?", (game_id,))
            game = await cursor.fetchone()
            if not game or game["status"] != "active" or str(game["game_type"]) != "trap":
                await db.rollback()
                return None
            state = json.loads(str(game["state_json"]) or "{}")
            if str(state.get("phase") or "") != "pick":
                await db.rollback()
                return None
            state["phase"] = "resolving"
            await db.execute(
                "UPDATE party_games SET state_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(state, ensure_ascii=False), now, game_id),
            )
            await db.commit()
            return state

    async def get_party_game(self, game_id: int) -> dict[str, Any] | None:
        row = await self.fetchone("SELECT * FROM party_games WHERE id = ?", (game_id,))
        if row:
            row["state"] = json.loads(str(row.pop("state_json")))
        return row

    async def active_party_game(self, chat_id: int) -> dict[str, Any] | None:
        row = await self.fetchone(
            "SELECT * FROM party_games WHERE chat_id = ? AND status IN ('lobby', 'active') ORDER BY id DESC LIMIT 1",
            (chat_id,),
        )
        if row:
            row["state"] = json.loads(str(row.pop("state_json")))
        return row

    async def list_game_players(self, game_id: int) -> list[dict[str, Any]]:
        rows = await self.fetchall(
            """
            SELECT p.*, u.username, u.telegram_name, u.profile_name
            FROM party_game_players p JOIN users u ON u.user_id = p.user_id
            WHERE p.game_id = ? ORDER BY p.joined_at
            """,
            (game_id,),
        )
        for row in rows:
            row["secret"] = json.loads(str(row.pop("secret_json")))
        return rows

    async def join_party_game(self, game_id: int, user_id: int, maximum: int = 10) -> tuple[bool, str]:
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT status FROM party_games WHERE id = ?", (game_id,))
            game = await cursor.fetchone()
            if not game or game["status"] != "lobby":
                await db.rollback()
                return False, "Набор в эту игру уже закрыт."
            cursor = await db.execute("SELECT COUNT(*) AS count FROM party_game_players WHERE game_id = ?", (game_id,))
            count = int((await cursor.fetchone())["count"])
            if count >= maximum:
                await db.rollback()
                return False, "В лобби уже нет мест."
            cursor = await db.execute(
                "INSERT OR IGNORE INTO party_game_players(game_id, user_id, joined_at) VALUES (?, ?, ?)",
                (game_id, user_id, now),
            )
            await db.commit()
            return (True, "Вы в игре.") if cursor.rowcount == 1 else (False, "Вы уже присоединились.")

    async def start_party_game(
        self,
        game_id: int,
        creator_id: int,
        state: dict[str, Any],
        secrets_by_user: dict[int, dict[str, Any]],
    ) -> bool:
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "UPDATE party_games SET status = 'active', state_json = ?, updated_at = ? "
                "WHERE id = ? AND creator_id = ? AND status = 'lobby'",
                (json.dumps(state, ensure_ascii=False), now, game_id, creator_id),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                return False
            for user_id, secret_data in secrets_by_user.items():
                await db.execute(
                    "UPDATE party_game_players SET secret_json = ? WHERE game_id = ? AND user_id = ?",
                    (json.dumps(secret_data, ensure_ascii=False), game_id, user_id),
                )
            await db.commit()
            return True

    async def cast_party_vote(self, game_id: int, voter_id: int, target_id: int) -> tuple[bool, str]:
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT status FROM party_games WHERE id = ?", (game_id,))
            game = await cursor.fetchone()
            if not game or game["status"] != "active":
                await db.rollback()
                return False, "Голосование уже завершено."
            cursor = await db.execute(
                "SELECT COUNT(*) AS count FROM party_game_players WHERE game_id = ? AND user_id IN (?, ?)",
                (game_id, voter_id, target_id),
            )
            if int((await cursor.fetchone())["count"]) != (1 if voter_id == target_id else 2):
                await db.rollback()
                return False, "Голосовать могут только участники этой игры."
            cursor = await db.execute(
                "INSERT OR IGNORE INTO party_game_votes(game_id, voter_id, target_id, created_at) VALUES (?, ?, ?, ?)",
                (game_id, voter_id, target_id, now),
            )
            await db.commit()
            return (True, "Голос принят.") if cursor.rowcount == 1 else (False, "Вы уже проголосовали.")

    async def resolve_party_game(self, game_id: int) -> dict[str, Any] | None:
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT * FROM party_games WHERE id = ?", (game_id,))
            game = await cursor.fetchone()
            if not game or game["status"] != "active":
                await db.rollback()
                return None
            cursor = await db.execute("SELECT COUNT(*) AS count FROM party_game_players WHERE game_id = ?", (game_id,))
            player_count = int((await cursor.fetchone())["count"])
            cursor = await db.execute("SELECT voter_id, target_id FROM party_game_votes WHERE game_id = ?", (game_id,))
            votes = await cursor.fetchall()
            if len(votes) < player_count:
                await db.rollback()
                return None
            counts: dict[int, int] = {}
            for vote in votes:
                target_id = int(vote["target_id"])
                counts[target_id] = counts.get(target_id, 0) + 1
            highest = max(counts.values())
            candidates = [user_id for user_id, count in counts.items() if count == highest]
            selected_id = secrets.choice(candidates)
            state = json.loads(str(game["state_json"]))
            outcome = {"selected_id": selected_id, "votes": counts, "tie": len(candidates) > 1}
            state["outcome"] = outcome
            await db.execute(
                "UPDATE party_games SET status = 'completed', state_json = ?, updated_at = ?, completed_at = ? "
                "WHERE id = ?",
                (json.dumps(state, ensure_ascii=False), now, now, game_id),
            )
            await db.commit()
            result = dict(game)
            result.update({"state": state, "outcome": outcome})
            return result

    async def cancel_party_game(self, game_id: int, actor_id: int, is_admin: bool = False) -> bool:
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT * FROM party_games WHERE id = ?", (game_id,))
            game = await cursor.fetchone()
            if not game or game["status"] not in {"lobby", "active"}:
                await db.rollback()
                return False
            if not is_admin and int(game["creator_id"]) != actor_id:
                await db.rollback()
                return False
            state = json.loads(str(game["state_json"] or "{}"))
            stake = int(state.get("stake") or 0)
            if stake > 0 and game["status"] == "active" and not is_admin:
                # A player must not cancel a losing round after seeing its cards/results.
                await db.rollback()
                return False
            if stake > 0:
                cursor = await db.execute("SELECT user_id FROM party_game_players WHERE game_id = ?", (game_id,))
                players = await cursor.fetchall()
                for player in players:
                    user_id = int(player["user_id"])
                    await db.execute(
                        "UPDATE users SET cookies = cookies + ?, updated_at = ? WHERE user_id = ?",
                        (stake, now, user_id),
                    )
                    await db.execute(
                        "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
                        (user_id, stake, "cookie_game_refund", str(game_id), now),
                    )
            await db.execute(
                "UPDATE party_games SET status = 'cancelled', updated_at = ?, completed_at = ? WHERE id = ?",
                (now, now, game_id),
            )
            await db.commit()
            return True

    async def restore_daily_reputation(self, local_date: date) -> list[dict[str, Any]]:
        from community_bot.domain import AUTO_REPUTATION_CAP, DAILY_REPUTATION_CAP
        from community_bot.profile_fill import profile_is_complete

        key = "last_reputation_restore"
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT value FROM bot_state WHERE key = ?", (key,))
            state = await cursor.fetchone()
            if state and state["value"] == local_date.isoformat():
                await db.rollback()
                return []
            cursor = await db.execute("SELECT * FROM users")
            changed: list[dict[str, Any]] = []
            now = utcnow()
            for raw in await cursor.fetchall():
                user = dict(raw)
                current = int(user["reputation"])
                cap = DAILY_REPUTATION_CAP if profile_is_complete(user) else AUTO_REPUTATION_CAP
                if current >= cap:
                    continue
                nxt = min(cap, current + 5)
                await db.execute(
                    "UPDATE users SET reputation = ?, updated_at = ? WHERE user_id = ?",
                    (nxt, now, int(user["user_id"])),
                )
                changed.append({"user_id": int(user["user_id"]), "reputation": nxt})
            await db.execute(
                "INSERT INTO bot_state(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, local_date.isoformat()),
            )
            await db.commit()
            return changed

    async def iso_week_id(self) -> str:
        return datetime.now(UTC).strftime("%G-W%V")

    async def unlock_achievement(self, user_id: int, slug: str) -> bool:
        now = utcnow()
        async with self.connect() as db:
            cursor = await db.execute(
                "INSERT OR IGNORE INTO achievements(user_id, slug, unlocked_at) VALUES (?, ?, ?)",
                (user_id, slug, now),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def list_achievements(self, user_id: int) -> list[str]:
        rows = await self.fetchall(
            "SELECT slug FROM achievements WHERE user_id = ? ORDER BY unlocked_at",
            (user_id,),
        )
        return [str(row["slug"]) for row in rows]

    async def create_report(
        self,
        reporter_id: int,
        target_id: int,
        chat_id: int,
        message_id: int,
        text: str,
        reason: str,
        *,
        attachment: tuple[str, str] | None = None,
    ) -> int:
        async with self.connect() as connection:
            cursor = await connection.execute(
                """
                INSERT INTO reports(reporter_id, target_id, chat_id, message_id, text, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (reporter_id, target_id, chat_id, message_id, text[:4096], reason[:200], utcnow()),
            )
            report_id = int(cursor.lastrowid)
            if attachment:
                await connection.execute(
                    "INSERT INTO bot_state(key, value) VALUES (?, ?)",
                    (f"report_attachment:{report_id}", json.dumps(attachment)),
                )
            await connection.commit()
            return report_id

    async def list_pending_reports(self, limit: int = 15) -> list[dict[str, Any]]:
        return await self.fetchall(
            "SELECT * FROM reports WHERE status = 'pending' ORDER BY id DESC LIMIT ?",
            (limit,),
        )

    async def review_report(self, report_id: int, moderator_id: int, status: str) -> bool:
        async with self.connect() as db:
            cursor = await db.execute(
                "UPDATE reports SET status = ?, moderator_id = ?, reviewed_at = ? "
                "WHERE id = ? AND status = 'pending'",
                (status, moderator_id, utcnow(), report_id),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def create_mail(self, user_id: int, text: str) -> int:
        return await self.execute(
            "INSERT INTO mailbox(user_id, text, created_at) VALUES (?, ?, ?)",
            (user_id, text[:2000], utcnow()),
        )

    async def list_pending_mail(self, limit: int = 15) -> list[dict[str, Any]]:
        return await self.fetchall(
            "SELECT * FROM mailbox WHERE status = 'pending' ORDER BY id DESC LIMIT ?",
            (limit,),
        )

    async def review_mail(self, mail_id: int, moderator_id: int, status: str) -> dict[str, Any] | None:
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT * FROM mailbox WHERE id = ? AND status = 'pending'", (mail_id,))
            row = await cursor.fetchone()
            if not row:
                await db.rollback()
                return None
            await db.execute(
                "UPDATE mailbox SET status = ?, moderator_id = ?, reviewed_at = ? WHERE id = ?",
                (status, moderator_id, utcnow(), mail_id),
            )
            await db.commit()
            return dict(row)

    async def list_stop_words(self) -> list[dict[str, Any]]:
        return await self.fetchall("SELECT * FROM stop_words ORDER BY word")

    async def add_stop_word(self, word: str, created_by: int) -> bool:
        cleaned = " ".join(word.casefold().split())
        if not 1 <= len(cleaned) <= 40:
            return False
        async with self.connect() as db:
            cursor = await db.execute(
                "INSERT OR IGNORE INTO stop_words(word, created_by, created_at) VALUES (?, ?, ?)",
                (cleaned, created_by, utcnow()),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def delete_stop_word(self, word_id: int) -> bool:
        async with self.connect() as db:
            cursor = await db.execute("DELETE FROM stop_words WHERE id = ?", (word_id,))
            await db.commit()
            return cursor.rowcount == 1

    async def add_rsvp(
        self, event_id: str, user_id: int, stake: int, *, kind: str = "legacy",
    ) -> tuple[bool, str]:
        if stake < 0 or kind not in {"legacy", "rsvp", "payment"}:
            return False, "Некорректные условия участия."
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute('SELECT status FROM studio_events WHERE event_id=?', (event_id,))
            event = await cursor.fetchone()
            if event and event['status'] != 'active':
                await db.rollback()
                return False, "Мероприятие отменено. Запись закрыта, возвраты выполняет администрация."

            cursor = await db.execute(
                "SELECT 1 FROM event_rsvps WHERE event_id = ? AND user_id = ?",
                (event_id, user_id),
            )
            if await cursor.fetchone():
                await db.rollback()
                return False, "Вы уже оплатили участие." if stake > 0 else "Вы уже отметились."
            if stake > 0:
                cursor = await db.execute(
                    "UPDATE users SET cookies = cookies - ?, updated_at = ? WHERE user_id = ? AND cookies >= ?",
                    (stake, now, user_id, stake),
                )
                if cursor.rowcount != 1:
                    await db.rollback()
                    return False, "Недостаточно печенек для залога."
                await db.execute(
                    "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
                    (user_id, -stake, "rsvp", event_id, now),
                )
            await db.execute(
                "INSERT INTO event_rsvps(event_id, user_id, stake, kind, created_at) VALUES (?, ?, ?, ?, ?)",
                (event_id, user_id, stake, kind, now),
            )
            await db.execute("UPDATE studio_events SET markup_dirty = 1 WHERE event_id = ?", (event_id,))
            await db.commit()
            return True, "ok"

    async def save_studio_event(
        self, event_id: str, chat_id: int, message_id: int, title: str,
        buttons: list[dict[str, str]], stake: int, created_by: int, *, rsvp_enabled: bool = True,
        description: str = "", media_type: str = "",
    ) -> None:
        from community_bot.shop_text import plain_shop_text

        description = plain_shop_text(description)
        lines = description.splitlines()
        if lines and lines[0].strip() == plain_shop_text(title):
            description = '\n'.join(lines[1:]).strip()
        await self.execute(
            """INSERT OR IGNORE INTO studio_events(
                event_id, chat_id, message_id, title, buttons_json, stake, created_by, created_at, rsvp_enabled,
                description, media_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (event_id, chat_id, message_id, title, json.dumps(buttons, ensure_ascii=False),
             stake, created_by, utcnow(), int(rsvp_enabled), description, media_type),
        )

    async def get_studio_event(self, event_id: str) -> dict[str, Any] | None:
        return await self.fetchone("SELECT * FROM studio_events WHERE event_id = ?", (event_id,))

    async def event_participant_count(self, event_id: str) -> int:
        row = await self.fetchone("SELECT COUNT(*) AS n FROM event_rsvps WHERE event_id = ?", (event_id,))
        return int(row["n"])

    async def list_studio_events(self, offset: int = 0, limit: int = 8) -> list[dict[str, Any]]:
        return await self.fetchall(
            """WITH ids AS (
                SELECT event_id FROM studio_events UNION SELECT event_id FROM event_offers
                UNION SELECT event_id FROM event_rsvps
            )
            SELECT ids.event_id, COALESCE(s.title, NULLIF(o.title, ''), ids.event_id) AS title,
                COALESCE(s.created_at, o.created_at, MIN(r.created_at)) AS created_at,
                COALESCE(s.chat_id, o.chat_id) AS chat_id,
                COALESCE(s.message_id, o.message_id) AS message_id, COUNT(r.user_id) AS participants
            FROM ids LEFT JOIN studio_events s USING(event_id) LEFT JOIN event_offers o USING(event_id)
            LEFT JOIN event_rsvps r USING(event_id)
            GROUP BY ids.event_id ORDER BY created_at DESC, ids.event_id DESC LIMIT ? OFFSET ?""",
            (limit, offset),
        )

    async def get_event_rsvp(self, event_id: str, user_id: int) -> dict[str, Any] | None:
        return await self.fetchone("SELECT * FROM event_rsvps WHERE event_id = ? AND user_id = ?", (event_id, user_id))

    async def has_event_payment(self, event_id: str, user_id: int) -> bool:
        row = await self.get_event_rsvp(event_id, user_id)
        # Old code did not distinguish deposits from tickets. Never auto-refund ambiguous paid rows.
        return bool(row and (row["kind"] == "payment" or (row["kind"] == "legacy" and int(row["stake"]) > 0)))

    async def cancel_event_rsvp(self, event_id: str, user_id: int) -> tuple[bool, str]:
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute('SELECT status FROM studio_events WHERE event_id=?', (event_id,))
            event = await cursor.fetchone()
            if event and event['status'] != 'active':
                await db.rollback()
                return False, "Мероприятие отменено. Запись закрыта, возвраты выполняет администрация."

            cursor = await db.execute(
                "SELECT * FROM event_rsvps WHERE event_id = ? AND user_id = ?", (event_id, user_id),
            )
            row = await cursor.fetchone()
            if not row:
                return False, "Вы уже не записаны."
            if row["kind"] == "payment" or (row["kind"] == "legacy" and int(row["stake"]) > 0):
                return False, "Для отмены оплаченного участия обратитесь к администрации."
            refund = int(row["stake"])
            await db.execute("DELETE FROM event_rsvps WHERE event_id = ? AND user_id = ?", (event_id, user_id))
            if refund:
                now = utcnow()
                await db.execute(
                    "UPDATE users SET cookies = cookies + ?, updated_at = ? WHERE user_id = ?", (refund, now, user_id),
                )
                await db.execute(
                    "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
                    (user_id, refund, "rsvp_refund", event_id, now),
                )
            await db.execute("UPDATE studio_events SET markup_dirty = 1 WHERE event_id = ?", (event_id,))
            await db.commit()
            return True, f"Запись отменена. Возвращён залог {refund} 🍪." if refund else "Запись отменена."

    async def pay_event_offer(self, event_id: str, user_id: int, expected_price: int) -> tuple[bool, str, int]:
        """Turn a reservation into a paid ticket, crediting its deposit exactly once."""
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute('SELECT status FROM studio_events WHERE event_id=?', (event_id,))
            event = await cursor.fetchone()
            if event and event['status'] != 'active':
                await db.rollback()
                return False, "Мероприятие отменено. Новые оплаты закрыты.", 0

            cursor = await db.execute("SELECT price FROM event_offers WHERE event_id = ?", (event_id,))
            offer = await cursor.fetchone()
            if not offer or int(offer["price"]) != expected_price or expected_price <= 0:
                return False, "Условия участия изменились. Откройте оплату заново.", 0
            cursor = await db.execute(
                "SELECT * FROM event_rsvps WHERE event_id = ? AND user_id = ?", (event_id, user_id),
            )
            row = await cursor.fetchone()
            if row and (row["kind"] == "payment" or (row["kind"] == "legacy" and int(row["stake"]) > 0)):
                return False, "Вы уже оплатили участие.", 0
            deposit = int(row["stake"]) if row else 0
            charge = expected_price - deposit
            now = utcnow()
            cursor = await db.execute(
                "UPDATE users SET cookies = cookies - ?, updated_at = ? WHERE user_id = ? AND cookies >= ?",
                (charge, now, user_id, max(0, charge)),
            )
            if cursor.rowcount != 1:
                return False, "Недостаточно печенек для оплаты.", 0
            if charge:
                await db.execute(
                    "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
                    (user_id, -charge, "rsvp" if charge > 0 else "rsvp_refund", event_id, now),
                )
            await db.execute(
                """INSERT INTO event_rsvps(event_id, user_id, stake, kind, created_at) VALUES (?, ?, ?, 'payment', ?)
                ON CONFLICT(event_id, user_id) DO UPDATE SET stake=excluded.stake, kind='payment'""",
                (event_id, user_id, expected_price, now),
            )
            await db.execute("UPDATE studio_events SET markup_dirty = 1 WHERE event_id = ?", (event_id,))
            await db.commit()
            return True, "ok", charge

    async def list_rsvps(self, event_id: str, *, offset: int = 0, limit: int | None = None) -> list[dict[str, Any]]:
        return await self.fetchall(
            """
            SELECT r.*, u.telegram_name, u.profile_name, u.username
            FROM event_rsvps r
            JOIN users u ON u.user_id = r.user_id
            WHERE r.event_id = ?
            ORDER BY r.created_at, r.user_id
            LIMIT ? OFFSET ?
            """,
            (event_id, limit if limit is not None else -1, offset),
        )

    async def weekly_board(self, week_id: str) -> dict[str, list[dict[str, Any]]]:
        messages = await self.fetchall(
            """
            SELECT s.user_id, s.messages, u.telegram_name, u.profile_name, u.username
            FROM weekly_scores s
            JOIN users u ON u.user_id = s.user_id
            WHERE s.week_id = ?
            ORDER BY s.messages DESC
            LIMIT 5
            """,
            (week_id,),
        )
        plus = await self.fetchall(
            """
            SELECT target_id AS user_id, COUNT(*) AS score, u.telegram_name, u.profile_name, u.username
            FROM reputation_actions a
            JOIN users u ON u.user_id = a.target_id
            WHERE a.delta > 0 AND a.action_date >= ?
            GROUP BY target_id
            ORDER BY score DESC
            LIMIT 5
            """,
            ((datetime.now(UTC) - timedelta(days=7)).date().isoformat(),),
        )
        farm = await self.fetchall(
            """
            SELECT t.user_id, SUM(t.amount) AS score, u.telegram_name, u.profile_name, u.username
            FROM transactions t
            JOIN users u ON u.user_id = t.user_id
            WHERE t.kind IN ('pet_farm', 'pet_expedition') AND t.created_at >= ?
            GROUP BY t.user_id
            ORDER BY score DESC
            LIMIT 5
            """,
            ((datetime.now(UTC) - timedelta(days=7)).isoformat(),),
        )
        return {"messages": messages, "plus": plus, "farm": farm}

    async def daily_message_board(self, day: str, chat_id: int, limit: int = 10) -> list[dict[str, Any]]:
        return await self.fetchall(
            """
            SELECT s.user_id, s.messages, u.telegram_name, u.profile_name, u.username
            FROM daily_scores s
            JOIN users u ON u.user_id = s.user_id
            WHERE s.day = ? AND s.chat_id = ? AND s.messages > 0
            ORDER BY s.messages DESC, s.user_id ASC
            LIMIT ?
            """,
            (day, chat_id, limit),
        )

    async def list_command_overrides(self) -> list[dict[str, Any]]:
        return await self.fetchall("SELECT * FROM command_overrides ORDER BY slug")

    async def save_command_override(
        self,
        slug: str,
        *,
        kind: str,
        enabled: bool,
        title: str,
        description: str,
        aliases: list[str],
        ttl_seconds: int | None,
        scope: str,
        reply_text: str,
        options: dict[str, str],
    ) -> None:
        await self.execute(
            """
            INSERT INTO command_overrides(
                slug, kind, enabled, title, description, aliases_json, ttl_seconds,
                scope, reply_text, options_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                kind = excluded.kind,
                enabled = excluded.enabled,
                title = excluded.title,
                description = excluded.description,
                aliases_json = excluded.aliases_json,
                ttl_seconds = excluded.ttl_seconds,
                scope = excluded.scope,
                reply_text = excluded.reply_text,
                options_json = excluded.options_json,
                updated_at = excluded.updated_at
            """,
            (
                slug,
                kind,
                1 if enabled else 0,
                title,
                description,
                json.dumps(aliases, ensure_ascii=False),
                ttl_seconds,
                scope,
                reply_text,
                json.dumps(options, ensure_ascii=False),
                utcnow(),
            ),
        )

    async def delete_command_override(self, slug: str) -> None:
        await self.execute("DELETE FROM command_overrides WHERE slug = ?", (slug,))

    async def create_lottery(self, chat_id: int, creator_id: int, entry_fee: int) -> tuple[int | None, str]:
        if not 1 <= entry_fee <= 100:
            return None, "Взнос — от 1 до 100 🍪."
        open_row = await self.fetchone(
            "SELECT id FROM lotteries WHERE chat_id = ? AND status = 'open'",
            (chat_id,),
        )
        if open_row:
            return None, "Уже есть открытый розыгрыш. Сначала подведите итог."
        lottery_id = await self.execute(
            "INSERT INTO lotteries(chat_id, creator_id, entry_fee, created_at) VALUES (?, ?, ?, ?)",
            (chat_id, creator_id, entry_fee, utcnow()),
        )
        return lottery_id, "ok"

    async def join_lottery(self, lottery_id: int, user_id: int) -> tuple[bool, str, int]:
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT * FROM lotteries WHERE id = ?", (lottery_id,))
            lottery = await cursor.fetchone()
            if not lottery or lottery["status"] != "open":
                await db.rollback()
                return False, "Розыгрыш закрыт.", 0
            fee = int(lottery["entry_fee"])
            cursor = await db.execute(
                "INSERT OR IGNORE INTO lottery_entries(lottery_id, user_id, created_at) VALUES (?, ?, ?)",
                (lottery_id, user_id, now),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                return False, "Вы уже в котле.", 0
            cursor = await db.execute(
                "UPDATE users SET cookies = cookies - ?, updated_at = ? WHERE user_id = ? AND cookies >= ?",
                (fee, now, user_id, fee),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                return False, "Недостаточно печенек.", 0
            await db.execute(
                "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, -fee, "lottery", str(lottery_id), now),
            )
            cursor = await db.execute(
                "SELECT COUNT(*) AS count FROM lottery_entries WHERE lottery_id = ?",
                (lottery_id,),
            )
            row = await cursor.fetchone()
            await db.commit()
            return True, "ok", int(row["count"]) if row else 1

    async def draw_lottery(self, lottery_id: int) -> tuple[bool, str, dict[str, Any] | None]:
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT * FROM lotteries WHERE id = ? AND status = 'open'", (lottery_id,))
            lottery = await cursor.fetchone()
            if not lottery:
                await db.rollback()
                return False, "Розыгрыш не найден или уже закрыт.", None
            cursor = await db.execute(
                "SELECT user_id FROM lottery_entries WHERE lottery_id = ?",
                (lottery_id,),
            )
            players = [int(row["user_id"]) for row in await cursor.fetchall()]
            if len(players) < 2:
                await db.rollback()
                return False, "Нужно хотя бы двое участников.", None
            winner_id = secrets.choice(players)
            pot = int(lottery["entry_fee"]) * len(players)
            await db.execute(
                "UPDATE users SET cookies = cookies + ?, updated_at = ? WHERE user_id = ?",
                (pot, now, winner_id),
            )
            await db.execute(
                "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
                (winner_id, pot, "lottery_win", str(lottery_id), now),
            )
            await db.execute(
                "UPDATE lotteries SET status = 'drawn', winner_id = ?, drawn_at = ? WHERE id = ?",
                (winner_id, now, lottery_id),
            )
            await db.commit()
            return True, "ok", {"winner_id": winner_id, "pot": pot, "players": len(players)}

    async def open_lottery(self, chat_id: int) -> dict[str, Any] | None:
        return await self.fetchone(
            "SELECT * FROM lotteries WHERE chat_id = ? AND status = 'open' ORDER BY id DESC LIMIT 1",
            (chat_id,),
        )

    async def create_cookie_contest(
        self,
        chat_id: int,
        creator_id: int,
        prize: int,
        body: str,
        extra_text: str = "",
        media_type: str | None = None,
        media_file_id: str | None = None,
    ) -> tuple[int | None, str]:
        if prize < 1 or prize > 100_000:
            return None, "Приз — от 1 до 100 000 🍪."
        if await self.open_cookie_contest(chat_id):
            return None, "Уже есть открытый конкурс. Сначала подведите итог или снимите его."
        contest_id = await self.execute(
            """
            INSERT INTO cookie_contests(
                chat_id, creator_id, prize, body, extra_text, media_type, media_file_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (chat_id, creator_id, prize, body, extra_text, media_type, media_file_id, utcnow()),
        )
        return contest_id, "ok"

    async def set_cookie_contest_message(self, contest_id: int, message_id: int) -> None:
        await self.execute("UPDATE cookie_contests SET message_id = ? WHERE id = ?", (message_id, contest_id))

    async def get_cookie_contest(self, contest_id: int) -> dict[str, Any] | None:
        return await self.fetchone("SELECT * FROM cookie_contests WHERE id = ?", (contest_id,))

    async def open_cookie_contest(self, chat_id: int) -> dict[str, Any] | None:
        return await self.fetchone(
            "SELECT * FROM cookie_contests WHERE chat_id = ? AND status = 'open' ORDER BY id DESC LIMIT 1",
            (chat_id,),
        )

    async def cookie_contest_entry_count(self, contest_id: int) -> int:
        row = await self.fetchone(
            "SELECT COUNT(*) AS count FROM cookie_contest_entries WHERE contest_id = ?",
            (contest_id,),
        )
        return int(row["count"]) if row else 0

    async def list_cookie_contest_entries(self, contest_id: int, limit: int = 80) -> list[dict[str, Any]]:
        return await self.fetchall(
            """
            SELECT e.user_id, e.created_at, u.profile_name, u.telegram_name, u.username
            FROM cookie_contest_entries e
            JOIN users u ON u.user_id = e.user_id
            WHERE e.contest_id = ?
            ORDER BY e.created_at
            LIMIT ?
            """,
            (contest_id, limit),
        )

    async def join_cookie_contest(self, contest_id: int, user_id: int) -> tuple[bool, str, int]:
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT * FROM cookie_contests WHERE id = ?", (contest_id,))
            contest = await cursor.fetchone()
            if not contest or contest["status"] != "open":
                await db.rollback()
                return False, "Конкурс уже закрыт.", 0
            cursor = await db.execute(
                "INSERT OR IGNORE INTO cookie_contest_entries(contest_id, user_id, created_at) VALUES (?, ?, ?)",
                (contest_id, user_id, now),
            )
            joined = cursor.rowcount == 1
            cursor = await db.execute(
                "SELECT COUNT(*) AS count FROM cookie_contest_entries WHERE contest_id = ?",
                (contest_id,),
            )
            count_row = await cursor.fetchone()
            count = int(count_row["count"]) if count_row else 0
            await db.commit()
            if not joined:
                return False, "Вы уже участвуете.", count
            return True, "ok", count

    async def draw_cookie_contest(self, contest_id: int) -> tuple[bool, str, dict[str, Any] | None]:
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT * FROM cookie_contests WHERE id = ? AND status = 'open'",
                (contest_id,),
            )
            contest = await cursor.fetchone()
            if not contest:
                await db.rollback()
                return False, "Открытого конкурса нет.", None
            cursor = await db.execute(
                "SELECT user_id FROM cookie_contest_entries WHERE contest_id = ?",
                (contest_id,),
            )
            players = [int(row["user_id"]) for row in await cursor.fetchall()]
            if not players:
                await db.rollback()
                return False, "Пока никто не нажал «Участвовать».", None
            winner_id = secrets.choice(players)
            prize = int(contest["prize"])
            await db.execute(
                "UPDATE users SET cookies = cookies + ?, updated_at = ? WHERE user_id = ?",
                (prize, now, winner_id),
            )
            await db.execute(
                "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
                (winner_id, prize, "contest_win", str(contest_id), now),
            )
            await db.execute(
                "UPDATE cookie_contests SET status = 'drawn', winner_id = ?, drawn_at = ? WHERE id = ?",
                (winner_id, now, contest_id),
            )
            await db.commit()
            return True, "ok", {"winner_id": winner_id, "prize": prize, "players": len(players)}

    async def cancel_cookie_contest(self, contest_id: int) -> bool:
        async with self.connect() as db:
            cursor = await db.execute(
                "UPDATE cookie_contests SET status = 'cancelled' WHERE id = ? AND status = 'open'",
                (contest_id,),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def start_expedition(
        self, user_id: int, timezone: str = "Europe/Moscow", *, intent_id: str | None = None,
    ) -> tuple[bool, str, int]:
        from community_bot.expedition import expedition_until_iso, remaining_label

        pet = await self.get_pet(user_id)
        if not pet:
            return False, "Сначала заведите тамагочи.", 0
        until = expedition_until_iso()
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            error = await self._consume_wallet_intent(db, intent_id, user_id, 'pet_action', 1, user_id)
            if error:
                await db.rollback()
                return False, error, 0

            cursor = await db.execute(
                """
                UPDATE pets SET expedition_until = ?, expedition_reward = 0, expedition_loot = NULL,
                    expedition_notice_sent = 1, updated_at = ?
                WHERE user_id = ? AND (expedition_until IS NULL OR expedition_until <= ?)
                """,
                (until, now, user_id, now),
            )
            if cursor.rowcount != 1:
                cursor = await db.execute("SELECT * FROM pets WHERE user_id = ?", (user_id,))
                row = await cursor.fetchone()
                await db.rollback()
                leftover = remaining_label(str(dict(row).get("expedition_until") if row else ""), timezone)
                return False, f"Талисман ещё в экспедиции ({leftover}).", 0
            await db.commit()
        return True, "ok", 0

    async def claim_expedition_notice(self, user_id: int) -> dict[str, Any] | None:
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """
                UPDATE pets SET expedition_notice_sent = 1, updated_at = ?
                WHERE user_id = ? AND expedition_notice_sent = 0
                """,
                (now, user_id),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                return None
            row = await (await db.execute("SELECT * FROM pets WHERE user_id = ?", (user_id,))).fetchone()
            await db.commit()
            return dict(row) if row else None

    async def list_due_expeditions(self, now_iso: str | None = None) -> list[dict[str, Any]]:
        stamp = now_iso or datetime.now(UTC).isoformat()
        return await self.fetchall(
            "SELECT * FROM pets WHERE expedition_until IS NOT NULL AND expedition_until <= ?",
            (stamp,),
        )

    async def list_pending_expedition_notices(self) -> list[dict[str, Any]]:
        return await self.fetchall("SELECT * FROM pets WHERE expedition_notice_sent = 0")

    async def add_captcha(self, user_id: int, chat_id: int) -> None:
        await self.execute(
            "INSERT OR REPLACE INTO captcha_pending(user_id, chat_id, created_at) VALUES (?, ?, ?)",
            (user_id, chat_id, utcnow()),
        )

    async def pop_captcha(self, user_id: int, chat_id: int) -> bool:
        async with self.connect() as db:
            cursor = await db.execute(
                "DELETE FROM captcha_pending WHERE user_id = ? AND chat_id = ?",
                (user_id, chat_id),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def consume_vitrine(self, item: str) -> bool:
        featured = await self.get_bot_state("shop_featured")
        if featured != item:
            return False
        raw = await self.get_bot_state("shop_featured_stock")
        if not raw or raw == "0":
            return False
        try:
            stock = int(raw)
        except ValueError:
            return False
        stock -= 1
        if stock <= 0:
            await self.set_bot_state("shop_featured", "")
            await self.set_bot_state("shop_featured_label", "")
            await self.set_bot_state("shop_featured_stock", "")
            await self.set_bot_state("shop_featured_until", "")
            return True
        await self.set_bot_state("shop_featured_stock", str(stock))
        return False

    async def notify_channel_on(self, user_id: int, channel: str) -> bool:
        row = await self.fetchone(
            "SELECT enabled FROM notify_prefs WHERE user_id = ? AND channel = ?",
            (user_id, channel),
        )
        return bool(row and int(row["enabled"]))

    async def notify_digest_on(self, user_id: int, channel: str) -> bool:
        row = await self.fetchone(
            "SELECT digest FROM notify_prefs WHERE user_id = ? AND channel = ?",
            (user_id, channel),
        )
        return bool(row and int(row["digest"]))

    async def notify_prefs_map(self, user_id: int) -> dict[str, dict[str, int]]:
        rows = await self.fetchall(
            "SELECT channel, enabled, digest FROM notify_prefs WHERE user_id = ?",
            (user_id,),
        )
        return {
            str(row["channel"]): {"enabled": int(row["enabled"]), "digest": int(row["digest"])}
            for row in rows
        }

    async def notify_toggle_enabled(self, user_id: int, channel: str) -> bool:
        row = await self.fetchone(
            "SELECT enabled FROM notify_prefs WHERE user_id = ? AND channel = ?",
            (user_id, channel),
        )
        if not row:
            await self.execute(
                "INSERT INTO notify_prefs(user_id, channel, enabled, digest) VALUES (?, ?, 1, 0)",
                (user_id, channel),
            )
            return True
        enabled = 0 if int(row["enabled"]) else 1
        await self.execute(
            "UPDATE notify_prefs SET enabled = ? WHERE user_id = ? AND channel = ?",
            (enabled, user_id, channel),
        )
        return bool(enabled)

    async def notify_toggle_digest(self, user_id: int, channel: str) -> bool:
        row = await self.fetchone(
            "SELECT digest FROM notify_prefs WHERE user_id = ? AND channel = ?",
            (user_id, channel),
        )
        if not row:
            await self.execute(
                "INSERT INTO notify_prefs(user_id, channel, enabled, digest) VALUES (?, ?, 0, 1)",
                (user_id, channel),
            )
            return True
        digest = 0 if int(row["digest"]) else 1
        await self.execute(
            "UPDATE notify_prefs SET digest = ? WHERE user_id = ? AND channel = ?",
            (digest, user_id, channel),
        )
        return bool(digest)

    async def notify_unread_count(self, user_id: int) -> int:
        row = await self.fetchone(
            "SELECT COUNT(*) AS n FROM notify_inbox WHERE user_id = ? AND read = 0",
            (user_id,),
        )
        return int(row["n"]) if row else 0

    async def notify_list_unread(self, user_id: int, limit: int = 8) -> list[dict[str, Any]]:
        return await self.fetchall(
            """
            SELECT id, channel, text, created_at
            FROM notify_inbox
            WHERE user_id = ? AND read = 0
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, limit),
        )

    async def notify_mark_read_all(self, user_id: int) -> None:
        await self.execute("UPDATE notify_inbox SET read = 1 WHERE user_id = ? AND read = 0", (user_id,))

    async def notify_inbox_add(self, user_id: int, channel: str, text: str) -> int:
        return await self.execute(
            """
            INSERT INTO notify_inbox(user_id, channel, text, created_at, read, delivered)
            VALUES (?, ?, ?, ?, 0, 0)
            """,
            (user_id, channel, text, utcnow()),
        )

    async def notify_mark_delivered(self, inbox_id: int) -> None:
        await self.execute("UPDATE notify_inbox SET delivered = 1 WHERE id = ?", (inbox_id,))

    async def notify_mark_delivered_ids(self, inbox_ids: list[int]) -> None:
        if not inbox_ids:
            return
        placeholders = ",".join("?" for _ in inbox_ids)
        await self.execute(
            f"UPDATE notify_inbox SET delivered = 1, read = 1 WHERE id IN ({placeholders})",
            tuple(inbox_ids),
        )

    async def list_channel_subscribers(self, channel: str) -> list[int]:
        rows = await self.fetchall(
            "SELECT user_id FROM notify_prefs WHERE channel = ? AND enabled = 1",
            (channel,),
        )
        return [int(row["user_id"]) for row in rows]

    async def notify_pending_digest(self) -> list[dict[str, Any]]:
        return await self.fetchall(
            """
            SELECT i.id, i.user_id, i.channel, i.text, i.created_at
            FROM notify_inbox i
            JOIN notify_prefs p ON p.user_id = i.user_id AND p.channel = i.channel
            WHERE i.delivered = 0 AND p.enabled = 1 AND p.digest = 1
            ORDER BY i.user_id, i.id
            """
        )

    async def list_panel_user_ids(self) -> list[int]:
        from community_bot.permissions import PERM_ADMIN_PANEL, role_has_permission

        roles = {str(row["slug"]): list(row["permissions"]) for row in await self.list_staff_roles()}
        ids: list[int] = []
        for user in await self.list_all_users():
            perms = roles.get(str(user["role"]), [])
            if role_has_permission(perms, PERM_ADMIN_PANEL):
                ids.append(int(user["user_id"]))
        return ids
