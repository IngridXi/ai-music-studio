# 🎵 ai-music-studio

**AI 歌曲创作 + MV 动画生成工具包** —— 把一段主题或歌词，变成一首带人声的完整歌曲，再合成为一条带音频可视化动画与逐字歌词高亮的音乐视频。

基于两个优秀开源项目改造优化：

| 能力 | 基础项目 | 本仓库的优化 |
|------|----------|--------------|
| 歌曲生成 | [ACE-Step 1.5](https://github.com/ace-step/ACE-Step-1.5)（MIT） | 封装为一行命令的脚本化调用，支持中文歌词、主题自动写词、LRC 时间戳产出 |
| MV 合成 | [Karaoke-Music-Vid-Generator](https://github.com/danielrosehill/Karaoke-Music-Vid-Generator) | 跨平台、支持中文、免 Whisper/API key、多可视化风格、逐字高亮 |

## ✨ 特性

- **🎼 本地 AI 作曲**：ACE-Step 1.5，MIT 协议，支持 50+ 语言带人声，10 秒～10 分钟，Apple 芯片 / NVIDIA / CPU 均可运行。
- **📝 主题自动写词**：给一句主题，模型自动作词 + 作曲 + 编曲，并产出带时间戳的 LRC。
- **🎬 动态 MV 合成**：Ken Burns 封面缓动 + 音频波形/频谱可视化 + 逐字卡拉OK歌词高亮。
- **🇨🇳 中文友好**：完整支持中文歌词与中文字体（原版 Karaoke 脚本硬编码英文）。
- **📦 近乎零依赖**：歌曲生成与 MV 合成脚本仅用 Python 标准库，只需系统安装 ffmpeg。
- **🔌 模块化**：每个环节都可独立使用，也可一键全流程。

## 📋 工作流

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐
│  主题 / 歌词 │──▶│  AI 生成歌曲  │──▶│  合成 MV 动画 │
│  (用户输入)  │    │ (ACE-Step)   │    │   (ffmpeg)   │
└─────────────┘    └──────────────┘    └─────────────┘
                          │  ▲                ▲
                    音频+歌词+LRC         封面图
                          │                   │
                          └──── 封面生成 ◀────┘
```

## 🚀 快速开始

### 0. 前置依赖

```bash
# ffmpeg（MV 必需）
brew install ffmpeg          # macOS；Ubuntu: sudo apt install ffmpeg

# uv（ACE-Step 用它管理环境）
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 1. 安装 ACE-Step（生成歌曲时才需要）

```bash
git clone https://github.com/ace-step/ACE-Step-1.5.git
cd ACE-Step-1.5 && uv sync
```

### 2. 一键生成歌曲 + MV

```bash
# 终端 A：启动 ACE-Step 服务（保持运行）
cd ACE-Step-1.5 && uv run acestep-api

# 终端 B：一键生成
cd ai-music-studio
python3 scripts/pipeline.py \
  --topic "一首关于夏天和告别的中文流行情歌" \
  --style "温暖治愈的流行，钢琴与弦乐" \
  --title "夏末" --lang zh -o ./output
```

完成后在 `./output` 得到：

```
output/
├── songs/夏末_1.mp3   # 歌曲音频
├── songs/夏末_1.txt   # 歌词
├── songs/夏末_1.lrc   # 带时间戳歌词
├── cover.jpg          # 专辑封面
└── 夏末.mp4           # MV 成片 ★
```

## 🔧 各脚本说明

| 脚本 | 作用 | 用法 |
|------|------|------|
| `scripts/pipeline.py` | 一键全流程（歌曲→封面→MV） | `--topic` 或 `--lyrics` |
| `scripts/generate_song.py` | 生成歌曲（调 ACE-Step API） | `--topic "..."` / `--lyrics 文件` |
| `scripts/generate_cover.py` | 生成渐变封面 | `--title "..." --artist "..."` |
| `scripts/make_mv.py` | 合成 MV 动画 | `音频 封面 -l 歌词 --karaoke` |
| `scripts/lrc.py` | LRC 解析/字幕生成（库） | 被 make_mv 引用 |
| `scripts/visualizer.py` | 可视化滤镜构建（库） | 被 make_mv 引用 |

### 常用命令示例

```bash
# 只生成歌曲（主题驱动，模型自动写词）
python3 scripts/generate_song.py --topic "一首治愈系日语歌" --lang ja --style "J-Pop 温暖"

# 用已有歌词谱曲
python3 scripts/generate_song.py --lyrics 歌词.txt --style "抒情民谣" --lang zh --duration 90

# 只合成 MV（已有音频 + 封面 + 歌词）
python3 scripts/make_mv.py song.mp3 cover.jpg -l lyrics.lrc --karaoke --style spectrum

# 生成封面
python3 scripts/generate_cover.py --title "夏末" --artist "AI 音乐工作室" -o cover.jpg
```

### make_mv.py 的可视化风格

| 风格 | 说明 |
|------|------|
| `wave` | 中心线波形，叠在画面底部（默认） |
| `spectrum` | 滚动频谱热力图，适合全幅背景 |
| `bars` | 频谱柱状图，跳跃感强 |
| `dots` | 频谱点阵，科技感 |

## 🆚 相对原项目的优化

**歌曲生成侧**：原 ACE-Step 以 Gradio/API 服务为主，本仓库封装出**脚本化 CLI**，把"主题/歌词 → 歌曲 → 带时间戳 LRC"整理成一条命令，便于在自动化/Agent 中调用。

**MV 合成侧**（相对 Karaoke-Music-Vid-Generator）：

| 维度 | 原版 | 本仓库 |
|------|------|--------|
| 平台 | VAAPI 硬编（仅 Linux） | libx264 跨平台 + macOS VideoToolbox |
| 语言 | 硬编码英文 | 完整中文/多语言 |
| 字幕来源 | Whisper API 转录（需 key） | 直接用生成歌曲时的 LRC 时间戳 |
| 字体 | Comic Sans MS | 自动检测中文字体 |
| 可视化 | 仅波形 | 波形/频谱/频谱柱/圆形 4 种 |
| 卡拉OK | 词级高亮 | 词级 + 行级，支持增强 LRC |

## 📁 目录结构

```
ai-music-studio/
├── SKILL.md                # WorkBuddy 技能定义
├── README.md               # 本文件
├── LICENSE                 # MIT
├── pyproject.toml          # 依赖与命令行入口
├── config/settings.yaml    # 默认配置
├── scripts/                # 核心脚本（纯标准库）
│   ├── pipeline.py         # 一键全流程
│   ├── generate_song.py    # 歌曲生成
│   ├── generate_cover.py   # 封面生成（需 Pillow）
│   ├── make_mv.py          # MV 合成
│   ├── lrc.py              # LRC 歌词解析
│   └── visualizer.py       # 可视化滤镜
├── examples/               # 示例脚本
└── references/             # 详细使用说明
```

## ⚖️ 许可证

本项目采用 MIT 协议。生成音乐所用 ACE-Step 模型权重为 MIT，可商用；但请避免输入易侵权描述（如"某歌手的风格"），并建议标注 AI 参与创作。

## 🙏 致谢

- [ACE-Step 1.5](https://github.com/ace-step/ACE-Step-1.5) — ACE Studio × StepFun 开源音乐生成模型
- [Karaoke-Music-Vid-Generator](https://github.com/danielrosehill/Karaoke-Music-Vid-Generator) — 卡拉OK MV 生成思路
