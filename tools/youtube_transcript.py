#!/usr/bin/env python3
"""YouTube 单条视频的字幕全文（纯文本）。

存在理由同 xhs_note：搜索只给标题和一句简介，视频讲了什么得看字幕。按需取，不批量——
$0.008/次（搜索的 8 倍），视频没有字幕也照样计费。

数据源：TikHub `youtube/web_v2/get_video_captions`（经 L30D_BASE_URL 转发层），format=txt。
直接按语种取，不先调一次「列字幕语种」（那也是 $0.008）。只返回视频自带字幕（含自动字幕），不做语音转写。
大视频上游会转异步：返回 status=processing + job_id，再轮询 `get_video_captions_result`。

实测（2026-10-06）：2 小时 13 分的教程同步返回，14 秒，11.8 万字符 / 2.1 万词。
所以默认截断到 --max-chars（20000），返回里带 total_chars 与 truncated，调用方要全文再调大。

用法：
  python3 youtube_transcript.py u2QqWkMv3Lg
  python3 youtube_transcript.py "https://www.youtube.com/watch?v=u2QqWkMv3Lg" --lang en --max-chars 50000 --json
"""
import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from lib import env, tikhub  # noqa: E402

_PATH = "/api/v1/youtube/web_v2/get_video_captions"
_RESULT_PATH = "/api/v1/youtube/web_v2/get_video_captions_result"
_POLL_EVERY = 6
_POLL_MAX = 15          # 约 90 秒
MAX_CHARS = 200_000

_ID = re.compile(r"(?:v=|youtu\.be/|/shorts/|/live/|/embed/)([A-Za-z0-9_-]{11})")


def video_id(s: str) -> str:
    s = (s or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", s):
        return s
    m = _ID.search(s)
    if not m:
        raise ValueError(f"认不出 YouTube 视频 ID：{s!r}")
    return m.group(1)


def fetch(vid: str, lang: str, key: str, max_chars: int = 20000) -> dict:
    out = {"video_id": vid, "url": f"https://www.youtube.com/watch?v={vid}", "language_code": lang, "calls": 0}
    payload = tikhub.get(_PATH, {"video_id": vid, "language_code": lang, "format": "txt"}, key, tag="YouTube")
    out["calls"] += 1
    data = (payload or {}).get("data")
    if not isinstance(data, dict):
        return {**out, "error": "上游无响应或报错（见 stderr）"}
    if data.get("status") == "processing" and data.get("job_id"):
        for _ in range(_POLL_MAX):
            time.sleep(_POLL_EVERY)
            p = tikhub.get(_RESULT_PATH, {"job_id": data["job_id"], "format": "txt"}, key, tag="YouTube")
            out["calls"] += 1
            d = (p or {}).get("data")
            if isinstance(d, dict) and d.get("status") != "processing":
                data = d
                break
        else:
            return {**out, "error": f"字幕异步任务超时（job_id={data['job_id']}）"}
    content = data.get("content")
    if not isinstance(content, str) or not content.strip():
        # 无字幕 / 无此语种：上游 200 + 提示，照样计费；把可用语种原样带回去
        return {**out, "error": data.get("message_zh") or data.get("message") or "该视频没有此语种字幕",
                "available": [c.get("language_code") for c in data.get("captions") or [] if isinstance(c, dict)]}
    content = re.sub(r"\s+", " ", content).strip()
    return {**out, "language_name": data.get("language_name") or "", "total_chars": len(content),
            "truncated": len(content) > max_chars, "content": content[:max_chars]}


def main() -> int:
    ap = argparse.ArgumentParser(description="取 YouTube 视频字幕全文（纯文本）")
    ap.add_argument("video", help="视频 ID 或链接")
    ap.add_argument("--lang", default="en", help="字幕语种（默认 en；中文如 zh-Hans）")
    ap.add_argument("--max-chars", type=int, default=20000, help=f"最多返回多少字符（默认 20000，上限 {MAX_CHARS}）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    key = env.get_config().get("L30D_API_KEY") or env.get_config().get("TIKHUB_API_KEY")
    if not key:
        sys.exit("未找到 L30D_API_KEY")
    try:
        vid = video_id(args.video)
    except ValueError as e:
        sys.exit(str(e))
    res = fetch(vid, args.lang.strip() or "en", key, max(1000, min(args.max_chars, MAX_CHARS)))
    if args.json:
        print(json.dumps(res, ensure_ascii=False))
    elif res.get("error"):
        print(f"[失败] {res['error']}  可用语种：{res.get('available')}", file=sys.stderr)
        return 1
    else:
        print(f"{res['url']}  {res['total_chars']} 字符{'（已截断）' if res['truncated'] else ''}\n")
        print(res["content"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
