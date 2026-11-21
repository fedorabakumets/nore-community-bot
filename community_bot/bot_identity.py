"""Hide Telegram bot accounts from Mini App people surfaces."""


def likely_bot(row):
    # Telegram bot usernames conventionally end in bot; explicit Bot API flags
    # are recorded separately for bots without a username.
    return bool(row.get('telegram_is_bot') or str(row.get('username') or '').casefold().endswith('bot'))


async def marked_bots(db):
    rows = await db.fetchall("SELECT key FROM bot_state WHERE key LIKE 'telegram_is_bot:%' AND value='1'")
    return {r['key'].partition(':')[2] for r in rows}


async def is_bot(db, row, bot_id=None):
    if not row:
        return False
    return (int(row['user_id']) == bot_id or likely_bot(row)
            or await db.get_bot_state(f"telegram_is_bot:{row['user_id']}") == '1')
