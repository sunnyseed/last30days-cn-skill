"""不指定源时跑哪些源：只看可用性闸门，不再按查询类型挑（2026-10-05）。

跑法（本机无 pytest）：python3 tests/test_source_selection.py

回归背景：原先 run_research 用 qt.is_source_enabled 按查询类型挑源，
抖音只在 product 一格，hub 日报的子查询（AI视频生成 / 国产大模型 …）全判成
breaking_news 或 how_to，于是抖音天天 0 条；带「部署」判 how_to，微信也被丢掉。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import last30days  # noqa: E402

SEARCHERS = ["_search_weibo", "_search_xiaohongshu", "_search_bilibili", "_search_zhihu",
             "_search_douyin", "_search_wechat", "_search_baidu", "_search_toutiao"]


def _run(available, topic="AI视频生成", query_type="breaking_news", search_sources=None):
    """桩掉各源检索与闸门，返回实际被调用的源。"""
    called = set()
    patches = []
    for name in SEARCHERS:
        src = name[len("_search_"):]

        def fake(*_a, _src=src, **_k):
            called.add(_src)
            return [], None
        patches.append(mock.patch.object(last30days, name, side_effect=fake))
    patches.append(mock.patch.object(last30days.env, "is_source_available",
                                     side_effect=lambda s, _c: s in available))
    with mock.patch.dict(os.environ, {"LAST30DAYS_FORCE_SOURCES": ""}):
        for p in patches:
            p.start()
        try:
            last30days.run_research(topic, {}, "2026-10-04", "2026-10-05",
                                    search_sources=search_sources, query_type=query_type)
        finally:
            for p in patches:
                p.stop()
    return called


TIKHUB_FIVE = {"weibo", "xiaohongshu", "bilibili", "douyin", "wechat"}


class TestDefaultSources(unittest.TestCase):
    def test_douyin_runs_for_breaking_news(self):
        """**回归**：breaking_news 是日常话题的默认判型，原先不含抖音。"""
        self.assertEqual(_run(TIKHUB_FIVE, query_type="breaking_news"), TIKHUB_FIVE)

    def test_wechat_and_douyin_run_for_how_to(self):
        """**回归**：「大模型 本地部署」判 how_to，原先抖音、微信都不跑。"""
        self.assertEqual(_run(TIKHUB_FIVE, "大模型 本地部署", "how_to"), TIKHUB_FIVE)

    def test_every_query_type_runs_all_available(self):
        for qt in ["product", "concept", "opinion", "how_to", "comparison",
                   "breaking_news", "prediction"]:
            self.assertEqual(_run(TIKHUB_FIVE, query_type=qt), TIKHUB_FIVE, qt)

    def test_gate_still_blocks_unavailable(self):
        """挑源交给闸门：知乎/头条/百度没有数据路径就不跑。"""
        called = _run(TIKHUB_FIVE)
        self.assertFalse(called & {"zhihu", "toutiao", "baidu"})

    def test_explicit_search_respected(self):
        self.assertEqual(_run(TIKHUB_FIVE, search_sources={"douyin"}), {"douyin"})


if __name__ == "__main__":
    unittest.main()
