"""Private S3 cache of Telegram image derivatives; Telegram remains the source."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from io import BytesIO

logger = logging.getLogger(__name__)
MAX_IMAGE = 5 * 1024 * 1024


async def _thread(operation, *args):
    task = asyncio.create_task(asyncio.to_thread(operation, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # A cancelled HTTP request must not release the decoder slot while its thread runs.
        try:
            await task
        finally:
            raise


class MediaImages:
    def __init__(self, bot):
        self.bot = bot
        self.gate = asyncio.Lock()
        self.client = None
        self.retry_after = 0.0
        self.config = {name: os.getenv('MEDIA_S3_' + name, '').strip() for name in (
            'ENDPOINT', 'BUCKET', 'REGION', 'ACCESS_KEY_ID', 'SECRET_ACCESS_KEY',
        )}

    def _client(self):
        if self.client is None:
            # The SDK and its schemas are loaded only when S3 is configured and used.
            import boto3
            from botocore.config import Config

            self.client = boto3.client(
                's3', endpoint_url=self.config['ENDPOINT'], region_name=self.config['REGION'],
                aws_access_key_id=self.config['ACCESS_KEY_ID'],
                aws_secret_access_key=self.config['SECRET_ACCESS_KEY'],
                config=Config(connect_timeout=2, read_timeout=3, retries={'max_attempts': 0},
                              signature_version='s3v4', request_checksum_calculation='when_required',
                              response_checksum_validation='when_required',
                              s3={'addressing_style': 'virtual'}),
            )
        return self.client

    def _get(self, key):
        from botocore.exceptions import ClientError

        try:
            result = self._client().get_object(Bucket=self.config['BUCKET'], Key=key)
        except ClientError as error:
            if error.response.get('Error', {}).get('Code') in {'NoSuchKey', '404'}:
                return None
            raise
        body = result['Body']
        try:
            raw = body.read(MAX_IMAGE + 1)
            return raw if len(raw) <= MAX_IMAGE else None
        finally:
            body.close()

    def _put(self, key, raw):
        self._client().put_object(Bucket=self.config['BUCKET'], Key=key, Body=raw, ContentType='image/jpeg')

    async def _storage(self, operation, *args):
        if not all(self.config.values()) or time.monotonic() < self.retry_after:
            return None
        try:
            # Import and network I/O both stay off the asyncio event loop.
            return await _thread(operation, *args)
        except Exception:
            self.retry_after = time.monotonic() + 60
            logger.warning('Media S3 unavailable; using Telegram for 60 seconds')
            return None

    async def photo(self, file_id, *, thumb=False):
        from community_bot.miniapp import normalized_photo

        key = 'images/v1/' + hashlib.sha256(file_id.encode()).hexdigest() + ('-thumb' if thumb else '') + '.jpg'
        # Bound downloads and image decoders, and recheck S3 after waiting for another request.
        async with self.gate:
            raw = await self._storage(self._get, key)
            if raw is not None:
                return raw
            output = BytesIO()
            await self.bot.download(file_id, destination=output)
            raw = await _thread(normalized_photo, output.getvalue())
            if thumb:
                from community_bot.social_profiles import thumbnail

                raw = await _thread(thumbnail, raw)
            await self._storage(self._put, key, raw)
            return raw

    async def normalize(self, raw):
        from community_bot.miniapp import normalized_photo

        async with self.gate:
            return await _thread(normalized_photo, raw)

    async def close(self):
        if self.client is not None:
            await asyncio.to_thread(self.client.close)


def images(request):
    return request.app.get('media_images') or MediaImages(request.app.get('bot'))
