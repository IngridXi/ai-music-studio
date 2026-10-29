"""
MV 动画合成脚本 —— 把「封面图 + 歌曲音频 + 歌词」合成为一条动态 MV。

基于开源项目 Karaoke-Music-Vid-Generator 的核心思路重写并优化：
  1. 跨平台软件编码（原版 VAAPI 仅限 Linux），可选 macOS VideoToolbox 硬编；
  2. 完整支持中文歌词与中文字体（原版硬编码英文 + Comic Sans 字体）；
  3. 直接消费歌曲生成阶段产出的 LRC 时间戳，无需 Whisper 转录、无需 API key；
  4. 多种音频可视化风格（波形 / 频谱 / 频谱条 / 圆形频谱）；
  5. 支持逐字卡拉OK高亮（ASS \\k 标签）与普通字幕（SRT）两种模式。

依赖：仅需系统安装 ffmpeg（含 libass）。macOS: brew install ffmpeg
用法：
  python3 make_mv.py 歌曲.mp3 封面.jpg -l 歌词.lrc -o 成片.mp4
  python3 make_mv.py 歌曲.mp3 封面.jpg -l 歌词.txt --style spectrum --karaoke
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lrc as lrc_mod          # noqa: E402
from visualizer import (       # noqa: E402
    VisualConfig, build_visual_filter, overlay_position, build_kenburns,
)


# --------------------------------------------------------------------------- #
# 字体检测（中文优先）
# --------------------------------------------------------------------------- #
FONT_CANDIDATES = [
    # (字体名, [候选文件路径...])
    ("PingFang SC", ["/System/Library/Fonts/PingFang.ttc",
                     "/System/Library/Fonts/Hiragino Sans GB.ttc"]),
    ("STHeiti", ["/System/Library/Fonts/STHeiti Medium.ttc",
                 "/System/Library/Fonts/STHeiti Light.ttc"]),
    ("Songti SC", ["/System/Library/Fonts/Supplemental/Songti.ttc"]),
    ("Microsoft YaHei", ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyh.ttf"]),
    ("Noto Sans CJK SC", ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                          "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc"]),
    ("DejaVu Sans", ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]),
]


def detect_font() -> tuple:
    """返回 (字体名, 字体目录)，优先命中中文字体。"""
    for name, paths in FONT_CANDIDATES:
        for p in paths:
            if Path(p).exists():
                return name, str(Path(p).parent)
    return "sans-serif", ""


def find_ffmpeg(override: str | None = None) -> str:
    if override:
        if not Path(override).exists() and shutil.which(override) is None:
            raise FileNotFoundError(f"找不到 ffmpeg: {override}")
        return override
    exe = shutil.which("ffmpeg")
    if not exe:
        raise FileNotFoundError(
            "未找到 ffmpeg，请先安装：macOS 执行 `brew install ffmpeg`；"
            "或通过 --ffmpeg 指定二进制路径。"
        )
    return exe


def _run(cmd: list, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"命令失败: {' '.join(cmd)}\n{r.stderr[-2000:]}")
    return r


def probe_duration(ffprobe: str, audio_path: Path) -> float:
    exe = Path(ffprobe) if ffprobe else shutil.which("ffprobe")
    if not exe:
        return 90.0
    try:
        r = _run([str(exe), "-v", "quiet", "-show_entries", "format=duration",
                  "-of", "csv=p=0", str(audio_path)])
        return float(r.stdout.strip())
    except Exception:
        return 90.0


# --------------------------------------------------------------------------- #
# 歌词 → 字幕
# --------------------------------------------------------------------------- #
def load_lyric_lines(args: argparse.Namespace, duration: float):
    """根据输入类型返回 (lyric_lines, subtitle_path, ass_mode)。"""
    if args.no_subtitles:
        return None, None, False

    if args.ass:
        return None, Path(args.ass), True
    if args.srt:
        return None, Path(args.srt), False

    lyric_path = Path(args.lyrics) if args.lyrics else None
    if lyric_path and lyric_path.exists():
        raw = lyric_path.read_text(encoding="utf-8")
        if lyric_path.suffix.lower() == ".lrc":
            lines = lrc_mod.parse_lrc(raw)
            return lines, None, args.karaoke
        # 纯文本歌词：均分时间戳
        lines = lrc_mod.lyrics_to_lrc(raw.splitlines(), duration)
        return lines, None, args.karaoke

    return None, None, False


def build_subtitle(workdir: Path, lines, duration: float,
                   args: argparse.Namespace) -> Path | None:
    """把歌词行渲染为字幕文件（ASS 或 SRT），返回文件路径。"""
    if not lines:
        return None
    fontname, _ = detect_font()
    w, h = _parse_resolution(args.resolution)
    if args.karaoke:
        ass = lrc_mod.to_ass(lines, width=w, height=h,
                             fontname=args.font or fontname,
                             fontsize=args.fontsize, margin_v=args.margin_v)
        out = workdir / "lyrics.ass"
    else:
        srt = lrc_mod.to_srt(lines)
        out = workdir / "lyrics.srt"
        out.write_text(srt, encoding="utf-8")
        return out
    out.write_text(ass, encoding="utf-8")
    return out


def _parse_resolution(res: str) -> tuple:
    m = re.match(r"(\d+)x(\d+)", res)
    if not m:
        raise ValueError(f"分辨率格式错误: {res}")
    return int(m.group(1)), int(m.group(2))


# --------------------------------------------------------------------------- #
# 合成主逻辑
# --------------------------------------------------------------------------- #
def make_mv(args: argparse.Namespace) -> Path:
    ffmpeg = find_ffmpeg(args.ffmpeg)
    audio = Path(args.audio)
    image = Path(args.image)
    out = Path(args.output) if args.output else audio.with_suffix(".mv.mp4")

    if not audio.exists():
        raise FileNotFoundError(f"音频不存在: {audio}")
    if not image.exists():
        raise FileNotFoundError(f"封面图不存在: {image}")

    duration = args.duration or probe_duration(None, audio)
    w, h = _parse_resolution(args.resolution)
    fps = args.fps

    lines, sub_path, ass_mode = load_lyric_lines(args, duration)
    workdir = out.parent / ".mv_tmp"
    workdir.mkdir(parents=True, exist_ok=True)
    if lines:
        sub_path = build_subtitle(workdir, lines, duration, args)

    # 1) 封面 Ken Burns 动画
    kb = build_kenburns(w, h, duration, fps=fps)
    # 2) 音频可视化
    vcfg = VisualConfig(style=args.style, color=args.color, alpha=args.alpha,
                        height=args.vis_height, position=args.position,
                        width=w, fps=fps, margin=args.margin)
    vis = build_visual_filter(vcfg)
    ovl = overlay_position(vcfg)

    # 3) 组装 filter_complex（字幕通过 libass 自动匹配系统字体，无需显式 fontsdir）
    parts = [f"[0:v]{kb}[bg]", f"{vis}", f"[bg][vis]{ovl}[comp]"]
    if sub_path:
        if ass_mode:
            parts.append(f"[comp]ass={_escape_path(sub_path)}[vout]")
        else:
            parts.append(f"[comp]subtitles={_escape_path(sub_path)}[vout]")
    else:
        parts[-1] = parts[-1].replace("[comp]", "[vout]", 1)
    filter_complex = ";".join(parts)

    # 4) 编码参数
    cmd = [ffmpeg, "-y",
           "-loop", "1", "-i", str(image),
           "-i", str(audio),
           "-filter_complex", filter_complex,
           "-map", "[vout]", "-map", "1:a",
           "-c:a", "aac", "-b:a", args.audio_bitrate,
           "-pix_fmt", "yuv420p", "-movflags", "+faststart"]

    if args.hwaccel == "videotoolbox":
        cmd += ["-c:v", "h264_videotoolbox", "-b:v", args.video_bitrate]
    else:
        cmd += ["-c:v", "libx264", "-preset", args.preset, "-crf", str(args.crf)]

    cmd += ["-shortest", str(out)]

    print(f"▶ 合成 MV（{duration:.1f}s, {w}x{h}, 风格={args.style}）")
    print("  " + " ".join(cmd))
    r = _run(cmd)
    print(f"✓ 已生成: {out}")
    return out


def _escape_path(p: Path) -> str:
    """ffmpeg 滤镜中的路径需转义 Windows 冒号与反斜杠。"""
    s = str(p)
    s = s.replace("\\", "/")
    s = s.replace(":", "\\:")
    return s


def main() -> int:
    p = argparse.ArgumentParser(description="AI 歌曲 MV 动画合成")
    p.add_argument("audio", help="歌曲音频文件（mp3/wav/flac）")
    p.add_argument("image", help="封面图片（jpg/png）")
    p.add_argument("-o", "--output", help="输出 MP4 路径（默认 <音频名>.mv.mp4）")
    p.add_argument("-l", "--lyrics", help="歌词文件（.lrc 或纯文本 .txt）")
    p.add_argument("--srt", help="已有 SRT 字幕文件（跳过歌词处理）")
    p.add_argument("--ass", help="已有 ASS 字幕文件（跳过歌词处理）")
    p.add_argument("--karaoke", action="store_true", help="启用逐字卡拉OK高亮（需 .lrc 词级时间戳）")
    p.add_argument("--no-subtitles", action="store_true", help="不添加字幕")
    p.add_argument("--style", default="wave",
                   choices=["wave", "spectrum", "bars", "dots"],
                   help="可视化风格（默认 wave）")
    p.add_argument("--color", default="0xFFFFFF", help="可视化颜色（0xRRGGBB）")
    p.add_argument("--alpha", type=float, default=0.9, help="可视化不透明度 0-1")
    p.add_argument("--vis-height", type=int, default=160, help="可视化区域高度（px）")
    p.add_argument("--position", default="bottom",
                   choices=["bottom", "top", "center"], help="可视化位置")
    p.add_argument("--margin", type=int, default=24, help="可视化距边缘留白（px）")
    p.add_argument("-r", "--resolution", default="1920x1080", help="输出分辨率 WxH")
    p.add_argument("--fps", type=int, default=25, help="输出帧率")
    p.add_argument("--font", help="字幕字体名（默认自动检测中文字体）")
    p.add_argument("--fontsize", type=int, default=64, help="字幕字号")
    p.add_argument("--margin-v", type=int, default=60, help="字幕底部边距")
    p.add_argument("--duration", type=float, help="音频时长（秒，默认 ffprobe 自动探测）")
    p.add_argument("--preset", default="medium", help="x264 预设（ultrafast~slow）")
    p.add_argument("--crf", type=int, default=18, help="x264 质量（越小越清晰，默认 18）")
    p.add_argument("--audio-bitrate", default="192k", help="音频码率")
    p.add_argument("--video-bitrate", default="8M", help="硬编码视频码率")
    p.add_argument("--hwaccel", choices=["none", "videotoolbox"], default="none",
                   help="硬件加速（macOS 可选 videotoolbox）")
    p.add_argument("--ffmpeg", help="ffmpeg 可执行文件路径")
    args = p.parse_args()

    try:
        make_mv(args)
        return 0
    except Exception as e:
        print(f"✗ {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
