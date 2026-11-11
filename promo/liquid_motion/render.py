"""Deterministic 20-second motion film made from the owner's actual screenshots.

Install requirements into a separate renderer environment. No bot is started.
python render.py --attachments PATH [--preview | --render]
"""

from __future__ import annotations

import argparse
import math
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".render-deps"))
import imageio_ffmpeg  # noqa: E402
import numpy as np  # noqa: E402
import skia  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

W, H, FPS = 1080, 1920, 60
DURATION, AUDIO_START, DROP = 20.0, 20.74, 4.0
BEAT = 60 / 155
CUTS = [4 + BEAT * n for n in (0, 6, 12, 18, 24, 30, 36)]
OUT = Path(__file__).parent
CREAM, RED, CYAN = "#fff3e2", "#ff1755", "#00c8ed"
WHITE = "#ffffff"
IMAGES = {}
FONTS = {}
SAMPLING = skia.SamplingOptions(skia.FilterMode.kLinear)


def clamp(x, a=0.0, b=1.0):
    return min(b, max(a, x))


def ease(x):
    x = clamp(x)
    return x * x * x * (x * (x * 6 - 15) + 10)


def out(x):
    return 1 - (1 - clamp(x)) ** 4


def color(c, a=1):
    c = c.lstrip("#")
    return skia.ColorSetARGB(round(clamp(a) * 255), *[int(c[i : i + 2], 16) for i in (0, 2, 4)])


def paint(c=WHITE, a=1, stroke=0):
    p = skia.Paint(Color=color(c, a), AntiAlias=True)
    if stroke:
        p.setStyle(skia.Paint.kStroke_Style)
        p.setStrokeWidth(stroke)
    return p


def rect(x, y, w, h):
    return skia.Rect.MakeXYWH(x, y, w, h)


def roundrect(c, x, y, w, h, r, fill=WHITE, a=1, stroke=0):
    c.drawRoundRect(rect(x, y, w, h), r, r, paint(fill, a, stroke))


def text(c, s, x, y, size=50, fill=CREAM, a=1, center=False):
    if size not in FONTS:
        f = skia.Font(skia.Typeface.MakeFromFile(str(ROOT / "assets/fonts/Inter-Bold.ttf")), size)
        f.setSubpixel(True)
        FONTS[size] = f
    f = FONTS[size]
    if center:
        x -= f.measureText(s) / 2
    c.drawString(s, x, y, f, paint(fill, a))


def image(c, img, x, y, w, h, a=1, src=None):
    p = skia.Paint(Alphaf=clamp(a), AntiAlias=True)
    if src:
        c.drawImageRect(img, rect(*src), rect(x, y, w, h), SAMPLING, p)
    else:
        c.drawImageRect(img, rect(x, y, w, h), SAMPLING, p)


def load_images(attachments):
    for k, n in [("home", 2), ("shop", 3), ("community", 4), ("leaderboard", 5), ("events", 6), ("profile", 7)]:
        p = next(attachments.glob(f"{n}-*.jpg"))
        im = Image.open(p).convert("RGB").resize((948, 2048), Image.Resampling.LANCZOS)
        IMAGES[k] = skia.Image.fromarray(np.array(im.convert("RGBA")), colorType=skia.ColorType.kRGBA_8888_ColorType)
    # Use the exact SVG contours already used by NORA's actual startup wordmark.
    js = (ROOT / "community_bot/web/intro.js").read_text(encoding="utf-8")
    outline = re.search(r"const outline = '([^']+)'", js).group(1)
    block = js.split("const letters = ", 1)[1].split(";", 1)[0]
    letters = "".join(re.findall(r"'([^']*)'", block))
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="430" viewBox="90 260 1100 430">'
        '<g stroke="#08090e" stroke-width="13" stroke-linejoin="round">'
        f'<path transform="translate(34 90)" fill="#00c8ed" d="{outline}"/>'
        f'<path transform="translate(24 62)" fill="#ff09ae" d="{outline}"/>'
        f'<path transform="translate(12 32)" fill="#ffd500" d="{outline}"/>'
        f'<path fill="#08090e" d="{outline}"/></g>'
        '<g stroke="#08090e" stroke-width="15" stroke-linejoin="round" paint-order="stroke fill">'
        f"{letters}</g></svg>"
    )
    IMAGES["logo"] = skia.SVGDOM.MakeFromStream(skia.MemoryStream(svg.encode()))
    # Cached soft frame shadow: expensive blur is calculated once.
    sf = skia.Surface(1020, 1660)
    sc = sf.getCanvas()
    p = paint("#000000", 0.85)
    p.setMaskFilter(skia.MaskFilter.MakeBlur(skia.BlurStyle.kNormal_BlurStyle, 26))
    sc.drawRoundRect(rect(60, 55, 900, 1500), 68, 68, p)
    IMAGES["shadow"] = sf.makeImageSnapshot()


