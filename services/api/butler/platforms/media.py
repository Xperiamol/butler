"""多模态媒体：真实绘制的图片 / 扫描件 PDF（Pillow），以及随仓库提交的录音。

每个媒体都带 derived 文本（图片描述 + 画面上的文字 / OCR / 语音转写）。图片是我们自己画的，所以识别文本和画面严格一致；
配置了视觉模型时，`vision.describe` 可以对同一张图重新识别，用来核对（scripts/verify_media.py）。
媒体文件按“键”存放在媒体库目录：BUTLER_MEDIA_DIR，默认 <仓库>/.runtime/sim-media。
"""
from __future__ import annotations
import io
import json
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[4]
SEED_AUDIO = ROOT / "seed" / "enterprise" / "media"
_FONTS = ["/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/Supplemental/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf"]
_BOLD = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
_MONO = ["/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Monaco.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"]


def media_dir() -> Path:
    d = Path(os.getenv("BUTLER_MEDIA_DIR") or ROOT / ".runtime" / "sim-media")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _font(paths: list[str], size: int):
    for p in paths:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default()


def F(size: int):
    return _font(_FONTS, size)


def FB(size: int):
    return _font(_BOLD + _FONTS, size)


def FM(size: int):
    return _font(_MONO + _FONTS, size)


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _box(d: ImageDraw.ImageDraw, xy, text: str, fill="#ffffff", outline="#26332b", font=None, tc="#1c2a21", w=2):
    d.rounded_rectangle(xy, radius=8, fill=fill, outline=outline, width=w)
    x0, y0, x1, y1 = xy
    lines = text.split("\n")
    f = font or FB(15)
    th = sum(f.getbbox(l)[3] - f.getbbox(l)[1] + 4 for l in lines)
    y = (y0 + y1) / 2 - th / 2
    for l in lines:
        b = f.getbbox(l)
        d.text(((x0 + x1) / 2 - (b[2] - b[0]) / 2, y), l, font=f, fill=tc)
        y += b[3] - b[1] + 4


def _arrow(d, a, b, color="#5b6f63", w=3, label=""):
    d.line([a, b], fill=color, width=w)
    import math
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    for s in (0.4, -0.4):
        d.line([b, (b[0] - 12 * math.cos(ang + s), b[1] - 12 * math.sin(ang + s))], fill=color, width=w)
    if label:
        d.text(((a[0] + b[0]) / 2 + 4, (a[1] + b[1]) / 2 - 18), label, font=F(12), fill="#4a5a50")


# ---- 图片 ----
def architecture(title: str, nodes: list[tuple[str, int, int]], edges: list[tuple[int, int, str]], note: str = "") -> tuple[bytes, str]:
    img = Image.new("RGB", (1100, 620), "#f7f8f5")
    d = ImageDraw.Draw(img)
    d.text((30, 20), title, font=FB(26), fill="#1c2a21")
    boxes = []
    for label, x, y in nodes:
        xy = (x, y, x + 190, y + 70)
        _box(d, xy, label)
        boxes.append(xy)
    for a, b, lab in edges:
        ax = (boxes[a][0] + boxes[a][2]) / 2
        ay = (boxes[a][1] + boxes[a][3]) / 2
        bx = (boxes[b][0] + boxes[b][2]) / 2
        by = (boxes[b][1] + boxes[b][3]) / 2
        # 从方框边缘出发
        sa = (boxes[a][2], ay) if bx > ax + 100 else (boxes[a][0], ay) if bx < ax - 100 else (ax, boxes[a][3] if by > ay else boxes[a][1])
        sb = (boxes[b][0], by) if bx > ax + 100 else (boxes[b][2], by) if bx < ax - 100 else (bx, boxes[b][1] if by > ay else boxes[b][3])
        _arrow(d, sa, sb, label=lab)
    if note:
        d.text((30, 580), note, font=F(14), fill="#6a776f")
    caption = (f"Architecture diagram titled \"{title}\". Boxes: " + "; ".join(n[0].replace("\n", " ") for n in nodes) + ". Arrows: " +
               "; ".join(f"{nodes[a][0].splitlines()[0]} -> {nodes[b][0].splitlines()[0]}" + (f" ({lab})" if lab else "") for a, b, lab in edges) + (f". Footnote: {note}" if note else "."))
    return _png(img), caption


