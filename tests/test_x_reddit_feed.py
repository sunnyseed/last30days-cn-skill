"""tools/x_feed.py 与 tools/reddit_feed.py 离线回归（桩掉 tikhub.get，不发网络不计费）。

跑法：cd engine && python3 tests/test_x_reddit_feed.py
fixture 按 2026-10-06 经网关实测的响应结构手写（X：data.timeline[]/next_cursor；
Reddit：data.children[].post/pageInfo）。
"""
import os
import sys
import unittest
from email.utils import format_datetime
from datetime import datetime, timezone
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))

import reddit_feed  # noqa: E402
import x_feed  # noqa: E402

NOW = 1791273600.0  # 2026-10-06 00:00 UTC


def _rfc(ts):
    return format_datetime(datetime.fromtimestamp(ts, timezone.utc))


def _tweet(i, age_h, text="Codex 新功能实测，配置过程如下", sn="dotey"):
    ts = NOW - age_h * 3600
    return {"tweet_id": str(1000 + i), "screen_name": sn, "created_at": _rfc(ts), "text": text,
            "favorites": 10, "retweets": 2, "replies": 1, "views": "3473", "lang": "zh",
            "user_info": {"screen_name": sn, "name": "宝玉", "created_at": "Sun Feb 15 00:00:00 +0000 2009"}}


def _x_page(tweets, cursor="NEXT"):
    return {"code": 200, "data": {"timeline": tweets, "next_cursor": cursor}}


class TestX(unittest.TestCase):
    def setUp(self):
        self.t = mock.patch.object(x_feed.time, "time", return_value=NOW)
        self.t.start()

    def tearDown(self):
        self.t.stop()

    def test_query_shape(self):
        q = x_feed.build_query(["a", "b"], "Codex", "2026-10-04", "2026-10-07")
        self.assertEqual(q, "(from:a OR from:b) Codex since:2026-10-04 until:2026-10-07")

    def test_window_filter_by_created_at_not_user_info(self):
        """since/until 实测不可靠，要按推文顶层 created_at 再筛；user_info 里的注册时间不能当推文时间。"""
        page = _x_page([_tweet(0, 2), _tweet(1, 30), _tweet(2, 50)], cursor=None)
        with mock.patch.object(x_feed.tikhub, "get", return_value=page):
            r = x_feed.fetch_group(["dotey"], "Codex", NOW - 86400, "K")
        self.assertEqual([i["tweet_id"] for i in r["items"]], ["1000"])
        self.assertEqual(r["items"][0]["url"], "https://x.com/dotey/status/1000")
        self.assertEqual(r["items"][0]["engagement"]["views"], 3473)

    def test_drops_retweets_and_empty_replies(self):
        page = _x_page([_tweet(0, 1, "RT @x: 转推"), _tweet(1, 1, "@someone Yes https://t.co/abc"),
                        _tweet(2, 1, "哈哈"), _tweet(3, 1)], cursor=None)
        with mock.patch.object(x_feed.tikhub, "get", return_value=page):
            r = x_feed.fetch_group(["dotey"], "Codex", NOW - 86400, "K")
        self.assertEqual([i["tweet_id"] for i in r["items"]], ["1003"])

    def test_stops_paging_once_older_than_window(self):
        pages = [_x_page([_tweet(0, 1), _tweet(1, 40)]), _x_page([_tweet(2, 1)])]
        with mock.patch.object(x_feed.tikhub, "get", side_effect=pages) as g:
            x_feed.fetch_group(["dotey"], "Codex", NOW - 86400, "K", pages=2)
        self.assertEqual(g.call_count, 1)

    def test_pages_with_cursor(self):
        pages = [_x_page([_tweet(0, 1)], "C1"), _x_page([_tweet(1, 2)], None)]
        with mock.patch.object(x_feed.tikhub, "get", side_effect=pages) as g:
            r = x_feed.fetch_group(["dotey"], "Codex", NOW - 86400, "K", pages=3)
        self.assertEqual(len(r["items"]), 2)
        self.assertEqual(g.call_args_list[1].args[1]["cursor"], "C1")

    def test_run_groups_accounts_and_merges_keywords(self):
        accts = [f"a{i}" for i in range(20)]   # 20 个号 → 两组
        page = _x_page([_tweet(0, 1)], cursor=None)
        with mock.patch.object(x_feed.tikhub, "get", return_value=page) as g:
            r = x_feed.run(accts, ["Codex", "智能体"], 1, "K")
        self.assertEqual(g.call_count, 4)        # 2 组 × 2 词
        self.assertEqual(r["calls"], 4)
        self.assertEqual(len(r["items"]), 1)     # 同一条去重
        self.assertEqual(sorted(r["items"][0]["keywords"]), ["Codex", "智能体"])

    def test_upstream_failure_reported(self):
        with mock.patch.object(x_feed.tikhub, "get", return_value=None):
            r = x_feed.run(["a"], ["Codex"], 1, "K")
        self.assertEqual(r["items"], [])
        self.assertEqual(len(r["errors"]), 1)


