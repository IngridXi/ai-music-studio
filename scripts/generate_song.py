"""
AI 歌曲生成脚本 —— 通过 ACE-Step 本地 REST API 生成带人声的完整歌曲。

技术方案：调用开源模型 ACE-Step 1.5（MIT 协议，支持中英文带人声），
通过其官方 REST API（POST /release_task → 轮询 /query_result → GET /v1/audio）
实现"歌词/主题 + 风格 → 完整歌曲"，纯 Python 标准库，零第三方依赖。

前置条件：
  1. 已按 README 安装 ACE-Step（uv sync）；
  2. 启动服务：uv run acestep-api   （默认监听 http://127.0.0.1:8001）

用法示例：
  # 用主题自动生成（模型自动写词 + 作曲）
  python3 generate_song.py --topic "一首关于夏天和告别的中文流行情歌" --lang zh

  # 用已有歌词 + 风格生成
  python3 generate_song.py --lyrics lyrics.txt --style "温暖治愈的民谣，木吉他伴奏" --lang zh

  # 指定时长/BPM/模型
  python3 generate_song.py --topic "..." --duration 60 --bpm 120 --model acestep-v15-turbo
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lrc  # noqa: E402


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8001


class AceStepClient:
    """ACE-Step REST API 的极简客户端（标准库 urllib 实现）。"""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, api_key: str = ""):
        self.base = f"http://{host}:{port}"
        self.api_key = api_key

    def _post(self, path: str, payload: dict, timeout: int = 120) -> dict:
        url = f"{self.base}{path}"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _get(self, path: str, timeout: int = 120) -> bytes:
        url = f"{self.base}{path}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()

    def health(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base}/health", timeout=5) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return body.get("code") == 200
        except Exception:
            return False

    def release_task(self, payload: dict) -> str:
        """提交生成任务，返回 task_id。"""
        r = self._post("/release_task", payload)
        if r.get("code") != 200:
            raise RuntimeError(f"release_task 失败: {r.get('error') or r}")
        task_id = r.get("data", {}).get("task_id")
        if not task_id:
            raise RuntimeError(f"未返回 task_id: {r}")
        return task_id

    def query_result(self, task_ids: list) -> dict:
        r = self._post("/query_result", {"task_id_list": task_ids})
        if r.get("code") != 200:
            raise RuntimeError(f"query_result 失败: {r.get('error') or r}")
        return r.get("data", {})

    def download(self, path: str, dest: Path) -> Path:
        data = self._get(f"/v1/audio?path={urllib.parse.quote(path)}")
        dest.write_bytes(data)
        return dest


def _extract_task(data, task_id: str):
    """兼容 query_result 返回 data 的多种可能结构，取出指定任务结果。"""
    if isinstance(data, dict):
        if task_id in data:
            return data[task_id]
        if "tasks" in data and isinstance(data["tasks"], list):
            for t in data["tasks"]:
                if isinstance(t, dict) and t.get("task_id") == task_id:
                    return t
        if "result" in data:
            return data["result"]
        # data 本身可能就是任务结果
        if "status" in data or "file" in data:
            return data
    elif isinstance(data, list):
        for t in data:
            if isinstance(t, dict):
                if t.get("task_id") == task_id or "status" in t:
                    return t
    return data


def wait_for_result(client: AceStepClient, task_id: str,
                    poll_interval: float = 3.0, timeout: float = 1800.0) -> dict:
    """轮询直到任务成功（status=1）或失败（status=2）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.query_result([task_id])
        task = _extract_task(data, task_id)
        status = task.get("status") if isinstance(task, dict) else None
        if status == 1:
            return task
        if status == 2:
            raise RuntimeError(f"生成失败: {task}")
        time.sleep(poll_interval)
    raise TimeoutError(f"任务 {task_id} 超过 {timeout}s 未完成")


def build_payload(args: argparse.Namespace) -> dict:
    """根据命令行参数构造 release_task 请求体。"""
    payload: dict = {
        "thinking": not args.no_thinking,
        "vocal_language": args.lang,
        "audio_format": args.format,
        "inference_steps": args.steps,
        "batch_size": args.batch,
    }
    if args.model:
        payload["model"] = args.model
    if args.bpm:
        payload["bpm"] = args.bpm
    if args.duration:
        payload["audio_duration"] = args.duration

    if args.lyrics:
        lyrics_text = Path(args.lyrics).read_text(encoding="utf-8") if Path(args.lyrics).exists() else args.lyrics
        payload["lyrics"] = lyrics_text
        payload["prompt"] = args.style or ""
        payload["use_format"] = True  # 让 LM 优化歌词结构
    else:
        # 主题驱动：模型自动写词 + 作曲
        payload["sample_mode"] = True
        payload["sample_query"] = args.topic
        if args.style:
            payload["prompt"] = args.style
    return payload


