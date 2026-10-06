"""tools/youtube_feed.py 与 tools/youtube_transcript.py 离线回归（桩掉 tikhub.get，不发网络不计费）。

跑法：cd engine && python3 tests/test_youtube.py
fixture 按 2026-10-06 经网关实测的响应结构手写（搜索：data.videos[] / continuation_token；
字幕：data.content，大视频 status=processing + job_id）。
"""
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))

import youtube_feed  # noqa: E402
import youtube_transcript  # noqa: E402

NOW = 1791273600.0  # 2026-10-06 00:00 UTC


def _video(i, published="2 days ago", views="10,357 views", title="Claude Code Full Course"):
    vid = f"vid{i:08d}"
    return {"video_id": vid, "title": title, "duration": "18:10", "view_count": views,
            "published_time": published, "author": "AI Master", "channel_id": "UCabc",
            "thumbnails": [], "description_snippet": "How senior engineers build with AI ...",
            "url": f"https://www.youtube.com/watch?v={vid}"}


def _page(videos, token="TOK"):
    return {"code": 200, "data": {"keyword": "x", "videos": videos, "shorts": [], "channels": [],
                                  "playlists": [], "continuation_token": token}}


class TestYouTubeFeed(unittest.TestCase):
    def setUp(self):
        self.t = mock.patch.object(youtube_feed.time, "time", return_value=NOW)
        self.t.start()

    def tearDown(self):
        self.t.stop()

    def test_relative_time(self):
        a = youtube_feed.age_seconds
        self.assertEqual(a("20 hours ago"), 20 * 3600)
        self.assertEqual(a("1 day ago"), 86400)
        self.assertEqual(a("Streamed 2 weeks ago"), 14 * 86400)
        self.assertEqual(a("1 month ago"), 30 * 86400)
        self.assertIsNone(a(""))
        self.assertEqual([youtube_feed.upload_date(d) for d in (1, 3, 30, 90)],
                         ["today", "this_week", "this_month", "this_year"])

    def test_params_window_and_fields(self):
        page = _page([_video(0, "20 hours ago"), _video(1, "1 week ago"), _video(2, "2 weeks ago"),
                      _video(3, None)], token=None)
        with mock.patch.object(youtube_feed.tikhub, "get", return_value=page) as g:
            r = youtube_feed.run(["Claude Code"], 7, "K")
        self.assertEqual(g.call_args.args[1], {"keyword": "Claude Code", "upload_date": "this_week",
                                               "type": "video", "sort_by": "relevance"})
        # 2 weeks ago 出窗；认不出时间的留下（窗口已由 upload_date 档挡过一道）
        self.assertEqual([i["video_id"] for i in r["items"]], ["vid00000000", "vid00000001", "vid00000003"])
        it = r["items"][0]
        self.assertEqual(it["engagement"], {"views": 10357})
        self.assertTrue(it["date_approx"])
        self.assertEqual(it["channel"], "AI Master")

    def test_pages_with_full_params_and_token(self):
        """只传 token 实测 400，翻页必须带上全部检索参数。"""
        pages = [_page([_video(0)], "T1"), _page([_video(1)], None)]
        with mock.patch.object(youtube_feed.tikhub, "get", side_effect=pages) as g:
            r = youtube_feed.run(["Codex"], 30, "K", pages=3)
        self.assertEqual(r["calls"], 2)
        self.assertEqual(g.call_args_list[1].args[1], {"keyword": "Codex", "upload_date": "this_month", "type": "video",
                                                       "sort_by": "relevance", "continuation_token": "T1"})

    def test_merge_keywords_and_keep_relevance_order(self):
        page = _page([_video(1, "3 days ago"), _video(0, "1 hour ago")], token=None)
        with mock.patch.object(youtube_feed.tikhub, "get", return_value=page):
            r = youtube_feed.run(["Claude Code", "Codex"], 7, "K")
        self.assertEqual([i["video_id"] for i in r["items"]], ["vid00000001", "vid00000000"])
        self.assertEqual(r["items"][0]["keywords"], ["Claude Code", "Codex"])

    def test_upstream_failure(self):
        with mock.patch.object(youtube_feed.tikhub, "get", return_value=None):
            r = youtube_feed.run(["Codex"], 7, "K")
        self.assertEqual((r["items"], len(r["errors"])), ([], 1))


class TestYouTubeTranscript(unittest.TestCase):
    def test_video_id(self):
        v = youtube_transcript.video_id
        self.assertEqual(v("u2QqWkMv3Lg"), "u2QqWkMv3Lg")
        self.assertEqual(v("https://www.youtube.com/watch?v=u2QqWkMv3Lg&t=30s"), "u2QqWkMv3Lg")
        self.assertEqual(v("https://youtu.be/u2QqWkMv3Lg"), "u2QqWkMv3Lg")
        self.assertEqual(v("https://www.youtube.com/shorts/u2QqWkMv3Lg"), "u2QqWkMv3Lg")
        with self.assertRaises(ValueError):
            v("not a video")

    def test_sync_and_truncate(self):
        resp = {"data": {"video_id": "u2QqWkMv3Lg", "language_code": "en", "language_name": "English",
                         "format": "txt", "content": "This is claude code\nrefusing  to read " * 100}}
        with mock.patch.object(youtube_transcript.tikhub, "get", return_value=resp) as g:
            r = youtube_transcript.fetch("u2QqWkMv3Lg", "en", "K", max_chars=1000)
        self.assertEqual(g.call_args.args[1], {"video_id": "u2QqWkMv3Lg", "language_code": "en", "format": "txt"})
        self.assertTrue(r["truncated"])
        self.assertEqual(len(r["content"]), 1000)
        self.assertNotIn("\n", r["content"])
        self.assertEqual(r["calls"], 1)

    def test_async_job_polled(self):
        first = {"data": {"video_id": "x", "status": "processing", "job_id": "J1"}}
        done = {"data": {"video_id": "x", "status": "completed", "content": "hello world"}}
        with mock.patch.object(youtube_transcript.time, "sleep"), \
                mock.patch.object(youtube_transcript.tikhub, "get", side_effect=[first, first, done]) as g:
            r = youtube_transcript.fetch("u2QqWkMv3Lg", "en", "K")
        self.assertEqual(r["content"], "hello world")
        self.assertEqual(r["calls"], 3)
        self.assertEqual(g.call_args.args[1]["job_id"], "J1")

    def test_no_captions_reports_available(self):
        resp = {"data": {"video_id": "x", "captions": [{"language_code": "ja"}], "message_zh": "该视频没有可用字幕"}}
        with mock.patch.object(youtube_transcript.tikhub, "get", return_value=resp):
            r = youtube_transcript.fetch("u2QqWkMv3Lg", "en", "K")
        self.assertEqual(r["error"], "该视频没有可用字幕")
        self.assertEqual(r["available"], ["ja"])


if __name__ == "__main__":
    unittest.main()
