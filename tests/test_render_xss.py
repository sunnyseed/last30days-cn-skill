"""HTML 报告 XSS 加固回归测试（对齐上游 #434）。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from lib import render, schema


def test_safe_href_blocks_dangerous_schemes():
    assert render._safe_href("javascript:alert(1)") == "#"
    assert render._safe_href("JavaScript:alert(1)") == "#"
    assert render._safe_href("data:text/html,<script>") == "#"
    assert render._safe_href("") == "#"
    assert render._safe_href(None) == "#"


def test_safe_href_allows_http_https():
    assert render._safe_href("http://example.com/a") == "http://example.com/a"
    assert render._safe_href("https://example.com/a") == "https://example.com/a"
    # 前后空白被裁剪，大小写协议仍放行
    assert render._safe_href("  https://example.com  ") == "https://example.com"


def test_html_report_does_not_emit_javascript_href():
    report = schema.create_report("测试主题", "2026-01-01", "2026-01-31", "all")
    report.baidu = [
        schema.BaiduItem(
            id="BD1",
            title="恶意标题",
            snippet="片段",
            url="javascript:alert(document.cookie)",
            source_domain="evil",
            score=80,
        )
    ]
    html = render.render_html_report(report)
    assert 'href="javascript:' not in html
    # 危险链接被降级为 #
    assert 'href="#"' in html
