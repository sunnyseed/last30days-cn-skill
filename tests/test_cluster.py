"""跨源聚类回归测试（D）。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from lib import cluster, schema

_SAME = "OpenAI 发布 GPT-6 多模态大模型 引发热议"


def _weibo(i, text, score):
    return schema.WeiboItem(id=i, text=text, url=f"https://weibo.com/{i}",
                            author_handle="u", score=score)


def _baidu(i, title, score):
    return schema.BaiduItem(id=i, title=title, snippet="", url=f"https://baidu.com/{i}",
                            source_domain="x", score=score)


def _bili(i, title, score):
    return schema.BilibiliItem(id=i, title=title, url=f"https://b.com/{i}",
                               bvid=i, channel_name="c", score=score)


def test_same_event_across_three_sources_forms_one_cluster():
    weibo = [_weibo("WB1", _SAME, 70)]
    baidu = [_baidu("BD1", _SAME, 90)]   # 最高分 → 应为代表项
    bili = [_bili("BL1", _SAME, 60)]

    clusters = cluster.build_clusters(weibo, [], bili, [], [], [], baidu, [])

    assert len(clusters) == 1
    c = clusters[0]
    assert c["size"] == 3
    assert set(c["member_ids"]) == {"WB1", "BD1", "BL1"}
    assert c["representative_id"] == "BD1"            # 最高分代表
    assert set(c["sources"]) == {"微博", "百度", "B站"}


def test_unrelated_single_source_item_not_clustered():
    weibo = [_weibo("WB1", _SAME, 70), _weibo("WB2", "今天天气不错适合出门散步", 50)]
    baidu = [_baidu("BD1", _SAME, 90)]

    clusters = cluster.build_clusters(weibo, [], [], [], [], [], baidu, [])

    # 仅 WB1+BD1 跨源成簇；WB2 与谁都不相似，不进任何簇
    assert len(clusters) == 1
    assert set(clusters[0]["member_ids"]) == {"WB1", "BD1"}


def test_same_source_only_does_not_cluster():
    # 两条同源近似条目不构成"跨平台"簇
    weibo = [_weibo("WB1", _SAME, 70), _weibo("WB2", _SAME, 60)]
    clusters = cluster.build_clusters(weibo, [], [], [], [], [], [], [])
    assert clusters == []
