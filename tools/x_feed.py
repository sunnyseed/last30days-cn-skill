#!/usr/bin/env python3
"""X 订阅号：在指定账号范围内按关键词搜最近 N 天的推文。

为什么是「订阅号 + 关键词」而不是全站搜（2026-10-06）：用户只想看自己挑过的那批中文 AI 号，
做法同公众号白名单；但 X 号每天发帖量大、话题杂，所以再按当天检索词收一道。
号名单从用户 X 书签频次 + 关注列表交叉得来，放在 hub 侧（hub/x_accounts.json）。

数据源：TikHub `twitter/web/fetch_search_timeline`（经 L30D_BASE_URL 转发层），$0.001/页，每页约 20 条。
查询写成 `(from:a OR from:b …) <关键词> since:D until:D`，账号按组切开，避免查询串过长。

实测要点（2026-10-06）：
- since/until 不可靠：查询复杂 + Latest 排序时会漏进窗外几天的帖，必须按 created_at 再筛一次；
  until 当天的帖也会返回（与 X 惯例不同）。
- created_at 只认 timeline[] 顶层那个；user_info / quoted 里也有 created_at（注册时间、被引推文）。
- X 的匹配范围大于正文（引用推文、外链、账号信号都算），关键词不在 text 里的帖也会回来，属正常。

用法：
  python3 x_feed.py dotey op7418 vista8 --keyword "Codex" --days 1
  python3 x_feed.py dotey op7418 --keyword "智能体" --days 3 --pages 2 --json   # MCP 用这个
"""
import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from lib import env, tikhub  # noqa: E402

_PATH = "/api/v1/twitter/web/fetch_search_timeline"
GROUP_SIZE = 14      # 14 个 from: 约 280 字符，给关键词和时间算子留余量（X 查询上限约 512）
MAX_PAGES = 3
_WORKERS = 3
_MIN_TEXT = 6        # 去掉 @、链接后不足 6 个字符的（「Yes」「哈哈」「👍」）不算内容

_MENTION_URL = re.compile(r"@\w+|https?://\S+")


def _date(ts: float) -> str:
    """北京时间日期。服务器是 UTC。"""
    return time.strftime("%Y-%m-%d", time.gmtime(int(ts) + 8 * 3600))


def _ts(created_at: str):
    try:
        return parsedate_to_datetime(created_at).timestamp()
    except (TypeError, ValueError):
        return None


def build_query(accounts, keyword: str, since: str, until: str) -> str:
    froms = " OR ".join(f"from:{a}" for a in accounts)
    return f"({froms}) {keyword} since:{since} until:{until}".replace("  ", " ")


def _item(t: dict, keyword: str):
    sn = t.get("screen_name") or (t.get("user_info") or {}).get("screen_name") or ""
    tid = str(t.get("tweet_id") or "")
    text = (t.get("text") or "").strip()
    if not sn or not tid:
        return None
    eng = {"likes": t.get("favorites"), "reposts": t.get("retweets"), "num_comments": t.get("replies"),
           "quotes": t.get("quotes"), "bookmarks": t.get("bookmarks"), "views": t.get("views")}
    eng = {k: int(v) for k, v in eng.items() if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit())}
    return {
        "account": sn,
        "name": (t.get("user_info") or {}).get("name") or sn,
        "text": text,
        "url": f"https://x.com/{sn}/status/{tid}",
        "tweet_id": tid,
        "lang": t.get("lang") or "",
        "engagement": eng,
        "keyword": keyword,
    }


def fetch_group(accounts, keyword: str, cutoff: float, key: str, pages: int = 2) -> dict:
    """一组账号 × 一个关键词，翻 pages 页，按 created_at 收窄到 cutoff 之后。"""
    since = time.strftime("%Y-%m-%d", time.gmtime(cutoff - 86400))   # 宽一天，窗口由 cutoff 定
    until = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 86400))
    q = build_query(accounts, keyword, since, until)
    items, cursor, err = [], None, None
    for _ in range(max(1, min(pages, MAX_PAGES))):
        params = {"keyword": q, "search_type": "Latest"}
        if cursor:
            params["cursor"] = cursor
        payload = tikhub.get(_PATH, params, key, tag="X")
        if not payload:
            err = "上游无响应或报错（见 stderr）"
            break
        data = payload.get("data") or {}
        tl = data.get("timeline") or []
        oldest = None
        for t in tl:
            ts = _ts(t.get("created_at"))
            if ts is None:
                continue
            oldest = ts if oldest is None else min(oldest, ts)
            if ts < cutoff:
                continue
            it = _item(t, keyword)
            if not it or it["text"].startswith("RT @"):
                continue
            if len(_MENTION_URL.sub("", it["text"]).strip()) < _MIN_TEXT:
                continue
            it.update(ts=int(ts), date=_date(ts))
            items.append(it)
        nxt = data.get("next_cursor")
        # Latest 按时间倒序：本页最老的已早于窗口，再翻也只会更老
        if not tl or not nxt or nxt == cursor or (oldest is not None and oldest < cutoff):
            break
        cursor = nxt
    return {"accounts": accounts, "keyword": keyword, "error": err, "items": items}


def run(accounts, keywords, days: float, key: str, pages: int = 2) -> dict:
    cutoff = time.time() - days * 86400
    groups = [accounts[i:i + GROUP_SIZE] for i in range(0, len(accounts), GROUP_SIZE)]
    tasks = [(g, k) for k in keywords for g in groups]
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        results = list(pool.map(lambda gk: fetch_group(gk[0], gk[1], cutoff, key, pages), tasks))
    seen, items = {}, []
    for r in results:
        for it in r["items"]:
            if it["tweet_id"] in seen:          # 同一条被两个关键词搜到：记下两个词
                kw = seen[it["tweet_id"]]["keywords"]
                if it["keyword"] not in kw:
                    kw.append(it["keyword"])
                continue
            it["keywords"] = [it.pop("keyword")]
            seen[it["tweet_id"]] = it
            items.append(it)
    items.sort(key=lambda x: -x["ts"])
    errors = [{"accounts": r["accounts"][:3], "keyword": r["keyword"], "error": r["error"]}
              for r in results if r["error"]]
    return {"items": items, "errors": errors, "calls": len(tasks)}


def main() -> int:
    ap = argparse.ArgumentParser(description="在 X 订阅号范围内按关键词搜最近推文")
    ap.add_argument("accounts", nargs="+", help="X 账号 screen_name（不带 @）")
    ap.add_argument("--keyword", action="append", required=True, help="关键词，可重复给多个（各自单独搜）")
    ap.add_argument("--days", type=float, default=1, help="最近多少天（默认 1，按时间戳滚动计算）")
    ap.add_argument("--pages", type=int, default=2, help=f"每组每词最多翻几页（默认 2，上限 {MAX_PAGES}）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    key = env.get_config().get("L30D_API_KEY") or env.get_config().get("TIKHUB_API_KEY")
    if not key:
        sys.exit("未找到 L30D_API_KEY")
    accounts = [a.strip().lstrip("@") for a in args.accounts if a.strip()]
    res = run(accounts, [k.strip() for k in args.keyword if k.strip()], args.days, key, args.pages)
    if args.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        for it in res["items"]:
            print(f"{it['date']}  @{it['account']}  {it['text'][:80]}\n    {it['url']}")
        for e in res["errors"]:
            print(f"[失败] {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
