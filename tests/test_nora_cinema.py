import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from community_bot.aliases import is_command_message
from community_bot.database import Database
from community_bot.nora_cinema import ENTRANCE, MAX_FILE, Cinema, cinema_api, source_from_url
from community_bot.nora_game_api import lobby_snapshot, register, save_outfit

VIDEO = 'https://youtu.be/M7lc1UVf-VE'
MP4 = 'https://videos.example.org/direct.mp4'


@pytest.mark.parametrize('url, expected', [
    (VIDEO, ('youtube', 'M7lc1UVf-VE')),
    ('https://www.youtube.com/watch?v=M7lc1UVf-VE', ('youtube', 'M7lc1UVf-VE')),
    ('https://www.youtube.com/shorts/M7lc1UVf-VE?feature=share', ('youtube', 'M7lc1UVf-VE')),
    (MP4, ('mp4', MP4)),
    ('https://www.youtube.com.fake.test/watch?v=M7lc1UVf-VE', None),
    ('https://example.com:invalid/movie.mp4', None),
    ('https://192.168.0.1/movie.mp4', None),
    ('https://user@example.org/video.mp4', None),
    ('http://example.org/video.mp4', None),
])
def test_cinema_source_validation(url, expected):
    if expected:
        assert source_from_url(url) == expected
    else:
        with pytest.raises(ValueError):
            source_from_url(url)


async def test_seats_and_shared_playback(tmp_path, monkeypatch):
    db = Database(Path(tmp_path) / 'cinema.sqlite')
    await db.initialize()
    cinema = Cinema(None)
    presence = {}
    app = {'db': db, 'nora_lobby': presence, 'nora_cinema': cinema}
    sessions = {uid: str(uuid4()) for uid in (101, 102)}
    now = 1040.0
    monkeypatch.setattr('community_bot.nora_game_api.time', SimpleNamespace(monotonic=lambda: now))

    async def frame(uid, rev='?', entrance=True):
        x, z = ENTRANCE if entrance else (0, 0)
        return await lobby_snapshot(app, uid, {
            'session': sessions[uid], 'x': x, 'z': z, 'y': .017, 'heading': 0, 'cinema': rev,
        })

    class GameRequest(dict):
        async def json(self):
            return self.body

    for uid in sessions:
        await db.ensure_user(uid, telegram_name=f'Player {uid}')
        request = GameRequest(actor={'id': uid})
        request.app = app
        request.body = {'nickname': ('PlayerOne' if uid == 101 else 'PlayerTwo')}
        await register(request)
        request.body = {'shirt': 'white', 'pants': 'blue_slim', 'shoes': 'white_stripes'}
        await save_outfit(request)

    assert (await frame(101, entrance=False))['cinema']['seat'] is None
    first = (await frame(101))['cinema']
    assert first == {'seat': 0, 'revision': '', 'show': None}
    cinema.update(presence, 101, {'action': 'start', 'revision': '', 'url': VIDEO}, False, now)
    now += 5
    payload = await frame(102)
    second = payload['cinema']
    assert second['seat'] == 1
    assert payload['players'][0]['seat'] == 0
    assert second['show']['source'] == 'M7lc1UVf-VE'
    assert not second['show']['host']
    assert (payload['time'] - second['show']['changed']) / 1000 == 5
    revision = second['revision']
    with pytest.raises(ValueError, match='ведущего'):
        cinema.update(presence, 102, {'action': 'toggle', 'revision': revision}, False, now)
    cinema.update(presence, 101, {'action': 'toggle', 'revision': revision}, False, now)
    paused = (await frame(101, revision))['cinema']
    assert paused['show']['position'] == 5 and not paused['show']['playing']
    assert (await frame(101, paused['revision']))['cinema'] == {'seat': 0}
    with pytest.raises(ValueError, match='Сеанс изменился'):
        cinema.update(presence, 101, {'action': 'seek', 'revision': revision, 'position': 3}, False, now)
    cinema.update(presence, 101, {'action': 'seek', 'revision': paused['revision'], 'position': 12}, False, now)
    await lobby_snapshot(app, 101, {'session': sessions[101], 'leave': True})
    handoff = (await frame(102))['cinema']
    assert handoff['show']['host'] and handoff['show']['position'] == 12
    await lobby_snapshot(app, 102, {'session': sessions[102], 'leave': True})
    assert cinema.show is None


async def test_telegram_import_has_one_upload_and_seated_signed_requests(monkeypatch):
    assert is_command_message('Нора, в кино')
    storage = SimpleNamespace(config={'BUCKET': 'fixture'})
    cinema = Cinema(storage)
    uploads = []

    def upload(key, file):
        uploads.append((key, file.read()))

    async def download(_, *, destination, **options):
        destination.write(b'\x00\x00\x00\x14ftypisomfixtures')

    monkeypatch.setattr(cinema, '_upload', upload)
    monkeypatch.setattr(cinema, '_sign', lambda _: MP4)
    bot = SimpleNamespace(download=AsyncMock(side_effect=download))
    item = SimpleNamespace(mime_type='video/mp4', file_unique_id='unique', file_id='file', file_size=20)
    message = SimpleNamespace(video=item, document=None, has_protected_content=False, caption='Ролик', message_id=1)
    await cinema.import_clip(bot, message)
    cinema.next_import = 0
    await cinema.import_clip(bot, message)
    assert bot.download.await_count == len(uploads) == 1
    key = cinema.clip_list()[0]['id']
    item.file_size = MAX_FILE + 1
    with pytest.raises(ValueError, match='20 МБ'):
        await cinema.import_clip(bot, message)

    now = time.monotonic()
    presence = {101: (now, 'seated', {'seat': 0})}
    cinema.update(presence, 101, {'action': 'start', 'revision': '', 'clip': key}, False, now)
    snapshot = cinema.snapshot(presence, 101, '', now)
    assert snapshot['show']['source'] == ''
    assert key not in json.dumps(snapshot)

    class Request:
        method = 'GET'
        app = {'nora_cinema': cinema, 'nora_lobby': presence}
        query = {'session': 'seated', 'show': cinema.show.id}

        def __getitem__(self, _):
            return {'id': 101}

    response = await cinema_api(Request())
    assert json.loads(response.body) == {'url': MP4}
    req = Request()
    req.query = req.query | {'session': 'other'}
    with pytest.raises(ValueError, match='зайди'):
        await cinema_api(req)
