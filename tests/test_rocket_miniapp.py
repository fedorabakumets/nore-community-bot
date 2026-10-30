"""Rocket money, proof, identity and persisted deadline regression tests."""

import asyncio
import hashlib
import json
import math

import pytest

from community_bot import rocket_api as rocket
from community_bot.database import Database

NOW = 1_800_000_000.0
SEEDS = {
    100: 'isolated-rocket-seed-16',
    150: 'isolated-rocket-seed-51',
    200: 'isolated-rocket-seed-32',
    250: 'isolated-rocket-seed-2236',
    500: 'isolated-rocket-seed-1217',
    1000: 'isolated-rocket-seed-11',
}


@pytest.fixture
async def db(tmp_path):
    db = Database(tmp_path / 'rocket.sqlite3')
    await db.initialize()
    for uid in (7, 8):
        await db.ensure_user(uid, username=f'player{uid}', telegram_name=f'Игрок {uid}')
        await db.execute(
            "UPDATE users SET profile_name=?,age=25,hobbies='Космос',profile_bio='Люблю гулять',"
            "avatar_file_id='isolated-avatar',role='moderator' WHERE user_id=?", (f'Игрок {uid}', uid),
        )
        await db.add_cookies(uid, 1000, 'fixture')
    return db


def at(round_data, cents):
    return round_data['starts_at'] + math.log(cents / 100) / rocket.GROWTH_RATE


async def prepare_with_point(db, monkeypatch, point=500, bet=10, auto=None, uid=7, now=NOW):
    monkeypatch.setattr(rocket.secrets, 'token_hex', lambda _: SEEDS[point])
    return await rocket.prepare_round(db, uid, bet, auto, now=now)


async def start(db, monkeypatch, point=500, bet=10, auto=None, uid=7, now=NOW):
    quote = await prepare_with_point(db, monkeypatch, point, bet, auto, uid, now)
    launched = await rocket.launch_round(db, uid, quote['token'], now=now)
    return quote, launched['round']


async def rocket_ledger(db, uid=7):
    return await db.fetchall(
        "SELECT amount,kind,details FROM transactions WHERE user_id=? AND kind LIKE 'rocket_%' ORDER BY id", (uid,),
    )


async def test_prepare_is_free_secret_commitment_and_actor_bound_launch_is_exactly_once(db, monkeypatch):
    quote = await prepare_with_point(db, monkeypatch, bet=30)
    assert (await db.get_user(7))['cookies'] == 1000
    assert await rocket_ledger(db) == []
    assert quote['commitment'] == hashlib.sha256(SEEDS[500].encode()).hexdigest()
    assert SEEDS[500] not in json.dumps(quote)
    assert not {'seed', 'crash_cents', 'crash_multiplier'} & quote.keys()
    with pytest.raises(ValueError, match='не найдено'):
        await rocket.launch_round(db, 8, quote['token'], now=NOW)
    results = await asyncio.gather(*[
        rocket.launch_round(db, 7, quote['token'], now=NOW) for _ in range(8)
    ])
    assert len({r['round']['id'] for r in results}) == 1
    assert all(r['balance'] == 970 and r['round']['status'] == 'countdown' for r in results)
    assert (await db.get_user(8))['cookies'] == 1000
    assert await rocket_ledger(db) == [
        {'amount': -30, 'kind': 'rocket_bet', 'details': 'round:' + results[0]['round']['id']},
    ]
    status = await rocket.get_status(db, 7, now=NOW + 3.1)
    assert status['round']['status'] == 'flying'
    assert status['round']['proof'] is None
    assert SEEDS[500] not in json.dumps(status)
    assert not {'seed', 'crash_cents', 'crash_multiplier'} & status['round'].keys()
    assert (await rocket.get_status(db, 8, now=NOW + 3.1))['round'] is None
    assert not (await rocket.get_status(db, 8, now=NOW + 3.1))['history']


async def test_manual_cashout_is_atomic_concurrent_and_round_owned(db, monkeypatch):
    _, flight = await start(db, monkeypatch, bet=7)
    when = at(flight, 137) + .001
    with pytest.raises(ValueError, match='недоступен'):
        await rocket.cashout_round(db, 8, flight['id'], now=when)
    results = await asyncio.gather(*[
        rocket.cashout_round(db, 7, flight['id'], now=when) for _ in range(8)
    ])
    assert all(r['round']['payout'] == 9 for r in results)  # floor(7 * 1.37), not a second stake credit.
    assert all(r['round']['cashout_multiplier'] == 1.37 for r in results)
    assert (await db.get_user(7))['cookies'] == 1002
    assert [r['amount'] for r in await rocket_ledger(db)] == [-7, 9]
    assert (await rocket.get_status(db, 7, now=when))['round'] is None
    proof = results[0]['round']['proof']
    assert proof['crash_multiplier'] == 5
    assert hashlib.sha256(proof['seed'].encode()).hexdigest() == flight['commitment']
    assert rocket.crash_point(proof['seed']) == proof['crash_multiplier'] * 100
    assert await rocket.tick(db, now=when + 1000) == 0
    assert (await db.get_user(7))['cookies'] == 1002


