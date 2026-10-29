#!/usr/bin/env python3
"""
多图运镜 MV 合成脚本 —— 把「多张画面 + 歌曲音频 + 歌词」合成为带镜头运动的电影感 MV。

相比 make_mv.py（单封面 + 波形）的升级：
  1. 多张画面按歌词时间轴依次呈现，每张做独立运镜（推/拉/摇/移，见 camera.py）；
  2. 画面之间用 xfade 淡入淡出转场，过渡自然；
  3. 叠加文化纹样边框（古建窗棂式框景）与逐字卡拉OK歌词字幕。

依赖：ffmpeg（含 libass）、lrc.py、camera.py。
用法：
  python3 slideshow_mv.py 歌曲.mp3 分镜.json -l 歌词.lrc -o 成片.mp4

分镜.json 格式：
{
  "ornament": "纹样边框.png",      // 可选，装饰叠加层
  "fade": 0.8,                     // 转场时长（秒）
  "shots": [
    {"image": "01_云冈石窟.png", "move": "pan_right", "duration": 12.5},
    ...
  ]
}
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lrc as lrc_mod            # noqa: E402
from camera import build_camera_move  # noqa: E402


FONT_CANDIDATES = [
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
    for name, paths in FONT_CANDIDATES:
        for p in paths:
            if Path(p).exists():
                return name, str(Path(p).parent)
    return "sans-serif", ""


def _run(cmd: list, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"命令失败: {' '.join(cmd)}\n{r.stderr[-3000:]}")
    return r


def find_ffmpeg(override: str | None = None) -> str:
    if override:
        if not Path(override).exists() and shutil.which(override) is None:
            raise FileNotFoundError(f"找不到 ffmpeg: {override}")
        return override
    exe = shutil.which("ffmpeg")
    if not exe:
        raise FileNotFoundError("未找到 ffmpeg，请先安装")
    return exe


def probe_duration(audio_path: Path, ffmpeg: str = "ffmpeg") -> float:
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        try:
            r = _run([ffprobe, "-v", "quiet", "-show_entries", "format=duration",
                      "-of", "csv=p=0", str(audio_path)])
            val = r.stdout.strip()
            if val and val not in ("N/A", "nan"):
                return float(val)
        except Exception:
            pass
    try:
        r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(audio_path)],
                           capture_output=True, text=True)
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    except Exception:
        pass
    return 90.0


def _escape(p) -> str:
    s = str(p).replace("\\", "/").replace(":", "\\:")
    return s


def build_storyboard_filter(shots, w, h, fps, fade, audio_duration):
    """构造 filter_complex：每图运镜 -> xfade 串联。返回 (filter_complex, 输入文件列表)。"""
    n = len(shots)
    inputs = [s["image"] for s in shots]
    parts = []
    VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm"}
    # 1) 每个 shot 处理：视频片段直接截取，图片做运镜
    for i, s in enumerate(shots):
        is_video = Path(s["image"]).suffix.lower() in VIDEO_EXTS
        dur = s["duration"]
        if is_video:
            cam = (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
                   f"crop={w}:{h},trim=duration={dur:.3f},"
                   f"setpts=PTS-STARTPTS,fps={fps}")
        else:
            move = s.get("move", "zoom_in")
            cam = build_camera_move(move, w, h, fps, dur)
        parts.append(f"[{i}:v]{cam}[cam{i}]")

    # 2) xfade 串联（补偿转场损失，使总时长对齐音频）
    if n == 1:
        parts.append(f"[cam0]trim=duration={audio_duration},setpts=PTS-STARTPTS[vbase]")
    else:
        cur = "cam0"
        acc = shots[0]["duration"]
        for i in range(1, n):
            offset = acc - fade
            nxt = f"x{i-1}"
            parts.append(
                f"[{cur}][cam{i}]xfade=transition=fade:duration={fade}"
                f":offset={offset:.3f}[{nxt}]"
            )
            cur = nxt
            acc = acc + shots[i]["duration"] - fade
        # 尾部补足到音频时长（转场损失）
        parts.append(f"[{cur}]tpad=stop_mode=clone:stop_duration="
                     f"{max(audio_duration - acc, 0):.3f}[vbase]")

    return ";".join(parts), inputs


def main() -> int:
    p = argparse.ArgumentParser(description="多图运镜 MV 合成")
    p.add_argument("audio", help="歌曲音频")
    p.add_argument("storyboard", help="分镜 JSON（shots 列表）")
    p.add_argument("-o", "--output", help="输出 MP4")
    p.add_argument("-l", "--lyrics", help="歌词 .lrc 文件")
    p.add_argument("--karaoke", action="store_true", help="逐字卡拉OK高亮（需词级时间戳 LRC）")
    p.add_argument("-r", "--resolution", default="1920x1080")
    p.add_argument("--fps", type=int, default=25)
    p.add_argument("--fontsize", type=int, default=60)
    p.add_argument("--margin-v", type=int, default=110, help="字幕底部边距（避开纹样边框）")
    p.add_argument("--preset", default="medium")
    p.add_argument("--crf", type=int, default=18)
    p.add_argument("--audio-bitrate", default="192k")
    p.add_argument("--ffmpeg", help="ffmpeg 路径")
    args = p.parse_args()

    ffmpeg = find_ffmpeg(args.ffmpeg)
    audio = Path(args.audio)
    sb_path = Path(args.storyboard)
    if not audio.exists():
        print(f"✗ 音频不存在: {audio}"); return 1
    if not sb_path.exists():
        print(f"✗ 分镜不存在: {sb_path}"); return 1

    storyboard = json.loads(sb_path.read_text(encoding="utf-8"))
    shots = storyboard["shots"]
    fade = float(storyboard.get("fade", 0.8))
    base_dir = sb_path.parent
    # logo（左上角品牌标识）
    logo = storyboard.get("logo")
    if logo:
        logo = str((base_dir / logo).resolve())
    logo_width = int(storyboard.get("logo_width", 240))
    logo_x = storyboard.get("logo_x", 40)
    logo_y = storyboard.get("logo_y", 40)
    # 书法标题
    title = storyboard.get("title", "")
    title_font = storyboard.get("title_font", "")
    if title_font:
        title_font = str((base_dir / title_font).resolve())
    title_size = int(storyboard.get("title_size", 110))
    title_color = storyboard.get("title_color", "0xD4AF37")
    title_x = storyboard.get("title_x", "(w-text_w)/2")
    title_y = storyboard.get("title_y", 60)
    title_enable = storyboard.get("title_enable", "1")
    # 图片路径相对分镜文件目录解析
    for s in shots:
        s["image"] = str((base_dir / s["image"]).resolve())

    m = re.match(r"(\d+)x(\d+)", args.resolution)
    w, h = int(m.group(1)), int(m.group(2))
    fps = args.fps

    # 补偿转场重叠：xfade 会让第 k 段的切换点比歌词时间戳提前 k*fade 秒，
    # 前 n-1 段每段多加 fade，使画面切换精确对齐歌词时间戳。
    if len(shots) > 1:
        for i in range(len(shots) - 1):
            shots[i]["duration"] += fade
    # 校准：xfade 后实际总时长 = sum - (n-1)*fade，与音频对齐
    audio_dur = probe_duration(audio, ffmpeg)
    shot_sum = sum(s["duration"] for s in shots)
    effective = shot_sum - (len(shots) - 1) * fade if len(shots) > 1 else shot_sum
    if effective < audio_dur:
        shots[-1]["duration"] += (audio_dur - effective)

    filter_complex, inputs = build_storyboard_filter(shots, w, h, fps, fade, audio_dur)

    # 字幕
    sub_part = ""
    workdir = Path(args.output).parent / ".mv_tmp"
    if args.lyrics and Path(args.lyrics).exists():
        workdir.mkdir(parents=True, exist_ok=True)
        raw = Path(args.lyrics).read_text(encoding="utf-8")
        lines = lrc_mod.parse_lrc(raw)
        if lines:
            fontname, _ = detect_font()
            if args.karaoke:
                ass = lrc_mod.to_ass(lines, width=w, height=h,
                                     fontname=fontname, fontsize=args.fontsize,
                                     margin_v=args.margin_v)
                sub_path = workdir / "lyrics.ass"
                sub_path.write_text(ass, encoding="utf-8")
                sub_part = f"[vbase]ass={_escape(sub_path)}[vsub]"
            else:
                srt = lrc_mod.to_srt(lines)
                sub_path = workdir / "lyrics.srt"
                sub_path.write_text(srt, encoding="utf-8")
                sub_part = f"[vbase]subtitles={_escape(sub_path)}[vsub]"

    # 组装视频尾链：vbase -> (字幕) -> (logo) -> (书法标题) -> vout
    chain = filter_complex          # 以 [vbase] 结尾
    cur = "vbase"
    if sub_part:
        chain += ";" + sub_part      # [vbase]ass=...[vsub]
        cur = "vsub"
    if logo and Path(logo).exists():
        inputs.append(logo)
        lidx = len(inputs) - 1
        chain += f";[{lidx}:v]scale={logo_width}:-1[lgs];[{cur}][lgs]overlay={logo_x}:{logo_y}:format=auto[vlg]"
        cur = "vlg"
    if title and title_font and Path(title_font).exists():
        fontfile = str(Path(title_font)).replace("\\", "/").replace(":", "\\:")
        chain += (f";[{cur}]drawtext=fontfile='{fontfile}':text='{title}':"
                  f"fontsize={title_size}:fontcolor={title_color}:"
                  f"x={title_x}:y={title_y}:enable='{title_enable}'[vout]")
        cur = "vout"
    if cur != "vout":
        chain += f";[{cur}]null[vout]"
    filter_complex = chain

    out = Path(args.output) if args.output else audio.with_suffix(".mv.mp4")

    VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm"}
    cmd = [ffmpeg, "-y"]
    for s in shots:
        is_video = Path(s["image"]).suffix.lower() in VIDEO_EXTS
        if is_video:
            cmd += ["-stream_loop", "-1", "-i", str(s["image"])]
        else:
            cmd += ["-loop", "1", "-t", f"{s['duration']:.3f}", "-i", str(s["image"])]
    if logo and Path(logo).exists():
        cmd += ["-loop", "1", "-i", str(logo)]
    cmd += ["-i", str(audio)]
    cmd += ["-filter_complex", filter_complex]
    cmd += ["-map", "[vout]", "-map", f"{len(inputs)}:a"]
    cmd += ["-c:a", "aac", "-b:a", args.audio_bitrate,
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-c:v", "libx264", "-preset", args.preset, "-crf", str(args.crf),
            "-shortest", str(out)]

    print(f"▶ 合成多图运镜 MV（{len(shots)} 段，{audio_dur:.1f}s, {w}x{h}）")
    _run(cmd)
    print(f"✓ 已生成: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
