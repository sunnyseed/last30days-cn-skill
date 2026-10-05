"""tools/wechat_feed.py 离线回归（桩掉 tikhub.post，不发网络不计费）。

跑法：cd engine && python3 tests/test_wechat_feed.py
fixture 按 TikHub 文档 raw=false 的结构手写（data.articles[].title/digest/url/create_time）；
真实响应形状要等网关白名单加上端点后拿一次实测核对。
"""
import os
import sys
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))

import wechat_feed  # noqa: E402

NOW = 1791200000


def _payload(*ages_h):
    return {"code": 200, "data": {"biz_username": "gh_x", "is_end": 0, "articles": [
        {"title": f"文章{i}", "digest": "摘要", "url": f"https://mp.weixin.qq.com/s/{i}",
         "create_time": NOW - int(h * 3600), "is_paid": 0} for i, h in enumerate(ages_h)]}}


class TestFeed(unittest.TestCase):
    def test_window_filters_by_timestamp(self):
        with mock.patch.object(wechat_feed.tikhub, "post", return_value=_payload(2, 20, 30, 200)):
            r = wechat_feed.fetch_account("gh_x", NOW - 86400, "K")
        self.assertEqual([it["title"] for it in r["items"]], ["文章0", "文章1"])
        self.assertIsNone(r["error"])

    def test_request_shape(self):
        with mock.patch.object(wechat_feed.tikhub, "post", return_value=_payload()) as p:
            wechat_feed.fetch_account("gh_abc", NOW, "K")
        path, body = p.call_args[0][0], p.call_args[0][1]
        self.assertTrue(path.endswith("wechat_mp/v2/fetch_account_articles"))
        self.assertEqual(body, {"username": "gh_abc", "raw": False})

    def test_upstream_failure_is_reported_not_raised(self):
        with mock.patch.object(wechat_feed.tikhub, "post", return_value=None):
            r = wechat_feed.fetch_account("gh_x", NOW, "K")
        self.assertEqual(r["items"], [])
        self.assertTrue(r["error"])

    def test_date_is_beijing(self):
        # 2026-10-04 20:00 UTC = 10-05 04:00 北京
        ts = int(time.mktime(time.strptime("2026-10-04 20:00", "%Y-%m-%d %H:%M"))) - time.timezone
        self.assertEqual(wechat_feed._date(ts), "2026-10-05")


if __name__ == "__main__":
    unittest.main()
