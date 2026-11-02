"""Render a ten-second NORA Mini App promo from repository artwork.

Run with a Python environment containing Pillow and imageio-ffmpeg.
All on-screen sample interface cards are illustrative; no user data is used.
"""

from __future__ import annotations

import math
import struct
import subprocess
import tempfile
import wave
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).with_name("nora-miniapp-tiktok-10s.mp4")
W, H, FPS = 540, 960, 30
RED = (243, 40, 67)
WHITE = (247, 245, 241)
MUTED = (183, 183, 191)
FONT = ROOT / "assets/fonts/Inter-Bold.ttf"
PIXEL = ROOT / "assets/fonts/Monocraft.ttf"

SCENES = [
    (1.35, "home/gathering-v1.webp", "СВОИ", "РЯДОМ.", "NORA  /  MINI APP", ""),
    (1.75, "home/gathering-v1.webp", "НАХОДИ", "СВОИХ.", "КОММЬЮНИТИ", "Друзья  ·  чат  ·  общение"),
    (1.85, "covers/mafia.jpg", "ИГРАЙ", "ВМЕСТЕ.", "ИГРЫ", "Мафия  ·  Морской бой  ·  Ракета"),
    (1.85, "covers/events.jpg", "ВСТРЕЧАЙСЯ", "ВЖИВУЮ.", "СОБЫТИЯ", "Анонсы  ·  запись  ·  встречи"),
    (1.75, "covers/shop.jpg", "ТВОЯ", "НОРА.", "ПРОФИЛЬ + МАГАЗИН", "Печеньки  ·  покупки  ·  профиль"),
    (1.45, "branding/nora-liquid-v1.webp", "NORA", "", "СВОИ РЯДОМ", "Мини-приложение в Telegram"),
]
STARTS = [0.0]
for duration, *_ in SCENES:
    STARTS.append(STARTS[-1] + duration)


def font(size: int, pixel: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(PIXEL if pixel else FONT), size)


