"""
一键全流程编排 —— 主题/歌词 → AI 歌曲 → 封面 → MV 成片。

把三个独立模块串联起来：
  1. generate_song ：调用 ACE-Step 生成带人声歌曲 + 歌词 + LRC；
  2. generate_cover：生成渐变风格专辑封面；
  3. make_mv      ：合成带音频可视化 + 逐字歌词的 MV 动画。

用法：
  python3 pipeline.py --topic "一首关于夏天和告别的中文流行情歌" \
      --style "温暖治愈的流行，钢琴与弦乐" --lang zh -o ./my_song

  # 用已有歌词
  python3 pipeline.py --lyrics 歌词.txt --style "..." --title "歌名" -o ./my_song
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_song as gs      # noqa: E402
import generate_cover as gc     # noqa: E402
import make_mv as mv            # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="AI 歌曲 + MV 一键生成")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--topic", help="歌曲主题（模型自动写词+作曲）")
    g.add_argument("--lyrics", help="歌词文件路径")
    p.add_argument("--title", help="歌曲标题（默认用主题前若干字/文件名）")
    p.add_argument("--style", help="音乐风格描述")
    p.add_argument("--artist", default="AI 音乐工作室", help="封面署名")
    p.add_argument("--lang", default="zh", help="人声语言（默认 zh）")
    p.add_argument("--duration", type=float, help="时长（秒）")
    p.add_argument("--bpm", type=int, help="BPM")
    p.add_argument("--model", help="DiT 模型，如 acestep-v15-turbo")
    p.add_argument("--host", default=gs.DEFAULT_HOST, help="ACE-Step API 主机")
    p.add_argument("--port", type=int, default=gs.DEFAULT_PORT, help="ACE-Step API 端口")
    p.add_argument("--no-thinking", action="store_true", help="关闭 LM 思考")
    # MV 参数
    p.add_argument("--mv-style", default="wave",
                   choices=["wave", "spectrum", "bars", "dots"], help="MV 可视化风格")
    p.add_argument("--karaoke", action="store_true", default=True, help="逐字卡拉OK高亮")
    p.add_argument("--resolution", default="1920x1080", help="MV 分辨率")
    p.add_argument("--hwaccel", choices=["none", "videotoolbox"], default="none")
    p.add_argument("-o", "--out-dir", default="./output", help="输出目录")
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---------- 1. 生成歌曲 ----------
    client = gs.AceStepClient(args.host, args.port)
    if not client.health():
        print("✗ 无法连接 ACE-Step API。请先启动服务：")
        print("    cd ACE-Step-1.5 && uv run acestep-api")
        return 1

    # 复用 generate_song 的参数构造
    gs_args = argparse.Namespace(
        topic=getattr(args, "topic", None),
        lyrics=getattr(args, "lyrics", None),
        style=args.style, lang=args.lang, duration=args.duration, bpm=args.bpm,
        model=args.model, steps=8, batch=1, format="mp3",
        no_thinking=args.no_thinking,
        title=args.title or _default_title(args), out_dir=str(out_dir / "songs"),
    )
    songs = gs.generate_song(client, gs_args, out_dir / "songs")
    if not songs or not songs[0].get("audio"):
        print("✗ 未生成出音频，终止。")
        return 1

    audio = songs[0]["audio"]
    lrc_file = songs[0].get("lrc")

    title = args.title or _default_title(args)

    # ---------- 2. 生成封面 ----------
    cover = out_dir / "cover.jpg"
    try:
        gc.generate_cover(title, args.artist, cover, theme=args.style or args.topic or title)
    except Exception as e:
        print(f"⚠ 封面生成失败（将用纯色兜底）: {e}")
        cover = _fallback_cover(out_dir)

    # ---------- 3. 合成 MV ----------
    mv_args = argparse.Namespace(
        audio=audio, image=cover, output=out_dir / f"{title}.mp4",
        lyrics=lrc_file, srt=None, ass=None, karaoke=args.karaoke,
        no_subtitles=(lrc_file is None),
        style=args.mv_style, color="0xFFFFFF", alpha=0.9, vis_height=160,
        position="bottom", margin=24, resolution=args.resolution, fps=25,
        font=None, fontsize=64, margin_v=60, duration=None,
        preset="medium", crf=18, audio_bitrate="192k", video_bitrate="8M",
        hwaccel=args.hwaccel, ffmpeg=None,
    )
    final = mv.make_mv(mv_args)

    print("\n===== 全部完成 =====")
    print(f"  歌曲: {audio}")
    print(f"  封面: {cover}")
    print(f"  MV : {final}")
    return 0


def _default_title(args) -> str:
    if args.topic:
        # 取主题前 12 个字符作为标题
        t = args.topic.strip()
        return t[:12] if len(t) > 12 else t
    if args.lyrics and Path(args.lyrics).exists():
        return Path(args.lyrics).stem
    return "ai_song"


def _fallback_cover(out_dir: Path) -> Path:
    try:
        from PIL import Image
    except ImportError:
        # 连 Pillow 都没有时，让 make_mv 报错提示，这里给个占位
        return out_dir / "cover.jpg"
    img = Image.new("RGB", (1920, 1080), (30, 30, 40))
    cover = out_dir / "cover.jpg"
    img.save(cover, quality=92)
    return cover


if __name__ == "__main__":
    raise SystemExit(main())