@pytest.mark.parametrize('offset,expected', [(-.0001, 'cashed_out'), (0, 'crashed'), (.0001, 'crashed')])
async def test_server_deadline_and_manual_cashout_boundary_crash_wins_ties(db, monkeypatch, offset, expected):
    _, flight = await start(db, monkeypatch, point=200, bet=10)
    response = await rocket.cashout_round(db, 7, flight['id'], now=at(flight, 200) + offset)
    assert response['round']['status'] == expected
    if expected == 'crashed':
        assert response['round']['payout'] == 0
        assert response['balance'] == 990
        assert [t['amount'] for t in await rocket_ledger(db)] == [-10]
    else:
        assert response['round']['payout'] == 19
        assert response['round']['cashout_multiplier'] == 1.99


async def test_countdown_cannot_cashout_and_instant_crash_has_no_free_escape(db, monkeypatch):
    _, flight = await start(db, monkeypatch, point=100)
    with pytest.raises(ValueError, match='ещё не взлетела'):
        await rocket.cashout_round(db, 7, flight['id'], now=flight['starts_at'] - .001)
    status = await rocket.get_status(db, 7, now=flight['starts_at'] - .001)
    assert status['round']['status'] == 'countdown' and status['round']['proof'] is None
    lost = await rocket.cashout_round(db, 7, flight['id'], now=flight['starts_at'])
    assert lost['round']['status'] == 'crashed' and lost['round']['current_multiplier'] == 1
    assert lost['balance'] == 990


@pytest.mark.parametrize('auto,expected,payout', [(1.5, 'cashed_out', 15), (2, 'crashed', 0), (3, 'crashed', 0)])
async def test_auto_cashout_selected_before_launch_survives_offline_and_equal_target_loses(
    db, monkeypatch, auto, expected, payout,
):
    _, flight = await start(db, monkeypatch, point=200, auto=auto)
    restored = Database(db.path)
    await restored.initialize()
    assert await rocket.tick(restored, now=flight['starts_at'] + 600) == 1
    result = await rocket.get_status(restored, 7, now=flight['starts_at'] + 600)
    assert result['round'] is None
    assert result['history'][0]['status'] == expected
    assert result['history'][0]['payout'] == payout
    assert result['balance'] == 990 + payout
    assert await rocket.tick(restored, now=flight['starts_at'] + 601) == 0


@pytest.mark.parametrize('auto', [None, 10])
async def test_maximum_multiplier_finishes_with_capped_payout_even_after_restart(db, monkeypatch, auto):
    _, flight = await start(db, monkeypatch, point=1000, bet=100, auto=auto)
    assert await rocket.tick(Database(db.path), now=at(flight, 1000)) == 1
    result = await rocket.get_status(db, 7, now=at(flight, 1000) + 20)
    assert result['history'][0]['status'] == 'cashed_out'
    assert result['history'][0]['payout'] == 1000
    assert result['history'][0]['cashout_multiplier'] == 10
    assert result['balance'] == 1900
    assert [t['amount'] for t in await rocket_ledger(db)] == [-100, 1000]


async def test_started_round_pays_even_after_access_profile_feature_age_or_debt_changes(db, monkeypatch):
    _, flight = await start(db, monkeypatch, point=500, bet=100, auto=2)
    await db.execute("UPDATE users SET role='member',age=15,profile_bio='',cookie_debt=70 WHERE user_id=7")
    await db.execute("UPDATE feature_flags SET enabled=0 WHERE key='games'")
    assert await rocket.tick(db, now=at(flight, 200)) == 1
    status = await rocket.get_status(db, 7, now=at(flight, 200))
    assert status['eligible'] is False
    assert status['balance'] == 1100
    assert status['history'][0]['payout'] == 200
    assert (await db.get_user(7))['cookie_debt'] == 70


