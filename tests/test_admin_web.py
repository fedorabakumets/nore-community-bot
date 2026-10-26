import asyncio
import json
from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.types import Chat, File, Message, PhotoSize, User
from aiohttp import web
from PIL import Image

from community_bot.admin_text import compose
from community_bot.admin_web import ACTIVE, AdminBridge, safe_html
from community_bot.database import Database


class TelegramSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []
        output = BytesIO()
        Image.new('RGB', (64, 64), 'red').save(output, 'JPEG')
        self.media = output.getvalue()

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109 - BaseSession interface
        self.calls.append(method)
        name = method.__api_method__
        if name == 'getFile':
            return File(file_id=method.file_id, file_unique_id='fixture', file_size=len(self.media),
                        file_path='photos/local.jpg')
        if name.startswith('send'):
            mid = len(self.calls)+100
            extra = {}
            if name == 'sendPhoto':
                extra['photo'] = [PhotoSize(file_id='telegram-uploaded-photo', file_unique_id='fixture',
                                            width=64, height=64)]
            return Message(message_id=mid, date=datetime.now(UTC),
                           chat=Chat(id=method.chat_id, type='private' if method.chat_id > 0 else 'supergroup'),
                           from_user=User(id=bot.id, is_bot=True, first_name='Нора'),
                           text=getattr(method, 'text', None), caption=getattr(method, 'caption', None),
                           caption_entities=getattr(method, 'caption_entities', None), **extra)
        return True

    async def stream_content(self, url, headers=None, timeout=30, chunk_size=65536, raise_for_status=True):  # noqa: ASYNC109
        yield self.media


@pytest.fixture
async def env(tmp_path):
    db = Database(tmp_path / 'admin.db')
    await db.initialize()
    for uid in (7, 8, 9):
        await db.ensure_user(uid, telegram_name=f'Участник {uid}')
    settings = SimpleNamespace(owner_id=7, owner_ids=frozenset({7}), moderator_ids=frozenset(),
                               reviewers=frozenset({7}), is_owner=lambda uid: uid == 7,
                               restricted_reputation_threshold=0, timezone='Europe/Moscow',
                               community_chat_id=-100123, community_invite_url='', cookie_price_rub=1)
    telegram = TelegramSession()
    bot = Bot('123456:isolated-fake-key', session=telegram)
    bridge = AdminBridge(db, settings, bot, {'restart_stop': asyncio.Event()})
    yield SimpleNamespace(db=db, bridge=bridge, bot=bot, telegram=telegram,
                          actor={'id': 7, 'first_name': 'Владелец'}, settings=settings)
    await bridge.dispatcher.storage.close()
    await bot.session.close()


def button(view, label):
    found = [b for card in view['cards'] for row in card['buttons'] for b in row
             if label in b['text'] and 'action' in b]
    assert found, f'Missing {label}: {[c["html"] for c in view["cards"]]}'
    return {'action': found[0]['action'], 'version': view['version']}


async def click(env, view, label):
    return await env.bridge.action(env.actor, button(view, label))


async def text(env, view, value):
    return await env.bridge.input(env.actor, {'form': view['form'], 'version': view['version'], 'text': value})


async def test_all_main_sections_and_system_tools_render_without_telegram_messages(env):
    for label, nested in [('Очередь', ['Анкеты', 'Платежи', 'Тикеты', 'Репорты', 'Почта']),
                          ('Люди', ['Права', 'Профили', 'Инактив']),
                          ('Чат', ['События', 'Автосообщения', 'Функции', 'Стоп-слова']),
                          ('Система', ['Сводка дня', 'Журнал', 'Управление магазином', 'Витрина', 'Команды'])]:
        for target in nested:
            root = await env.bridge.open(env.actor, reset=True)
            view = await click(env, root, label)
            result = await click(env, view, target)
            assert result['cards']
    root = await env.bridge.open(env.actor, reset=True)
    shop = await click(env, root, 'Управление магазином')
    for target in ('Товары', 'Категории', 'Шапка магазина', 'Покупка печенек', 'Предпросмотр'):
        view = await click(env, shop, target)
        assert view['cards']
        shop = await click(env, await env.bridge.open(env.actor, reset=True), 'Управление магазином')
    contest = await click(env, await env.bridge.open(env.actor, reset=True), 'Конкурс')
    assert contest['cards']
    assert not env.telegram.calls  # Opening menus neither posts nor starts another poller.


