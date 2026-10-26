import json
import sqlite3

import pytest

from community_bot.database import Database
from community_bot.release_backup import REQUEST_VARIABLE, verify_requested_release_backup


async def database(tmp_path):
    db = Database(tmp_path / "source.sqlite3")
    await db.initialize()
    await db.ensure_user(7, telegram_name="Анна")
    await db.add_cookies(7, 123, "test")
    await db.execute("UPDATE users SET cookie_debt = 17 WHERE user_id = 7")
    # Exercise the upgrade from the actual pre-release table layout.
    await db.execute("DROP TABLE wallet_intents")
    return db


async def test_backup_gate_without_request_does_not_create_or_open_database(tmp_path, monkeypatch):
    monkeypatch.delenv(REQUEST_VARIABLE, raising=False)
    db = Database(tmp_path / "missing.sqlite3")
    assert not await verify_requested_release_backup(db)
    assert not db.path.exists()


async def test_backup_restores_wal_and_checks_upgrade_without_mutating_live_data(tmp_path, monkeypatch):
    db = await database(tmp_path)
    monkeypatch.setenv(REQUEST_VARIABLE, "nora-release-17-test")
    async with db.connect() as active:
        await active.execute("UPDATE users SET cookies = 456 WHERE user_id = 7")
        await active.commit()
        assert await verify_requested_release_backup(db)
    user = await db.get_user(7)
    assert (user["cookies"], user["cookie_debt"]) == (456, 17)
    assert await db.fetchone("SELECT name FROM sqlite_master WHERE name = 'wallet_intents'") is None
    assert (await db.fetchone("SELECT COUNT(*) AS count FROM users"))["count"] == 1
    backup = tmp_path / ".nora-backups" / "before-nora-release-17-test.sqlite3"
    assert backup.stat().st_mode & 0o777 == 0o600
    assert backup.parent.stat().st_mode & 0o777 == 0o700
    report = json.loads(backup.with_suffix(".verified.json").read_text())
    assert report["integrity_ok"] and report["balances_preserved"] and report["replay_blocked"]
    assert not list(backup.parent.glob("restore-check-*"))


async def test_success_marker_preserves_original_recovery_point_on_restart(tmp_path, monkeypatch):
    db = await database(tmp_path)
    monkeypatch.setenv(REQUEST_VARIABLE, "nora-release-17-test")
    assert await verify_requested_release_backup(db)
    await db.add_cookies(7, 50, "later")
    assert not await verify_requested_release_backup(db)
    with sqlite3.connect(tmp_path / ".nora-backups" / "before-nora-release-17-test.sqlite3") as backup:
        assert backup.execute("SELECT cookies FROM users WHERE user_id = 7").fetchone()[0] == 123
    assert (await db.get_user(7))["cookies"] == 173


async def test_restore_failure_never_marks_success_or_changes_live_data(tmp_path, monkeypatch):
    db = await database(tmp_path)
    monkeypatch.setenv(REQUEST_VARIABLE, "nora-release-17-test")

    async def fail(*_args):
        raise RuntimeError("simulated restore failure")

    monkeypatch.setattr("community_bot.release_backup._verify_restored_copy", fail)
    with pytest.raises(RuntimeError, match="simulated"):
        await verify_requested_release_backup(db)
    assert (await db.get_user(7))["cookies"] == 123
    assert not list((tmp_path / ".nora-backups").glob("*.verified.json"))


async def test_missing_production_database_blocks_release_instead_of_creating_empty_database(tmp_path, monkeypatch):
    monkeypatch.setenv(REQUEST_VARIABLE, "nora-release-17-test")
    db = Database(tmp_path / "missing.sqlite3")
    with pytest.raises(RuntimeError, match="existing database"):
        await verify_requested_release_backup(db)
    assert not db.path.exists()
