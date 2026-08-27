from __future__ import annotations

import json
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, AsyncIterator

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
    reputation INTEGER NOT NULL DEFAULT 100,
    warnings INTEGER NOT NULL DEFAULT 0 CHECK(warnings >= 0),
    hate_immunity_until TEXT,
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

CREATE TABLE IF NOT EXISTS bot_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

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
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
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
"""

DEFAULT_FEATURE_FLAGS = {
    "games": 1,
    "tamagotchi": 1,
    "profile_video": 1,
    "activity_rewards": 1,
    "anti_flood": 0,
    "link_filter": 0,
    "media_filter": 0,
    "quiet_hours": 0,
    "raid_mode": 0,
}


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with self.connect() as db:
            await db.executescript(SCHEMA)
            columns = {str(row[1]) for row in await (await db.execute("PRAGMA table_info(users)")).fetchall()}
            if "avatar_media_type" not in columns:
                await db.execute("ALTER TABLE users ADD COLUMN avatar_media_type TEXT NOT NULL DEFAULT 'photo'")
            now = utcnow()
            for key, enabled in DEFAULT_FEATURE_FLAGS.items():
                await db.execute(
                    "INSERT OR IGNORE INTO feature_flags(key, enabled, updated_at) VALUES (?, ?, ?)",
                    (key, enabled, now),
                )
            await db.commit()

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
        return await self.fetchall("SELECT * FROM feature_flags ORDER BY key")

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
                "INSERT INTO admin_audit_log(actor_id, action, target, details, created_at) VALUES (?, ?, ?, ?, ?)",
                (actor_id, "feature_toggle", key, f"enabled:{enabled}", now),
            )
            await db.commit()
            return bool(enabled)

    async def log_admin_action(self, actor_id: int, action: str, target: str = "", details: str = "") -> None:
        await self.execute(
            "INSERT INTO admin_audit_log(actor_id, action, target, details, created_at) VALUES (?, ?, ?, ?, ?)",
            (actor_id, action, target, details, utcnow()),
        )

    async def recent_admin_actions(self, limit: int = 20) -> list[dict[str, Any]]:
        return await self.fetchall(
            "SELECT * FROM admin_audit_log ORDER BY id DESC LIMIT ?",
            (limit,),
        )

    async def dashboard_stats(self) -> dict[str, int]:
        queries = {
            "users": "SELECT COUNT(*) AS count FROM users",
            "pets": "SELECT COUNT(*) AS count FROM pets",
            "active_games": "SELECT COUNT(*) AS count FROM party_games WHERE status IN ('lobby', 'active')",
            "pending_orders": "SELECT COUNT(*) AS count FROM cookie_orders WHERE status = 'pending'",
            "pending_applications": "SELECT COUNT(*) AS count FROM applications WHERE status = 'pending'",
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
        now = utcnow()
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO users(user_id, username, telegram_name, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username=excluded.username,
                    telegram_name=excluded.telegram_name,
                    updated_at=excluded.updated_at
                """,
                (user_id, username, telegram_name, now, now),
            )
            await db.commit()
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

    async def list_users(self, limit: int = 30) -> list[dict[str, Any]]:
        return await self.fetchall(
            """
            SELECT user_id, username, telegram_name, profile_name, role
            FROM users
            ORDER BY
                CASE role WHEN 'owner' THEN 3 WHEN 'admin' THEN 2 WHEN 'moderator' THEN 1 ELSE 0 END DESC,
                updated_at DESC
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
        allowed = {"profile_name", "age", "hobbies", "avatar_file_id", "avatar_media_type", "custom_status"}
        if field not in allowed:
            raise ValueError("Недопустимое поле профиля")
        await self.execute(
            f"UPDATE users SET {field} = ?, updated_at = ? WHERE user_id = ?",
            (value, utcnow(), user_id),
        )

    async def create_application(self, user_id: int, answers: dict[str, Any]) -> int:
        return await self.execute(
            "INSERT INTO applications(user_id, answers_json, created_at) VALUES (?, ?, ?)",
            (user_id, json.dumps(answers, ensure_ascii=False), utcnow()),
        )

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

    async def apply_reputation(self, actor_id: int, target_id: int, delta: int, action_date: date) -> int:
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                "UPDATE users SET reputation = MIN(100, reputation + ?), updated_at = ? WHERE user_id = ?",
                (delta, now, target_id),
            )
            await db.execute(
                """
                INSERT INTO reputation_actions(actor_id, target_id, delta, action_date, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (actor_id, target_id, delta, action_date.isoformat(), now),
            )
            cursor = await db.execute("SELECT reputation FROM users WHERE user_id = ?", (target_id,))
            row = await cursor.fetchone()
            await db.commit()
            if not row:
                raise ValueError("Пользователь не найден")
            return int(row["reputation"])

    async def create_transfer(self, sender_id: int, receiver_id: int, amount: int) -> int:
        return await self.execute(
            """
            INSERT INTO pending_transfers(sender_id, receiver_id, amount, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (sender_id, receiver_id, amount, utcnow()),
        )

    async def complete_transfer(self, transfer_id: int, sender_id: int) -> tuple[bool, str, int]:
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
            receiver_amount = amount * 80 // 100
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

    async def buy_item(self, user_id: int, item: str, price: int) -> tuple[bool, str]:
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "UPDATE users SET cookies = cookies - ?, updated_at = ? WHERE user_id = ? AND cookies >= ?",
                (price, now, user_id, price),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                return False, "Недостаточно печенек."
            if item == "restore_rep":
                await db.execute("UPDATE users SET reputation = 100 WHERE user_id = ?", (user_id,))
            elif item == "reset_limits":
                await db.execute(
                    "DELETE FROM reputation_actions WHERE actor_id = ? AND action_date = ?",
                    (user_id, datetime.now().date().isoformat()),
                )
            elif item == "forgive":
                await db.execute("UPDATE users SET warnings = 0 WHERE user_id = ?", (user_id,))
            await db.execute(
                "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, -price, "shop", item, now),
            )
            await db.commit()
            return True, "ok"

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
            cursor = await db.execute(
                "SELECT user_id, cookies, reputation FROM users WHERE user_id IN (?, ?)",
                players,
            )
            users = {int(row["user_id"]): row for row in await cursor.fetchall()}
            stake = int(game["stake"])
            if len(users) != 2 or any(int(users[player]["cookies"]) < stake for player in players):
                await db.rollback()
                return False, f"У обоих игроков должно быть минимум {stake} 🍪.", None
            loser_id = players[1] if winner_id == players[0] else players[0]
            payout = stake if int(users[winner_id]["reputation"]) >= 90 else stake * 80 // 100
            await db.execute(
                "UPDATE users SET cookies = cookies - ?, updated_at = ? WHERE user_id = ?",
                (stake, now, loser_id),
            )
            await db.execute(
                "UPDATE users SET cookies = cookies + ?, updated_at = ? WHERE user_id = ?",
                (payout, now, winner_id),
            )
            await db.execute(
                """
                UPDATE roulette_games
                SET status = 'completed', winner_id = ?, payout = ?, completed_at = ?
                WHERE id = ?
                """,
                (winner_id, payout, now, game_id),
            )
            await db.execute(
                "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
                (loser_id, -stake, "roulette", f"game:{game_id}:lost", now),
            )
            await db.execute(
                "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
                (winner_id, payout, "roulette", f"game:{game_id}:won", now),
            )
            await db.commit()
            result = dict(game)
            result.update({"winner_id": winner_id, "loser_id": loser_id, "payout": payout})
            return True, "ok", result

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
        """Count one community message and grant pet supplies every 50 messages."""
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
            checkpoint = count // 50
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
            await db.commit()
            return count, rewarded

    async def get_activity(self, user_id: int, chat_id: int) -> dict[str, Any] | None:
        return await self.fetchone(
            "SELECT * FROM user_activity WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id),
        )

    async def purchase_pet(self, user_id: int, species: str, name: str, price: int) -> tuple[bool, str]:
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
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
        now_dt = datetime.now(UTC)
        now = now_dt.isoformat()
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
            earned_milli = 0
            payout = 0
            if hours:
                average = (int(pet["hunger"]) + int(pet["thirst"])) // 2
                rate = 300 if average >= 70 else 200 if average >= 35 else 100
                if int(pet["hunger"]) == 0 or int(pet["thirst"]) == 0:
                    rate = 0
                hourly_rate = {100: 17, 200: 34, 300: 50}.get(rate, 0)
                earned_milli = hours * hourly_rate
                farm_total = int(pet["farm_milli"]) + earned_milli
                payout, farm_milli = divmod(farm_total, 1000)
                hunger = max(0, int(pet["hunger"]) - hours * 2)
                thirst = max(0, int(pet["thirst"]) - hours * 3)
                sleeping = int(hunger == 0 or thirst == 0)
                mood = max(0, min(100, (hunger + thirst) // 2 - (20 if sleeping else 0)))
                new_tick = (last_tick + timedelta(hours=hours)).isoformat()
                await db.execute(
                    """
                    UPDATE pets SET hunger = ?, thirst = ?, mood = ?, farm_milli = ?, sleeping = ?,
                        last_tick_at = ?, updated_at = ? WHERE user_id = ?
                    """,
                    (hunger, thirst, mood, farm_milli, sleeping, new_tick, now, user_id),
                )
                if payout:
                    await db.execute(
                        "UPDATE users SET cookies = cookies + ?, updated_at = ? WHERE user_id = ?",
                        (payout, now, user_id),
                    )
                    await db.execute(
                        "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
                        (user_id, payout, "pet_farm", f"milli:{earned_milli}", now),
                    )
            await db.commit()
        result = await self.fetchone("SELECT * FROM pets WHERE user_id = ?", (user_id,))
        if result is not None:
            result["earned_milli"] = earned_milli
            result["payout"] = payout
        return result

    async def get_pet(self, user_id: int, settle: bool = True) -> dict[str, Any] | None:
        if settle:
            return await self.settle_pet(user_id)
        return await self.fetchone("SELECT * FROM pets WHERE user_id = ?", (user_id,))

    async def list_pets(self) -> list[dict[str, Any]]:
        return await self.fetchall("SELECT * FROM pets ORDER BY updated_at")

    async def use_pet_supply(self, user_id: int, kind: str) -> tuple[bool, str, dict[str, Any] | None]:
        if kind not in {"food", "water"}:
            return False, "Неизвестный припас.", None
        await self.settle_pet(user_id)
        column = "food_units" if kind == "food" else "water_units"
        stat = "hunger" if kind == "food" else "thirst"
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                f"UPDATE pets SET {column} = {column} - 1, {stat} = MIN(100, {stat} + 20), "
                "sleeping = 0, updated_at = ? WHERE user_id = ? AND " + column + " > 0",
                (now, user_id),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                return False, "Нет подходящих припасов. Их дают за каждые 50 сообщений.", None
            await db.commit()
        return True, "ok", await self.get_pet(user_id, settle=False)

    async def purchase_pet_supply(
        self,
        user_id: int,
        kind: str,
        gain: int,
        price: int,
        item: str,
    ) -> tuple[bool, str, dict[str, Any] | None]:
        if kind not in {"food", "water"} or gain <= 0 or price <= 0:
            return False, "Некорректный товар.", None
        await self.settle_pet(user_id)
        stat = "hunger" if kind == "food" else "thirst"
        now = utcnow()
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT 1 FROM pets WHERE user_id = ?", (user_id,))
            if not await cursor.fetchone():
                await db.rollback()
                return False, "Сначала заведите тамагочи."
            cursor = await db.execute(
                "UPDATE users SET cookies = cookies - ?, updated_at = ? WHERE user_id = ? AND cookies >= ?",
                (price, now, user_id, price),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                return False, "Недостаточно печенек."
            await db.execute(
                f"UPDATE pets SET {stat} = MIN(100, {stat} + ?), sleeping = 0, updated_at = ? WHERE user_id = ?",
                (gain, now, user_id),
            )
            await db.execute(
                "INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, -price, "pet_shop", item, now),
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

    async def create_party_game(self, chat_id: int, game_type: str, creator_id: int) -> tuple[int, bool]:
        now = utcnow()
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
                "INSERT INTO party_games(chat_id, game_type, creator_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (chat_id, game_type, creator_id, now, now),
            )
            game_id = int(cursor.lastrowid)
            await db.execute(
                "INSERT INTO party_game_players(game_id, user_id, joined_at) VALUES (?, ?, ?)",
                (game_id, creator_id, now),
            )
            await db.commit()
            return game_id, True

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
        query = (
            "UPDATE party_games SET status = 'cancelled', updated_at = ?, completed_at = ? "
            "WHERE id = ? AND status IN ('lobby', 'active')"
        )
        parameters: tuple[Any, ...] = (now, now, game_id)
        if not is_admin:
            query += " AND creator_id = ?"
            parameters += (actor_id,)
        async with self.connect() as db:
            cursor = await db.execute(query, parameters)
            await db.commit()
            return cursor.rowcount == 1

    async def restore_daily_reputation(self, local_date: date) -> list[dict[str, Any]]:
        key = "last_reputation_restore"
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT value FROM bot_state WHERE key = ?", (key,))
            state = await cursor.fetchone()
            if state and state["value"] == local_date.isoformat():
                await db.rollback()
                return []
            await db.execute(
                "UPDATE users SET reputation = MIN(100, reputation + 5), updated_at = ? WHERE reputation < 100",
                (utcnow(),),
            )
            await db.execute(
                "INSERT INTO bot_state(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, local_date.isoformat()),
            )
            cursor = await db.execute("SELECT user_id, reputation FROM users WHERE reputation < 100")
            rows = [dict(row) for row in await cursor.fetchall()]
            await db.commit()
            return rows