def logo(c, cx, cy, width, a=1):
    c.saveLayer(None, skia.Paint(Alphaf=clamp(a)))
    c.translate(cx - width / 2, cy - width * 430 / 1100 / 2)
    c.scale(width / 1100, width / 1100)
    IMAGES["logo"].render(c)
    c.restore()


def glow(c, x, y, r, c1, a):
    sh = skia.GradientShader.MakeRadial((x, y), r, [color(c1, a), color(c1, 0)], [0, 1])
    c.drawCircle(x, y, r, skia.Paint(Shader=sh, AntiAlias=True))


def background(c, t):
    c.clear(color("#090a10"))
    pulse = math.exp(-((t - DROP) % BEAT) * 12) if t >= DROP else 0.1
    glow(c, 170 + math.sin(t * 0.34) * 180, 650 + math.sin(t * 0.45) * 260, 970, RED, 0.17 + 0.035 * pulse)
    glow(c, 1000 + math.cos(t * 0.4) * 120, 1330, 830, "#4032a4", 0.19)
    glow(c, 700, 2100, 650, CYAN, 0.09)
    # Large optical contours: restrained specular arcs, drifting behind the UI.
    for j in range(3):
        c.save()
        c.translate(610 + 50 * math.sin(t * 0.3), 1000)
        c.rotate(-28 + t * 2 + j * 12)
        rr = rect(-500 - j * 100, -850 - j * 110, 1000 + j * 200, 1700 + j * 220)
        p = paint("#a9b6d8", 0.045 + j * 0.013, 2)
        c.drawOval(rr, p)
        c.restore()
    for j in range(22):
        x = (j * 331.7 + 17) % 1080
        y = (j * 417.1 - t * (9 + j % 4 * 4)) % 1920
        c.drawCircle(x, y, 1.1 + (j % 3) * 0.35, paint("#e2dff5", 0.12))


def glass(c, x, y, w, h, r=45, a=1):
    roundrect(c, x, y, w, h, r, "#15151f", 0.8 * a)
    sh = skia.GradientShader.MakeLinear(
        [(x, y), (x + w, y + h)],
        [color("#ffffff", 0.13 * a), color("#ffffff", 0.015 * a), color("#aab7e2", 0.06 * a)],
        [0, 0.45, 1],
    )
    c.drawRoundRect(rect(x, y, w, h), r, r, skia.Paint(Shader=sh, AntiAlias=True))
    sh = skia.GradientShader.MakeLinear(
        [(x, y), (x + w, y + h)],
        [color("#ffffff", 0.65 * a), color("#b2b8e8", 0.12 * a), color("#ffffff", 0.34 * a)],
        [0, 0.5, 1],
    )
    p = skia.Paint(Shader=sh, AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.8)
    c.drawRoundRect(rect(x, y, w, h), r, r, p)


def touch(c, x, y, age):
    if not 0 <= age <= 0.7:
        return
    u = age / 0.7
    glow(c, x, y, 90, CREAM, 0.18 * (1 - u))
    c.drawCircle(x, y, 17 + 67 * out(u), paint(WHITE, (1 - u) * 0.9, 2.5))
    c.drawCircle(x, y, 12 * (1 - u * 0.4), paint(WHITE, (1 - u) * 0.9))


def screenshot(c, key, scroll=0, expanded=0):
    # 900 x 1500 viewport. 1310px content and a fixed 190px tab bar.
    # All imagery below comes from user screenshots, including the selected tab.
    c.save()
    c.clipRRect(skia.RRect.MakeRectXY(rect(0, 0, 900, 1500), 53, 53), True)
    c.drawRect(rect(0, 0, 900, 1500), paint("#101012"))
    im = IMAGES[key]
    if key == "community" and expanded > 0:
        # Reveal the real expanded list while the real collapsed content slides down.
        top = 425
        grow = 1014 * expanded
        image(c, IMAGES["leaderboard"], 0, 0, 900, 1310, src=(20, 205, 908, 1310))
        if expanded < 1:
            c.save()
            c.clipRect(rect(0, top + grow, 900, 1310 - top - grow))
            image(c, im, 0, top + grow, 900, 1310 - top, src=(20, 205 + top, 908, 1310 - top))
            c.restore()
    else:
        image(c, im, 0, 0, 900, 1310, src=(20, 205 + scroll, 908, 1310))
    # Header of the screenshot remains untouched; nav is pinned over moving content.
    image(c, im, 0, 1310, 900, 190, src=(18, 1793, 912, 190))
    # Small optical edge at bottom and animated scroll indicator.
    roundrect(c, 886, 70, 3, 108, 1.5, WHITE, 0.14)
    roundrect(c, 886, 70 + scroll * 0.13, 3, 34, 1.5, WHITE, 0.5)
    c.restore()


