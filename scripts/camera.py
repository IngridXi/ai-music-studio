"""
运镜模块 —— 为 MV 多图画面提供电影感镜头运动（camera moves）。

借鉴 HyperFrames（HTML/CSS 运镜）与 seedance2（镜头语言）的思路，
用 ffmpeg zoompan 滤镜实现多种运镜，让静态画面"活"起来：

  推镜头 zoom_in    从全景推向细节（注意力聚焦）
  拉镜头 zoom_out   从细节拉向全景（揭示环境）
  右摇   pan_right  镜头向右摇（画面内容向左移）
  左摇   pan_left   镜头向左摇
  下摇   tilt_down  镜头向下摇
  上摇   tilt_up    镜头向上摇
  对角   diag_in    对角推近（推 + 摇 组合，最有电影感）

每张图先预放大（pre_zoom），留出运镜余量，避免边缘露白。
"""
from __future__ import annotations


# 预放大倍数：输入图会先 scale 到 (1+pre_zoom) 倍，运镜在余量内进行
PRE_ZOOM = 1.35

# 运镜时的最大 zoom（相对预放大后的图，1.0 = 无缩放）
ZOOM_MAX = 1.30

CAMERA_MOVES = {
    "zoom_in", "zoom_out", "pan_right", "pan_left",
    "tilt_down", "tilt_up", "diag_in", "diag_out",
}


def _ease(expr_from, expr_to, frames: int) -> str:
    """对 on/frames 做平滑缓动（smoothstep），避免生硬起止。"""
    t = f"(on/{max(frames, 1)})"
    # smoothstep: t*t*(3-2t)
    s = f"({t}*{t}*(3-2*{t}))"
    return f"({expr_from}+({expr_to}-({expr_from}))*{s})"


def build_camera_move(move: str, width: int, height: int, fps: int,
                      duration: float) -> str:
    """返回 zoompan 滤镜串（输入为单张图，输出 [camN]）。"""
    if move not in CAMERA_MOVES:
        raise ValueError(f"未知运镜: {move}（可选 {sorted(CAMERA_MOVES)}）")

    frames = max(int(round(duration * fps)), 1)
    # 预放大后的图尺寸
    iw = int(width * PRE_ZOOM)
    ih = int(height * PRE_ZOOM)

    # 居中坐标（zoom=1.0 时）
    cx0 = "(iw-iw/zoom)/2"
    cy0 = "(ih-ih/zoom)/2"

    if move == "zoom_in":
        z = _ease("1.0", f"{ZOOM_MAX}", frames)
        x, y = cx0, cy0
    elif move == "zoom_out":
        z = _ease(f"{ZOOM_MAX}", "1.0", frames)
        x, y = cx0, cy0
    elif move == "pan_right":
        z = f"{ZOOM_MAX}"
        x = _ease("0", "(iw-iw/zoom)", frames)
        y = cy0
    elif move == "pan_left":
        z = f"{ZOOM_MAX}"
        x = _ease("(iw-iw/zoom)", "0", frames)
        y = cy0
    elif move == "tilt_down":
        z = f"{ZOOM_MAX}"
        x = cx0
        y = _ease("0", "(ih-ih/zoom)", frames)
    elif move == "tilt_up":
        z = f"{ZOOM_MAX}"
        x = cx0
        y = _ease("(ih-ih/zoom)", "0", frames)
    elif move == "diag_in":
        # 从左上角推近到右下（对角推近，电影感）
        z = _ease("1.0", f"{ZOOM_MAX}", frames)
        x = _ease("0", "(iw-iw/zoom)", frames)
        y = _ease("0", "(ih-ih/zoom)", frames)
    elif move == "diag_out":
        z = _ease(f"{ZOOM_MAX}", "1.0", frames)
        x = _ease("(iw-iw/zoom)", "0", frames)
        y = _ease("(ih-ih/zoom)", "0", frames)
    else:
        raise ValueError(f"未知运镜: {move}")

    # 预放大 + 裁剪到统一尺寸 + 运镜
    # 注意：输入为「-loop 1 -t duration」的循环图，zoompan d=1（每输入帧输出 1 帧），
    # on 随输入帧 0..frames-1 递增，运镜在 duration 秒内平滑完成。
    return (
        f"scale={iw}:{ih}:force_original_aspect_ratio=increase,"
        f"crop={iw}:{ih},"
        f"zoompan=z='{z}':x='{x}':y='{y}':"
        f"d=1:s={width}x{height}:fps={fps}"
    )


def move_for_keyword(text: str) -> str:
    """根据画面主题关键词推荐运镜（简单启发式，可扩展）。"""
    kw = text
    if any(k in kw for k in ("面", "牛", "醋", "酒", "酸枣", "栲栳", "算盘", "票号")):
        # 美食/静物/细节 → 推近特写
        return "zoom_in"
    if any(k in kw for k in ("瀑布", "石窟", "佛", "黄河", "太行", "五台")):
        # 大场景风光 → 拉远揭示或平移
        return "pan_right"
    if any(k in kw for k in ("大院", "古城", "城墙", "悬空")):
        # 建筑 → 对角推近，突出纵深
        return "diag_in"
    if any(k in kw for k in ("黄土", "驼铃", "高原")):
        # 苍茫 → 平移摇镜头
        return "pan_left"
    # 默认推近
    return "zoom_in"
