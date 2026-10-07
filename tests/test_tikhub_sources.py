"""TikHub 四个源（微博/B站/微信/抖音）的离线回归。

fixture 是**实测响应**裁到 2 条，不是手搓的——TikHub 的 OpenAPI 对所有端点只标
一个通用 ResponseModel，字段全靠实测，所以回归必须拿真实结构跑。
桩掉 lib.tikhub 的 get/post，不发网络请求、不计费。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from lib import bilibili, douyin, tikhub, wechat, weibo  # noqa: E402

FROM, TO = "2026-08-15", "2026-09-14"


def _fixture(name):
    with open(os.path.join(ROOT, "fixtures", f"tikhub_{name}.json"), encoding="utf-8") as f:
        return json.load(f)


def _stub(payload, calls):
    def fake(path, arg, key, tag=""):
        calls.append((path, arg))
        return payload
    return fake


def check(name, module, payload, runner, expect_min=2):
    calls = []
    tikhub.get = _stub(payload, calls)
    tikhub.post = _stub(payload, calls)
    items = runner()
    assert len(items) >= expect_min, f"{name}: 只解析出 {len(items)} 条"
    for it in items:
        assert it.get("date"), f"{name}: 条目缺日期 {it}"
        assert it.get("url"), f"{name}: 条目缺链接 {it}"
        text = it.get("text") or it.get("title") or ""
        assert text, f"{name}: 条目缺正文/标题 {it}"
        assert "<em" not in text and "<a " not in text, f"{name}: 高亮标签没清干净 {text[:60]}"
    print(f"  {name}: {len(items)} 条 OK | 首条 {items[0]['date']} "
          f"{(items[0].get('text') or items[0].get('title'))[:28]}")
    return calls


print("TikHub 源解析回归：")

calls = check("微博", weibo, _fixture("weibo"),
              lambda: weibo._search_via_tikhub("纳指100", FROM, TO, 10, "K"))
assert calls[0][1]["timescope"] == f"custom:{FROM}:{TO}", "微博没把 30 天窗压到服务端"
assert calls[0][1]["search_type"] == "hot", "微博用热门（all 按时间倒序，30 天窗会退化成当天）"

# 回归（2026-10-07）：hot 档对多词查询会回落成全站热门（与检索词零重叠），首页全 0 相关就换 all 档
_junk = json.loads(json.dumps(_fixture("weibo")))
for _r, _t in zip(_junk["data"]["parsed_data"]["results"], ("开工", "#阿根廷vs贝宁#上半场比赛结束")):
    _r["content"] = _t
_calls = []
def _by_sort(path, arg, key, tag=""):
    _calls.append(arg)
    return _junk if arg["search_type"] == "hot" else _fixture("weibo")
tikhub.get = _by_sort
_items = weibo._search_via_tikhub("纳指100", FROM, TO, 10, "K")
assert [c["search_type"] for c in _calls][:2] == ["hot", "all"], f"首页全不相关时应改用 all 档：{_calls}"
assert len(_items) == 2 and all("开工" not in i["text"] for i in _items), "全站热门的帖子不该留下"
tikhub.get = lambda path, arg, key, tag="": _junk
assert weibo._search_via_tikhub("纳指100", FROM, TO, 10, "K") == [], "两档都不相关时宁可空着"
print("  微博 hot 回落全站热门 → 改 all 档、丢 0 相关 OK")

calls = check("B站", bilibili, _fixture("bilibili"),
              lambda: bilibili._search_via_tikhub("纳指100", FROM, TO, 10, 1, "K"))
assert calls[0][1]["order"] == "totalrank", "B站 order 必填，用综合排序"
assert calls[0][1]["pubtime_begin_s"] > 0 and calls[0][1]["pubtime_end_s"] > calls[0][1]["pubtime_begin_s"]

calls = check("微信", wechat, _fixture("wechat"),
              lambda: wechat._search_via_tikhub("纳指100", FROM, TO, 10, "K"))
assert calls[0][1]["publish_time"] == "half_year", "30 天窗应落到半年档再由引擎收窄"
assert calls[0][1]["sort"] == "hot", "微信用最热"

calls = check("抖音", douyin, _fixture("douyin"),
              lambda: douyin._search_via_tikhub("纳指100", FROM, TO, 10, "K"))
assert calls[0][0].endswith("fetch_video_search_v1"), "旧的 web/fetch_general_search 端点已下线"
assert calls[0][1]["sort_type"] == "0" and calls[0][1]["publish_time"] == "180", "抖音用综合排序"

# 回归（2026-10-05）：抖音一天档上游时好时坏（400 Please retry），1 天窗必须用一周档
calls = check("抖音 1 天窗", douyin, _fixture("douyin"),
              lambda: douyin._search_via_tikhub("纳指100", "2026-09-12", "2026-09-12", 10, "K"),
              expect_min=1)
assert calls[0][1]["publish_time"] == "7", "1 天窗应落到一周档、由引擎收窄，别用不稳的一天档"

# 窗口过滤（2026-10-05）：档位比窗口宽 + 综合/最热排序时，窗外老条目不能占名额
assert tikhub.in_window("2026-09-12", "2026-09-12", "2026-09-12")
assert not tikhub.in_window("2026-08-01", "2026-09-05", "2026-10-05")
assert tikhub.in_window(None, "2026-09-05", "2026-10-05"), "没日期的放行，交给引擎判"
tikhub.post = _stub(_fixture("wechat"), [])
assert wechat._search_via_tikhub("纳指100", "2027-01-01", "2027-01-30", 10, "K") == [], \
    "窗外条目不该进结果"
print("  微信 窗外全丢: OK")

# 分档边界：1 天窗不能拿半年档去查
assert tikhub.bucket("2026-09-14", "2026-09-14", "d", "w", "h") == "d"
assert tikhub.bucket("2026-09-08", "2026-09-14", "d", "w", "h") == "w"
assert tikhub.bucket("2026-08-15", "2026-09-14", "d", "w", "h") == "h"

print("PASS")
