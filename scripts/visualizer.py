"""
音频可视化滤镜构建模块（纯 Python 标准库）。

基于 ffmpeg 内置滤镜（showwaves / showspectrum / showfreqs）生成"音频响应"动画，
配合封面的 Ken Burns 缩放叠加，形成 MV 的动态背景。

相比原版 Karaoke 脚本的优化：
  1. 从单一"波形"扩展为多风格（波形 / 频谱 / 频谱条 / 圆形频谱）；
  2. 支持自定义颜色、透明度、高度与位置；
  3. 参数通过 dataclass 传递，便于扩展新风格。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class VisualConfig:
    style: str = "wave"          # wave | spectrum | bars | dots
    color: str = "0xFFFFFF"      # 主色（0xRRGGBB）
    alpha: float = 0.9           # 不透明度 0-1
    height: int = 160            # 可视化区域高度（px）
    position: str = "bottom"     # bottom | top | center
    width: int = 1920            # 目标宽度
    fps: int = 25                # 输出帧率
    margin: int = 24             # 距离画面边缘的留白


def _color_arg(color: str, alpha: float) -> str:
    """ffmpeg 颜色参数：colors=0xFFFFFF@0.9"""
    if alpha < 1.0:
        return f"{color}@{alpha:.2f}"
    return color


def build_visual_filter(cfg: VisualConfig) -> str:
    """返回针对输入音频流（索引 [1:a]）的可视化滤镜串，输出标签为 [vis]。"""
    color = _color_arg(cfg.color, cfg.alpha)
    w, h = cfg.width, cfg.height

    if cfg.style == "wave":
        # 中心线波形，适合叠在画面底部
        f = (
            f"showwaves=s={w}x{h}:mode=cline:rate={cfg.fps}"
            f":colors={color}:scale=sqrt"
        )
    elif cfg.style == "spectrum":
        # 滚动频谱热力图（showspectrum 无 rate，用 fps 滤镜统一帧率）
        f = (
            f"showspectrum=s={w}x{h}:mode=combined:slide=scroll"
            f":scale=log:color=rainbow:saturation=1.2"
            f",fps={cfg.fps}"
        )
    elif cfg.style == "bars":
        # 频谱柱状图，跳跃感强
        f = (
            f"showfreqs=s={w}x{h}:mode=bar:fscale=log"
            f":colors={color}:win_size=512:rate={cfg.fps}"
        )
    elif cfg.style == "dots":
        # 频谱点阵，科技感
        f = (
            f"showfreqs=s={w}x{h}:mode=dot:fscale=log"
            f":colors={color}:win_size=512:rate={cfg.fps}"
        )
    else:
        raise ValueError(f"未知可视化风格: {cfg.style}")

    return f"[1:a]{f}[vis]"


def overlay_position(cfg: VisualConfig) -> str:
    """返回 overlay 滤镜的 x:y 表达式，把 [vis] 叠到 [bg] 上。"""
    w, h = cfg.width, cfg.height
    if cfg.position == "bottom":
        return f"overlay=(W-w)/2:H-h-{cfg.margin}"
    if cfg.position == "top":
        return f"overlay=(W-w)/2:{cfg.margin}"
    if cfg.position == "center":
        return f"overlay=(W-w)/2:(H-h)/2"
    raise ValueError(f"未知位置: {cfg.position}")


def build_kenburns(width: int, height: int, duration: float,
                   fps: int = 25, zoom_min: float = 1.05,
                   zoom_amp: float = 0.05, period: float = 10.0) -> str:
    """Ken Burns 缩放滤镜：封面图轻微放大 + 正弦缓动，避免静态呆板。"""
    frames = int(round(duration * fps))
    if frames < 1:
        frames = 1
    zoom_period = max(int(period * fps), 1)
    # 输入图先放大 1.2 倍留出缩放余量，避免边缘露白
    return (
        f"scale={int(width * 1.2)}:{int(height * 1.2)}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        f"zoompan=z='{zoom_min}+{zoom_amp}*sin(on/{zoom_period}*2*PI)':"
        f"x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':"
        f"d={frames}:s={width}x{height}:fps={fps}"
    )
