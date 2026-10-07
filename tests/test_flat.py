"""输出形状契约：用 schema.py 的真 dataclass 生成 `--emit json` 同款报告，再拍平。

下游（hub、MCP）只认 lib/flat.py，这里钉住两件事：
1. flat.SOURCES 与 Report.to_dict() 里的源数组一一对应——新增/改名一个源，这里先红；
2. 每个源都能拍出非空的 title、url，以及该源实有的 body/author——
   某个 dataclass 改了字段名（比如 snippet → summary），这里先红，
   而不是等 MCP 真跑 0 条、hub 简报静默缺正文。
"""
import sys
import unittest

sys.path.insert(0, "scripts")

from lib import flat, schema  # noqa: E402


def _report() -> schema.Report:
    e = schema.Engagement(likes=3)
    return schema.Report(
        topic="t", range_from="2026-09-01", range_to="2026-09-29",
        generated_at="2026-09-29T00:00:00Z", mode="quick",
        weibo=[schema.WeiboItem(id="WB1", text="微博正文", url="u-wb", author_handle="博主",
                                date="2026-09-28", engagement=e)],
        xiaohongshu=[schema.XiaohongshuItem(id="XHS1", title="小红书标题", desc="小红书正文",
                                            url="u-xhs", author_name="薯")],
        bilibili=[schema.BilibiliItem(id="BL1", title="B站标题", url="u-bl", bvid="BV1",
                                      channel_name="UP主", description="B站简介")],
        zhihu=[schema.ZhihuItem(id="ZH1", title="知乎标题", excerpt="知乎摘要", url="u-zh",
                                author="答主")],
        douyin=[schema.DouyinItem(id="DY1", text="抖音文案", url="u-dy", author_name="抖主")],
        wechat=[schema.WechatItem(id="WC1", title="微信标题", snippet="微信摘要", url="u-wc",
                                  source_name="公众号")],
        baidu=[schema.BaiduItem(id="BD1", title="百度标题", snippet="百度摘要", url="u-bd",
                                source_domain="example.com")],
        toutiao=[schema.ToutiaoItem(id="TT1", title="头条标题", abstract="头条摘要", url="u-tt",
                                    source_name="头条号")],
        wechat_error=None, douyin_error=None,
    )


class Shape(unittest.TestCase):
    def test_sources_match_report_arrays(self):
        d = _report().to_dict()
        arrays = {k for k, v in d.items()
                  if isinstance(v, list) and k not in ("best_practices", "prompt_pack", "clusters")}
        self.assertEqual(arrays, set(flat.SOURCES))

    def test_every_source_flattens(self):
        items = {it["source"]: it for it in flat.flatten(_report().to_dict())}
        self.assertEqual(set(items), set(flat.SOURCES))
        for src, it in items.items():
            with self.subTest(src=src):
                self.assertTrue(it["title"], "title 空")
                self.assertTrue(it["url"], "url 空")
                self.assertTrue(it["author"], "author 空")

    def test_body_where_source_has_one(self):
        items = {it["source"]: it for it in flat.flatten(_report().to_dict())}
        expect = {"xiaohongshu": "小红书正文", "bilibili": "B站简介", "zhihu": "知乎摘要",
                  "wechat": "微信摘要", "baidu": "百度摘要", "toutiao": "头条摘要",
                  "weibo": "", "douyin": ""}  # 微博、抖音只有 text，已作 title
        for src, body in expect.items():
            with self.subTest(src=src):
                self.assertEqual(items[src]["body"], body)

    def test_engagement_and_date_pass_through(self):
        wb = flat.flatten(_report().to_dict())[1]
        self.assertEqual(wb["source"], "weibo")
        self.assertEqual(wb["date"], "2026-09-28")
        self.assertEqual(wb["engagement"].get("likes"), 3)

    def test_duration_seconds(self):
        # B站是「分:秒」/「时:分:秒」字符串（schema 标 int 但引擎实际塞字符串），抖音是毫秒
        d = {"bilibili": [{"title": "a", "duration": "7:26"}, {"title": "b", "duration": "1:02:03"},
                          {"title": "c", "duration": ""}],
             "douyin": [{"text": "d", "duration": 73267}, {"text": "e", "duration": 0}],
             "weibo": [{"text": "f"}]}
        got = [i["duration"] for i in flat.flatten(d)]
        self.assertEqual(got, [None, 446, 3723, None, 73, None])

    def test_source_status(self):
        d = {"weibo": [], "weibo_error": "超时", "wechat": [{"title": "x"}]}
        ok, skipped = flat.source_status(d)
        self.assertEqual(ok, ["wechat"])
        reasons = {s["source"]: s["reason"] for s in skipped}
        self.assertEqual(reasons["weibo"], "超时")
        self.assertEqual(reasons["douyin"], "无结果")


if __name__ == "__main__":
    unittest.main()
