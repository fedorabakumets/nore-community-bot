"""Presentation metadata for the web workspace; callbacks remain server-issued capabilities."""
from __future__ import annotations

import re

from community_bot.permissions import role_has_permission

# Each entry opens an existing read-only screen or a draft, never a publication.
SECTIONS = (
    ('overview', 'Обзор', 'Все задачи команды', 'admin:panel', ()),
    ('people', 'Участники', 'Профили, печеньки, репутация и права', 'admin:people', ()),
    ('queue', 'Обращения', 'Анкеты, платежи, тикеты и почта', 'admin:queue', ()),
    ('content', 'Публикации', 'Посты, рассылки и автосообщения', 'admin:chatroom', ()),
    ('events', 'События', 'Мероприятия, участники и оплаты', 'admin:events:0', ('events.participants', 'chat.post')),
    ('shop', 'Магазин', 'Товары, категории и покупка печенек', 'ashop:home', ('features', 'users.edit')),
    ('settings', 'Настройки', 'Функции Норы и правила чата', 'admin:features', ('features',)),
    ('system', 'Система', 'Сводка, журнал и инструменты', 'admin:system', ()),
)

TOOLS = (
    ('people', 'directory', 'Все участники', 'Профиль, баланс, репутация и роль', 'admin:users',
     ('users.edit', 'users.cookies')),
    ('people', 'search', 'Найти участника', 'По имени, @username или Telegram ID', 'admin:search',
     ('users.edit', 'users.cookies')),
    ('people', 'roles', 'Роли и права', 'Состав команды и разрешения ролей', 'admin:roles',
     ('roles.assign', 'roles.edit')),
    ('people', 'inactive', 'Неактивные участники', 'Посмотреть активность сообщества', 'admin:inactive', ()),
    ('queue', 'applications', 'Анкеты', 'Заявки на вступление', 'admin:applications', ('applications',)),
    ('queue', 'payments', 'Платежи', 'Проверка пополнений СБП', 'admin:orders', ('payments',)),
    ('queue', 'tickets', 'Тикеты', 'Обращения в поддержку', 'admin:tickets:0', ('tickets',)),
    ('queue', 'reports', 'Репорты', 'Сообщения о нарушениях', 'admin:reports', ()),
    ('queue', 'mail', 'Почта', 'Входящие сообщения участников', 'admin:mail', ()),
    ('content', 'post', 'Создать публикацию', 'Текст, медиа, кнопки и опросы', 'admin:post', ('chat.post',)),
    ('content', 'broadcast', 'Рассылка в личку', 'Сообщение участникам от Норы', 'admin:broadcast',
     ('chat.broadcast',)),
    ('content', 'auto', 'Автосообщения', 'Расписание и включение сообщений', 'admin:auto:list', ('automessages',)),
    ('content', 'lottery', 'Розыгрыш', 'Настроить розыгрыш в сообществе', 'admin:lottery', ('chat.post',)),
    ('content', 'contest', 'Конкурс на печеньки', 'Участники и итоги конкурса', 'admin:contest', ('contest.cookies',)),
    ('settings', 'features', 'Функции Норы', 'Включение возможностей сообщества', 'admin:features', ('features',)),
    ('settings', 'stopwords', 'Стоп-слова', 'Правила автоматической модерации', 'admin:stopwords', ('features',)),
    ('settings', 'chat', 'Управление чатом', 'Открыть, закрыть или упомянуть участников', 'admin:chatroom',
     ('chat.lock', 'chat.mention')),
    ('shop', 'vitrine', 'Витрина', 'Выбор главного товара', 'admin:vitrine', ('features', 'users.edit')),
    ('system', 'health', 'Сводка дня', 'Текущее состояние сообщества', 'admin:health', ()),
    ('system', 'audit', 'Журнал действий', 'История административных операций', 'admin:audit', ('audit',)),
    ('system', 'commands', 'Команды', 'Команды и ответы Норы', 'admin:cmds', ('commands.studio',)),
)


