import asyncio
import threading
import time
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

from PIL import Image

from community_bot.media_cache import MediaImages
from community_bot.miniapp import normalized_photo


def photo():
    output = BytesIO()
    with Image.new('RGB', (200, 100), 'red') as image:
        image.save(output, 'JPEG')
    return output.getvalue()


async def test_s3_hit_skips_telegram_and_decoder_and_thumb_has_separate_key(monkeypatch):
    raw = photo()
    bot = SimpleNamespace(download=AsyncMock())
    service = MediaImages(bot)
    service.config = dict.fromkeys(service.config, 'configured')
    objects = {}
    def download(file_id, destination):
        destination.write(raw)
    bot.download.side_effect = download
    monkeypatch.setattr(service, '_get', lambda key: objects.get(key))
    monkeypatch.setattr(service, '_put', lambda key, value: objects.__setitem__(key, value))
    full = await service.photo('private-telegram-id')
    assert await service.photo('private-telegram-id') == full
    assert bot.download.await_count == 1
    thumb = await service.photo('private-telegram-id', thumb=True)
    assert Image.open(BytesIO(thumb)).size == (96, 48)
    assert len(objects) == 2
    assert all('private-telegram-id' not in key for key in objects)


async def test_storage_outage_falls_back_and_has_cooldown(monkeypatch, caplog):
    raw = photo()
    async def download(file_id, destination):
        destination.write(raw)
    service = MediaImages(SimpleNamespace(download=download))
    service.config = dict.fromkeys(service.config, 'secret-not-for-logs')
    calls = []
    def unavailable(key):
        calls.append(key)
        raise OSError('secret-not-for-logs')
    monkeypatch.setattr(service, '_get', unavailable)
    assert await service.photo('first')
    assert await service.photo('second')
    assert len(calls) == 1
    assert 'secret-not-for-logs' not in caplog.text


async def test_parallel_decoders_are_serialized(monkeypatch):
    from community_bot import miniapp

    service = MediaImages(None)
    active = 0
    peak = 0
    lock = threading.Lock()
    def decode(raw):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(.02)
        with lock:
            active -= 1
        return raw
    monkeypatch.setattr(miniapp, 'normalized_photo', decode)
    assert await asyncio.gather(*(service.normalize(b'image') for _ in range(5))) == [b'image'] * 5
    assert peak == 1


def test_large_jpeg_is_reduced_and_exif_orientation_preserved():
    output = BytesIO()
    with Image.new('RGB', (4000, 2000), 'blue') as image:
        exif = Image.Exif()
        exif[274] = 6
        image.save(output, 'JPEG', exif=exif)
    result = normalized_photo(output.getvalue())
    with Image.open(BytesIO(result)) as image:
        assert image.size == (800, 1600)
        assert image.mode == 'RGB'


def test_s3_sdk_requests_and_missing_key():
    from botocore.response import StreamingBody
    from botocore.stub import Stubber

    service = MediaImages(None)
    service.config = dict(ENDPOINT='https://storage.example.test', BUCKET='test-bucket', REGION='auto',
                          ACCESS_KEY_ID='test-access', SECRET_ACCESS_KEY='test-secret')
    client = service._client()
    with Stubber(client) as stub:
        stub.add_client_error('get_object', service_error_code='NoSuchKey', http_status_code=404,
                              expected_params={'Bucket': 'test-bucket', 'Key': 'missing'})
        assert service._get('missing') is None
        stream = BytesIO(b'cached')
        body = StreamingBody(stream, 6)
        stub.add_response('get_object', {'Body': body}, {'Bucket': 'test-bucket', 'Key': 'image'})
        assert service._get('image') == b'cached'
        assert stream.closed
        stub.add_response('put_object', {}, {'Bucket': 'test-bucket', 'Key': 'image', 'Body': b'jpeg',
                                             'ContentType': 'image/jpeg'})
        service._put('image', b'jpeg')
        stub.assert_no_pending_responses()
    client.close()


async def test_cancellation_waits_for_decoder_before_releasing_slot(monkeypatch):
    from community_bot import miniapp

    started, finish = threading.Event(), threading.Event()
    def decode(raw):
        started.set()
        finish.wait(timeout=2)
        return raw
    monkeypatch.setattr(miniapp, 'normalized_photo', decode)
    service = MediaImages(None)
    task = asyncio.create_task(service.normalize(b'image'))
    assert await asyncio.to_thread(started.wait, 2)
    task.cancel()
    await asyncio.sleep(.01)
    assert service.gate.locked()
    finish.set()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert not service.gate.locked()