def generate_song(client: AceStepClient, args: argparse.Namespace, out_dir: Path) -> list:
    """生成歌曲，返回输出文件信息列表 [{audio, lyrics, lrc}]。"""
    payload = build_payload(args)
    print(f"▶ 提交生成任务 ...")
    task_id = client.release_task(payload)
    print(f"  task_id = {task_id}")

    print(f"⏳ 生成中（轮询查询，首次可能需下载模型）...")
    result = wait_for_result(client, task_id)

    outputs = []
    # 提取音频文件路径（可能有多个 batch）
    files = result.get("file") if isinstance(result, dict) else None
    if isinstance(files, str):
        files = [files]
    files = files or []

    lyrics_text = result.get("lyrics", "") if isinstance(result, dict) else ""

    out_dir.mkdir(parents=True, exist_ok=True)
    base = args.title or "song"
    for i, f in enumerate(files):
        ext = Path(f).suffix or f".{args.format}"
        audio_path = out_dir / f"{base}_{i + 1}{ext}"
        try:
            client.download(f, audio_path)
            print(f"✓ 已下载: {audio_path}")
        except Exception as e:
            print(f"✗ 下载失败 {f}: {e}")
            audio_path = None

        item = {"audio": audio_path, "lyrics": None, "lrc": None}
        if lyrics_text:
            lyric_path = out_dir / f"{base}_{i + 1}.txt"
            lyric_path.write_text(lyrics_text, encoding="utf-8")
            item["lyrics"] = lyric_path
            # 兜底：生成均分时间戳的 LRC（若 ACE-Step 未返回 LRC）
            lrc_path = out_dir / f"{base}_{i + 1}.lrc"
            duration = args.duration or _probe_duration(audio_path)
            lrc.lyrics_to_lrc(lyrics_text.splitlines(), duration)
            lrc.text_to_lrc(lyrics_text.splitlines(), duration, str(lrc_path))
            item["lrc"] = lrc_path
        outputs.append(item)
    return outputs


def _probe_duration(audio_path) -> float:
    """无 ffprobe 时按 90s 兜底（仅用于生成 LRC 的均分估算）。"""
    try:
        import subprocess
        out = subprocess.check_output(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(audio_path)],
            text=True, stderr=subprocess.DEVNULL,
        )
        return float(out.strip())
    except Exception:
        return 90.0


def main() -> int:
    p = argparse.ArgumentParser(description="ACE-Step AI 歌曲生成")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--topic", help="歌曲主题（模型自动写词+作曲），例如“一首关于夏天的中文民谣”")
    g.add_argument("--lyrics", help="歌词文件路径或歌词文本")
    p.add_argument("--style", help="音乐风格描述，例如“温暖治愈的民谣，木吉他伴奏”")
    p.add_argument("--lang", default="zh", help="人声语言（zh/en/ja 等，默认 zh）")
    p.add_argument("--duration", type=float, help="时长（秒，10-600）")
    p.add_argument("--bpm", type=int, help="节拍 BPM（30-300）")
    p.add_argument("--model", help="DiT 模型，如 acestep-v15-turbo / acestep-v15-base")
    p.add_argument("--steps", type=int, default=8, help="推理步数（turbo 推荐 8，base 推荐 32-64）")
    p.add_argument("--batch", type=int, default=2, help="并行生成数量（1-8）")
    p.add_argument("--format", default="mp3", help="输出格式 mp3/wav/flac")
    p.add_argument("--no-thinking", action="store_true", help="关闭 LM 思考（速度更快，质量略降）")
    p.add_argument("--title", help="输出文件名前缀（默认 song）")
    p.add_argument("--host", default=DEFAULT_HOST, help=f"API 主机（默认 {DEFAULT_HOST}）")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"API 端口（默认 {DEFAULT_PORT}）")
    p.add_argument("--api-key", default="", help="若服务端启用了鉴权，提供 API key")
    p.add_argument("--out-dir", default="./output/songs", help="输出目录")
    args = p.parse_args()

    client = AceStepClient(args.host, args.port, args.api_key)
    if not client.health():
        print("✗ 无法连接 ACE-Step API。请先启动服务：")
        print("    cd ACE-Step-1.5 && uv run acestep-api")
        return 1

    out_dir = Path(args.out_dir)
    try:
        outputs = generate_song(client, args, out_dir)
    except Exception as e:
        print(f"✗ 生成失败: {e}")
        return 1

    print("\n===== 完成 =====")
    for o in outputs:
        for k, v in o.items():
            if v:
                print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
