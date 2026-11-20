"""Isolated, HTTPS-only yt-dlp extractor and bounded media downloader."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from yt_dlp import YoutubeDL
from yt_dlp.networking import Request
from yt_dlp.networking import _urllib as transport
from yt_dlp.networking.exceptions import HTTPError, RequestError
from yt_dlp.utils import DownloadError

from community_bot.pet_progress import VIDEO_MAX_MB
from community_bot.pet_video import MUSIC_UNAVAILABLE
from community_bot.profile_track import MAX_TRACK_MB

MAX_BYTES = VIDEO_MAX_MB * 1024 * 1024
CDN_DOMAINS = (
    "tiktok.com", "tiktokcdn.com", "tiktokcdn-us.com", "tiktokv.com", "byteoversea.com",
    "ibytedtos.com", "ibyteimg.com", "muscdn.com", "instagram.com", "cdninstagram.com", "fbcdn.net",
    "facebook.com", "youtube.com", "youtubei.googleapis.com", "googlevideo.com", "ytimg.com",
)
MUSIC_APIS = ("api.music.yandex.ru", "api.music.yandex.net")
MUSIC_UNAVAILABLE_HTTP = {401, 403, 404, 451}
MUSIC_CDN = ("storage.mds.yandex.net", "mds.storage.yandex.net")
_getaddrinfo = socket.getaddrinfo


def check_url(url):
    parts = urlsplit(url)
    host = parts.hostname or ""
    if (parts.scheme != "https" or parts.username is not None or parts.password is not None
            or parts.port not in (None, 443)
            or not (host in ("music.yandex.ru", *MUSIC_APIS, *MUSIC_CDN)
                    or any(host == root or host.endswith("." + root) for root in CDN_DOMAINS))):
        raise ValueError("Video host is not allowed")


def public_addresses(host, port, family=0, type=0, proto=0, flags=0):
    check_url(f"https://{host}")
    # Return only verified IPv4 addresses directly to socket.create_connection.
    # HTTPS still uses the original hostname for SNI and certificate verification.
    rows = _getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
    if not rows or any(not ipaddress.ip_address(row[4][0]).is_global
                       or ipaddress.ip_address(row[4][0]).is_multicast for row in rows):
        raise OSError("Non-public video address")
    return rows


class SafeRedirect(transport.RedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class SafeYoutubeDL(YoutubeDL):
    def build_request_director(self, handlers, preferences=None):
        return super().build_request_director([transport.UrllibRH])

    def urlopen(self, req):
        check_url(req if isinstance(req, str) else req.url)
        return super().urlopen(req)


class VideoTooLarge(Exception):
    pass


class MusicUnavailable(Exception):
    pass


def download(url, path):
    check_url(url)
    options = {
        "quiet": True, "no_warnings": True, "noplaylist": True,
        "proxy": "", "socket_timeout": 12, "cachedir": False, "remote_components": [],
        "allowed_extractors": ["tiktok", r"vm\.tiktok", "instagram", "youtube"],
    }
    # Prefer compatible progressive formats within the cap when the source provides a size.
    capped = f"[filesize<={MAX_BYTES}]"
    base = "b[ext=mp4][protocol=https]"
    video = "bv[ext=mp4][protocol=https][vcodec^=avc1]"
    audio = "ba[ext=m4a][protocol=https]"
    options["format"] = f"{base}{capped}/{base}[filesize<=?{MAX_BYTES}]/{video}+{audio}/{base}"
    with SafeYoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
        if info.get("_type") not in (None, "video") or info.get("has_drm"):
            raise ValueError("Not a public video")
        if info.get("filesize", 0) and info["filesize"] > MAX_BYTES:
            raise VideoTooLarge
        formats = info.get("requested_formats")
        if not formats:
            stream(ydl, info, path, MAX_BYTES)
            return
        video, audio = formats
        video_path, audio_path = path.with_suffix(".video.mp4"), path.with_suffix(".audio.m4a")
        used = stream(ydl, video, video_path, MAX_BYTES)
        stream(ydl, audio, audio_path, MAX_BYTES - used)
        subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-protocol_whitelist", "file",
             "-f", "mov", "-i", str(video_path), "-f", "mov", "-i", str(audio_path), "-map", "0:v:0",
             "-map", "1:a:0", "-c", "copy", "-movflags", "+faststart", "-fs", str(MAX_BYTES), str(path)],
            check=True, timeout=15,
        )
        if path.stat().st_size >= MAX_BYTES:
            raise VideoTooLarge


def music_json(ydl, url):
    with ydl.urlopen(url) as response:
        limit = 1024 * 1024
        body = response.read(limit + 1)
        if len(body) > limit:
            raise ValueError("Oversized music response")
        result = json.loads(body)
        if not isinstance(result, dict):
            raise ValueError("Unexpected music response")
        return result


def music_variants(ydl, track_id):
    for host in MUSIC_APIS:
        api = f"https://{host}/tracks/{track_id}"
        try:
            variants = music_json(ydl, f"{api}/download-info").get("result")
            if not isinstance(variants, list):
                raise ValueError("Invalid music variant list")
        except HTTPError as error:
            error.close()
            if error.status in MUSIC_UNAVAILABLE_HTTP:
                raise MusicUnavailable from None
            if error.status < 500 or host == MUSIC_APIS[-1]:
                raise
        except (RequestError, OSError, ValueError):
            if host == MUSIC_APIS[-1]:
                raise
        else:
            return api, variants


def music_metadata(ydl, api):
    try:
        track = music_json(ydl, api)["result"][0]
        name = " ".join(track["title"].split())
        version = " ".join((track.get("version") or "").split())
        if version:
            name = f"{name} ({version})"
        artist = ", ".join(item["name"] for item in track.get("artists", []) if item.get("name"))
        return name[:120] or "Трек Яндекс Музыки", " ".join(artist.split())[:120]
    except HTTPError as error:
        error.close()
    except (RequestError, OSError, ValueError, KeyError, IndexError, TypeError, AttributeError):
        pass
    return "Трек Яндекс Музыки", ""


def download_music(url, path):
    match = re.fullmatch(r"/(?:album/[0-9]{1,16}/)?track/([0-9]{1,16})/?", urlsplit(url).path)
    if urlsplit(url).hostname != "music.yandex.ru" or not match:
        raise ValueError("Not a Yandex Music track")
    track_id = match[1]
    options = {"quiet": True, "proxy": "", "socket_timeout": 8, "cachedir": False, "remote_components": []}
    with SafeYoutubeDL(options) as ydl:
        api, variants = music_variants(ydl, track_id)
        candidate = min(
            (item for item in variants if isinstance(item, dict) and item.get("codec") == "mp3"
             and type(item.get("preview")) is bool and item.get("downloadInfoUrl")),
            key=lambda item: (item["preview"], -int(item.get("bitrateInKbps") or 0)), default=None,
        )
        if not candidate:
            raise MusicUnavailable
        source = urlsplit(candidate["downloadInfoUrl"])
        if source.hostname not in MUSIC_CDN:
            raise ValueError("Unrecognized music CDN")
        query = dict(parse_qsl(source.query))
        query["format"] = "json"
        location = music_json(ydl, urlunsplit(source._replace(query=urlencode(query), fragment="")))
        host, resource, stamp, salt = (location[key] for key in ("host", "path", "ts", "s"))
        if (host not in MUSIC_CDN or not re.fullmatch(r"/[A-Za-z0-9_./-]+", resource)
                or ".." in resource.split("/") or not re.fullmatch(r"[0-9a-fA-F]{1,32}", stamp)):
            raise ValueError("Invalid MP3 location")
        # Public CDN signature used by the upstream Yandex Music extractor.
        key = hashlib.md5(("XGRlBW9FXlekgbPrRHuSiA" + resource[1:] + salt).encode()).hexdigest()
        media = f"https://{host}/get-mp3/{key}/{stamp}{resource}?track-id={track_id}"
        stream(ydl, {"url": media}, path, MAX_TRACK_MB * 1024 * 1024, mp3=True)
        title, artist = music_metadata(ydl, api)
        path.with_suffix(".json").write_text(json.dumps({
            "title": title, "artist": artist, "preview": candidate["preview"],
        }), encoding="utf-8")


def stream(ydl, info, path, limit, *, mp3=False):
    with ydl.urlopen(Request(info["url"], headers=info.get("http_headers"))) as response, path.open("xb") as output:
        length = response.get_header("Content-Length")
        if length and int(length) > limit:
            raise VideoTooLarge
        prefix = response.read(12)
        if mp3:
            if len(prefix) < 12 or not (prefix.startswith(b"ID3") or prefix[0] == 255 and prefix[1] & 224 == 224):
                raise ValueError("The source did not return an MP3")
        elif len(prefix) < 12 or prefix[4:8] != b"ftyp":
            raise ValueError("The source did not return an MP4")
        size = len(prefix)
        if size > limit:
            raise VideoTooLarge
        output.write(prefix)
        while chunk := response.read(64 * 1024):
            size += len(chunk)
            if size > limit:
                raise VideoTooLarge
            output.write(chunk)
        if length and size != int(length):
            raise ValueError("Incomplete video")
        return size


def main():
    # These hooks are isolated to this short-lived subprocess, never the bot.
    socket.getaddrinfo = public_addresses
    transport.RedirectHandler = SafeRedirect
    try:
        url, path = sys.argv[1], Path(sys.argv[2])
        check_url(url)
        if path.suffix == ".mp3":
            download_music(url, path)
        else:
            download(url, path)
    except VideoTooLarge:
        return 2
    except MusicUnavailable:
        return MUSIC_UNAVAILABLE
    except HTTPError as error:
        error.close()
        if path.suffix == ".mp3" and error.status in MUSIC_UNAVAILABLE_HTTP:
            return MUSIC_UNAVAILABLE
        return 1
    except (
        DownloadError, RequestError, OSError, ValueError, KeyError, TypeError, IndexError, subprocess.SubprocessError,
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
