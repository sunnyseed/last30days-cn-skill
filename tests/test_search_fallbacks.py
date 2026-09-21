import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from lib import douyin, env, normalize, toutiao, xiaohongshu, zhihu


BING_XHS_HTML = """
<html><body>
<li class="b_algo">
  <h2><a href="https://www.xiaohongshu.com/explore/abc123">小红书 AI 工具测评</a></h2>
  <p>这是一条来自小红书的公开搜索摘要。</p>
</li>
</body></html>
"""


BING_ZHIHU_HTML = """
<html><body>
<li class="b_algo">
  <h2><a href="https://www.zhihu.com/question/123456">知乎 AI 工具讨论</a></h2>
  <p>这是一条来自知乎的公开搜索摘要。</p>
</li>
</body></html>
"""


def test_xiaohongshu_site_search_fallback_parses_bing_html():
    with patch.object(xiaohongshu, "_fetch_html", return_value=BING_XHS_HTML):
        items = xiaohongshu._search_via_site_search("AI 工具", 5)

    assert len(items) == 1
    assert items[0]["title"] == "小红书 AI 工具测评"
    assert items[0]["source"] == "site-search-fallback"
    assert items[0]["url"].endswith("/abc123")


def test_zhihu_site_search_fallback_parses_bing_html():
    with patch.object(zhihu, "_fetch_html", return_value=BING_ZHIHU_HTML):
        items = zhihu._search_via_site_search("AI 工具", 5)

    assert len(items) == 1
    assert items[0]["title"] == "知乎 AI 工具讨论"
    assert items[0]["source"] == "site-search-fallback"
    assert items[0]["content_type"] == "question"


BING_DOUYIN_HTML = """
<html><body>
<li class="b_algo">
  <h2><a href="https://www.douyin.com/video/7234567890">抖音 AI 编程助手实测</a></h2>
  <p>这是一条来自抖音的公开搜索摘要。</p>
</li>
</body></html>
"""


BING_TOUTIAO_HTML = """
<html><body>
<li class="b_algo">
  <h2><a href="https://www.toutiao.com/article/7234567890/">头条 AI 编程助手评测</a></h2>
  <p>这是一条来自头条的公开搜索摘要。</p>
</li>
</body></html>
"""


def test_douyin_site_search_fallback_parses_bing_html():
    with patch.object(douyin, "_fetch_html", return_value=BING_DOUYIN_HTML):
        items = douyin._search_via_site_search("AI 编程助手", 5)

    assert len(items) == 1
    assert "抖音 AI 编程助手实测" in items[0]["text"]
    assert items[0]["source"] == "site-search-fallback"
    assert "douyin.com/video" in items[0]["url"]
    # 字段形状能被 normalize 正常消费
    normalize.normalize_douyin_items(items, "2026-01-01", "2026-12-31")


def test_toutiao_site_search_fallback_parses_bing_html():
    with patch.object(toutiao, "_fetch_html", return_value=BING_TOUTIAO_HTML):
        items = toutiao._search_via_site_search("AI 编程助手", 5)

    assert len(items) == 1
    assert items[0]["title"] == "头条 AI 编程助手评测"
    assert items[0]["source"] == "site-search-fallback"
    assert "toutiao.com/article" in items[0]["url"]
    normalize.normalize_toutiao_items(items, "2026-01-01", "2026-12-31")


def test_xiaohongshu_unavailable_when_mcp_down_and_no_key():
    """mcp 挂了 + 无 Playwright + 无 TikHub key ⇒ 判**不可用**。

    上游原逻辑在这种情况下仍 return True（理由是还有 Bing 站内搜索兜底）。
    但那不是小红书的数据，是搜索引擎收录的零星链接；本机实测三条路全灭
    （mcp 503 / 公开接口 404 / Bing 0 条），判可用只会让报告里出现
    「小红书: 0 条」而不是老实说这个源没接通。
    """
    with patch("lib.http.get", side_effect=RuntimeError("mcp down")):
        with patch("lib.crawler_bridge.is_playwright_available", return_value=False):
            assert env.is_xiaohongshu_available({}) is False
            assert env.is_xiaohongshu_available({"TIKHUB_API_KEY": "k"}) is True