def panel(c, key, cx, cy, width=760, angle=0, perspective=0, scroll=0, alpha=1, expanded=0, tap=None, shine=0):
    c.save()
    c.translate(cx, cy)
    c.rotate(angle)
    s = width / 900
    c.scale(s, s)
    # Subtle projective yaw gives each real screen depth without device mockups.
    if perspective:
        c.concat(skia.Matrix.MakeAll(1, 0, 0, 0, 1, 0, perspective / 900, 0, 1))
    c.translate(-450, -750)
    c.saveLayer(None, skia.Paint(Alphaf=clamp(alpha)))
    image(c, IMAGES["shadow"], -60, -40, 1020, 1660)
    glass(c, -13, -13, 926, 1526, 66)
    screenshot(c, key, scroll, expanded)
    if tap:
        touch(c, *tap)
    # Fine glass bevel and a moving diagonal reflection, never washing out the UI.
    c.save()
    c.clipRRect(skia.RRect.MakeRectXY(rect(0, 0, 900, 1500), 53, 53), True)
    sh = skia.GradientShader.MakeLinear(
        [(-400 + shine, 0), (450 + shine, 1500)], [color(WHITE, 0), color(WHITE, 0.045), color(WHITE, 0)], [0, 0.5, 1]
    )
    c.drawRect(rect(0, 0, 900, 1500), skia.Paint(Shader=sh, AntiAlias=True))
    c.restore()
    roundrect(c, -1, -1, 902, 1502, 54, WHITE, 0.32, 1.3)
    c.restore()
    c.restore()


def heading(c, kicker, title, sub, t, enter=0):
    u = out((t - enter) / 0.55)
    y = (1 - u) * 24
    text(c, kicker, 540, 141 + y, 24, "#b5b5c5", u, True)
    text(c, title, 540, 236 + y, 72, CREAM, u, True)
    text(c, sub, 540, 294 + y, 26, "#aeadbd", u, True)


def pill(c, s, cx, y, w, a=1):
    glass(c, cx - w / 2, y, w, 66, 33, a)
    text(c, s, cx, y + 43, 24, CREAM, a, True)


def footer(c, index, t):
    for n in range(5):
        roundrect(c, 431 + n * 46, 1782, 32, 4, 2, RED if n == index else WHITE, 1 if n == index else 0.18)
    text(c, "NORA  /  СВОИ РЯДОМ", 540, 1834, 20, "#9595a6", 0.85, True)


def intro(c, t):
    # Real screens build into a dimensional fan underneath the exact brand mark.
    en = out(t / 1.25)
    collapse = ease((t - 3.25) / 0.75)
    fan = 1 - collapse
    c.save()
    c.translate(0, 170 * (1 - en))
    panel(c, "shop", 540 - 290 * fan, 1160 + 50 * fan, 430 + 80 * collapse, -12 * fan, 0.06 * fan, 140, alpha=0.55 * en)
    panel(
        c, "events", 540 + 290 * fan, 1160 + 50 * fan, 430 + 80 * collapse, 12 * fan, -0.06 * fan, 100, alpha=0.55 * en
    )
    panel(
        c,
        "home",
        540,
        1150,
        520 + 180 * collapse,
        -3 * (1 - collapse),
        0.025 * (1 - collapse),
        55 * ease((t - 1.8) / 1),
        en,
    )
    c.restore()
    logo(c, 540, 450 - 70 * collapse, 760 * (0.93 + 0.07 * en) * (1 - 0.12 * collapse), en)
    text(c, "ТВОЁ МЕСТО В TELEGRAM", 540, 180, 24, "#c6c2d0", out(t / 0.8), True)
    text(c, "Свои рядом.", 540, 686 - 70 * collapse, 62, CREAM, en * (1 - clamp(collapse * 2)), True)
    pill(c, "Один тап — и ты дома", 540, 1715, 390, en * (1 - collapse))
    if t > 3.15:
        # Expanding optical ring converges into the first full-screen UI on the drop.
        p = clamp((t - 3.15) / 0.85)
        rr = 900 * (1 - p) + 150
        c.drawCircle(540, 960, rr, paint(RED, 0.25 * math.sin(p * math.pi), 2))


