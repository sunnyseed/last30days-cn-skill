import io, json, sys, urllib.request
sys.path.insert(0, "scripts")
from lib import xiaohongshu as x

PAYLOAD = {"code": 200, "data": {
    "search_id": "sid-1", "search_session_id": "ssid-1",
    "items": [
        {"id": "697c0eee000000000a03c308", "model_type": "note",
         "note_card": {"note_id": "697c0eee000000000a03c308",
            "display_title": "纳指100 QDII 限购实测",
            "desc": "今天又只能买100块 #纳指100#",
            "time": 1757800000000,
            "user": {"nickname": "老韭菜", "user_id": "u123"},
            "interact_info": {"liked_count": "1234", "collected_count": "88",
                              "comment_count": "42", "shared_count": "7"}}},
        {"id": "x2", "model_type": "note",
         "note_card": {"note_id": "x2", "display_title": "标普500定投", "desc": "d",
            "timestamp": 1757700000,
            "user": {"nickname": "B", "user_id": "u2"}, "interact_info": {}}},
    ]}}

class FakeResp:
    def __init__(self, b): self.b = b
    def read(self): return self.b
    def __enter__(self): return self
    def __exit__(self, *a): return False

calls = []
def fake_urlopen(req, timeout=None):
    calls.append(req.full_url)
    assert req.get_header("Authorization") == "Bearer TESTKEY", req.headers
    if len(calls) > 1:  # 第二页返回空，验证翻页会停
        return FakeResp(json.dumps({"code": 200, "data": {"items": []}}).encode())
    return FakeResp(json.dumps(PAYLOAD, ensure_ascii=False).encode())

urllib.request.urlopen = fake_urlopen
x.urllib.request.urlopen = fake_urlopen

items = x.search_xiaohongshu("纳指100", "2026-08-15", "2026-09-14", depth="default", tikhub_token="TESTKEY")
print("requests:", len(calls))
print(calls[0])
print(json.dumps(items, ensure_ascii=False, indent=2)[:1200])
assert len(items) == 2, items
assert items[0]["date"] and items[1]["date"], "时间字段没解析出来"
assert items[0]["engagement"]["likes"] == 1234
assert items[0]["url"].endswith("697c0eee000000000a03c308")
assert "time_filter=%E5%8D%8A%E5%B9%B4%E5%86%85" in calls[0], calls[0]
print("PASS")