def line_chart(title: str, xs: list[str], series: list[tuple[str, list[float], str]], ylabel: str, annotation: tuple[int, str] | None = None, threshold: tuple[float, str] | None = None) -> tuple[bytes, str]:
    W, H = 1000, 560
    img = Image.new("RGB", (W, H), "#161b22")
    d = ImageDraw.Draw(img)
    d.text((24, 16), title, font=FB(22), fill="#e6edf3")
    d.text((24, 48), ylabel, font=F(14), fill="#8b949e")
    x0, y0, x1, y1 = 80, 90, W - 40, H - 70
    ymax = max(max(s[1]) for s in series) * 1.15
    for k in range(5):
        y = y1 - (y1 - y0) * k / 4
        d.line([(x0, y), (x1, y)], fill="#30363d")
        d.text((14, y - 8), f"{ymax * k / 4:.1f}", font=F(12), fill="#8b949e")
    n = len(xs)
    for i, xl in enumerate(xs):
        x = x0 + (x1 - x0) * i / (n - 1)
        if i % max(1, n // 8) == 0:
            d.text((x - 16, y1 + 10), xl, font=F(12), fill="#8b949e")
    if threshold:
        ty = y1 - (y1 - y0) * threshold[0] / ymax
        d.line([(x0, ty), (x1, ty)], fill="#f85149", width=2)
        d.text((x1 - 200, ty - 20), threshold[1], font=F(13), fill="#f85149")
    for name, vals, color in series:
        pts = [(x0 + (x1 - x0) * i / (n - 1), y1 - (y1 - y0) * v / ymax) for i, v in enumerate(vals)]
        d.line(pts, fill=color, width=3)
    ly = 56
    for name, _, color in series:
        d.rectangle([W - 260, ly, W - 244, ly + 12], fill=color)
        d.text((W - 238, ly - 3), name, font=F(14), fill="#c9d1d9")
        ly += 22
    if annotation:
        i, text = annotation
        x = x0 + (x1 - x0) * i / (n - 1)
        d.line([(x, y0), (x, y1)], fill="#d29922", width=2)
        d.text((x + 8, y0 + 6), text, font=FB(14), fill="#d29922")
    peak = max(max(s[1]) for s in series)
    cap = (f"Dark-theme dashboard screenshot titled \"{title}\" with y-axis \"{ylabel}\", x-axis from {xs[0]} to {xs[-1]}. Series: " + ", ".join(s[0] for s in series) +
           f". The highest value shown is {peak}. " + (f"A vertical marker says \"{annotation[1]}\". " if annotation else "") + (f"A red threshold line is labelled \"{threshold[1]}\"." if threshold else ""))
    return _png(img), cap


def whiteboard(title: str, boxes: list[tuple[str, int, int]], notes: list[str], arrows: list[tuple[int, int]]) -> tuple[bytes, str]:
    img = Image.new("RGB", (1000, 640), "#f4f1e8")
    d = ImageDraw.Draw(img)
    for i in range(0, 1000, 40):
        d.line([(i, 0), (i, 640)], fill="#ece8dc")
    d.text((40, 22), title, font=FB(30), fill="#243b6b")
    cent = []
    for text, x, y in boxes:
        d.rounded_rectangle((x, y, x + 200, y + 80), radius=14, outline="#243b6b", width=4)
        lines = text.split("\n")
        for k, l in enumerate(lines):
            d.text((x + 14, y + 14 + k * 24), l, font=FB(19), fill="#243b6b")
        cent.append((x + 100, y + 40))
    for a, b in arrows:
        _arrow(d, (cent[a][0] + 100, cent[a][1]), (cent[b][0] - 100, cent[b][1]), color="#b3322b", w=4)
    y = 400
    for n in notes:
        d.text((60, y), "• " + n, font=F(20), fill="#b3322b")
        y += 34
    cap = (f"Photo of a whiteboard titled \"{title}\" with boxes: " + "; ".join(t.replace("\n", " ") for t, _, _ in boxes) + ". Red arrows connect them left to right. Notes written below: " + "; ".join(notes) + ".")
    return _png(img), cap


def timeline(title: str, rows: list[tuple[str, int, int, str]], weeks: int, today: int, note: str = "") -> tuple[bytes, str]:
    img = Image.new("RGB", (1100, 120 + 52 * len(rows)), "#ffffff")
    d = ImageDraw.Draw(img)
    d.text((24, 16), title, font=FB(24), fill="#1c2a21")
    x0, x1 = 300, 1060
    for w in range(weeks + 1):
        x = x0 + (x1 - x0) * w / weeks
        d.line([(x, 64), (x, 100 + 52 * len(rows) - 24)], fill="#e4e7e2")
        d.text((x - 10, 66), f"W{w + 1}" if w < weeks else "", font=F(12), fill="#6a776f")
    colors = {"done": "#3f7a52", "active": "#c9922b", "blocked": "#c2453b", "todo": "#9aa6a0"}
    for i, (label, a, b, state) in enumerate(rows):
        y = 96 + 52 * i
        d.text((24, y + 8), label, font=F(16), fill="#26332b")
        d.rounded_rectangle((x0 + (x1 - x0) * a / weeks, y, x0 + (x1 - x0) * b / weeks, y + 28), radius=6, fill=colors[state])
        d.text((x0 + (x1 - x0) * a / weeks + 8, y + 6), state.upper(), font=FB(12), fill="#ffffff")
    tx = x0 + (x1 - x0) * today / weeks
    d.line([(tx, 62), (tx, 100 + 52 * len(rows) - 24)], fill="#1f6feb", width=3)
    d.text((tx + 6, 62), "today", font=FB(13), fill="#1f6feb")
    if note:
        d.text((24, 100 + 52 * len(rows) - 20), note, font=F(14), fill="#6a776f")
    cap = f"Gantt-style timeline titled \"{title}\" over {weeks} weeks. Rows: " + "; ".join(f"{l} ({s}, weeks {a + 1}-{b})" for l, a, b, s in rows) + f". A blue line marks today at week {today + 1}." + (f" Note: {note}" if note else "")
    return _png(img), cap


def screenshot_error(title: str, lines: list[str]) -> tuple[bytes, str]:
    img = Image.new("RGB", (900, 420), "#0f1419")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 900, 34), fill="#1c2128")
    for i, c in enumerate(("#ff5f56", "#ffbd2e", "#27c93f")):
        d.ellipse((14 + i * 22, 10, 26 + i * 22, 22), fill=c)
    d.text((100, 8), title, font=F(14), fill="#8b949e")
    y = 56
    for ln in lines:
        d.text((24, y), ln, font=FM(16), fill="#f85149" if "ERROR" in ln or "FATAL" in ln else "#c9d1d9")
        y += 26
    return _png(img), f"Terminal screenshot titled \"{title}\". Visible text: " + " | ".join(lines)


