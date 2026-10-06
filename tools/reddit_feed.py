#!/usr/bin/env python3
"""Reddit 订阅版块：拉指定版块最近 N 天的热帖（不带关键词）。

为什么只接订阅版块（2026-10-06）：按话题搜 Reddit 相关性很松，搜 "Claude Code" 当天 TOP 7 条里
3 条无关（段子版、二手 iPod 版），加引号也一样；限定版块后结果干净。做法同公众号白名单，
版块名单放在 hub 侧（hub/reddit_subs.json）。版块是社区而非作者，质量交给 hub 的完整闸门。

数据源：TikHub `reddit/app/fetch_dynamic_search`（经 L30D_BASE_URL 转发层），$0.001/页，每页 7 条，
用 `subreddit:A OR subreddit:B …` 一次查全部版块，sort=TOP，time_range 按窗口取 day/week/month，
createdAt（ISO，UTC）再按窗口收窄一次。

用法：
  python3 reddit_feed.py ClaudeAI LocalLLaMA --days 1
  python3 reddit_feed.py ClaudeAI LocalLLaMA ClaudeCode --days 1 --pages 3 --json   # MCP 用这个
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from lib import env, tikhub  # noqa: E402

_PATH = "/api/v1/reddit/app/fetch_dynamic_search"
MAX_PAGES = 4


def _date(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(int(ts) + 8 * 3600))


def _ts(iso: str):
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def time_range(days: float) -> str:
    return "day" if days <= 1 else "week" if days <= 7 else "month"


def build_query(subs) -> str:
    return " OR ".join(f"subreddit:{s}" for s in subs)


def _item(p: dict):
    sub = p.get("subreddit")
    sub = (sub.get("name") if isinstance(sub, dict) else sub) or ""
    link = p.get("permalink") or ""
    if link and not link.startswith("http"):
        link = "https://www.reddit.com" + link
    content = p.get("content") or {}
    body = content.get("markdown") if isinstance(content, dict) else ""
    author = p.get("authorInfo") or {}
    eng = {"score": p.get("score"), "num_comments": p.get("commentCount")}
    eng = {k: int(v) for k, v in eng.items() if isinstance(v, (int, float))}
    return {
        "subreddit": sub,
        "title": (p.get("postTitle") or "").strip(),
        "body": (body or "").strip()[:600],
        "author": author.get("name") if isinstance(author, dict) else "",
        "url": link or p.get("url") or "",
        "engagement": eng,
        "upvote_ratio": p.get("upvoteRatio"),
    }


def run(subs, days: float, key: str, pages: int = 2) -> dict:
    cutoff = time.time() - days * 86400
    items, seen, cursor, err, calls = [], set(), "", None, 0
    for _ in range(max(1, min(pages, MAX_PAGES))):
        params = {"query": build_query(subs), "search_type": "post", "sort": "TOP",
                  "time_range": time_range(days), "need_format": "true"}
        if cursor:
            params["after"] = cursor
        payload = tikhub.get(_PATH, params, key, tag="Reddit")
        calls += 1
        if not payload:
            err = "上游无响应或报错（见 stderr）"
            break
        data = payload.get("data") or {}
        for c in data.get("children") or []:
            p = (c or {}).get("post") or {}
            ts = _ts(p.get("createdAt"))
            if ts is None or ts < cutoff or p.get("isNsfw") or p.get("isStickied"):
                continue
            it = _item(p)
            if not it["title"] or it["url"] in seen:
                continue
            seen.add(it["url"])
            it.update(ts=int(ts), date=_date(ts))
            items.append(it)
        info = data.get("pageInfo") or {}
        nxt = info.get("endCursor")
        if not info.get("hasNextPage") or not nxt or nxt == cursor:
            break
        cursor = nxt
    return {"items": items, "errors": [{"error": err}] if err else [], "calls": calls}


def main() -> int:
    ap = argparse.ArgumentParser(description="拉 Reddit 订阅版块的最近热帖")
    ap.add_argument("subs", nargs="+", help="版块名（不带 r/）")
    ap.add_argument("--days", type=float, default=1, help="最近多少天（默认 1）")
    ap.add_argument("--pages", type=int, default=2, help=f"最多翻几页（默认 2，每页 7 条，上限 {MAX_PAGES}）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    key = env.get_config().get("L30D_API_KEY") or env.get_config().get("TIKHUB_API_KEY")
    if not key:
        sys.exit("未找到 L30D_API_KEY")
    subs = [s.strip().removeprefix("r/") for s in args.subs if s.strip()]
    res = run(subs, args.days, key, args.pages)
    if args.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        for it in res["items"]:
            print(f"{it['date']}  r/{it['subreddit']}  {it['engagement']}  {it['title'][:70]}\n    {it['url']}")
        for e in res["errors"]:
            print(f"[失败] {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