def permitted(permissions, required):
    return not required or any(role_has_permission(permissions, key) for key in required)


def button_meta(callback, text):
    """Describe controls, without exposing callbacks to the browser."""
    clean = re.sub(r'^[\W_]+', '', text, flags=re.UNICODE).strip() or text
    meta = {'label': clean, 'group': 'actions'}
    if callback.startswith(('admin:prefix:color:', 'admin:prefix:emoji:')):
        meta.update(kind='choice', checked=text.startswith('✓'),
                    group='prefix_color' if ':color:' in callback else 'prefix_emoji')
        if ':color:' in callback:
            meta['prefix_color'] = callback.rsplit(':', 1)[1]
    if callback in {row[3] for row in SECTIONS} or callback in {row[4] for row in TOOLS}:
        meta['kind'] = 'link'
    if text.startswith(('←', '⬅', '🔙', '↩')) or callback in {'ui:close', 'flow:cancel', 'flow:restart'}:
        meta['kind'] = 'back'
    toggles = ('admin:feature:', 'admin:roletog:', 'admin:auto:toggle:', 'ashop:itog:', 'ashop:ctog:')
    if callback.startswith(toggles) or callback in {'ashop:htog', 'ashop:cktog'}:
        meta.update(kind='toggle', checked=text.startswith(('🟢', '✅')) or 'Выключить' in text)
        meta['group'] = 'permissions' if callback.startswith('admin:roletog:') else 'settings'
        if callback.startswith('ashop:itog:'):
            meta['label'] = 'Товар доступен в магазине'
        elif callback.startswith('ashop:ctog:'):
            meta['label'] = 'Категория включена'
        elif callback == 'ashop:htog':
            meta['label'] = 'Шапка магазина включена'
        elif callback == 'ashop:cktog':
            meta['label'] = 'Покупка печенек включена'
        elif callback.startswith('admin:feature:'):
            from community_bot.keyboards import FEATURE_META

            key = callback.rsplit(':', 1)[1]
            meta['description'] = FEATURE_META.get(key, ('', ''))[1]
            meta['group'] = ('community' if key in {'games', 'tamagotchi', 'profile_video', 'activity_rewards'}
                             else 'automation' if key == 'morning_digest' else 'protection')
        elif callback.startswith('admin:roletog:'):
            key = callback.rsplit(':', 1)[1]
            meta['group'] = ('perm_people' if key.startswith(('users.', 'roles.', 'profile.', 'mod.')) else
                             'perm_content' if key.startswith(('chat.', 'events.')) or key == 'automessages' else
                             'perm_system')
    if callback.startswith(('admin:manage:', 'admin:user:')):
        meta.update(kind='user', group='directory')
    if callback in {'admin:health', 'admin:audit', 'admin:updates', 'admin:staffguide'}:
        meta['group'] = 'reports'
    if callback in {'admin:cmds', 'admin:morning', 'admin:rsvpstake'}:
        meta['group'] = 'tools'
    if callback in {'ashop:home', 'admin:vitrine', 'ashop:items', 'ashop:cats', 'ashop:newitem', 'ashop:newcat'}:
        meta['group'] = 'catalog'
    if callback in {'ashop:header', 'ashop:cookies', 'ashop:preview'}:
        meta['group'] = 'storefront'
    if callback.startswith('admin:edit:'):
        field = callback.split(':')[2]
        meta['group'] = ('wallet' if field in {'cookies', 'add_cookies'} else
                         'moderation' if field in {'warnings', 'note', 'rep'} else
                         'danger' if field.startswith('clear_') else 'profile')
    if callback.startswith(('admin:setrole:', 'admin:rolev', 'admin:rolerank:', 'admin:roledel:')):
        meta['group'] = 'roles'
    if callback.startswith(('admin:roledel:', 'ashop:idel:', 'admin:features:reset', 'admin:restart')):
        meta['group'] = 'danger'
    return meta
