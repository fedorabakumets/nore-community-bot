"""Operator entry point for rolling back a release with open Durak stakes."""
import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path

from community_bot.database import Database
from community_bot.durak_rooms import pause_and_refund
from community_bot.release_backup import verify_requested_release_backup


async def run(path, action):
    if not path.is_file():
        raise ValueError("Укажи существующую базу NORA")
    db = Database(path)
    if not await db.fetchone("SELECT 1 FROM sqlite_master WHERE name='durak_rooms'"):
        raise ValueError("В этой базе ещё нет столов Дурака")
    if action == "resume":
        await db.execute("DELETE FROM bot_state WHERE key='durak_paused'")
        return
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    await verify_requested_release_backup(db, request=f"durak-rollback-{stamp}")
    print(f"Столов закрыто с возвратом резервов: {await pause_and_refund(db)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("refund", "resume"))
    parser.add_argument("--db", required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(run(args.db, args.action))
