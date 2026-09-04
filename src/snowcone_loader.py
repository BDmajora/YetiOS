"""Generate the FreeBSD loader-stage SnowCone splash bitmap."""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path


WIDTH = 640
HEIGHT = 480
DESIGN_W = 1024.0
DESIGN_H = 768.0

BLACK = 0
WHITE = 1
BABYBLUE = 2
DIM_BLUE = 3
COPY = 4
BAR_25 = 5
BAR_50 = 6
BAR_75 = 7

RGB = {
    BLACK: (0, 0, 0),
    WHITE: (255, 255, 255),
    BABYBLUE: (142, 197, 255),
    DIM_BLUE: (90, 143, 207),
    COPY: (187, 187, 187),
    BAR_25: (35, 49, 63),
    BAR_50: (71, 98, 127),
    BAR_75: (106, 147, 191),
}

PU = None

FONT = {
    "Y": (8, [(0, 0), (4, 7), (8, 0), PU, (4, 7), (4, 14)]),
    "I": (6, [(0, 0), (6, 0), PU, (3, 0), (3, 14), PU, (0, 14), (6, 14)]),
    "L": (6, [(0, 0), (0, 14), (6, 14)]),
    "M": (8, [(0, 14), (0, 0), (4, 8), (8, 0), (8, 14)]),
    "T": (8, [(0, 0), (8, 0), PU, (4, 0), (4, 14)]),
    "e": (7, [(0, 11), (7, 11), (7, 9), (6, 7), (1, 7), (0, 9), (0, 12), (2, 14), (5, 14), (7, 12)]),
    "t": (5, [(2, 2), (2, 12), (4, 14), PU, (0, 7), (5, 7)]),
    "i": (2, [(1, 0), (1, 2), PU, (1, 5), (1, 14)]),
    "O": (9, [(2, 0), (7, 0), (9, 3), (9, 11), (7, 14), (2, 14), (0, 11), (0, 3), (2, 0)]),
    "S": (8, [(8, 2), (6, 0), (2, 0), (0, 2), (0, 5), (2, 7), (6, 7), (8, 9), (8, 12), (6, 14), (2, 14), (0, 12)]),
    "C": (8, [(8, 2), (6, 0), (2, 0), (0, 2), (0, 12), (2, 14), (6, 14), (8, 12)]),
    "o": (7, [(3, 7), (6, 7), (7, 9), (7, 12), (5, 14), (2, 14), (0, 12), (0, 9), (2, 7), (3, 7)]),
    "p": (7, [(0, 7), (0, 18), PU, (0, 8), (2, 7), (5, 7), (7, 9), (7, 12), (5, 14), (2, 14), (0, 12)]),
    "y": (7, [(0, 7), (3, 14), PU, (7, 7), (3, 14), (0, 18)]),
    "r": (5, [(0, 14), (0, 7), PU, (0, 9), (2, 7), (5, 7)]),
    "g": (7, [(7, 7), (7, 18), (5, 20), (1, 20), PU, (7, 8), (5, 7), (2, 7), (0, 9), (0, 12), (2, 14), (5, 14), (7, 12)]),
    "h": (6, [(0, 0), (0, 14), PU, (0, 9), (2, 7), (5, 7), (6, 9), (6, 14)]),
    "P": (6, [(0, 14), (0, 0), (5, 0), (6, 2), (6, 5), (5, 7), (0, 7)]),
    "j": (3, [(2, 0), (2, 2), PU, (2, 5), (2, 17), (0, 19)]),
    "c": (7, [(7, 9), (5, 7), (2, 7), (0, 9), (0, 12), (2, 14), (5, 14), (7, 12)]),
    "n": (6, [(0, 14), (0, 7), PU, (0, 9), (2, 7), (5, 7), (6, 9), (6, 14)]),
    "s": (7, [(7, 9), (5, 7), (2, 7), (0, 9), (2, 11), (5, 11), (7, 13), (5, 14), (2, 14), (0, 12)]),
    "0": (7, [(3, 0), (0, 3), (0, 11), (3, 14), (4, 14), (7, 11), (7, 3), (4, 0), (3, 0)]),
    "2": (7, [(0, 3), (3, 0), (4, 0), (7, 3), (7, 5), (0, 14), (7, 14)]),
    "6": (7, [(6, 0), (2, 0), (0, 4), (0, 12), (2, 14), (5, 14), (7, 12), (7, 9), (5, 7), (2, 7), (0, 9)]),
    " ": (4, []),
    "-": (6, [(0, 7), (6, 7)]),
    "(": (4, [(3, 0), (2, 1), (1, 3), (0, 6), (0, 8), (1, 11), (2, 13), (3, 14)]),
    ")": (4, [(0, 0), (1, 1), (2, 3), (3, 6), (3, 8), (2, 11), (1, 13), (0, 14)]),
}

