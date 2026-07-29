from __future__ import annotations

import math
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "assets"
ICONSET_DIR = ASSET_DIR / "EdgeIQ.iconset"
ICNS_PATH = ASSET_DIR / "EdgeIQ.icns"
PNG_PATH = ASSET_DIR / "EdgeIQ-1024.png"


def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial Bold.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _text_center(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font, fill) -> None:
    box = draw.textbbox((0, 0), text, font=font)
    width = box[2] - box[0]
    height = box[3] - box[1]
    draw.text((xy[0] - width / 2, xy[1] - height / 2 - box[1]), text, font=font, fill=fill)


def _rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size, size), radius=radius, fill=255)
    return mask


def build_icon(size: int = 1024) -> Image.Image:
    scale = size / 1024
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    for y in range(size):
        t = y / max(size - 1, 1)
        r = int(4 + 8 * t)
        g = int(6 + 12 * t)
        b = int(13 + 24 * t)
        draw.line((0, y, size, y), fill=(r, g, b, 255))

    mask = _rounded_mask(size, int(210 * scale))
    img.putalpha(mask)
    draw = ImageDraw.Draw(img)

    grid = int(96 * scale)
    for offset in range(-size, size * 2, grid):
        draw.line((offset, 0, offset - size, size), fill=(57, 255, 136, 24), width=max(1, int(2 * scale)))
        draw.line((offset, size, offset + size, 0), fill=(25, 230, 255, 18), width=max(1, int(2 * scale)))

    pad = int(76 * scale)
    draw.rounded_rectangle(
        (pad, pad, size - pad, size - pad),
        radius=int(160 * scale),
        outline=(57, 255, 136, 210),
        width=int(10 * scale),
    )
    draw.rounded_rectangle(
        (pad + int(34 * scale), pad + int(34 * scale), size - pad - int(34 * scale), size - pad - int(34 * scale)),
        radius=int(128 * scale),
        outline=(25, 230, 255, 78),
        width=int(4 * scale),
    )

    banner_y = int(196 * scale)
    banner_h = int(128 * scale)
    banner = [
        (int(78 * scale), banner_y),
        (size - int(56 * scale), banner_y - int(32 * scale)),
        (size - int(112 * scale), banner_y + banner_h),
        (int(28 * scale), banner_y + banner_h + int(28 * scale)),
    ]
    draw.polygon(banner, fill=(57, 255, 136, 235))
    draw.line((int(92 * scale), banner_y + banner_h + int(34 * scale), size - int(132 * scale), banner_y + banner_h), fill=(25, 230, 255, 170), width=int(8 * scale))

    center = size // 2
    radius = int(254 * scale)
    for step in range(8):
        alpha = max(10, 86 - step * 9)
        draw.ellipse(
            (
                center - radius - step * int(11 * scale),
                center - radius - step * int(11 * scale),
                center + radius + step * int(11 * scale),
                center + radius + step * int(11 * scale),
            ),
            outline=(25, 230, 255, alpha),
            width=max(1, int(4 * scale)),
        )

    points = []
    for i in range(11):
        x = int((260 + i * 50) * scale)
        wave = math.sin(i * 0.85) * 55
        y = int((594 + wave) * scale)
        points.append((x, y))
    draw.line(points, fill=(57, 255, 136, 255), width=int(20 * scale), joint="curve")
    for x, y in points:
        draw.ellipse((x - int(11 * scale), y - int(11 * scale), x + int(11 * scale), y + int(11 * scale)), fill=(25, 230, 255, 255))

    title_font = _font(int(210 * scale))
    small_font = _font(int(54 * scale))
    _text_center(draw, (center, int(468 * scale)), "EIQ", title_font, (242, 248, 255, 255))
    _text_center(draw, (center, int(742 * scale)), "EDGE INTELLIGENCE", small_font, (57, 255, 136, 235))

    return img


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    ICONSET_DIR.mkdir(parents=True, exist_ok=True)
    base = build_icon()
    base.save(PNG_PATH)

    sizes = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]
    for pixel_size, filename in sizes:
        base.resize((pixel_size, pixel_size), Image.Resampling.LANCZOS).save(ICONSET_DIR / filename)

    subprocess.run(["/usr/bin/iconutil", "-c", "icns", str(ICONSET_DIR), "-o", str(ICNS_PATH)], check=True)
    print(ICNS_PATH)


if __name__ == "__main__":
    main()
