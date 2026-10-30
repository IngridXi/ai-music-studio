"""
AI 歌曲局部修改脚本 —— 只重新生成歌曲的某一句（甚至某个词），其余部分保持不变。

技术方案：ACE-Step 1.5 的 Repaint（局部重绘）能力，通过官方 REST API
（POST /release_task，task_type="repaint"）实现：
  - repainting_start / repainting_end 指定重绘时间区间（秒）；
  - chunk_mask_mode="explicit" 把该区间作为 0/1 mask，区间外音频保持原样；
  - caption 描述重绘内容的期望（改了词就写新词，没改就写"重唱/修复发音"）；
  - lyrics 传完整歌词（目标行替换为新词），帮助模型对齐唱词。

定位方式（三选一）：
  --line N            第 N 行歌词（只数带时间戳的歌词行，1 起）
  --line-text 文本    匹配包含该文本的歌词行（多条命中时报错，改用 --line）
  --word 文本         词/字级定位。增强 LRC（行内 <mm:ss.xx> 词级时间戳）用真实
                      时间戳；普通 LRC 按行内字数均分估算。

注意：
  1. Repaint 只有 base 系列模型支持（acestep-v15-base / xl-base），
     turbo / sft 不支持，脚本默认使用 acestep-v15-base。
  2. 重绘区间不宜过短（模型按 chunk 处理），默认最短 3 秒，自动向两侧外扩。
  3. 前置条件与 generate_song.py 相同：ACE-Step 服务需常驻
     （cd ACE-Step-1.5 && uv run acestep-api）。

用法示例：
  # 第 5 句唱错了，重唱一遍（不换词）
  python3 edit_song.py 歌曲.mp3 -l 歌曲.lrc --line 5

  # 把"夏天的风"里的"风"换个唱法/修复发音
  python3 edit_song.py 歌曲.mp3 -l 歌曲.lrc --word "风"

  # 把第 5 句换成新词重新唱
  python3 edit_song.py 歌曲.mp3 -l 歌曲.lrc --line 5 --new-lyrics "冬天的雪"

  # 词级 + 第 2 次出现 + 自定义外扩
  python3 edit_song.py 歌曲.mp3 -l 歌曲.lrc --word "你" --occurrence 2 --pad 1.0
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_song  # noqa: E402  (复用 AceStepClient / wait_for_result / 结果解析)
import lrc  # noqa: E402


MIN_REPAINT_LEN = 3.0  # 重绘区间最短时长（秒），过短会向两侧外扩


# --------------------------------------------------------------------------- #
# 定位：从 LRC 求出重绘时间区间
# --------------------------------------------------------------------------- #
def reconstruct_lyrics_text(lrc_path: Path) -> str:
    """从 LRC 文件还原完整歌词文本（保留 [Verse] 等结构标签，去掉时间戳）。"""
    out = []
    for raw in lrc_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if lrc._META_TAG.match(line):
            continue
        # 结构标签（无时间的 [..] 行）原样保留
        if re.match(r"^\[[A-Za-z][^\]]*\]$", line):
            out.append(line)
            continue
        # 去时间戳
        body = lrc._LRC_TAG.sub("", line)
        body = lrc._INLINE_WORD.sub("", body).strip()
        if body:
            out.append(body)
    return "\n".join(out)


def resolve_line(lines, args) -> lrc.Line:
    """按 --line / --line-text 定位歌词行。"""
    if args.line is not None:
        if not (1 <= args.line <= len(lines)):
            raise SystemExit(f"✗ --line 超出范围：共 {len(lines)} 行歌词")
        return lines[args.line - 1]
    # --line-text
    hits = [i for i, ln in enumerate(lines, 1) if args.line_text in ln.text]
    if not hits:
        raise SystemExit(f"✗ 没有歌词行包含文本「{args.line_text}」")
    if len(hits) > 1:
        raise SystemExit(f"✗ 文本「{args.line_text}」命中多行 {hits}，请用 --line 指定其一")
    return lines[hits[0] - 1]


def resolve_word_range(line: lrc.Line, word: str, occurrence: int):
    """在歌词行内定位词/字，返回 (start, end)。优先用词级时间戳，否则按字数均分。"""
    if line.words:
        hits = [w for w in line.words if word in w.text]
        if not hits:
            raise SystemExit(f"✗ 行「{line.text}」内没有包含「{word}」的词")
        if occurrence > len(hits):
            raise SystemExit(f"✗ 「{word}」在该行只出现 {len(hits)} 次")
        w = hits[occurrence - 1]
        return w.start or line.start or 0.0, w.end or ((w.start or 0.0) + 0.5)

    # 无词级时间戳：按字符均分估算（中文一字一音节，足够定位）
    text = line.text
    idx = -1
    start_search = 0
    for _ in range(occurrence):
        idx = text.find(word, start_search)
        if idx < 0:
            raise SystemExit(f"✗ 行「{line.text}」内没有第 {occurrence} 个「{word}」")
        start_search = idx + 1
    line_start = line.start or 0.0
    line_end = line.end or (line_start + 3.0)
    n = max(len(text), 1)
    w_start = line_start + (line_end - line_start) * idx / n
    w_end = line_start + (line_end - line_start) * (idx + len(word)) / n
    print(f"ℹ 该行无词级时间戳，按字数均分估算「{word}」区间"
          f"（{w_start:.2f}s-{w_end:.2f}s）")
    return w_start, w_end


def expand_range(start: float, end: float, pad: float, total: float,
                 line: lrc.Line | None = None) -> tuple:
    """外扩区间：先加 pad，仍短于最短时长则继续外扩（优先不超出行范围太多）。"""
    s, e = start - pad, end + pad
    if e - s < MIN_REPAINT_LEN:
        need = (MIN_REPAINT_LEN - (e - s)) / 2
        s, e = s - need, e + need
    s = max(0.0, s)
    e = min(total, e)
    return round(s, 3), round(e, 3)


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main() -> int:
    p = argparse.ArgumentParser(description="ACE-Step 歌曲局部修改（单句/单词重绘）")
    p.add_argument("audio", help="原始歌曲音频（mp3/wav/flac）")
    p.add_argument("-l", "--lrc", required=True, help="对应的歌词 .lrc 文件")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--line", type=int, help="第 N 行歌词（1 起，只数带时间戳的行）")
    g.add_argument("--line-text", help="包含该文本的歌词行（唯一命中时才可用）")
    g.add_argument("--word", help="词/字级定位（见 --occurrence）")
    p.add_argument("--occurrence", type=int, default=1, help="取第几次出现（默认 1）")
    p.add_argument("--new-lyrics", help="重绘区间要唱的新词（不填则原词重唱/修复发音）")
    p.add_argument("--caption", help="重绘内容描述（默认自动生成）")
    p.add_argument("--pad", type=float, default=0.6, help="区间前后外扩秒数（默认 0.6）")
    p.add_argument("--style", help="歌曲风格描述（帮助重绘衔接，如“温暖流行，女声带和声”）")
    p.add_argument("--model", default="acestep-v15-base",
                   help="DiT 模型（repaint 仅支持 base/xl-base，默认 acestep-v15-base）")
    p.add_argument("--repaint-mode", default="conservative",
                   choices=["conservative", "balanced", "aggressive"],
                   help="重绘模式（默认 conservative：最大保留源音频，避免破坏区间外歌词）")
    p.add_argument("--steps", type=int, default=50, help="推理步数（base 推荐 32-64）")
    p.add_argument("--format", default="mp3", help="输出格式 mp3/wav/flac")
    p.add_argument("--host", default=generate_song.DEFAULT_HOST)
    p.add_argument("--port", type=int, default=generate_song.DEFAULT_PORT)
    p.add_argument("--api-key", default="")
    p.add_argument("-o", "--output", help="输出音频路径（默认 <原名>_edit.<ext>）")
    args = p.parse_args()

    audio_path = Path(args.audio).resolve()
    if not audio_path.exists():
        print(f"✗ 音频不存在: {audio_path}")
        return 1
    lrc_path = Path(args.lrc).resolve()

    # 1. 定位重绘区间
    lines = lrc.parse_lrc(lrc_path.read_text(encoding="utf-8"))
    if not lines:
        print("✗ LRC 中没有带时间戳的歌词行")
        return 1

    target_line = None
    if args.word:
        # 词级：先在所有行里找包含该词的行（带词级时间戳的行优先）
        candidates = [ln for ln in lines if args.word in ln.text]
        if not candidates:
            print(f"✗ 没有任何歌词行包含「{args.word}」")
            return 1
        target_line = candidates[min(args.occurrence - 1, len(candidates) - 1)]
        if args.occurrence > len(candidates):
            print(f"ℹ 「{args.word}」只出现 {len(candidates)} 行，取最后一行")
        # 行内第几次出现该词
        w_start, w_end = resolve_word_range(target_line, args.word, 1)
    else:
        target_line = resolve_line(lines, args)
        w_start = target_line.start or 0.0
        w_end = target_line.end or (w_start + 3.0)

    total = generate_song._probe_duration(audio_path)
    start, end = expand_range(w_start, w_end, args.pad, total)

    line_no = lines.index(target_line) + 1
    print(f"🎯 定位: 第 {line_no} 行 「{target_line.text}」")
    print(f"   重绘区间: {start:.2f}s → {end:.2f}s"
          f"（原区间 {w_start:.2f}s-{w_end:.2f}s，pad={args.pad}s，全曲 {total:.1f}s）")
    if args.new_lyrics:
        print(f"   新词: 「{args.new_lyrics}」")

    # 2. 构造歌词：完整歌词 + 目标行替换为新词
    lyrics_text = reconstruct_lyrics_text(lrc_path)
    if args.new_lyrics:
        lyrics_text = lyrics_text.replace(target_line.text, args.new_lyrics, 1)

    if args.caption:
        caption = args.caption
    elif args.new_lyrics:
        caption = (f'sing the lyrics "{args.new_lyrics}" in this section, '
                   f"keep the same melody style, vocal timbre and accompaniment")
    else:
        caption = ("re-sing this section cleanly with accurate pronunciation, "
                   "keep the melody, vocal timbre and accompaniment consistent")

    # 3. 提交 repaint 任务
    client = generate_song.AceStepClient(args.host, args.port, args.api_key)
    if not client.health():
        print("✗ 无法连接 ACE-Step API。请先启动服务：")
        print("    cd ACE-Step-1.5 && uv run acestep-api")
        return 1

    payload = {
        "task_type": "repaint",
        "repainting_start": start,
        "repainting_end": end,
        "chunk_mask_mode": "explicit",
        "repaint_mode": args.repaint_mode,
        "caption": caption,
        "lyrics": lyrics_text,
        "model": args.model,
        "inference_steps": args.steps,
        "audio_format": args.format,
    }
    if args.style:
        payload["prompt"] = args.style

    print(f"▶ 提交 repaint 任务 (model={args.model}) ...")
    # ACE-Step 不允许绝对路径引用音频，必须以 src_audio 字段上传文件
    task_id = client.release_task_multipart(payload, "src_audio", audio_path)
    print(f"  task_id = {task_id}")

    print("⏳ 重绘中（区间外音频保持不变，base 模型首次加载需数分钟）...")
    result = generate_song.wait_for_result(client, task_id, timeout=3600.0)

    # 4. 下载结果
    files, out_lyrics = generate_song._parse_task_result(result)
    if not files:
        print(f"✗ 结果中没有音频文件: {result}")
        return 1

    out_path = Path(args.output) if args.output else audio_path.with_name(
        f"{audio_path.stem}_edit.{args.format}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    client.download(files[0], out_path)
    print(f"✓ 已保存: {out_path}")

    if out_lyrics:
        lyric_out = out_path.with_suffix(".txt")
        lyric_out.write_text(out_lyrics, encoding="utf-8")
        print(f"✓ 歌词: {lyric_out}")
        lrc_out = out_path.with_suffix(".lrc")
        lrc.text_to_lrc(out_lyrics.splitlines(), generate_song._probe_duration(out_path), str(lrc_out))
        print(f"✓ LRC:  {lrc_out}")

    print("\n提示: 改完后如对结果满意，可用新音频重新合成 MV：")
    print(f"  python3 make_mv.py {out_path} 封面.jpg -l {out_path.with_suffix('.lrc')} --karaoke -o MV.mp4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