BITMAP_FONT = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "I": ("111", "010", "010", "010", "010", "010", "111"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "c": ("00000", "00000", "01110", "10000", "10000", "10000", "01110"),
    "e": ("00000", "00000", "01110", "10001", "11110", "10000", "01111"),
    "g": ("00000", "01110", "10001", "10001", "01111", "00001", "11110"),
    "h": ("10000", "10000", "11110", "10001", "10001", "10001", "10001"),
    "i": ("1", "0", "1", "1", "1", "1", "1"),
    "j": ("001", "000", "001", "001", "001", "101", "010"),
    "n": ("00000", "00000", "11110", "10001", "10001", "10001", "10001"),
    "o": ("00000", "00000", "01110", "10001", "10001", "10001", "01110"),
    "p": ("00000", "11110", "10001", "10001", "11110", "10000", "10000"),
    "r": ("00000", "00000", "10110", "11001", "10000", "10000", "10000"),
    "s": ("00000", "00000", "01111", "10000", "01110", "00001", "11110"),
    "t": ("01000", "01000", "11100", "01000", "01000", "01001", "00110"),
    "y": ("00000", "00000", "10001", "10001", "01111", "00001", "11110"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    "(": ("01", "10", "10", "10", "10", "10", "01"),
    ")": ("10", "01", "01", "01", "01", "01", "10"),
    " ": ("000", "000", "000", "000", "000", "000", "000"),
}


def _xform() -> tuple[float, float, float]:
    scale = min(WIDTH / DESIGN_W, HEIGHT / DESIGN_H)
    ox = (WIDTH - DESIGN_W * scale) * 0.5
    oy = (HEIGHT - DESIGN_H * scale) * 0.5
    return scale, ox, oy


SCALE, OX, OY = _xform()


def _set(px: bytearray, x: int, y: int, color: int) -> None:
    if 0 <= x < WIDTH and 0 <= y < HEIGHT:
        px[y * WIDTH + x] = color


def _rect(px: bytearray, x: int, y: int, w: int, h: int, color: int) -> None:
    for yy in range(y, y + h):
        for xx in range(x, x + w):
            _set(px, xx, yy, color)


def _rect_clip(px: bytearray, x: int, y: int, w: int, h: int, color: int, clip_x0: int, clip_x1: int) -> None:
    x1 = x + w
    x = max(x, clip_x0)
    x1 = min(x1, clip_x1)
    if x1 > x and h > 0:
        _rect(px, x, y, x1 - x, h, color)


def _dp(x: float, y: float) -> tuple[float, float]:
    return OX + x * SCALE, OY + y * SCALE


def _icon_point(dx: float, dy: float) -> tuple[float, float]:
    pivot_x = 512.0
    pivot_y = 340.0
    squish = 0.72
    y_scale = 0.78
    offset_y = -65.0
    tilt = 0.0
    lx = (dx - pivot_x) * squish
    ly = (dy - pivot_y) * y_scale
    rx = pivot_x + lx * math.cos(tilt) - ly * math.sin(tilt)
    ry = pivot_y + lx * math.sin(tilt) + ly * math.cos(tilt) + offset_y
    return _dp(rx, ry)


def _point_in_poly(x: float, y: float, poly: list[tuple[float, float]]) -> bool:
    inside = False
    j = len(poly) - 1
    for i, pi in enumerate(poly):
        pj = poly[j]
        if ((pi[1] > y) != (pj[1] > y)) and (
            x < (pj[0] - pi[0]) * (y - pi[1]) / (pj[1] - pi[1]) + pi[0]
        ):
            inside = not inside
        j = i
    return inside


def _fill_poly(px: bytearray, pts: list[tuple[float, float]], color: int) -> None:
    min_x = max(0, int(min(p[0] for p in pts)))
    max_x = min(WIDTH - 1, int(max(p[0] for p in pts)) + 1)
    min_y = max(0, int(min(p[1] for p in pts)))
    max_y = min(HEIGHT - 1, int(max(p[1] for p in pts)) + 1)
    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            if _point_in_poly(x + 0.5, y + 0.5, pts):
                _set(px, x, y, color)


def _line(px: bytearray, x0: float, y0: float, x1: float, y1: float, thickness: float, color: int) -> None:
    steps = max(1, int(max(abs(x1 - x0), abs(y1 - y0)) * 2))
    radius = max(1, int(thickness / 2))
    for i in range(steps + 1):
        t = i / steps
        x = int(round(x0 + (x1 - x0) * t))
        y = int(round(y0 + (y1 - y0) * t))
        _rect(px, x - radius, y - radius, radius * 2 + 1, radius * 2 + 1, color)


def _outline_poly(px: bytearray, pts: list[tuple[float, float]], thickness: float, color: int) -> None:
    for i, p in enumerate(pts):
        q = pts[(i + 1) % len(pts)]
        _line(px, p[0], p[1], q[0], q[1], thickness, color)


def _fill_and_outline(px: bytearray, pts: list[tuple[float, float]], fill: int, outline: int, thickness: float) -> None:
    _fill_poly(px, pts, fill)
    _outline_poly(px, pts, thickness, outline)


def _draw_icon(px: bytearray) -> None:
    thickness = max(2.0, 3.5 * SCALE)
    cone = [_icon_point(450, 320), _icon_point(570, 320), _icon_point(510, 490)]
    shadow = [_icon_point(510, 320), _icon_point(570, 320), _icon_point(510, 490)]
    _fill_poly(px, cone, BABYBLUE)
    _fill_poly(px, shadow, DIM_BLUE)
    _outline_poly(px, cone, thickness, BLACK)

    snow = [
        _icon_point(612, 320), _icon_point(600, 332), _icon_point(560, 336),
        _icon_point(512, 338), _icon_point(464, 336), _icon_point(424, 332),
        _icon_point(412, 320), _icon_point(400, 296), _icon_point(402, 264),
        _icon_point(422, 232), _icon_point(458, 208), _icon_point(488, 196),
        _icon_point(510, 204), _icon_point(540, 192), _icon_point(576, 200),
        _icon_point(604, 228), _icon_point(616, 268), _icon_point(618, 304),
    ]
    _fill_and_outline(px, snow, WHITE, BLACK, thickness)

    shard = [
        _icon_point(478, 244), _icon_point(506, 252), _icon_point(514, 282),
        _icon_point(494, 304), _icon_point(470, 280),
    ]
    _fill_and_outline(px, shard, BABYBLUE, BLACK, thickness * 0.75)
    glint = [_icon_point(484, 252), _icon_point(496, 256), _icon_point(486, 270)]
    _fill_poly(px, glint, WHITE)


def _text_width(text: str, scale: float) -> float:
    pixel = float(_font_pixel_size(scale))
    width = 0.0
    for ch in text:
        glyph = BITMAP_FONT.get(ch)
        if glyph is None:
            width += 4 * pixel
        else:
            width += (max(len(row) for row in glyph) + 1) * pixel
    return width


def _font_pixel_size(scale: float) -> int:
    return max(1, int(scale * 2.0 + 0.5))


def _draw_text(px: bytearray, x: float, y: float, scale: float, thickness: float, color: int, text: str) -> float:
    pixel = float(_font_pixel_size(scale))
    block = int(pixel)
    pen_x = x
    _ = thickness
    for ch in text:
        glyph = BITMAP_FONT.get(ch)
        if glyph is None:
            pen_x += 4 * pixel
            continue
        width = max(len(row) for row in glyph)
        for row_i, row in enumerate(glyph):
            for col_i, bit in enumerate(row):
                if bit == "1":
                    _rect(
                        px,
                        int(round(pen_x + col_i * pixel)),
                        int(round(y + row_i * pixel)),
                        block,
                        block,
                        color,
                    )
        pen_x += (width + 1) * pixel
    return pen_x - x


def _draw_wordmark(px: bytearray) -> None:
    text_scale = 4.0 * SCALE
    thickness = max(1.5, 2.5 * SCALE)
    part_a = "Yeti"
    part_b = "OS"
    total = _text_width(part_a, text_scale) + _text_width(part_b, text_scale)
    x = (WIDTH - total) * 0.5
    y = OY + 410.0 * SCALE
    x += _draw_text(px, x, y, text_scale, thickness, WHITE, part_a)
    _draw_text(px, x, y, text_scale, thickness, BABYBLUE, part_b)


def _draw_copyright(px: bytearray) -> None:
    scale = max(1.2, 1.8 * SCALE)
    thickness = max(1.5, 1.6 * SCALE)
    line_h = 24.0 * scale
    x = OX + 40.0 * SCALE
    y = OY + (768.0 - 80.0) * SCALE - line_h
    _draw_text(px, x, y, scale, thickness, COPY, "Copyright (C) 2026")
    _draw_text(px, x, y + line_h, scale, thickness, COPY, "YetiOS Project - MIT License")


def _draw_slug(px: bytearray, slug_x: int, slug_w: int, track_y: int, track_h: int, clip_x0: int, clip_x1: int) -> None:
    bands = 4
    band_w = max(1, slug_w // (bands * 2))
    colors = [BAR_25, BAR_50, BAR_75, BABYBLUE]

    for i, color in enumerate(colors):
        for j in range(band_w):
            xl = slug_x + i * band_w + j
            xr = slug_x + slug_w - 1 - i * band_w - j
            _rect_clip(px, xl, track_y, 1, track_h, color, clip_x0, clip_x1)
            if xr != xl:
                _rect_clip(px, xr, track_y, 1, track_h, color, clip_x0, clip_x1)

    core_x = slug_x + bands * band_w
    core_w = slug_w - 2 * bands * band_w
    if core_w > 0:
        _rect_clip(px, core_x, track_y, core_w, track_h, BABYBLUE, clip_x0, clip_x1)


def _draw_marquee(px: bytearray) -> None:
    x, y = _dp(412, 575)
    w = int(200.0 * SCALE)
    h = max(4, int(14.0 * SCALE))
    x = int(x)
    y = int(y)
    _rect(px, x - 1, y - 1, w + 2, 1, DIM_BLUE)
    _rect(px, x - 1, y + h, w + 2, 1, DIM_BLUE)
    _rect(px, x - 1, y, 1, h, DIM_BLUE)
    _rect(px, x + w, y, 1, h, DIM_BLUE)
    _rect(px, x, y, w, h, BLACK)
    slug_w = max(18, int(40.0 * SCALE))
    slug_x = x + int(w * 0.42)
    _draw_slug(px, slug_x, slug_w, y, h, x, x + w)


def _write_bmp(path: Path, px: bytearray) -> None:
    palette = [RGB.get(i, (0, 0, 0)) for i in range(256)]
    row_size = (WIDTH + 3) & ~3
    pixel_bytes = row_size * HEIGHT
    header_size = 14 + 40 + 256 * 4
    file_size = header_size + pixel_bytes

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.write(b"BM")
        f.write(struct.pack("<IHHI", file_size, 0, 0, header_size))
        f.write(struct.pack("<IIIHHIIIIII", 40, WIDTH, HEIGHT, 1, 8, 0, pixel_bytes, 0, 0, 256, 0))
        for r, g, b in palette:
            f.write(bytes((b, g, r, 0)))
        for y in range(HEIGHT - 1, -1, -1):
            row = px[y * WIDTH:(y + 1) * WIDTH]
            f.write(row)
            f.write(b"\0" * (row_size - WIDTH))


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    )


def _write_png(path: Path, px: bytearray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = bytearray()
    for y in range(HEIGHT):
        raw.append(0)
        for color in px[y * WIDTH:(y + 1) * WIDTH]:
            raw.extend(RGB.get(color, (0, 0, 0)))

    ihdr = struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0)
    with path.open("wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(_png_chunk(b"IHDR", ihdr))
        f.write(_png_chunk(b"IDAT", zlib.compress(bytes(raw), 9)))
        f.write(_png_chunk(b"IEND", b""))


def _draw_loader_pixels() -> bytearray:
    px = bytearray([BLACK] * (WIDTH * HEIGHT))
    _draw_icon(px)
    _draw_wordmark(px)
    _draw_copyright(px)
    _draw_marquee(px)
    return px


def _draw_black_pixels() -> bytearray:
    return bytearray([BLACK] * (WIDTH * HEIGHT))


def write_loader_splash(path: Path) -> None:
    px = _draw_loader_pixels()
    _write_bmp(path, px)


def write_loader_assets(boot_dir: Path) -> None:
    snowcone_px = _draw_loader_pixels()
    black_px = _draw_black_pixels()

    _write_bmp(boot_dir / "yetios-snowcone.bmp", snowcone_px)
    _write_png(boot_dir / "images" / "yetios-snowcone.png", snowcone_px)

    _write_bmp(boot_dir / "yetios-black.bmp", black_px)
    _write_png(boot_dir / "images" / "yetios-black.png", black_px)
    _write_png(boot_dir / "images" / "freebsd-logo-rev.png", black_px)
