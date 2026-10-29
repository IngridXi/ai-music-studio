---
name: ai-music-studio
description: AI 歌曲创作与 MV 动画生成。根据主题或歌词生成带人声的完整歌曲（开源模型 ACE-Step，支持中英文），并合成带音频可视化动画与逐字歌词高亮的音乐视频。当用户想要"写一首歌""生成歌曲""AI 作曲""做歌曲 MV""音乐视频""AI 音乐""歌词配曲"时使用本技能。
agent_created: true
---

# AI 歌曲创作 + MV 动画

本技能把「一段主题或歌词」变成「一首带人声的完整歌曲」和「一条带音频可视化动画 + 逐字歌词的 MV」。

- **歌曲生成**：基于开源模型 [ACE-Step 1.5](https://github.com/ace-step/ACE-Step-1.5)（MIT 协议），本地生成、支持中英文带人声、10 秒～10 分钟、可用 Apple 芯片 / NVIDIA GPU / CPU。
- **MV 动画**：基于 [Karaoke-Music-Vid-Generator](https://github.com/danielrosehill/Karaoke-Music-Vid-Generator) 思路重写的 ffmpeg 合成管线，支持 Ken Burns 封面动画、音频波形/频谱可视化、逐字卡拉OK歌词高亮。

## 使用场景

- "帮我写一首关于夏天的中文流行歌，并做成 MV"
- "把这段歌词谱成曲，再生成一个动态歌词视频"
- "生成一首纯音乐，配一个频谱动画视频"
- 自动化：定时生成歌曲 + MV（详见「自动化」一节）

## 前置依赖（首次使用需检查）

1. **ffmpeg**（MV 合成必需，含 libass）。macOS：`brew install ffmpeg`。用 `ffmpeg -version` 验证。
2. **ACE-Step**（歌曲生成必需，仅在需要生成歌曲时）。安装：
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh   # 安装 uv（若已有可跳过）
   git clone https://github.com/ace-step/ACE-Step-1.5.git
   cd ACE-Step-1.5 && uv sync
   ```
   生成歌曲前先启动其本地服务（保持运行）：
   ```bash
   cd ACE-Step-1.5 && uv run acestep-api    # 监听 http://127.0.0.1:8001
   ```
3. **Pillow**（仅本地生成封面时需要，可选）：`pip install pillow`

> 无 GPU 也能跑：ACE-Step 支持 CPU / Apple 芯片（MPS）/ NVIDIA / AMD。首跑会自动下载模型（约 4GB），请耐心等待。

## 工作流程

### 第一步：确认需求

- 用户给了**主题**（一句话）→ 走「主题驱动」，模型自动写词 + 作曲。
- 用户给了**歌词**（文本或 .txt/.lrc 文件）→ 走「歌词驱动」，模型按歌词谱曲。
- 用户只要**纯音乐**（无歌词）→ 歌词传 `[Instrumental]`。
- 用户只要**MV**（已有歌曲音频）→ 跳过第一步，直接进第三步。

### 第二步：生成歌曲（可选）

```bash
# 主题驱动（自动写词+作曲）
python3 <skill_dir>/scripts/generate_song.py \
  --topic "一首关于夏天和告别的中文流行情歌" \
  --style "温暖治愈的流行，钢琴与弦乐" --lang zh \
  --out-dir ./output/songs

# 歌词驱动（按已有歌词谱曲）
python3 <skill_dir>/scripts/generate_song.py \
  --lyrics 歌词.txt --style "抒情民谣，木吉他" --lang zh \
  --duration 90 --bpm 80 --out-dir ./output/songs
```

- 输出：`<名>_1.mp3`（音频）、`<名>_1.txt`（歌词）、`<名>_1.lrc`（带时间戳歌词）。
- 想生成多个候选：`--batch 4`；想要更高音质：`--model acestep-v15-base --steps 64`；更快的预览：默认 `acestep-v15-turbo`。

### 第三步：生成封面（可选，二选一）

```bash
# A. 本地渐变封面（零成本）
python3 <skill_dir>/scripts/generate_cover.py \
  --title "歌名" --artist "署名" -o ./output/cover.jpg

# B. 用文生图生成更精美的封面（在 WorkBuddy 里让图像工具按主题画一张），
#    保存为 cover.jpg 后直接用于下一步。
```

### 第四步：合成 MV

```bash
python3 <skill_dir>/scripts/make_mv.py \
  ./output/songs/<名>_1.mp3 ./output/cover.jpg \
  -l ./output/songs/<名>_1.lrc --karaoke \
  --style wave --resolution 1920x1080 -o ./output/<名>.mp4
```

- `--style`：`wave`（波形）/ `spectrum`（频谱热力图）/ `bars`（频谱柱）/ `dots`（频谱点阵）。
- `--karaoke`：逐字卡拉OK高亮；去掉则退化为普通字幕。
- 纯文本歌词（无 .lrc）也可直接 `-l 歌词.txt`，脚本会按歌曲时长自动均分时间戳。
- macOS 想加速编码：加 `--hwaccel videotoolbox`。

### 第五步：一键全流程（推荐）

```bash
python3 <skill_dir>/scripts/pipeline.py \
  --topic "主题" --style "风格" --title "歌名" --lang zh -o ./output
```

一条命令完成「歌曲 → 封面 → MV」。用已有歌词则把 `--topic` 换成 `--lyrics 歌词.txt`。

### 第六步：交付

- 用 `present_files` 交付 `MV 成片 .mp4`（优先）与歌曲 `.mp3`。
- 若有中文歌词，向用户说明生成结果可能出现的个别发音偏差。

## 自动化

需要「每天/每周定时生成歌曲 + MV」时，创建 recurring 自动化，prompt 直接复用上面的命令，把主题/风格/输出路径写全。生成歌曲依赖 ACE-Step 服务常驻，自动化运行前需确保 `uv run acestep-api` 在运行。

## 注意事项

- **版权**：ACE-Step 权重为 MIT，可商用；但避免输入"某歌手的风格"这类易侵权描述，生成内容建议标注 AI 参与。
- **歌词时长对齐**：若用纯文本歌词（无时间戳），MV 采用均分时间戳，可能出现轻微不对齐；有 .lrc 时间戳时对齐最准。
- **硬件**：CPU 推理较慢，Apple 芯片 / NVIDIA GPU 更快；ACE-Step 首跑下载模型耗时较长。
