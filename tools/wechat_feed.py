#!/usr/bin/env python3
"""微信公众号白名单：拉指定公众号在最近 N 天内发的文章。

为什么要它（2026-10-05）：关键词搜一搜搜出来的基本是营销号——用户标注的 87 条微信
没有一条「感兴趣」。用户要的是「只关注一小撮人」：从他 X 书签里反复出现的中文作者
反推出公众号，直接拉这些号的新文章，不再靠关键词碰运气。

数据源：TikHub `wechat_mp/v2/fetch_account_articles`（经 L30D_BASE_URL 转发层），
**$0.01/次**（搜索的 10 倍），每个号一次只取首页（公众号首页即最近一二十篇，日更窗口足够）。
上游慢，文档要求 30s 超时；`lib/tikhub.py` 的 45s + 3 次退避重试覆盖得住。

用法：
  python3 wechat_feed.py gh_d63c242792d8 gh_9a1919baf888 --days 1
  python3 wechat_feed.py gh_xxx --days 3 --json      # 机器可读（MCP 用这个）
"""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

# 只加 engine/scripts，经 lib 包导入（scripts/lib 本身加进去会让 lib/http.py 顶掉标准库 http）
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from lib import env, tikhub  # noqa: E402

_PATH = "/api/v1/wechat_mp/v2/fetch_account_articles"
_WORKERS = 4  # 上游单次可达 30s，串行 13 个号会超过 MCP 的子进程超时


def _date(ts: int) -> str:
    """北京时间日期。服务器是 UTC，用 localtime 会和本机差一天。"""
    return time.strftime("%Y-%m-%d", time.gmtime(int(ts) + 8 * 3600))


def fetch_account(username: str, cutoff: float, key: str) -> dict:
    payload = tikhub.post(_PATH, {"username": username, "raw": False}, key, tag="公众号")
    if not payload:
        return {"account": username, "error": "上游无响应或报错（见 stderr）", "items": []}
    data = payload.get("data") or {}
    items = []
    for a in data.get("articles") or []:
        ts = a.get("create_time") or a.get("update_time") or 0
        try:
            ts = int(ts)
        except (TypeError, ValueError):
            continue
        if ts < cutoff:
            continue
        items.append({
            "account": username,
            "title": (a.get("title") or "").strip(),
            "digest": (a.get("digest") or "").strip(),
            "url": a.get("url") or "",
            "ts": ts,
            "date": _date(ts),
            "is_paid": bool(a.get("is_paid") or a.get("is_pay_subscribe")),
        })
    return {"account": username, "error": None, "items": items}


def main() -> int:
    ap = argparse.ArgumentParser(description="拉微信公众号白名单的最近文章")
    ap.add_argument("accounts", nargs="+", help="公众号 username（gh_… 或自定义微信号）")
    ap.add_argument("--days", type=float, default=1, help="最近多少天（默认 1，按时间戳滚动计算）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    key = env.get_config().get("L30D_API_KEY") or env.get_config().get("TIKHUB_API_KEY")
    if not key:
        sys.exit("未找到 L30D_API_KEY")
    cutoff = time.time() - args.days * 86400

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        results = list(pool.map(lambda u: fetch_account(u, cutoff, key), args.accounts))

    items = sorted((it for r in results for it in r["items"]), key=lambda x: -x["ts"])
    errors = [{"account": r["account"], "error": r["error"]} for r in results if r["error"]]
    if args.json:
        print(json.dumps({"items": items, "errors": errors}, ensure_ascii=False))
    else:
        for it in items:
            print(f"{it['date']}  {it['account']}  {it['title']}\n    {it['url']}")
        for e in errors:
            print(f"[失败] {e['account']}: {e['error']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