async def test_profile_edit_shared_with_bot_and_form_and_action_cannot_replay(env):
    view = await click(env, await env.bridge.open(env.actor), 'Люди')
    view = await click(env, view, 'Найти')
    view = await text(env, view, '8')
    view = await click(env, view, 'Участник 8')
    view = await click(env, view, 'Начислить')
    submission = {'form': view['form'], 'version': view['version'], 'text': '15'}
    results = await asyncio.gather(env.bridge.input(env.actor, submission),
                                   env.bridge.input(env.actor, submission), return_exceptions=True)
    assert sum(isinstance(r, dict) for r in results) == 1
    assert any(isinstance(r, web.HTTPConflict) for r in results)
    assert (await env.db.get_user(8))['cookies'] == 15
    transactions = await env.db.list_transactions(8)
    assert len(transactions) == 1 and transactions[0]['amount'] == 15
    assert ACTIVE.get() is None


async def test_publishing_event_with_rsvp_is_once_and_real_side_effects_use_community(env):
    view = await click(env, await env.bridge.open(env.actor), 'Чат')
    view = await click(env, view, 'Сообщение в сообщество')
    view = await click(env, view, 'Мероприятие')
    view = await text(env, view, 'Встреча в Петербурге')
    view = await click(env, view, 'Пропустить')  # media
    view = await click(env, view, 'Пропустить')  # URL buttons
    view = await click(env, view, 'Нет')
    view = await click(env, view, 'Я буду')
    assert not [m for m in env.telegram.calls if getattr(m, 'chat_id', None) == -100123]
    publish = button(view, 'Опубликовать')
    result = await env.bridge.action(env.actor, publish)
    with pytest.raises(web.HTTPConflict):
        await env.bridge.action(env.actor, publish)
    posts = [m for m in env.telegram.calls if m.__api_method__ == 'sendMessage' and m.chat_id == -100123]
    assert len(posts) == 1
    event = await env.db.get_studio_event(await env.db.get_bot_state('current_studio_event'))
    assert event and event['rsvp_enabled'] == 1
    assert result['state'] == 'AdminFlow:post_pay_ask'
    await click(env, result, 'Нет, без кнопки')


async def test_queue_approval_is_once_and_notifies_applicant_not_the_admin_ui(env):
    app_id = await env.db.create_application(8, {'name': 'Анна', 'age': '25', 'referral': 'Друг',
                                                  'expectations': 'Общение', 'bio': 'Обо мне', 'interview': 'yes'})
    view = await click(env, await env.bridge.open(env.actor), 'Очередь')
    view = await click(env, view, 'Анкеты')
    approve = button(view, 'Одобрить')
    await env.bridge.action(env.actor, approve)
    with pytest.raises(web.HTTPConflict):
        await env.bridge.action(env.actor, approve)
    assert (await env.db.get_application(app_id))['status'] == 'approved'
    assert any(getattr(m, 'chat_id', None) == 8 for m in env.telegram.calls)