def _post(i, age_h, sub="ClaudeAI", **kw):
    created = datetime.fromtimestamp(NOW - age_h * 3600, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000+0000")
    p = {"id": f"t3_{i}", "createdAt": created, "postTitle": f"帖子{i}", "score": 100, "commentCount": 5,
         "subreddit": {"name": sub}, "permalink": f"/r/{sub}/comments/{i}/x/", "authorInfo": {"name": "u"},
         "content": {"markdown": "body"}, "isNsfw": False, "isStickied": False}
    p.update(kw)
    return {"post": p}


class TestReddit(unittest.TestCase):
    def setUp(self):
        self.t = mock.patch.object(reddit_feed.time, "time", return_value=NOW)
        self.t.start()

    def tearDown(self):
        self.t.stop()

    def test_query_and_params(self):
        page = {"data": {"children": [], "pageInfo": {"hasNextPage": False}}}
        with mock.patch.object(reddit_feed.tikhub, "get", return_value=page) as g:
            reddit_feed.run(["ClaudeAI", "LocalLLaMA"], 1, "K")
        params = g.call_args.args[1]
        self.assertEqual(params["query"], "subreddit:ClaudeAI OR subreddit:LocalLLaMA")
        self.assertEqual((params["sort"], params["time_range"]), ("TOP", "day"))
        self.assertEqual(reddit_feed.time_range(3), "week")

    def test_window_nsfw_sticky_filtered_and_permalink_absolute(self):
        page = {"data": {"children": [_post(1, 2), _post(2, 30), _post(3, 2, isNsfw=True),
                                      _post(4, 2, isStickied=True)],
                         "pageInfo": {"hasNextPage": False}}}
        with mock.patch.object(reddit_feed.tikhub, "get", return_value=page):
            r = reddit_feed.run(["ClaudeAI"], 1, "K")
        self.assertEqual([i["title"] for i in r["items"]], ["帖子1"])
        it = r["items"][0]
        self.assertEqual(it["url"], "https://www.reddit.com/r/ClaudeAI/comments/1/x/")
        self.assertEqual(it["engagement"], {"score": 100, "num_comments": 5})

    def test_pages_with_after_cursor(self):
        pages = [{"data": {"children": [_post(1, 1)], "pageInfo": {"hasNextPage": True, "endCursor": "E1"}}},
                 {"data": {"children": [_post(2, 1)], "pageInfo": {"hasNextPage": False}}}]
        with mock.patch.object(reddit_feed.tikhub, "get", side_effect=pages) as g:
            r = reddit_feed.run(["ClaudeAI"], 1, "K", pages=3)
        self.assertEqual(len(r["items"]), 2)
        self.assertEqual(g.call_args_list[1].args[1]["after"], "E1")


if __name__ == "__main__":
    unittest.main()
