"""Resolve and download Yandex tracks in a disposable process."""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

MAX_FILE_BYTES = 48 * 1024 * 1024


class SongError(Exception):
    """Expected configuration or provider failure safe to show in chat."""


@dataclass(frozen=True)
class Song:
    id: str
    album_id: str | None
    title: str
    artist: str
    duration: int
    cover: str | None = None

    @property
    def url(self) -> str:
        if self.album_id:
            return f"https://music.yandex.ru/album/{self.album_id}/track/{self.id}"
        return f"https://music.yandex.ru/track/{self.id}"


def resolve_metadata(track_id: str, album_id: str | None, cookie_file: str) -> Song:
    """Reuse the same modern Yandex extractor as actual audio downloads.

    The standalone /tracks request previously lacked web-client headers and
    could return an empty result even when the track was playable.
    """
    import yt_dlp

    canonical_url = (
        f"https://music.yandex.ru/album/{album_id}/track/{track_id}"
        if album_id else f"https://music.yandex.ru/track/{track_id}"
    )
    options = {
        "quiet": True,
        "logtostderr": True,
        "no_warnings": True,
        "ignoreerrors": False,
        "noplaylist": True,
        "skip_download": True,
        "cookiefile": str(cookie_file),
        "socket_timeout": 20,
        "retries": 1,
        "extractor_retries": 1,
        "cachedir": False,
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(canonical_url, download=False)
    except Exception as exc:
        raise SongError("Не удалось получить песню по ссылке. Проверь доступ к треку в Яндексе.") from exc

    if not isinstance(info, dict) or str(info.get("id") or "") != track_id:
        raise SongError("Яндекс не вернул данные нужной песни по этой ссылке.")
    title = info.get("title")
    if not isinstance(title, str) or not title.strip():
        raise SongError("Яндекс не вернул название песни по ссылке.")

    artist = info.get("artist") or info.get("performer") or "Неизвестный исполнитель"
    album_from_info = str(info.get("album_id") or "")
    if not album_from_info.isdecimal():
        album_from_info = ""
    try:
        duration = max(0, int(float(info.get("duration") or 0)))
    except (ValueError, TypeError):
        duration = 0
    return Song(track_id, album_id or album_from_info or None,
                title.strip()[:180], str(artist)[:180], duration)


def is_full_track(actual: float, expected: int) -> bool:
    """Reject 13–30 second preview files masquerading as full tracks."""
    if actual <= 0:
        return False
    if expected > 0:
        return actual >= max(1, expected * 0.72)
    return actual >= 40


def download_audio(song: Song, directory: str, cookie_file: str, *, max_bytes=MAX_FILE_BYTES) -> str:
    import yt_dlp
    from mutagen.mp3 import MP3

    options = {
        "quiet": True,
        "logtostderr": True,
        "no_warnings": True,
        "ignoreerrors": False,
        "noplaylist": True,
        "outtmpl": str(Path(directory) / "%(id)s.%(ext)s"),
        "format": "bestaudio[ext=mp3]",
        "cookiefile": cookie_file,
        "socket_timeout": 20,
        "retries": 2,
        "max_filesize": max_bytes,
        "cachedir": False,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        ydl.extract_info(song.url, download=True)
    files = list(Path(directory).glob("*.mp3"))
    if len(files) != 1:
        raise SongError("Яндекс не отдал MP3. Возможно, доступен только другой формат.")
    audio = files[0]
    if not 0 < audio.stat().st_size <= max_bytes:
        raise SongError("Файл превышает лимит размера Telegram.")
    try:
        actual = MP3(str(audio)).info.length
    except Exception as exc:
        raise SongError("Не удалось проверить полученный MP3.") from exc
    if not is_full_track(actual, song.duration):
        raise SongError("Яндекс отдал только фрагмент трека. Проверь подписку и сессию.")
    return str(audio)


def main() -> None:
    request = json.load(sys.stdin)
    try:
        if request["operation"] == "metadata":
            song = resolve_metadata(request["track_id"], request["album_id"], request["cookie_file"])
            result = asdict(song)
        else:
            result = Path(download_audio(
                Song(**request["song"]), request["directory"], request["cookie_file"], max_bytes=request["max_bytes"],
            )).name
    except SongError as exc:
        print(json.dumps({"error": str(exc)}))
    else:
        print(json.dumps({"result": result}))


if __name__ == "__main__":
    main()
