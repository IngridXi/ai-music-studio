"""
AI 歌曲封面生成脚本 —— 生成渐变风格 + 标题文字的专辑封面。

说明：
  - 这是"零成本兜底"方案：无网络、无 GPU 也能立刻产出像样的封面；
  - 想要更精美的封面，可在 WorkBuddy 中用文生图工具生成图片后，
    直接作为 make_mv.py 的封面输入（本脚本可跳过）。

依赖：Pillow（仅本脚本需要）。安装：pip install pillow
用法：
  python3 generate_cover.py --title "夏天的风" --artist "AI 音乐工作室" -o cover.jpg
  python3 generate_cover.py --title "..." --gradient "#FF6B6B" "#4ECDC4"
"""

from __future__ import annotations

import argparse
import hashlib
import math
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = ImageDraw = ImageFont = None  # type: ignore


# 预设渐变配色（按主题词 hash 选取）
PALETTES = [
    ("#FF6B6B", "#4ECDC4"),  # 珊瑚 → 青
    ("#667EEA", "#764BA2"),  # 蓝 → 紫
    ("#F093FB", "#F5576C"),  # 粉 → 红
    ("#4FACFE", "#00F2FE"),  # 天蓝 → 青
    ("#43E97B", "#38F9D7"),  # 绿 → 薄荷
    ("#FA709A", "#FEE140"),  # 粉 → 黄
    ("#30CFD0", "#330867"),  # 青 → 深蓝
    ("#A8EDEA", "#FED6E3"),  # 浅青 → 浅粉
]


def _pick_palette(theme: str) -> tuple:
    h = hashlib.md5(theme.encode("utf-8")).hexdigest()
    idx = int(h, 16) % len(PALETTES)
    return PALETTES[idx]


def _hex2rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _detect_font(size: int):
    candidates = [
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    for p in candidates:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _draw_gradient(img, c1, c2, angle_deg: float = 30.0):
    """在图像上绘制线性渐变。"""
    w, h = img.size
    angle = math.radians(angle_deg)
    draw = ImageDraw.Draw(img)
    # 渐变轴方向向量
    dx, dy = math.cos(angle), math.sin(angle)
    # 投影长度
    extent = abs(dx) * w + abs(dy) * h
    for i in range(int(extent) + 1):
        t = i / extent if extent else 0
        color = _lerp(c1, c2, t)
        # 沿法线方向画一条细线
        nx, ny = -dy, dx
        if abs(nx) > abs(ny):
            x = i - abs(dy) * h / 2
            draw.line([(x, 0), (x, h)], fill=color, width=1)
        else:
            y = i - abs(dx) * w / 2
            draw.line([(0, y), (w, y)], fill=color, width=1)


def generate_cover(title: str, artist: str, out: Path, size: tuple = (1920, 1080),
                   gradient: tuple | None = None, theme: str = "") -> Path:
    if Image is None:
        raise RuntimeError("需要安装 Pillow：pip install pillow")

    if gradient is None:
        gradient = _pick_palette(theme or title)
    c1, c2 = (_hex2rgb(g) for g in gradient)

    img = Image.new("RGB", size)
    _draw_gradient(img, c1, c2, angle_deg=25)

    draw = ImageDraw.Draw(img)
    w, h = size

    # 半透明装饰圆（营造层次感）
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    r = int(min(w, h) * 0.55)
    od.ellipse([w - r, -r // 2, w + r, h + r // 2], fill=(255, 255, 255, 40))
    od.ellipse([-r // 2, h - r, r // 2, h + r], fill=(255, 255, 255, 30))
    img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"), (0, 0))

    draw = ImageDraw.Draw(img)

    # 标题（大号）
    font_title = _detect_font(int(h * 0.12))
    font_artist = _detect_font(int(h * 0.05))

    def _center_text(y, text, font, shadow=True):
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        x = (w - tw) // 2
        if shadow:
            draw.text((x + 3, y + 3), text, font=font, fill=(0, 0, 0, 120))
        draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))

    title_y = int(h * 0.40)
    _center_text(title_y, title, font_title)

    if artist:
        artist_y = title_y + int(h * 0.16)
        _center_text(artist_y, artist, font_artist)

    out = out if out.suffix else out.with_suffix(".jpg")
    img.convert("RGB").save(out, quality=92)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="AI 歌曲封面生成")
    p.add_argument("--title", required=True, help="歌曲标题")
    p.add_argument("--artist", default="", help="艺术家/工作室名")
    p.add_argument("--theme", default="", help="主题词（用于自动配色）")
    p.add_argument("--gradient", nargs=2, metavar=("C1", "C2"),
                   help="自定义渐变色，如 --gradient '#FF6B6B' '#4ECDC4'")
    p.add_argument("--size", default="1920x1080", help="尺寸 WxH")
    p.add_argument("-o", "--output", default="cover.jpg", help="输出图片路径")
    args = p.parse_args()

    w, h = (int(x) for x in args.size.split("x"))
    try:
        out = generate_cover(args.title, args.artist, Path(args.output),
                             size=(w, h), gradient=tuple(args.gradient) if args.gradient else None,
                             theme=args.theme)
        print(f"✓ 已生成封面: {out}")
        return 0
    except Exception as e:
        print(f"✗ {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
