"""Shared playback state. Only the source and clock travel through the lobby."""
import asyncio
import hashlib
import ipaddress
import logging
import math
import re
import tempfile
import time
from dataclasses import dataclass, replace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from aiohttp import web

from community_bot.helpers import has_permission
from community_bot.media_cache import _thread
from community_bot.nora_game_api import LOBBY_TTL
from community_bot.permissions import PERM_GAMES

logger = logging.getLogger(__name__)
SEATS = tuple((x, z) for z in (-4.0, -2.3) for x in (10.8, 9.5, 12.1, 8.2, 13.4))
ENTRANCE = (10.8, -.3)
MAX_FILE = 20 * 1024 * 1024
MAX_CLIPS = 20
SHOW_TTL = 4 * 3600
CLIP_TTL = 24 * 3600
PREFIX = 'cinema/v1/'
YOUTUBE_ID = re.compile(r'[A-Za-z0-9_-]{11}\Z')


def source_from_url(url):
    if not isinstance(url, str) or len(url) > 2048 or re.search(r'[\s\\\x00-\x1f\x7f]', url):
        raise ValueError('Вставь HTTPS-ссылку на YouTube или MP4.')
    try:
        link = urlsplit(url)
        host, port = link.hostname or '', link.port
    except ValueError:
        raise ValueError('Проверь адрес видео.') from None
    if link.scheme != 'https' or link.username is not None or port not in (None, 443):
        raise ValueError('Вставь HTTPS-ссылку на YouTube или MP4.')
    if host in {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'}:
        parts = link.path.strip('/').split('/')
        video = ''
        if host == 'youtu.be' and len(parts) == 1:
            video = parts[0]
        elif len(parts) == 2 and parts[0] in {'shorts', 'embed', 'live'}:
            video = parts[1]
        elif link.path == '/watch':
            video = parse_qs(link.query).get('v', [''])[0]
        if YOUTUBE_ID.fullmatch(video):
            return 'youtube', video
        raise ValueError('В этой ссылке нет ролика YouTube.')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if (
            re.fullmatch(r'(?:[a-z0-9-]+\.)+[a-z][a-z0-9-]+', host)
            and not host.endswith(('.local', '.localhost', '.internal', '.test'))
            and link.path.lower().endswith('.mp4')
        ):
            return 'mp4', url
    raise ValueError('Нужна прямая ссылка на файл MP4 или ролик YouTube.')


@dataclass(frozen=True, slots=True)
class Show:
    id: str
    kind: str
    source: str
    host: int
    since: float
    changed: float
    position: float = 0
    playing: bool = True
    revision: str = ''

    def at(self, now):
        return self.position + max(0, now - self.changed) * self.playing


class Cinema:
    def __init__(self, storage):
        self.storage = storage
        self.show = None
        self.clips = {}
        self.import_lock = asyncio.Lock()
        self.next_import = 0.0

    def seat(self, presence, uid, current, session, pose, now):
        if current and current[1] == session and 'seat' in current[2]:
            return current[2]['seat']
        if math.hypot(pose['x'] - ENTRANCE[0], pose['z'] - ENTRANCE[1]) > 2:
            return None
        occupied = {p.get('seat') for seen, _, p in presence.values() if now - seen < LOBBY_TTL}
        return next((index for index in range(len(SEATS)) if index not in occupied), None)

    def refresh(self, presence, now):
        show = self.show
        if show is None:
            return
        seated = [uid for uid, (seen, _, pose) in presence.items() if now - seen < LOBBY_TTL and 'seat' in pose]
        if not seated or now - show.since >= SHOW_TTL:
            self.show = None
        elif show.host not in seated:
            self.show = replace(show, host=seated[0], revision=uuid4().hex)

    def snapshot(self, presence, uid, revision, now):
        self.refresh(presence, now)
        show = self.show
        actual = show.revision if show else ''
        if revision == actual:
            return {}
        return {
            'revision': actual,
            'show': {
                'id': show.id, 'kind': show.kind,
                'source': show.source if show.kind != 'telegram' else '',
                'host': show.host == uid, 'changed': show.changed * 1000,
                'position': show.position, 'playing': show.playing,
            } if show else None,
        }

    def clip_list(self):
        now = time.time()
        self.clips = {key: item for key, item in self.clips.items() if now - item[0] < CLIP_TTL - SHOW_TTL}
        return [{'id': key, 'label': item[1]} for key, item in reversed(self.clips.items())]

    def update(self, presence, uid, body, moderator, now):
        self.refresh(presence, now)
        show = self.show
        action = body.get('action')
        if body.get('revision') != (show.revision if show else ''):
            raise ValueError('Сеанс изменился. Попробуй ещё раз.')
        if show and show.host != uid and not moderator:
            raise ValueError('Управление сеансом сейчас у ведущего.')
        if action == 'start':
            clip = body.get('clip')
            if clip is not None:
                self.clip_list()
                if not isinstance(clip, str) or clip not in self.clips:
                    raise ValueError('Этот ролик уже недоступен.')
                kind, source = 'telegram', clip
            else:
                kind, source = source_from_url(body.get('url'))
            self.show = Show(uuid4().hex, kind, source, uid, now, now, revision=uuid4().hex)
        elif show and action == 'stop':
            self.show = None
        elif show and action in ('toggle', 'seek'):
            at = show.at(now)
            if action == 'seek':
                at = body.get('position')
                if type(at) not in (int, float) or not 0 <= at <= 86400:
                    raise ValueError('Проверь время перемотки.')
            self.show = replace(show, position=at, changed=now,
                                playing=not show.playing if action == 'toggle' else show.playing,
                                revision=uuid4().hex)
        else:
            raise ValueError('Сначала выбери видео.')

    def _upload(self, key, file):
        client = self.storage._client()
        bucket = self.storage.config['BUCKET']
        # Only prune objects created by the cinema. The Railway bucket has no lifecycle rules.
        entries = client.list_objects_v2(Bucket=bucket, Prefix=PREFIX, MaxKeys=100).get('Contents', ())
        current = set()
        for entry in entries:
            existing = entry['Key']
            if not re.fullmatch(PREFIX + r'\d+/[0-9a-f]{64}\.mp4', existing):
                continue
            day = int(existing.split('/')[2])
            if time.time() >= (day + 2) * CLIP_TTL:
                client.delete_object(Bucket=bucket, Key=existing)
            else:
                current.add(existing)
        if key not in current:
            if sum(item.rsplit('/', 1)[0] == key.rsplit('/', 1)[0] for item in current) >= MAX_CLIPS:
                raise ValueError('На сегодня лимит роликов из Telegram исчерпан.')
            client.put_object(Bucket=bucket, Key=key, Body=file, ContentType='video/mp4')

    async def import_clip(self, bot, message):
        item = message.video or message.document
        if message.has_protected_content or not item or item.mime_type != 'video/mp4':
            raise ValueError('Ответь на обычное видео MP4 в группе.')
        if not item.file_size or item.file_size > MAX_FILE:
            raise ValueError('Из Telegram можно добавить MP4 до 20 МБ.')
        if not all(self.storage.config.values()):
            raise ValueError('Хранилище видео пока недоступно.')
        if self.import_lock.locked() or time.monotonic() < self.next_import:
            raise ValueError('Подожди немного перед загрузкой следующего ролика.')
        async with self.import_lock:
            self.next_import = time.monotonic() + 15
            now = time.time()
            digest = hashlib.sha256(item.file_unique_id.encode()).hexdigest()
            key = f'{PREFIX}{int(now // CLIP_TTL)}/{digest}.mp4'
            if key not in self.clips:
                try:
                    with tempfile.TemporaryFile() as file:
                        await bot.download(item.file_id, destination=file, timeout=30)
                        file.seek(0, 2)
                        if not 0 < file.tell() <= MAX_FILE:
                            raise ValueError('Из Telegram можно добавить MP4 до 20 МБ.')
                        file.seek(0)
                        if file.read(8)[4:8] != b'ftyp':
                            raise ValueError('Этот файл нельзя открыть как MP4.')
                        file.seek(0)
                        await _thread(self._upload, key, file)
                except ValueError:
                    raise
                except Exception:
                    logger.warning('Cinema video import failed')
                    raise ValueError('Не удалось добавить ролик. Попробуй чуть позже.') from None
                caption = ' '.join((message.caption or '').split())[:70]
                self.clips[key] = (now, caption or f'Видео из чата · {message.message_id}')

    async def signed_source(self, show):
        try:
            return await _thread(self._sign, show.source)
        except Exception:
            logger.warning('Cinema video signing failed')
            raise ValueError('Хранилище видео временно недоступно.') from None

    def _sign(self, key):
        return self.storage._client().generate_presigned_url(
            'get_object', Params={'Bucket': self.storage.config['BUCKET'], 'Key': key},
            ExpiresIn=6 * 3600,
        )


async def cinema_api(request):
    cinema = request.app['nora_cinema']
    presence = request.app['nora_lobby']
    uid = request['actor']['id']
    if request.method == 'GET':
        session = request.query.get('session')
        body = {}
        moderator = False
    else:
        if request.content_length and request.content_length > 4096:
            raise ValueError('Проверь длину ссылки.')
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError('Проверь данные сеанса.')
        session = body.get('session')
        moderator = False
        if cinema.show and cinema.show.host != uid:
            moderator = await has_permission(request.app['db'], request.app['settings'], uid, PERM_GAMES)
    current = presence.get(uid)
    now = time.monotonic()
    if not current or now - current[0] >= LOBBY_TTL or current[1] != session or 'seat' not in current[2]:
        raise ValueError('Сначала зайди в кинотеатр.')
    cinema.refresh(presence, now)
    if request.method == 'POST':
        cinema.update(presence, uid, body, moderator, now)
        return web.json_response({'ok': True})
    if show_id := request.query.get('show'):
        show = cinema.show
        if not show or show.id != show_id or show.kind != 'telegram':
            raise ValueError('Этот сеанс уже сменился.')
        return web.json_response({'url': await cinema.signed_source(show)})
    return web.json_response({
        'clips': cinema.clip_list(),
        'moderator': await has_permission(request.app['db'], request.app['settings'], uid, PERM_GAMES),
    })
