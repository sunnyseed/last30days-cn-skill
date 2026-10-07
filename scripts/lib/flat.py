"""把 `--emit json` 的报告拍平成统一条目。**引擎输出形状的唯一解释者。**

`--emit json` 是各源顶层平行数组（`{"weibo": [...], "wechat": [...], ...}`），
不是 `{"sources": {...}}`；各源正文字段名也不同（微博只有 `text` 没 `title`，
微信是 `snippet`，头条是 `abstract`……见 schema.py 里 8 个 dataclass）。

下游（外层仓的 hub、远程 MCP server）原先各写一份解析，已经悄悄分叉过：
作者字段一边认 `source_domain` 一边不认，空白处理也不同。MCP 部署时还照着
脑补的形状写解析器、配上同一份脑补写的桩，测试全绿、真跑 0 条。
所以解析放在定义形状的地方，由 tests/test_flat.py 用真 dataclass 钉住：
schema 一改，这里的测试先红。

纯标准库、不 import 引擎其它模块。下游把 **scripts**（不是 scripts/lib）加进
sys.path 后 `from lib import flat`：lib/ 里有个 http.py，把 lib 本身加进 sys.path
会顶掉标准库 http。lib/__init__.py 是空的，不会连带加载检索代码。
"""
from typing import Any, Dict, List, Optional

SOURCES = ["xiaohongshu", "weibo", "bilibili", "douyin", "wechat", "zhihu", "baidu", "toutiao"]
SOURCE_CN = {"xiaohongshu": "小红书", "weibo": "微博", "bilibili": "B站", "douyin": "抖音",
             "wechat": "微信", "zhihu": "知乎", "baidu": "百度", "toutiao": "头条"}

TITLE_KEYS = ("title", "text")
BODY_KEYS = ("desc", "description", "snippet", "excerpt", "abstract", "text")
AUTHOR_KEYS = ("author_name", "author_handle", "channel_name", "source_name",
               "author", "source_domain")


def first(item: Dict[str, Any], keys) -> str:
    """按顺序取第一个非空字符串字段。"""
    for k in keys:
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def duration_seconds(source: str, raw: Any) -> Optional[int]:
    """视频时长统一成秒；拿不到给 None（不是 0：0 会被下游当成「很短」）。

    B站是网页版那样的字符串 `"7:26"` / `"1:02:03"`；抖音 `aweme.duration` 是**毫秒**（实测 73267）。
    """
    try:
        if source == "bilibili" and isinstance(raw, str) and raw.strip():
            secs = 0
            for part in raw.strip().split(":"):
                secs = secs * 60 + int(part)
            return secs
        if source == "douyin" and isinstance(raw, (int, float)) and raw > 0:
            return int(raw) // 1000
    except ValueError:
        pass
    return None


def flatten_item(source: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    title = first(raw, TITLE_KEYS)
    body = first(raw, BODY_KEYS)
    if body == title:  # 微博、抖音的 title 和 body 都取自 text
        body = ""
    return {
        "source": source,
        "source_cn": SOURCE_CN.get(source, source),
        "id": raw.get("id") or "",  # 每次运行内的序号（WB1…），不是内容标识，不能拿来跨次去重
        "title": title,
        "body": body,
        "url": raw.get("url") or "",
        "author": first(raw, AUTHOR_KEYS),
        "date": raw.get("date"),
        "date_confidence": raw.get("date_confidence", "low"),
        "engagement": raw.get("engagement") or {},
        "score": raw.get("score", 0),
        "relevance": raw.get("relevance", 0.0),
        "duration": duration_seconds(source, raw.get("duration")),
    }


def flatten(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """按 SOURCES 顺序拍平，不排序、不去重。"""
    return [flatten_item(src, raw) for src in SOURCES for raw in (report.get(src) or [])]


def source_status(report: Dict[str, Any]):
    """(有数据的源, [{source, reason}]) —— reason 取 `<src>_error`，没有就是「无结果」。"""
    ok, skipped = [], []
    for src in SOURCES:
        if report.get(src):
            ok.append(src)
        else:
            skipped.append({"source": src, "reason": report.get(f"{src}_error") or "无结果"})
    return ok, skipped