async def test_signed_actor_and_current_permissions_bound_every_control_and_input(env):
    for uid, role in ((8, 'member'), (9, 'moderator')):
        await env.db.set_role(uid, role)
        with pytest.raises(web.HTTPForbidden):
            await env.bridge.open({'id': uid, 'first_name': 'Не админ'})
    view = await click(env, await env.bridge.open(env.actor), 'Люди')
    with pytest.raises(web.HTTPConflict):
        await env.bridge.action(env.actor, {'action': 'admin:chat:mute', 'version': view['version']})
    await env.db.set_role(9, 'admin')
    actor = {'id': 9, 'first_name': 'Админ'}
    foreign = button(view, 'Найти')
    other = await env.bridge.open(actor)
    with pytest.raises(web.HTTPConflict):
        await env.bridge.action(actor, foreign)
    await env.db.execute('UPDATE staff_roles SET permissions_json=? WHERE slug=?',
                         (json.dumps(['admin.panel', 'users.edit']), 'admin'))
    with pytest.raises(web.HTTPConflict):
        await env.bridge.open(actor)
    other = await env.bridge.open(actor)
    other = await env.bridge.action(actor, button(other, 'Управление магазином'))
    other = await env.bridge.action(actor, button(other, 'Создать категорию'))
    assert other['form']
    await env.db.execute('UPDATE staff_roles SET permissions_json=? WHERE slug=?',
                         (json.dumps(['admin.panel']), 'admin'))
    with pytest.raises((web.HTTPConflict, web.HTTPForbidden)):
        await env.bridge.input(actor, {'form': other['form'], 'version': other['version'], 'text': 'Запрещено'})
    assert not any(c['title'] == 'Запрещено' for c in await env.db.list_shop_categories())


async def test_upload_uses_real_file_id_and_own_media_url_without_leaking_credentials(env):
    view = await click(env, await env.bridge.open(env.actor), 'Чат')
    view = await click(env, view, 'Сообщение в сообщество')
    view = await click(env, view, 'Мероприятие')
    view = await text(env, view, 'Собираемся')
    result = await env.bridge.input(env.actor, {'form': view['form'], 'version': view['version'], 'text': ''},
                                    upload=('photo', env.telegram.media))
    state = await env.bridge.context(7)
    assert (await state.get_data())['post_file_id'] == 'telegram-uploaded-photo'
    assert env.telegram.calls[0].__api_method__ == 'sendPhoto'
    assert env.telegram.calls[0].chat_id == 7
    assert 'isolated-fake-key' not in json.dumps(result)
    assert not [m for m in env.telegram.calls if getattr(m, 'chat_id', None) == -100123]


async def test_ticket_history_and_text_reply_recreate_synthetic_message_for_recipient(env):
    ticket_id, _ = await env.db.get_or_create_ticket(8)
    await env.db.add_ticket_message(ticket_id, 8, 'user', 'Помогите с мероприятием')
    view = await click(env, await env.bridge.open(env.actor), 'Очередь')
    view = await click(env, view, 'Тикеты')
    view = await click(env, view, f'№{ticket_id}')
    assert any('Помогите' in c['html'] for c in view['cards'])
    view = await click(env, view, 'Ответить')
    await text(env, view, 'Сейчас разберёмся')
    assert any(m.__api_method__ == 'sendMessage' and m.chat_id == 8 and m.text == 'Сейчас разберёмся'
               for m in env.telegram.calls)
    count = await env.db.fetchone('SELECT COUNT(*) AS n FROM ticket_messages WHERE ticket_id=?', (ticket_id,))
    assert count['n'] == 2


def test_web_output_cannot_execute_html_and_composer_preserves_telegram_formatting():
    result = safe_html('<b onclick="bad()">Текст</b><img src=x onerror=bad()><a href="javascript:bad()">X</a>', 'HTML')
    assert 'onclick' not in result and '<img' not in result and 'javascript' not in result
    text, entities = compose('🍪 <b>Привет</b> <a href="https://example.test">ссылка</a>', 'html')
    assert text == '🍪 Привет ссылка'
    assert [(e.type, e.offset, e.length) for e in entities] == [('bold', 3, 6), ('text_link', 10, 6)]
    for invalid in ('<script>bad()</script>', '<b>не закрыто', '<a href="javascript:bad()">X</a>'):
        with pytest.raises(ValueError):
            compose(invalid, 'html')


