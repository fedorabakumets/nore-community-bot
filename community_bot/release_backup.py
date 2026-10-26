"""Opt-in SQLite backup/restore gate, run before production schema initialization."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from community_bot.database import Database

logger = logging.getLogger(__name__)
REQUEST_VARIABLE = "NORA_PRE_RELEASE_BACKUP_ONCE"


def _read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)


def _snapshot(source: Path, destination: Path) -> None:
    # Exclusive creation prevents replacing an earlier pre-release recovery point.
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    try:
        with closing(_read_only(source)) as live, closing(sqlite3.connect(destination)) as backup:
            live.backup(backup, pages=256, sleep=0.01)
        with destination.open("rb") as result:
            os.fsync(result.fileno())
    except BaseException:
        destination.unlink(missing_ok=True)  # Only the incomplete file just created here.
        raise


def _financial_state(path: Path) -> tuple[str, str]:
    with closing(_read_only(path)) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise RuntimeError("SQLite integrity check failed")
        balances = hashlib.sha256()
        ledger = hashlib.sha256()
        for row in db.execute("SELECT user_id, cookies, cookie_debt FROM users ORDER BY user_id"):
            balances.update(json.dumps(row, ensure_ascii=False).encode())
        for row in db.execute("SELECT * FROM transactions ORDER BY id"):
            ledger.update(json.dumps(row, ensure_ascii=False).encode())
        return balances.hexdigest(), ledger.hexdigest()


def _prepare(database: Path, request: str) -> tuple[Path, Path] | None:
    if not database.is_file():
        raise RuntimeError("Pre-release backup requires an existing database")
    folder = database.parent / ".nora-backups"
    folder.mkdir(mode=0o700, exist_ok=True)
    folder.chmod(0o700)
    backup = folder / f"before-{request}.sqlite3"
    marker = folder / f"before-{request}.verified.json"
    if marker.is_file():
        if not backup.is_file():
            raise RuntimeError("Previously verified release backup is missing")
        return None
    if not backup.exists():
        _snapshot(database, backup)
    return backup, marker


async def _verify_restored_copy(backup: Path, restored: Path) -> None:
    before = await asyncio.to_thread(_financial_state, backup)
    await asyncio.to_thread(_snapshot, backup, restored)
    if await asyncio.to_thread(_financial_state, restored) != before:
        raise RuntimeError("Restored SQLite state differs from the backup")
    copy = Database(restored)
    await copy.initialize()
    if await asyncio.to_thread(_financial_state, restored) != before:
        raise RuntimeError("Schema initialization changed existing balances or ledger")
    # Synthetic participant and catalog changes exist only in the disposable restored copy.
    row = await copy.fetchone("SELECT MIN(user_id) AS minimum FROM users")
    actor_id = min(0, int(row["minimum"] or 0)) - 1
    await copy.ensure_user(actor_id, telegram_name="Isolated release verification")
    await copy.add_cookies(actor_id, 50, "release_verification")
    item = await copy.get_shop_item("rep_shield")
    await copy.execute("UPDATE shop_categories SET enabled = 1 WHERE slug = ?", (item["category_slug"],))
    await copy.upsert_shop_item("rep_shield", price=12, enabled=1)
    token = await copy.create_wallet_intent(actor_id, "rep_shield", 12)
    first = await copy.buy_item(actor_id, "rep_shield", 12, intent_id=token)
    second = await copy.buy_item(actor_id, "rep_shield", 12, intent_id=token)
    user = await copy.get_user(actor_id)
    if not first[0] or second[0] or (user["cookies"], user["hate_shields"]) != (38, 1):
        raise RuntimeError("Purchase replay verification failed on restored copy")


def _write_marker(marker: Path, backup: Path) -> None:
    result = {
        "backup": backup.name,
        "verified_at": datetime.now(UTC).isoformat(),
        "integrity_ok": True, "balances_preserved": True, "ledger_preserved": True, "replay_blocked": True,
    }
    descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as report:
        json.dump(result, report)
        report.flush()
        os.fsync(report.fileno())


async def verify_requested_release_backup(db: Database) -> bool:
    request = os.getenv(REQUEST_VARIABLE, "").strip()
    if not request:
        return False
    if not re.fullmatch(r"[a-z0-9-]{1,80}", request):
        raise ValueError("Invalid release backup request identifier")
    prepared = await asyncio.to_thread(_prepare, db.path, request)
    if prepared is None:
        return False
    backup, marker = prepared
    with tempfile.TemporaryDirectory(prefix="restore-check-", dir=backup.parent) as directory:
        await _verify_restored_copy(backup, Path(directory) / "restored.sqlite3")
    await asyncio.to_thread(_write_marker, marker, backup)
    logger.info(
        "Release backup verified: SQLite integrity, restored balances, ledger and purchase replay protection OK",
    )
    return True
