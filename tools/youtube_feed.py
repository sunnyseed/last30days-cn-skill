#!/usr/bin/env python3
"""YouTube：按关键词搜最近 N 天的视频。

为什么在 cn 引擎里（2026-10-06）：Claude Code 日常查询的英文源都收进远程 MCP，en（/last30days）退为备用。
只给检索结果（标题、频道、播放量、简介）；要看内容再用 tools/youtube_transcript.py 按需取字幕。

数据源：TikHub `youtube/web_v2/get_general_search_v2`（经 L30D_BASE_URL 转发层），每页 20 条，
continuation_token 翻页。upload_date 档：today / this_week / this_month / this_year。

实测要点（2026-10-06，「Claude Code」本月）：
- sort_by=relevance 最好（官方频道、教程大号在前）；view_count 会被「AI 赚钱」类泛流量视频顶上来；
  upload_date 排序实测不生效，和 relevance 几乎同序。所以默认 relevance、不开放别的。
- published_time 只有相对时间（「20 hours ago」「2 weeks ago」「1 month ago」），周以上精度很粗。
  换算成近似时间戳、条目标 date_approx=True；窗口主要靠 upload_date 档，本地只按近似时间再收一道。
- view_count 是字符串「180,263 views」。
- 翻页要**全部参数 + token** 一起传。文档说「keyword 仅首次请求必填」，照此只传 token 实测 400；
  全参数 + token 第二页 20 条、与第一页零重复。

用法：
  python3 youtube_feed.py --keyword "Claude Code" --days 7
  python3 youtube_feed.py --keyword "Claude Code" --keyword "Codex CLI" --days 30 --pages 2 --json   # MCP 用这个
"""
import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from lib import env, tikhub  # noqa: E402

_PATH = "/api/v1/youtube/web_v2/get_general_search_v2"
MAX_PAGES = 3
_WORKERS = 3

_UNIT = {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "week": 7 * 86400,
         "month": 30 * 86400, "year": 365 * 86400}
_REL = re.compile(r"(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago", re.I)


def _date(ts: float) -> str:
    """北京时间日期。服务器是 UTC。"""
    return time.strftime("%Y-%m-%d", time.gmtime(int(ts) + 8 * 3600))


def upload_date(days: float) -> str:
    return "today" if days <= 1 else "this_week" if days <= 7 else "this_month" if days <= 31 else "this_year"


def age_seconds(published: str):
    """「20 hours ago」「Streamed 2 days ago」→ 秒数；认不出返回 None。"""
    m = _REL.search(published or "")
    return int(m.group(1)) * _UNIT[m.group(2).lower()] if m else None


def _views(s):
    m = re.search(r"[\d,]+", str(s or ""))
    return int(m.group(0).replace(",", "")) if m else None


def _item(v: dict, keyword: str):
    vid = v.get("video_id") or ""
    if not vid or not v.get("title"):
        return None
    eng = {"views": _views(v.get("view_count"))}
    return {
        "channel": v.get("author") or "",
        "channel_id": v.get("channel_id") or "",
        "title": v["title"].strip(),
        "text": (v.get("description_snippet") or "").strip(),
        "url": v.get("url") or f"https://www.youtube.com/watch?v={vid}",
        "video_id": vid,
        "duration": v.get("duration") or "",
        "published": v.get("published_time") or "",
        "engagement": {k: x for k, x in eng.items() if x is not None},
        "keyword": keyword,
    }


def fetch_keyword(keyword: str, days: float, key: str, pages: int = 1) -> dict:
    now = time.time()
    items, err, calls, token = [], None, 0, None
    for _ in range(max(1, min(pages, MAX_PAGES))):
        params = {"keyword": keyword, "upload_date": upload_date(days), "type": "video", "sort_by": "relevance"}
        if token:
            params["continuation_token"] = token
        payload = tikhub.get(_PATH, params, key, tag="YouTube")
        calls += 1
        if not payload:
            err = "上游无响应或报错（见 stderr）"
            break
        data = payload.get("data") or {}
        vids = data.get("videos") or []
        for v in vids:
            age = age_seconds(v.get("published_time"))
            if age is not None and age > days * 86400:
                continue
            it = _item(v, keyword)
            if not it:
                continue
            ts = now - (age or 0)
            it.update(ts=int(ts), date=_date(ts), date_approx=True)
            items.append(it)
        nxt = data.get("continuation_token")
        if not vids or not nxt or nxt == token:
            break
        token = nxt
    return {"keyword": keyword, "error": err, "items": items, "calls": calls}


def run(keywords, days: float, key: str, pages: int = 1) -> dict:
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        results = list(pool.map(lambda k: fetch_keyword(k, days, key, pages), keywords))
    seen, items = {}, []
    for r in results:
        for it in r["items"]:
            if it["video_id"] in seen:          # 同一条被两个关键词搜到：记下两个词
                kw = seen[it["video_id"]]["keywords"]
                if it["keyword"] not in kw:
                    kw.append(it["keyword"])
                continue
            it["keywords"] = [it.pop("keyword")]
            seen[it["video_id"]] = it
            items.append(it)
    errors = [{"keyword": r["keyword"], "error": r["error"]} for r in results if r["error"]]
    # 保持上游相关性顺序（不按时间重排：时间是近似值，相关性才是这个源的强项）
    return {"items": items, "errors": errors, "calls": sum(r["calls"] for r in results)}


def main() -> int:
    ap = argparse.ArgumentParser(description="按关键词搜 YouTube 最近视频（按相关性）")
    ap.add_argument("--keyword", action="append", required=True, help="关键词，可重复给多个（各自单独搜）")
    ap.add_argument("--days", type=float, default=7, help="最近多少天（默认 7；按 today/this_week/this_month/this_year 取档）")
    ap.add_argument("--pages", type=int, default=1, help=f"每词最多翻几页（默认 1，每页 20 条，上限 {MAX_PAGES}）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    key = env.get_config().get("L30D_API_KEY") or env.get_config().get("TIKHUB_API_KEY")
    if not key:
        sys.exit("未找到 L30D_API_KEY")
    res = run([k.strip() for k in args.keyword if k.strip()], args.days, key, args.pages)
    if args.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        for it in res["items"]:
            print(f"{it['published']:>14}  {it['channel']}  {it['engagement'].get('views', '?')} views  "
                  f"{it['title'][:70]}\n    {it['url']}")
        for e in res["errors"]:
            print(f"[失败] {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
