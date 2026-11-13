"""Telegram Rich Message for the seasonal dedzytwo playlist."""
import json
import logging
from dataclasses import dataclass, replace
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest, TelegramNotFound
from aiogram.types import (
    FSInputFile,
    InputMediaAudio,
    InputMediaPhoto,
    InputRichBlockAudio,
    InputRichBlockButtons,
    InputRichBlockDetails,
    InputRichBlockDivider,
    InputRichBlockParagraph,
    InputRichBlockPhoto,
    InputRichBlockSectionHeading,
    InputRichMessage,
    RichBlockAudio,
    RichBlockPhoto,
    RichMessageButton,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Track:
    media: str | FSInputFile
    title: str
    performer: str | None = None
    duration: int | None = None


def load_tracks(manifest, original):
    tracks = [original]
    try:
        entries = json.loads(manifest.read_text(encoding='utf-8-sig'))
        if not isinstance(entries, list) or len(entries) > 48:
            raise ValueError('Expected a list of up to 48 additional tracks')
        for entry in entries:
            track = Track(**entry)
            if (
                not isinstance(track.media, str) or not track.media.strip()
                or not isinstance(track.title, str) or not 0 < len(track.title) <= 128
                or (track.performer is not None and (
                    not isinstance(track.performer, str) or len(track.performer) > 128
                ))
                or (track.duration is not None and (
                    type(track.duration) is not int or track.duration <= 0
                ))
            ):
                raise ValueError('Invalid track metadata')
            if track.media.startswith('./'):
                filename = track.media[2:]
                if Path(filename).name != filename or Path(filename).suffix.lower() != '.mp3':
                    raise ValueError('Expected an MP3 beside the playlist manifest')
                media = manifest.parent / filename
                if not media.is_file():
                    raise ValueError('Missing playlist MP3')
                track = replace(track, media=FSInputFile(media))
            tracks.append(track)
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError):
        logger.warning('Invalid dedzytwo playlist manifest; using the original track')
        return [original]
    return tracks


def playlist_message(cover, tracks, username):
    return InputRichMessage(blocks=[
        InputRichBlockPhoto(photo=InputMediaPhoto(media=cover)),
        InputRichBlockParagraph(text='NORA / MUSIC'),
        InputRichBlockSectionHeading(text='dedzytwo — музыкальная подборка', size=2),
        InputRichBlockDetails(summary='Старое ≠ бесполезное', is_open=True, blocks=[
            InputRichBlockParagraph(
                text='Привычные краски в особой палитре — невероятные мэшапы от dedzytwo, '
                     'начинающего автора из Санкт-Петербурга, теперь в Норе!',
            ),
        ]),
        InputRichBlockDivider(),
        *(InputRichBlockAudio(audio=InputMediaAudio(
            media=track.media, title=track.title, performer=track.performer, duration=track.duration,
        )) for track in tracks),
        InputRichBlockDivider(),
        InputRichBlockButtons(buttons=[
            RichMessageButton(text='НОРА', url=f'https://t.me/{username}?startapp'),
        ]),
    ])


class PlaylistDelivery:
    def __init__(self, bot, cover, tracks):
        self.bot = bot
        self.cover = cover
        self.tracks = tracks
        self.rich_available = True

    async def send(self, recipient):
        if self.rich_available:
            username = (await self.bot.me()).username
            try:
                sent = await self.bot.send_rich_message(
                    recipient, rich_message=playlist_message(self.cover, self.tracks, username),
                )
            except TelegramNotFound:
                self.rich_available = False
            except TelegramBadRequest as error:
                reason = error.message.lower().replace('_', ' ')
                if not any(marker in reason for marker in (
                    'rich message', 'rich block', 'method not found', 'unknown method',
                )):
                    raise
                self.rich_available = False
            else:
                if sent.rich_message:
                    # Reuse Telegram's file IDs for the second recipient in this request.
                    blocks = sent.rich_message.blocks
                    photos = [block.photo for block in blocks if isinstance(block, RichBlockPhoto)]
                    audios = [block.audio for block in blocks if isinstance(block, RichBlockAudio)]
                    if photos and photos[0]:
                        self.cover = photos[0][-1].file_id
                    if len(audios) == len(self.tracks):
                        self.tracks = [
                            Track(audio.file_id, track.title, track.performer, track.duration)
                            for audio, track in zip(audios, self.tracks, strict=True)
                        ]
                return

        original = self.tracks[0]
        await self.bot.send_audio(
            recipient, original.media, title=original.title, performer=original.performer,
            caption='Старое ≠ бесполезное\nSEASON 1 • BLOODY NORA\nhttps://t.me/thededzzyDJ',
        )