def main_scene(c, i, t, start, end):
    local = t - start
    dur = end - start
    en = ease(local / 0.52)
    keys = ["home", "shop", "community", "events", "profile"]
    titles = ["Свои рядом.", "То самое.", "Твои люди.", "Есть повод.", "Это ты."]
    subs = [
        "Всё начинается здесь",
        "Находки с характером",
        "Игры, музыка и общение",
        "Собираться вместе",
        "Профиль. Репутация. Питомец.",
    ]
    kicks = ["01  /  ГЛАВНАЯ", "02  /  МАГАЗИН", "03  /  КОММЬЮНИТИ", "04  /  СОБЫТИЯ", "05  /  ПРОФИЛЬ"]
    heading(c, kicks[i], titles[i], subs[i], t, start)
    scroll = (160 if i in (1, 3) else 240) * ease((local - 0.45) / 1.25)
    if i == 2:
        scroll = 0
    if i == 4:
        scroll = 185 * ease((local - 0.5) / 1.2)
    cx = 540 + (1 - en) * (1250 if i > 0 else -180)
    cy = 1040 + (1 - en) * 90
    width = 744 + 18 * ease(local / dur)
    angle = (1 - en) * (12 if i > 0 else -9) + math.sin(local * 0.8) * 0.7
    persp = (1 - en) * (0.11 if i % 2 else -0.11)
    expanded = ease((local - 0.68) / 0.52) if i == 2 else 0
    tap = None
    if local > dur - 0.45 and i < 4:
        target = [270, 450, 630, 810][i]
        tap = (target, 1400, local - (dur - 0.43))
    elif i == 2:
        tap = (825, 350, local - 0.57)
    if i > 0 and en < 1:
        # Shared-axis transition preserves continuity of the navigation click.
        panel(
            c,
            keys[i - 1],
            540 - 1250 * en,
            1040 + 90 * en,
            762 - 35 * en,
            -12 * en,
            -0.07 * en,
            0 if i == 3 else (160 if i in (2, 4) else 240),
            expanded=1 if i == 3 else 0,
            alpha=1 - 0.2 * en,
        )
    panel(c, keys[i], cx, cy, width, angle, persp, scroll, expanded=expanded, tap=tap, shine=local * 110)
    footer(c, i, t)
    # The tapped navigation tab launches the next panel along a shared trajectory.
    if local > dur - 0.28:
        q = ease((local - (dur - 0.28)) / 0.48)
        glow(c, 540, 1740, 420, RED, 0.11 * q)


def mosaic(c, t):
    start = CUTS[5]
    u = t - start
    en = out(u / 0.65)
    heading(c, "ОДНО ПРИЛОЖЕНИЕ", "Твоя Нора.", "Больше, чем просто чат", t, start)
    # Fan-out is a continuous camera move. Each panel is still a real screen.
    panel(c, "events", 540 - 410 * en, 1060, 430, -12 * en, 0.06, 130, 0.8)
    panel(c, "shop", 540 + 410 * en, 1060, 430, 12 * en, -0.06, 175, 0.8)
    panel(c, "profile", 540 - 200 * en, 1110, 470, -6 * en, 0.025, 100, 0.95)
    panel(c, "community", 540 + 200 * en, 1110, 470, 6 * en, -0.025, 0, 0.95)
    panel(c, "home", 540, 1030, 620 - 130 * en, 0, 0, 80, 1)
    labels = ["Общайся", "Играй", "Встречайся"]
    for j, s in enumerate(labels):
        a = out((u - 0.35 - j * 0.16) / 0.4)
        pill(c, s, 240 + j * 300, 1670 + (1 - a) * 35, 260, a)


def outro(c, t):
    u = t - CUTS[6]
    en = out(u / 0.65)
    # Screen stack falls away as the final wordmark comes forward.
    if u < 0.55:
        c.saveLayer(None, skia.Paint(Alphaf=1 - ease(u / 0.55)))
        panel(c, "home", 540, 1080 + u * 600, 490 * (1 - u * 0.5), -u * 8, 0, 80)
        c.restore()
    glow(c, 540, 910, 650, RED, 0.12 * en)
    logo(c, 540, 800 + (1 - en) * 180, 870 * (0.85 + 0.15 * en), en)
    text(c, "Свои рядом.", 540, 1120 + (1 - en) * 70, 78, CREAM, en, True)
    pill(c, "Внутри Telegram", 540, 1248, 350, en)
    text(c, "НОРА  /  СЕЗОН 1", 540, 1764, 23, "#a9a6b7", en, True)


