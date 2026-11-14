"""Isolated, HTTPS-only yt-dlp extractor and bounded MP4 downloader."""
from __future__ import annotations

import ipaddress
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from yt_dlp import YoutubeDL
from yt_dlp.networking import Request
from yt_dlp.networking import _urllib as transport
from yt_dlp.networking.exceptions import RequestError
from yt_dlp.utils import DownloadError

from community_bot.pet_progress import VIDEO_MAX_MB

MAX_BYTES = VIDEO_MAX_MB * 1024 * 1024
CDN_DOMAINS = (
    "tiktok.com", "tiktokcdn.com", "tiktokcdn-us.com", "tiktokv.com", "byteoversea.com",
    "ibytedtos.com", "ibyteimg.com", "muscdn.com", "instagram.com", "cdninstagram.com", "fbcdn.net",
    "facebook.com", "youtube.com", "youtubei.googleapis.com", "googlevideo.com", "ytimg.com",
)
_getaddrinfo = socket.getaddrinfo


def check_url(url):
    parts = urlsplit(url)
    host = parts.hostname or ""
    if (parts.scheme != "https" or parts.username is not None or parts.password is not None
            or parts.port not in (None, 443)
            or not any(host == root or host.endswith("." + root) for root in CDN_DOMAINS)):
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


def stream(ydl, info, path, limit):
    with ydl.urlopen(Request(info["url"], headers=info.get("http_headers"))) as response, path.open("xb") as output:
        length = response.get_header("Content-Length")
        if length and int(length) > limit:
            raise VideoTooLarge
        prefix = response.read(12)
        if len(prefix) < 12 or prefix[4:8] != b"ftyp":
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
        download(sys.argv[1], Path(sys.argv[2]))
    except VideoTooLarge:
        return 2
    except (DownloadError, RequestError, OSError, ValueError, KeyError, subprocess.SubprocessError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
