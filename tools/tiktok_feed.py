#!/usr/bin/env python3
"""TikTok：按英文关键词搜最近 N 天的视频（region=US）。

为什么在 cn 引擎里（2026-10-06）：en 日报停跑，原先 en 的 TikTok 挪进 cn。用英文词 + region=US，
与抖音（中文词）错开不重叠；关键词由 hub 的 plan 给（标了 tiktok 的子查询带一个英文关键词）。

数据源：TikHub `tiktok/app/v3/fetch_video_search_result`（经 L30D_BASE_URL 转发层），$0.001/页，每页 20 条，
offset 翻页。publish_time 档：1/7/30/90/180 天；sort_type 0=相关度、1=最多点赞。

实测要点（2026-10-06）：
- region=US 不限语种（俄/葡/西/越/阿拉伯语都有），按 desc_language 只留英文；
  desc_language="un" 多是只有 #标签 的视频，没内容可判，一并丢。
- 只有视频描述，没有字幕/口播；评论区要链接（Comment "X" and I'll send…）的引流帖多，交给 hub 闸门。
- 条目在 data.search_item_list[].aweme_info；data.aweme_list 恒空。

用法：
  python3 tiktok_feed.py --keyword "Claude Code" --days 1
  python3 tiktok_feed.py --keyword "personal AI agent" --keyword "ESP32 robot" --days 3 --pages 2 --json   # MCP 用这个
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

_PATH = "/api/v1/tiktok/app/v3/fetch_video_search_result"
MAX_PAGES = 3
PAGE_SIZE = 20
_WORKERS = 3
_MIN_TEXT = 12       # 去掉 #标签、@、链接后不足 12 个字符的不算内容
_LANGS = {"en"}

_NOISE = re.compile(r"#\S+|@\S+|https?://\S+")


def _date(ts: float) -> str:
    """北京时间日期。服务器是 UTC。"""
    return time.strftime("%Y-%m-%d", time.gmtime(int(ts) + 8 * 3600))


def publish_time(days: float) -> int:
    for d in (1, 7, 30, 90, 180):
        if days <= d:
            return d
    return 0


def _item(a: dict, keyword: str):
    au = a.get("author") or {}
    uid = au.get("unique_id") or ""
    vid = str(a.get("aweme_id") or "")
    if not uid or not vid:
        return None
    st = a.get("statistics") or {}
    eng = {"likes": st.get("digg_count"), "num_comments": st.get("comment_count"),
           "shares": st.get("share_count"), "views": st.get("play_count"), "bookmarks": st.get("collect_count")}
    eng = {k: int(v) for k, v in eng.items() if isinstance(v, (int, float))}
    return {
        "account": uid,
        "name": au.get("nickname") or uid,
        "text": (a.get("desc") or "").strip(),
        "url": f"https://www.tiktok.com/@{uid}/video/{vid}",
        "video_id": vid,
        "lang": a.get("desc_language") or "",
        "engagement": eng,
        "keyword": keyword,
    }


def fetch_keyword(keyword: str, cutoff: float, days: float, key: str, pages: int = 1) -> dict:
    items, err, calls = [], None, 0
    for p in range(max(1, min(pages, MAX_PAGES))):
        params = {"keyword": keyword, "offset": p * PAGE_SIZE, "count": PAGE_SIZE,
                  "sort_type": 0, "publish_time": publish_time(days), "region": "US"}
        payload = tikhub.get(_PATH, params, key, tag="TikTok")
        calls += 1
        if not payload:
            err = "上游无响应或报错（见 stderr）"
            break
        data = payload.get("data") or {}
        rows = data.get("search_item_list") or []
        for row in rows:
            a = (row or {}).get("aweme_info") or {}
            ts = a.get("create_time")
            if not isinstance(ts, (int, float)) or ts < cutoff or a.get("is_ads"):
                continue
            if (a.get("desc_language") or "") not in _LANGS:
                continue
            it = _item(a, keyword)
            if not it or len(_NOISE.sub("", it["text"]).strip()) < _MIN_TEXT:
                continue
            it.update(ts=int(ts), date=_date(ts))
            items.append(it)
        if not rows or not data.get("has_more"):
            break
    return {"keyword": keyword, "error": err, "items": items, "calls": calls}


def run(keywords, days: float, key: str, pages: int = 1) -> dict:
    cutoff = time.time() - days * 86400
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        results = list(pool.map(lambda k: fetch_keyword(k, cutoff, days, key, pages), keywords))
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
    items.sort(key=lambda x: -x["ts"])
    errors = [{"keyword": r["keyword"], "error": r["error"]} for r in results if r["error"]]
    return {"items": items, "errors": errors, "calls": sum(r["calls"] for r in results)}


def main() -> int:
    ap = argparse.ArgumentParser(description="按英文关键词搜 TikTok 最近视频（region=US，只留英文）")
    ap.add_argument("--keyword", action="append", required=True, help="英文关键词，可重复给多个（各自单独搜）")
    ap.add_argument("--days", type=float, default=1, help="最近多少天（默认 1）")
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
            print(f"{it['date']}  @{it['account']}  {it['engagement'].get('likes', 0)} like  {it['text'][:80]}\n    {it['url']}")
        for e in res["errors"]:
            print(f"[失败] {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