async def test_quote_superseding_expiry_and_replay_old_round_never_creates_second_bet(db, monkeypatch):
    first = await prepare_with_point(db, monkeypatch, point=200)
    second = await prepare_with_point(db, monkeypatch, point=200, now=NOW + 1)
    with pytest.raises(ValueError, match='устарело'):
        await rocket.launch_round(db, 7, first['token'], now=NOW + 2)
    with pytest.raises(ValueError, match='устарело'):
        await rocket.launch_round(db, 7, second['token'], now=second['expires_at'])
    quote, flight = await start(db, monkeypatch, point=200, now=NOW + 400)
    terminal = await rocket.cashout_round(db, 7, flight['id'], now=at(flight, 200))
    _, newer = await start(db, monkeypatch, point=500, bet=20, now=NOW + 800)
    replay = await rocket.launch_round(db, 7, quote['token'], now=NOW + 801)
    assert replay['round']['id'] == terminal['round']['id']
    assert replay['round']['status'] == 'crashed'
    assert replay['balance'] == 970
    assert (await rocket.get_status(db, 7, now=NOW + 801))['round']['id'] == newer['id']
    assert [t['amount'] for t in await rocket_ledger(db)] == [-10, -20]


async def test_current_flight_blocks_more_quotes_and_only_one_of_concurrent_quotes_can_launch(db, monkeypatch):
    monkeypatch.setattr(rocket.secrets, 'token_hex', lambda _: SEEDS[500])
    quotes = await asyncio.gather(*[rocket.prepare_round(db, 7, 100, now=NOW) for _ in range(4)])
    results = await asyncio.gather(*[
        rocket.launch_round(db, 7, q['token'], now=NOW) for q in quotes
    ], return_exceptions=True)
    assert len([r for r in results if isinstance(r, dict)]) == 1
    assert len([r for r in results if isinstance(r, ValueError)]) == 3
    assert (await db.get_user(7))['cookies'] == 900
    with pytest.raises(ValueError, match='уже идёт'):
        await rocket.prepare_round(db, 7, 1, now=NOW + 1)


@pytest.mark.parametrize('bet', [0, -1, 101, True, 1.5, '10', None, [], {}])
async def test_bets_must_be_bounded_integer_and_never_mutate_money(db, bet):
    with pytest.raises(ValueError, match='целое число'):
        await rocket.prepare_round(db, 7, bet, now=NOW)
    assert (await db.get_user(7))['cookies'] == 1000
    assert await rocket_ledger(db) == []


@pytest.mark.parametrize('auto', [True, 1, 1.09, 10.01, 1.111, '1.5', float('nan'), float('inf'), [], {}])
async def test_autocashout_rejects_nonfinite_invalid_precision_and_bounds(db, auto):
    with pytest.raises(ValueError):
        await rocket.prepare_round(db, 7, 10, auto, now=NOW)
    assert await rocket_ledger(db) == []


@pytest.mark.parametrize('change,reason', [
    ("UPDATE users SET age=17 WHERE user_id=7", '18 лет'),
    ("UPDATE users SET profile_bio='' WHERE user_id=7", '100%'),
    ("UPDATE users SET cookie_debt=1 WHERE user_id=7", 'долг'),
    ("UPDATE feature_flags SET enabled=0 WHERE key='games'", 'выключены'),
    ("UPDATE users SET cookies=0 WHERE user_id=7", 'хватает'),
])
async def test_eligibility_and_balance_are_checked_again_inside_launch(db, monkeypatch, change, reason):
    quote = await prepare_with_point(db, monkeypatch)
    await db.execute(change)
    with pytest.raises(ValueError, match=reason):
        await rocket.launch_round(db, 7, quote['token'], now=NOW)
    assert await rocket_ledger(db) == []


async def test_active_starter_pack_cannot_fund_a_new_stake_or_reuse_existing_quote(db, monkeypatch):
    quote = await prepare_with_point(db, monkeypatch)
    ok, _, loan = await db.take_cookie_loan(7)
    assert ok and loan['principal'] == 100
    assert (await db.get_user(7))['cookie_debt'] == 0  # The loan is not overdue yet.
    with pytest.raises(ValueError, match='займов'):
        await rocket.prepare_round(db, 7, 10, now=NOW)
    with pytest.raises(ValueError, match='займов'):
        await rocket.launch_round(db, 7, quote['token'], now=NOW)
    status = await rocket.get_status(db, 7, now=NOW)
    assert not status['eligible'] and 'СТАРТЕР-ПАК' in status['reason']
    assert status['balance'] == 1100 and await rocket_ledger(db) == []


async def test_prepare_checks_funds_and_quote_creation_rate(db, monkeypatch):
    await db.execute('UPDATE users SET cookies=2 WHERE user_id=7')
    with pytest.raises(ValueError, match='Недостаточно'):
        await rocket.prepare_round(db, 7, 3, now=NOW)
    for _ in range(20):
        await prepare_with_point(db, monkeypatch, bet=1)
    with pytest.raises(ValueError, match='Подожди минуту'):
        await rocket.prepare_round(db, 7, 1, now=NOW)
    await rocket.prepare_round(db, 7, 1, now=NOW + 61)
    assert (await db.get_user(7))['cookies'] == 2
    assert await rocket_ledger(db) == []