def frame(t, scale=1):
    surface = skia.Surface(round(W * scale), round(H * scale))
    c = surface.getCanvas()
    c.scale(scale, scale)
    background(c, t)
    if t < DROP:
        intro(c, t)
    elif t < CUTS[5]:
        i = max(j for j in range(5) if t >= CUTS[j])
        main_scene(c, i, t, CUTS[i], CUTS[i + 1])
    elif t < CUTS[6]:
        mosaic(c, t)
    else:
        outro(c, t)
    # One short cream exposure on the musical impact, not strobing.
    if DROP <= t < DROP + 0.16:
        c.drawRect(rect(0, 0, W, H), paint(CREAM, 0.23 * (1 - (t - DROP) / 0.16) ** 2))
    # Very short tail to black, keeping the end card readable for ~1.6 seconds.
    if t > 19.75:
        c.drawRect(rect(0, 0, W, H), paint("#090a10", ease((t - 19.75) / 0.25)))
    return surface.makeImageSnapshot()


def preview():
    times = [0.8, 2.2, 3.8, 4.4, 5.8, 6.9, 8.25, 9.2, 9.8, 10.6, 11.5, 12.9, 13.9, 15.2, 16.4, 17.6, 18.7, 19.4]
    thumb_w, thumb_h = 270, 480
    sheet = Image.new("RGB", (thumb_w * 6, 520 * 3), "#16161f")
    draw = ImageDraw.Draw(sheet)
    for k, t in enumerate(times):
        snapshot = frame(t, 0.5)
        p = OUT / f"preview-{t:04.1f}.png"
        snapshot.save(str(p), skia.kPNG)
        with Image.open(p) as im:
            sheet.paste(im.resize((thumb_w, thumb_h), Image.Resampling.LANCZOS), ((k % 6) * thumb_w, (k // 6) * 520))
        draw.text(((k % 6) * thumb_w + 12, (k // 6) * 520 + 490), f"{t:.2f}s", fill="white")
    sheet.save(OUT / "contact-sheet.jpg", quality=92)
    print("Preview:", OUT / "contact-sheet.jpg", flush=True)


def render_segment(job):
    attachments, seg, first, last = job
    load_images(attachments)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    target = OUT / f"segment-{seg}.mp4"
    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgra",
        "-s",
        f"{W}x{H}",
        "-r",
        str(FPS),
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-threads",
        "2",
        "-r",
        str(FPS),
        str(target),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    previous = None
    for n in range(first, last):
        raw = np.frombuffer(frame(n / FPS).tobytes(), dtype=np.uint8).reshape(H, W, 4)
        moving = any(0 < n / FPS - cut < 0.52 for cut in CUTS[1:5])
        if moving and previous is not None:
            # Short temporal exposure makes the fast camera moves feel filmed.
            raw = ((raw.astype(np.uint16) * 4 + previous.astype(np.uint16)) // 5).astype(np.uint8)
        previous = raw
        proc.stdin.write(raw.tobytes())
        if (n - first) % 100 == 0:
            print(f"Segment {seg + 1}/6: {n - first}/{last - first}", flush=True)
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError(f"FFmpeg segment {seg} failed")
    print(f"Segment {seg + 1}/6 complete", flush=True)
    return target


def render(attachments):
    jobs = [(attachments, k, k * 200, (k + 1) * 200) for k in range(6)]
    with ProcessPoolExecutor(max_workers=6) as pool:
        parts = list(pool.map(render_segment, jobs))
    mux(attachments, parts)


def mux(attachments, parts):
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    concat = OUT / "segments.txt"
    concat.write_text("\n".join(f"file '{p.name}'" for p in parts), encoding="utf-8")
    audio = next(attachments.glob("*.mp3"))
    target = OUT / "NORA-Liquid-Motion-20s.mp4"
    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat),
        "-ss",
        str(AUDIO_START),
        "-i",
        str(audio),
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-t",
        "20",
        "-c:v",
        "copy",
        "-af",
        "volume=0.47,alimiter=limit=0.94:level=false:latency=true,"
        "afade=t=in:st=0:d=0.08,afade=t=out:st=19.4:d=0.6",
        "-c:a",
        "aac",
        "-b:a",
        "256k",
        "-ar",
        "48000",
        "-movflags",
        "+faststart",
        "-metadata",
        "title=NORA — Свои рядом",
        "-metadata",
        "comment=Real NORA UI; 20 seconds; source audio 20.74–40.74s; drop at 4.00s",
        str(target),
    ]
    subprocess.run(cmd, check=True)
    print("Final:", target, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--attachments", type=Path, required=True)
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    load_images(args.attachments)
    if args.preview:
        preview()
    if args.render:
        render(args.attachments)
