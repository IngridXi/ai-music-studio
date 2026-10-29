"""
LRC 歌词解析与字幕生成模块（纯 Python 标准库，零第三方依赖）。

相比原版 Karaoke 脚本的优化：
  1. 不再依赖 OpenAI Whisper 转录 —— 直接用歌曲生成时同步产出的歌词/时间戳；
  2. 完整支持中文与多语言歌词（原版硬编码 language="en"）；
  3. 支持标准 LRC、增强 LRC（行内词级时间戳），以及无时间戳纯文本的智能均分对齐；
  4. 可导出 SRT（普通字幕）与 ASS（逐字卡拉OK高亮）两种格式。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #
@dataclass
class Word:
    """一个带可选时间戳的词。"""
    text: str
    start: Optional[float] = None
    end: Optional[float] = None


@dataclass
class Line:
    """一行歌词。words 为空时退化为按行展示。"""
    text: str
    start: Optional[float] = None
    end: Optional[float] = None
    words: List[Word] = field(default_factory=list)


# 时间戳正则： [mm:ss] 或 [mm:ss.xx] 或 [mm:ss.xxx]
_LRC_TAG = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_META_TAG = re.compile(r"\[(ti|ar|al|by|offset|re|ve):(.*)\]")
_INLINE_WORD = re.compile(r"<(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?>")


def _parse_ts(m: re.Match) -> float:
    mm = int(m.group(1))
    ss = int(m.group(2))
    frac = m.group(3) or "0"
    # 统一换算成秒：1 位=十分位，2 位=百分位，3 位=千分位
    frac = frac.ljust(3, "0")[:3]
    return mm * 60 + ss + int(frac) / 1000.0


def parse_lrc(text: str) -> List[Line]:
    """解析标准 / 增强 LRC 文本，返回按时间排序的歌词行列表。

    增强 LRC 支持行内 <mm:ss.xx> 词级时间戳，例如：
        [00:12.50]<00:12.50>我<00:12.80>爱<00:13.20>你
    """
    lines: List[Line] = []
    offset = 0.0

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue

        # 元数据标签
        meta = _META_TAG.match(line)
        if meta:
            if meta.group(1) == "offset":
                try:
                    offset = int(meta.group(2)) / 1000.0
                except ValueError:
                    pass
            continue

        # 提取所有行级时间戳（一行可能带多个 [..] 标签）
        tags = list(_LRC_TAG.finditer(line))
        if not tags:
            # 无时间戳的纯文本行（例如 [Verse 1] 之类结构标签或空行）
            continue

        # 去掉行首所有时间戳标签，得到正文
        body = line
        for t in tags:
            body = body.replace(t.group(0), "", 1)
        body = body.strip()

        for t in tags:
            start = _parse_ts(t) + offset
            if start < 0:
                start = 0.0
            lines.append(Line(text=body, start=start, words=_parse_inline_words(body, start)))

    # 排序并补齐 end 时间戳
    lines.sort(key=lambda x: x.start if x.start is not None else 0.0)
    for i, ln in enumerate(lines):
        if ln.end is None:
            if i + 1 < len(lines) and lines[i + 1].start is not None:
                ln.end = min(lines[i + 1].start, (ln.start or 0.0) + 10.0)
            else:
                ln.end = (ln.start or 0.0) + 4.0
    return lines


def _parse_inline_words(body: str, line_start: float) -> List[Word]:
    """解析行内词级时间戳。若无词级标记则返回空列表（退化为行级展示）。"""
    if "<" not in body or ">" not in body:
        return []

    words: List[Word] = []
    parts = _INLINE_WORD.split(body)
    # split 结果：['', '00', '12', '50', '我', '00', '12', '80', '爱', ...]
    # 每 4 个元素一组（空串 + min + sec + frac）后跟一个词
    i = 0
    text_buf = []
    # 更稳健的方式：手动扫描
    pos = 0
    last_ts: Optional[float] = None
    last_text: Optional[str] = None
    while True:
        m = _INLINE_WORD.search(body, pos)
        if m is None:
            tail = body[pos:].strip()
            if tail:
                words.append(Word(text=tail, start=last_ts, end=None))
            break
        ts = _parse_ts(m)
        seg = body[pos:m.start()].strip()
        if last_text is not None:
            words.append(Word(text=last_text, start=last_ts, end=ts))
        elif seg:
            # 第一个时间戳之前的文本视为整行开头（无独立时间戳）
            words.append(Word(text=seg, start=line_start, end=ts))
        last_ts = ts
        last_text = None
        pos = m.end()
        # 读取该时间戳后的词
        nxt = _INLINE_WORD.search(body, pos)
        seg = body[pos:nxt.start()].strip() if nxt else body[pos:].strip()
        last_text = seg
        if nxt is None:
            if last_text:
                words.append(Word(text=last_text, start=last_ts, end=None))
            break
    # 归一化 end
    for i, w in enumerate(words):
        if w.end is None:
            w.end = words[i + 1].start if i + 1 < len(words) else w.start + 1.0
    return words


def lyrics_to_lrc(lines: List[str], duration: float) -> List[Line]:
    """纯文本歌词（无时间戳）→ 按音频时长均分时间戳。

    启发式：忽略空行与结构标签（[Verse]/[Chorus]），把剩余歌词行按
    音频时长均匀分配。适合没有 LRC 时间戳时的兜底对齐。
    """
    content = [ln for ln in lines if ln.strip() and not re.match(r"^\[.*\]$", ln.strip())]
    if not content:
        return []
    n = len(content)
    # 留出前奏/尾奏余量（各 6%）
    intro = duration * 0.06
    usable = duration - intro * 2
    per = usable / n
    result: List[Line] = []
    for i, ln in enumerate(content):
        start = intro + i * per
        result.append(Line(text=ln.strip(), start=start, end=start + per))
    return result


# --------------------------------------------------------------------------- #
# 时间格式化
# --------------------------------------------------------------------------- #
def fmt_srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def fmt_ass_time(seconds: float) -> str:
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 60_00)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


# --------------------------------------------------------------------------- #
# 导出 SRT / ASS
# --------------------------------------------------------------------------- #
def to_srt(lines: List[Line]) -> str:
    """导出 SRT 字幕（ffmpeg subtitles 滤镜可用）。"""
    out = []
    for i, ln in enumerate(lines, 1):
        start = ln.start if ln.start is not None else 0.0
        end = ln.end if ln.end is not None else start + 3.0
        if end <= start:
            end = start + 1.0
        out.append(f"{i}\n{fmt_srt_time(start)} --> {fmt_srt_time(end)}\n{ln.text}\n")
    return "\n".join(out)


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{fontname},{fontsize},&H00FFFFFF,&H0000FF00,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,3,2,{align},{margin_l},{margin_r},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def to_ass(lines: List[Line], width: int = 1920, height: int = 1080,
           fontname: str = "PingFang SC", fontsize: int = 64,
           align: int = 2, margin_v: int = 60) -> str:
    r"""导出 ASS 卡拉OK字幕：逐字/逐行从左到右填充高亮（\k 标签）。

    - 若歌词行包含词级时间戳（增强 LRC），则逐词高亮；
    - 否则退化为整行按持续时间平滑填充。
    """
    header = ASS_HEADER.format(
        width=width, height=height, fontname=fontname, fontsize=fontsize,
        align=align, margin_l=40, margin_r=40, margin_v=margin_v,
    )
    events = []
    for ln in lines:
        if ln.start is None:
            continue
        start = fmt_ass_time(ln.start)
        end = fmt_ass_time(ln.end if ln.end is not None else ln.start + 3.0)

        if ln.words and len(ln.words) >= 1:
            # 逐词高亮
            text = ""
            for w in ln.words:
                dur = max(0.0, (w.end or w.start or 0.0) - (w.start or 0.0))
                cs = int(round(dur * 100))
                text += f"{{\\kf{cs}}}{w.text}"
            events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
        else:
            # 整行高亮
            dur = max(0.0, (ln.end or 0.0) - ln.start)
            cs = int(round(dur * 100))
            events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{{\\kf{cs}}}{ln.text}")

    return header + "\n".join(events) + "\n"


def text_to_lrc(lines: List[str], duration: float, out_path: str) -> None:
    """把纯文本歌词写入一个带均分时间戳的 .lrc 文件（可被 parse_lrc 重新读取）。"""
    parsed = lyrics_to_lrc(lines, duration)
    with open(out_path, "w", encoding="utf-8") as f:
        for ln in parsed:
            m, s = divmod(int(ln.start), 60)
            frac = int(round((ln.start - int(ln.start)) * 100))
            f.write(f"[{m:02d}:{s:02d}.{frac:02d}]{ln.text}\n")
