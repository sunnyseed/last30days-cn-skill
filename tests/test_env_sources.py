"""LAST30DAYS_DEFAULT_SEARCH / EXCLUDE_SOURCES 解析回归测试（C）。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import last30days


def _clear(monkeypatch):
    monkeypatch.delenv("LAST30DAYS_DEFAULT_SEARCH", raising=False)
    monkeypatch.delenv("EXCLUDE_SOURCES", raising=False)


def test_cli_search_takes_priority(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("LAST30DAYS_DEFAULT_SEARCH", "baidu")
    assert last30days.resolve_search_sources("weibo,bilibili") == {"weibo", "bilibili"}


def test_default_search_env_used_when_no_cli(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("LAST30DAYS_DEFAULT_SEARCH", "bilibili,zhihu")
    assert last30days.resolve_search_sources(None) == {"bilibili", "zhihu"}


def test_none_when_nothing_set(monkeypatch):
    _clear(monkeypatch)
    # 无 --search、无默认环境变量 → None（沿用按查询类型自动启用）
    assert last30days.resolve_search_sources(None) is None


def test_exclude_sources_subtracts_from_all(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("EXCLUDE_SOURCES", "baidu,wechat")
    result = last30days.resolve_search_sources(None)
    assert result == last30days.ALL_SOURCE_IDS - {"baidu", "wechat"}


def test_exclude_applies_after_default(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("LAST30DAYS_DEFAULT_SEARCH", "weibo,baidu,zhihu")
    monkeypatch.setenv("EXCLUDE_SOURCES", "baidu")
    assert last30days.resolve_search_sources(None) == {"weibo", "zhihu"}


def test_xhs_alias_normalized_in_exclude(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("EXCLUDE_SOURCES", "xhs")
    result = last30days.resolve_search_sources(None)
    assert "xiaohongshu" not in result
