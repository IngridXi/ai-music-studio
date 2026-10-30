---
name: ai-music-studio
description: AI 歌曲创作与 MV 动画生成。根据主题或歌词生成带人声的完整歌曲（开源模型 ACE-Step，支持中英文），并合成 MV——支持音频可视化动画、逐字歌词高亮，以及多图运镜（推/拉/摇/移镜头运动 + 转场 + 文化纹样边框）的电影感图文卡点视频。当用户想要"写一首歌""生成歌曲""AI 作曲""做歌曲 MV""音乐视频""AI 音乐""歌词配曲"时使用本技能。
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

### 第四步（进阶）：多图运镜 MV（电影感图文卡点）

当需要「每句歌词配一张画面 + 镜头运动」时（如宣传片、品牌主题曲 MV），用 `slideshow_mv.py`：

```bash
python3 <skill_dir>/scripts/slideshow_mv.py \
  歌曲.mp3 分镜.json -l 歌词.lrc --karaoke -o 成片.mp4
```

分镜.json 定义每段画面、运镜方式与时长：

```json
{
  "ornament": "纹样边框.png",
  "fade": 0.6,
  "shots": [
    {"image": "画面/01.png", "move": "zoom_in",  "duration": 6.0},
    {"image": "画面/02.png", "move": "pan_right","duration": 5.5}
  ]
}
```

- **运镜**（`move`，见 `camera.py`）：`zoom_in` 推近 / `zoom_out` 拉远 / `pan_left`·`pan_right` 左右摇 / `tilt_up`·`tilt_down` 上下摇 / `diag_in`·`diag_out` 对角推拉。
- **转场**：`fade` 淡入淡出（秒）；**纹样边框**：`ornament` 指定一张透明 PNG 叠加层（古建窗棂/回纹角花，营造文化韵味）。
- 歌词时间戳可用 faster-whisper 对齐（`language="zh"` 词级时间戳），保证画面切换与唱词同步。

### 第五步：一键全流程（推荐）

```bash
python3 <skill_dir>/scripts/pipeline.py \
  --topic "主题" --style "风格" --title "歌名" --lang zh -o ./output
```

一条命令完成「歌曲 → 封面 → MV」。用已有歌词则把 `--topic` 换成 `--lyrics 歌词.txt`。

### 第六步：交付

- 用 `present_files` 交付 `MV 成片 .mp4`（优先）与歌曲 `.mp3`。
- 若有中文歌词，向用户说明生成结果可能出现的个别发音偏差。

## 局部修改：只重唱某一句 / 某个词（Repaint）

生成结果某句唱错、某个字发音不对、或想改一句词？不需要整首重跑——用 ACE-Step 的
Repaint（局部重绘）：只重新生成指定时间区间，区间外音频保持不变。

```bash
# 按行号重唱第 5 句（不换词，仅修复发音/唱法）
python3 <skill_dir>/scripts/edit_song.py 歌曲.mp3 -l 歌曲.lrc --line 5

# 按文本定位（须唯一命中）
python3 <skill_dir>/scripts/edit_song.py 歌曲.mp3 -l 歌曲.lrc --line-text "夏天的风"

# 词/字级：只重唱"风"字（增强 LRC 用真实词级时间戳；普通 LRC 按字数均分估算）
python3 <skill_dir>/scripts/edit_song.py 歌曲.mp3 -l 歌曲.lrc --word "风"

# 换词重唱：把第 5 句换成新词
python3 <skill_dir>/scripts/edit_song.py 歌曲.mp3 -l 歌曲.lrc --line 5 --new-lyrics "冬天的雪"
```

要点：
- **模型必须是 base 系列**（`acestep-v15-base`，repaint 不支持 turbo/sft），脚本已默认。
- 重绘区间自动外扩（`--pad`，默认 0.6s）且最短 3 秒（模型按 chunk 处理，过短会被对齐）。
- `--new-lyrics` 会替换完整歌词中该行并传给模型，实现"改词重唱"；不传则原词重唱。
- 输出为完整新音频 `<原名>_edit.mp3`（区间外不变），改完可重新合成 MV。
- 逐字歌词时间戳可用 faster-whisper 对齐（`language="zh"` 词级时间戳），`--word` 定位更准。

## 进阶：专业词曲 / 视频知识库（references/skills）

`references/skills/`（索引见该目录 README.md）内置四类外部知识库，按需阅读对应 SKILL.md：

- **作词/编曲规格单**（lw-* 18 个 + mc-* 29 个，jtydhr88）：需要**提高词曲质量**时用。
  推荐 `lw-mandarin`（中文押韵/倒字检查，判断词能不能顺口唱）、`mc-arrangement-arch`
  （段落起伏）、`mc-vocal-direction`（演唱方式）、`mc-ai-tell-audit`（诊断"AI 味"）。
  产出的是规格单/判据文本，不改变生成后端，耗时较长，按需使用。
- **hand-drawn-video-prompts**（kaomei，MIT）：把歌词逐段拆成统一画风的分镜提示词
  （生图 + 图生视频两套），接 `slideshow_mv.py` 分镜 JSON 或图生视频工具，做手绘风 MV。
- **openmontage-skills**（OpenMontage 的 8 个 skill，AGPL 仅内部参考）：
  - `music-to-video` ⭐：音乐驱动、节拍同步视频工作流（分析音频 → 分帧 → HTML 合成 → 渲染 MP4）；
  - `hyperframes-*`：用 HTML/CSS/GSAP 写画面、逐帧渲染成视频的代码渲染路线，
    适合动态歌词排版、节奏卡点等纯 ffmpeg 难做的复杂动效（需 Node.js + `npx hyperframes` 工具链）；
  - `ffmpeg`、`visual-style`、`music` 参考。

路线选择：日常 MV 用纯 ffmpeg 的 `make_mv.py`/`slideshow_mv.py`（零依赖、稳定）；
需要复杂动效/节奏卡点时走 HyperFrames 代码渲染路线。

## 自动化

需要「每天/每周定时生成歌曲 + MV」时，创建 recurring 自动化，prompt 直接复用上面的命令，把主题/风格/输出路径写全。生成歌曲依赖 ACE-Step 服务常驻，自动化运行前需确保 `uv run acestep-api` 在运行。

## 注意事项

- **版权**：ACE-Step 权重为 MIT，可商用；但避免输入"某歌手的风格"这类易侵权描述，生成内容建议标注 AI 参与。
- **歌词时长对齐**：若用纯文本歌词（无时间戳），MV 采用均分时间戳，可能出现轻微不对齐；有 .lrc 时间戳时对齐最准。
- **硬件**：CPU 推理较慢，Apple 芯片 / NVIDIA GPU 更快；ACE-Step 首跑下载模型耗时较长。