async def test_receipt_approval_and_media_are_actor_bound_and_credit_only_once(env):
    order = await env.db.create_cookie_order(8, 40, 40, 'photo', 'fixture-receipt')
    view = await click(env, await env.bridge.open(env.actor), 'Очередь')
    view = await click(env, view, 'Платежи')
    card = next(c for c in view['cards'] if 'media' in c)
    image = await env.bridge.get_media(env.actor, card['media']['id'])
    assert image.content_type == 'image/jpeg' and image.body
    await env.db.set_role(9, 'admin')
    with pytest.raises(web.HTTPNotFound):
        await env.bridge.get_media({'id': 9, 'first_name': 'Другой админ'}, card['media']['id'])
    approve = button(view, 'Подтвердить')
    await env.bridge.action(env.actor, approve)
    with pytest.raises(web.HTTPConflict):
        await env.bridge.action(env.actor, approve)
    assert (await env.db.get_cookie_order(order))['status'] == 'approved'
    assert (await env.db.get_user(8))['cookies'] == 40


async def test_catalog_and_role_creation_use_shared_database(env):
    view = await click(env, await env.bridge.open(env.actor), 'Управление магазином')
    view = await click(env, view, 'Создать категорию')
    view = await text(env, view, 'Подарки тест')
    await text(env, view, 'Описание новой полки')
    assert any(c['title'] == 'Подарки тест' for c in await env.db.list_shop_categories())
    view = await click(env, await env.bridge.open(env.actor, reset=True), 'Люди')
    view = await click(env, view, 'Права')
    view = await click(env, view, 'Создать роль')
    await text(env, view, 'Помощник тест')
    assert any(r['name'] == 'Помощник тест' for r in await env.db.list_staff_roles())


async def test_broadcast_copies_web_text_to_real_recipients_once(env):
    view = await click(env, await env.bridge.open(env.actor), 'Чат')
    view = await click(env, view, 'Рассылка')
    payload = {'form': view['form'], 'version': view['version'], 'text': '<b>Тест</b>', 'format': 'html'}
    await env.bridge.input(env.actor, payload)
    with pytest.raises(web.HTTPConflict):
        await env.bridge.input(env.actor, payload)
    messages = [m for m in env.telegram.calls if m.__api_method__ == 'sendMessage' and m.text == 'Тест']
    assert sorted(m.chat_id for m in messages) == [7, 8, 9]
    assert all(m.entities[0].type == 'bold' for m in messages)


async def test_drafts_do_not_use_the_telegram_dialog_state(env):
    from aiogram import Dispatcher
    from aiogram.fsm.storage.memory import MemoryStorage

    original = Dispatcher(storage=MemoryStorage())
    state = original.fsm.get_context(bot=env.bot, chat_id=7, user_id=7)
    await state.set_state('OriginalBot:unchanged')
    view = await click(env, await env.bridge.open(env.actor), 'Люди')
    view = await click(env, view, 'Найти')
    assert view['state'] == 'AdminFlow:user_value'
    assert await state.get_state() == 'OriginalBot:unchanged'
    await env.bridge.open(env.actor, reset=True)
    assert await state.get_state() == 'OriginalBot:unchanged'
    await original.storage.close()


async def test_event_participants_and_payment_journal_are_reachable_in_web(env):
    await env.db.save_studio_event('event-web-test', -100123, 201, 'Тестовая встреча', [], 0, 7)
    await env.db.save_event_offer('event-web-test', -100123, 201, 'Оплатить', 20, 7, title='Тестовая встреча')
    await env.db.add_cookies(8, 100, 'test')
    assert (await env.db.pay_event_offer('event-web-test', 8, 20))[0]
    view = await click(env, await env.bridge.open(env.actor), 'Чат')
    view = await click(env, view, 'События и участники')
    view = await click(env, view, 'Тестовая встреча')
    assert any('оплачено 20' in c['html'] for c in view['cards'])
    view = await click(env, view, 'Журнал оплат')
    assert any('Журнал оплат' in c['html'] for c in view['cards'])
    assert not any('Действие больше' in n for n in view['notices'])
