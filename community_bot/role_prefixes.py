"""Small, validated palette shared by role creation and Mini App name badges."""

COLORS = {'red': 'Красный', 'orange': 'Оранжевый', 'gold': 'Золотой',
          'green': 'Зелёный', 'blue': 'Голубой', 'purple': 'Фиолетовый', 'pink': 'Розовый'}
EMOJI_LABELS = {'': 'Без символа', '🎉': 'Вечеринка', '🛡️': 'Щит', '👑': 'Корона',
                '👮': 'Полицейский', '♥': 'Сердечко', '★': 'Звёздочка', '67': '67'}
EMOJIS = tuple(EMOJI_LABELS)
# Existing role settings remain valid; the picker offers the new symbol set.
LEGACY_EMOJIS = ('⭐', '🔥', '🌙', '💎', '🌿')


def validate(color, emoji):
    if color not in ('', *COLORS) or emoji not in (*EMOJIS, *LEGACY_EMOJIS):
        raise ValueError('Выбери цвет и эмодзи из списка')


async def prefix_for(db, settings, uid):
    from community_bot.helpers import effective_role

    role = await db.get_staff_role(await effective_role(db, settings, uid))
    if not role or role.get('prefix_color') not in COLORS:
        return None
    return {'text': role['name'], 'color': role['prefix_color'],
            'emoji': role['prefix_emoji'] if role.get('prefix_emoji') in (*EMOJIS, *LEGACY_EMOJIS) else ''}


async def decorate_game_people(db, settings, payload):
    """Game state caches names; resolve CURRENT role appearance only in outgoing views."""
    cache = {}

    async def get(uid):
        if type(uid) is not int or uid <= 0:
            return None
        if uid not in cache:
            cache[uid] = await prefix_for(db, settings, uid)
        return cache[uid]

    async def visit(value):
        if isinstance(value, list):
            for item in value:
                await visit(item)
        elif isinstance(value, dict):
            for item in list(value.values()):
                await visit(item)
            uid = value.get('user_id', value.get('id'))
            if 'name' in value and type(uid) is int and uid > 0:
                value['prefix'] = await get(uid)
            for key in ('sender', 'host'):
                if key + '_name' in value and key + '_id' in value:
                    value[key + '_prefix'] = await get(value[key + '_id'])

    await visit(payload)
    return payload
