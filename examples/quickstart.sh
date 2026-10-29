#!/usr/bin/env bash
# ai-music-studio 快速开始示例
# 用法：bash examples/quickstart.sh "你的主题" "音乐风格" "歌名"
set -euo pipefail

TOPIC="${1:-一首关于夏天和告别的中文流行情歌}"
STYLE="${2:-温暖治愈的流行，钢琴与弦乐}"
TITLE="${3:-夏末}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "===== AI 歌曲 + MV 一键生成 ====="
echo "主题：$TOPIC"
echo "风格：$STYLE"
echo "标题：$TITLE"
echo

echo "[1/3] 生成歌曲（需 ACE-Step 服务已启动：uv run acestep-api）"
python3 "$SCRIPT_DIR/scripts/pipeline.py" \
  --topic "$TOPIC" \
  --style "$STYLE" \
  --title "$TITLE" \
  --lang zh \
  -o "$SCRIPT_DIR/output"

echo
echo "完成！查看 $SCRIPT_DIR/output 目录。"