def scan_pages(pages: list[list[str]], title: str) -> tuple[bytes, str]:
    imgs = []
    for n, lines in enumerate(pages, 1):
        im = Image.new("RGB", (794, 1123), "#fbfaf6")
        d = ImageDraw.Draw(im)
        d.text((60, 50), title, font=FB(22), fill="#222")
        d.text((60, 82), f"Page {n} of {len(pages)}", font=F(13), fill="#777")
        y = 130
        for ln in lines:
            d.text((60, y), ln, font=F(17), fill="#222")
            y += 30
        # 轻微的扫描噪声线
        for k in range(0, 1123, 97):
            d.line([(0, k), (794, k + 1)], fill="#f0eee6")
        imgs.append(im)
    buf = io.BytesIO()
    imgs[0].save(buf, "PDF", save_all=True, append_images=imgs[1:], resolution=100.0)
    text = f"Scanned PDF, {len(pages)} pages, OCR text:\n" + "\n".join(f"[page {n}] " + " ".join(p) for n, p in enumerate(pages, 1))
    return buf.getvalue(), text


def save(key: str, data: bytes) -> str:
    (media_dir() / key).write_bytes(data)
    return key


def path_of(key: str) -> Path | None:
    p = media_dir() / key
    if p.exists():
        return p
    s = SEED_AUDIO / key
    return s if s.exists() else None


def transcript(key: str) -> dict | None:
    p = SEED_AUDIO / (Path(key).stem + ".json")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
