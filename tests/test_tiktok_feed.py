"""tools/tiktok_feed.py 离线回归（桩掉 tikhub.get，不发网络不计费）。

跑法：cd engine && python3 tests/test_tiktok_feed.py
fixture 按 2026-10-06 经网关实测的响应结构手写（data.search_item_list[].aweme_info，has_more，offset 翻页）。
"""
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))

import tiktok_feed  # noqa: E402

NOW = 1791273600.0  # 2026-10-06 00:00 UTC


def _aweme(i, age_h, desc="Claude Code just added mods that change how it works", lang="en", **kw):
    a = {"aweme_id": str(7000 + i), "desc": desc, "desc_language": lang, "create_time": int(NOW - age_h * 3600),
         "is_ads": False, "author": {"unique_id": "dev", "nickname": "Dev Guy"},
         "statistics": {"digg_count": 35, "comment_count": 3, "share_count": 1, "play_count": 454, "collect_count": 9}}
    a.update(kw)
    return {"aweme_info": a, "search_aweme_info": {}}


def _page(rows, more=0):
    return {"code": 200, "data": {"search_item_list": rows, "aweme_list": [], "has_more": more, "cursor": 20}}


class TestTikTok(unittest.TestCase):
    def setUp(self):
        self.t = mock.patch.object(tiktok_feed.time, "time", return_value=NOW)
        self.t.start()

    def tearDown(self):
        self.t.stop()

    def test_params_and_bucket(self):
        with mock.patch.object(tiktok_feed.tikhub, "get", return_value=_page([])) as g:
            tiktok_feed.run(["Claude Code"], 1, "K")
        p = g.call_args.args[1]
        self.assertEqual((p["keyword"], p["publish_time"], p["region"], p["sort_type"], p["offset"]),
                         ("Claude Code", 1, "US", 0, 0))
        self.assertEqual(tiktok_feed.publish_time(3), 7)
        self.assertEqual(tiktok_feed.publish_time(400), 0)

    def test_filters_window_language_hashtag_only_and_ads(self):
        rows = [_aweme(0, 2), _aweme(1, 30), _aweme(2, 2, lang="ru"), _aweme(3, 2, lang="un"),
                _aweme(4, 2, desc="#claudecode #ai #coding"), _aweme(5, 2, is_ads=True)]
        with mock.patch.object(tiktok_feed.tikhub, "get", return_value=_page(rows)):
            r = tiktok_feed.run(["Claude Code"], 1, "K")
        self.assertEqual([i["video_id"] for i in r["items"]], ["7000"])
        it = r["items"][0]
        self.assertEqual(it["url"], "https://www.tiktok.com/@dev/video/7000")
        self.assertEqual(it["engagement"]["likes"], 35)
        self.assertEqual(it["engagement"]["views"], 454)

    def test_pages_by_offset_until_no_more(self):
        pages = [_page([_aweme(0, 1)], more=1), _page([_aweme(1, 1)], more=0)]
        with mock.patch.object(tiktok_feed.tikhub, "get", side_effect=pages) as g:
            r = tiktok_feed.run(["Claude Code"], 1, "K", pages=3)
        self.assertEqual(g.call_count, 2)
        self.assertEqual(g.call_args_list[1].args[1]["offset"], 20)
        self.assertEqual(r["calls"], 2)
        self.assertEqual(len(r["items"]), 2)

    def test_merges_keywords_and_reports_failure(self):
        with mock.patch.object(tiktok_feed.tikhub, "get", return_value=_page([_aweme(0, 1)])):
            r = tiktok_feed.run(["Claude Code", "coding agent"], 1, "K")
        self.assertEqual(len(r["items"]), 1)
        self.assertEqual(sorted(r["items"][0]["keywords"]), ["Claude Code", "coding agent"])
        with mock.patch.object(tiktok_feed.tikhub, "get", return_value=None):
            r = tiktok_feed.run(["Claude Code"], 1, "K")
        self.assertEqual((r["items"], len(r["errors"])), ([], 1))


if __name__ == "__main__":
    unittest.main()