async def test_periodic_tick_and_cashout_race_cannot_duplicate_auto_payout(db, monkeypatch):
    _, flight = await start(db, monkeypatch, point=500, bet=100, auto=2)
    when = at(flight, 200)
    await asyncio.gather(
        rocket.tick(db, now=when), rocket.tick(db, now=when),
        rocket.cashout_round(db, 7, flight['id'], now=when),
        rocket.get_status(db, 7, now=when),
    )
    assert (await db.get_user(7))['cookies'] == 1100
    assert [t['amount'] for t in await rocket_ledger(db)] == [-100, 200]


async def test_failed_ledger_write_rolls_back_debit_and_round_creation(db, monkeypatch):
    quote = await prepare_with_point(db, monkeypatch)
    await db.execute(
        "CREATE TRIGGER reject_rocket_bet BEFORE INSERT ON transactions "
        "WHEN NEW.kind='rocket_bet' BEGIN SELECT RAISE(ABORT, 'fixture write failure'); END",
    )
    with pytest.raises(Exception, match='fixture write failure'):
        await rocket.launch_round(db, 7, quote['token'], now=NOW)
    assert (await db.get_user(7))['cookies'] == 1000
    assert await rocket_ledger(db) == []
    assert (await db.fetchone('SELECT COUNT(*) AS n FROM mini_rocket_rounds'))['n'] == 0
    await db.execute('DROP TRIGGER reject_rocket_bet')
    assert (await rocket.launch_round(db, 7, quote['token'], now=NOW))['balance'] == 990


async def test_failed_payout_ledger_rolls_back_credit_and_round_settlement_then_retry_pays_once(db, monkeypatch):
    _, flight = await start(db, monkeypatch)
    await db.execute(
        "CREATE TRIGGER reject_rocket_payout BEFORE INSERT ON transactions "
        "WHEN NEW.kind='rocket_payout' BEGIN SELECT RAISE(ABORT, 'fixture payout failure'); END",
    )
    with pytest.raises(Exception, match='fixture payout failure'):
        await rocket.cashout_round(db, 7, flight['id'], now=at(flight, 200))
    assert (await db.get_user(7))['cookies'] == 990
    row = await db.fetchone('SELECT status FROM mini_rocket_rounds WHERE id=?', (flight['id'],))
    assert row['status'] == 'active'
    await db.execute('DROP TRIGGER reject_rocket_payout')
    assert (await rocket.cashout_round(db, 7, flight['id'], now=at(flight, 200)))['balance'] == 1010
    assert [t['amount'] for t in await rocket_ledger(db)] == [-10, 20]


async def test_recent_history_is_only_own_and_limited_without_active_outcome(db, monkeypatch):
    for index in range(12):
        _, flight = await start(db, monkeypatch, point=100, now=NOW + index * 5)
        await rocket.tick(db, now=flight['starts_at'])
    _, other = await start(db, monkeypatch, point=500, uid=8, now=NOW + 100)
    status = await rocket.get_status(db, 7, now=NOW + 100)
    assert len(status['history']) == 10
    assert not status['round']
    assert other['id'] not in json.dumps(status)
    assert status['balance'] == 880
    assert all(h['status'] == 'crashed' and h['proof'] for h in status['history'])


class Request(dict):
    def __init__(self, db, body, uid=7):
        super().__init__(actor={'id': uid})
        self.app, self.body = {'db': db}, body

    async def json(self):
        return self.body


@pytest.mark.parametrize('handler,body', [
    (rocket.prepare, {'bet': 10, 'user_id': 8}),
    (rocket.launch, {'token': 'x' * 32, 'bet': 1}),
    (rocket.cashout, {'round_id': 'x' * 32, 'multiplier': 1000}),
    (rocket.cashout, {'round_id': 'x' * 32, 'server_time': NOW}),
    (rocket.launch, []),
])
async def test_http_handlers_reject_actor_time_price_and_multiplier_override(db, handler, body):
    with pytest.raises(ValueError, match='параметры'):
        await handler(Request(db, body))
    assert await rocket_ledger(db) == []


def test_proof_uses_independent_hash_and_fixed_distribution():
    for expected, seed in SEEDS.items():
        commitment = hashlib.sha256(seed.encode()).hexdigest()
        outcome = hashlib.sha256(('nora-rocket-v1:' + seed).encode()).hexdigest()
        assert commitment != outcome
        n = int(outcome[:13], 16) + 1
        assert rocket.crash_point(seed) == min(1000, max(100, (97 * 2**52) // n)) == expected
    assert rocket.multiplier_cents(NOW + 3, NOW) == 100
    assert rocket.multiplier_cents(NOW, NOW + 100_000) == 1000