def fit(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    w, h = size
    scale = max(w / image.width, h / image.height)
    resized = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
    x = (resized.width - w) // 2
    y = (resized.height - h) // 2
    return resized.crop((x, y, x + w, y + h))


def eased(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return 1 - (1 - value) ** 3


def draw_text(d: ImageDraw.ImageDraw, xy: tuple[int, int], value: str, size: int,
              color: tuple[int, int, int] = WHITE, pixel: bool = False) -> None:
    d.text(xy, value, font=font(size, pixel), fill=color, stroke_width=0)


def rounded_image(image: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", image.size)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, image.width - 1, image.height - 1), radius, fill=255)
    image = image.copy().convert("RGBA")
    image.putalpha(mask)
    return image


def make_background(path: str) -> Image.Image:
    source = Image.open(ROOT / "assets" / path).convert("RGB")
    bg = fit(source, (W + 70, H + 70)).filter(ImageFilter.GaussianBlur(22))
    bg = ImageEnhance.Brightness(bg).enhance(0.28)
    return bg


def make_card(idx: int, path: str, label: str, detail: str) -> Image.Image:
    card = Image.new("RGBA", (460, 510), (24, 24, 27, 255))
    source = Image.open(ROOT / "assets" / path).convert("RGB")
    art = fit(source, (460, 390))
    if idx == 1:
        art = ImageEnhance.Contrast(art).enhance(1.12)
    card.paste(art, (0, 0))
    d = ImageDraw.Draw(card)
    d.rectangle((0, 360, 460, 510), fill=(22, 22, 25))
    d.rounded_rectangle((20, 382, 440, 491), radius=19, fill=(35, 35, 39), outline=(67, 67, 72), width=1)
    d.ellipse((35, 402, 48, 415), fill=RED)
    draw_text(d, (59, 394), label, 21)
    draw_text(d, (36, 433), detail, 14, MUTED)
    d.rounded_rectangle((367, 432, 423, 475), radius=13, fill=RED)
    draw_text(d, (386, 435), "↗", 25)
    return rounded_image(card, 28)


BGS = [make_background(scene[1]) for scene in SCENES]
CARDS = [make_card(i, scene[1], scene[4], scene[5]) for i, scene in enumerate(SCENES[:5])]


def scene_frame(idx: int, t: float) -> Image.Image:
    duration, _, first, second, label, detail = SCENES[idx]
    p = min(1.0, t / duration)
    shift = round(25 * p)
    frame = BGS[idx].crop((15 + shift, 12, 15 + shift + W, 12 + H)).copy()
    d = ImageDraw.Draw(frame, "RGBA")
    d.rectangle((0, 0, W, H), fill=(9, 9, 11, 55))
    d.ellipse((-170 + int(50 * p), 285, 270 + int(50 * p), 725), fill=(220, 17, 50, 28))
    d.text((40, 50), "NORA", font=font(19, True), fill=WHITE)
    d.text((397, 54), "MINI APP", font=font(11), fill=MUTED)
    d.rounded_rectangle((40, 88, 500, 92), radius=2, fill=(84, 84, 89, 180))
    d.rounded_rectangle((40, 88, 40 + round(460 * (STARTS[idx] + t) / 10), 92), radius=2, fill=RED)

    if idx == 5:
        pulse = 1 + 0.025 * math.sin(2 * math.pi * 2.2 * t)
        logo = Image.open(ROOT / "assets/branding/nora-liquid-v1.webp").convert("RGB")
        # Isolate the O from its black poster and let it fill the outro.
        alpha = logo.getchannel("R").point(lambda v: 0 if v < 150 else min(255, (v - 150) * 4))
        bounds = alpha.getbbox()
        assert bounds is not None
        logo = logo.crop(bounds).resize((round(205 * pulse), round(205 * pulse)), Image.Resampling.LANCZOS)
        alpha = alpha.crop(bounds).resize(logo.size, Image.Resampling.LANCZOS)
        logo = logo.convert("RGBA")
        logo.putalpha(alpha)
        frame.paste(logo, ((W - logo.width) // 2, 310), logo)
        draw_text(d, (40, 650), first, 94, RED, True)
        draw_text(d, (43, 769), label, 25, WHITE)
        draw_text(d, (43, 812), detail, 21, MUTED)
        return frame

    enter = eased(min(1.0, t / 0.38))
    title_y = round(160 + (1 - enter) * 35)
    d.text((40, title_y), first, font=font(44 if len(first) > 9 else 57), fill=WHITE)
    d.text((40, title_y + 62), second, font=font(58), fill=RED)
    card = CARDS[idx]
    bob = round(8 * math.sin(p * math.pi * 2))
    scale = 0.92 + 0.08 * eased(min(1, t / 0.42)) + 0.015 * p
    sw, sh = round(card.width * scale), round(card.height * scale)
    animated = card.resize((sw, sh), Image.Resampling.BICUBIC)
    x = (W - sw) // 2
    y = round(346 + (1 - enter) * 70 + bob)
    shadow = Image.new("RGBA", (sw + 34, sh + 34))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle((17, 17, sw + 17, sh + 17), radius=35, fill=(0, 0, 0, 170))
    shadow = shadow.filter(ImageFilter.GaussianBlur(15))
    frame.paste(shadow, (x - 17, y - 4), shadow)
    frame.paste(animated, (x, y), animated)
    if idx == 0:
        d = ImageDraw.Draw(frame, "RGBA")
        d.rounded_rectangle((40, 845, 500, 891), radius=23, fill=(*RED, 245))
        draw_text(d, (78, 853), "ТВОЯ ИСТОРИЯ НАЧИНАЕТСЯ ЗДЕСЬ", 16)
    return frame


def render_frame(n: int) -> Image.Image:
    time = n / FPS
    idx = max(i for i in range(len(SCENES)) if STARTS[i] <= time)
    local = time - STARTS[idx]
    frame = scene_frame(idx, local)
    transition = 0.19
    if idx < len(SCENES) - 1 and local > SCENES[idx][0] - transition:
        next_frame = scene_frame(idx + 1, max(0, local - SCENES[idx][0] + transition))
        factor = eased((local - SCENES[idx][0] + transition) / transition)
        frame = Image.blend(frame, next_frame, factor)
    return frame


def make_audio(path: Path) -> None:
    rate = 44100
    beat = 60 / 140
    boundaries = STARTS[1:-1]
    seed = 0x12345678
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        buf = bytearray()
        for n in range(rate * 10):
            t = n / rate
            phase = t % beat
            kick = math.sin(2 * math.pi * (65 - 27 * min(1, phase / 0.22)) * phase) * math.exp(-phase * 20)
            hat_phase = t % (beat / 2)
            seed ^= (seed << 13) & 0xFFFFFFFF
            seed ^= seed >> 17
            seed ^= (seed << 5) & 0xFFFFFFFF
            noise = ((seed & 65535) / 32768) - 1
            hat = noise * math.exp(-hat_phase * 65) * 0.07
            bass = math.sin(2 * math.pi * 55 * t) * (0.12 if phase < beat * 0.72 else 0)
            clap_phase = (t + beat) % (beat * 2)
            clap = noise * math.exp(-clap_phase * 38) * (0.13 if clap_phase < 0.12 else 0)
            whoosh = 0.0
            for cut in boundaries:
                delta = t - cut
                if -0.12 < delta < 0.16:
                    whoosh += noise * (1 - abs(delta) / 0.16) * 0.13
            fade = min(1, t / 0.12, (10 - t) / 0.35)
            sample = max(-1, min(1, (0.58 * kick + hat + bass + clap + whoosh) * fade))
            buf.extend(struct.pack("<h", round(sample * 25000)))
            if len(buf) > 131072:
                out.writeframes(buf)
                buf.clear()
        out.writeframes(buf)


def render() -> None:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="nora-promo-") as tmp:
        audio = Path(tmp) / "beat.wav"
        make_audio(audio)
        command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo",
                   "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "pipe:0",
                   "-i", str(audio), "-vf", "scale=1080:1920:flags=lanczos,format=yuv420p",
                   "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-r", str(FPS),
                   "-c:a", "aac", "-b:a", "192k", "-t", "10", "-movflags", "+faststart", str(OUT)]
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            assert proc.stdin is not None
            for n in range(FPS * 10):
                proc.stdin.write(render_frame(n).convert("RGB").tobytes())
            proc.stdin.close()
            assert proc.stderr is not None
            error = proc.stderr.read().decode(errors="replace")
            if proc.wait() != 0:
                raise RuntimeError(error)
        finally:
            if proc.poll() is None:
                proc.kill()
    print(OUT)


if __name__ == "__main__":
    render()
