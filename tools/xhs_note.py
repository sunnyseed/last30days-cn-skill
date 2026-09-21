#!/usr/bin/env python3
"""小红书单条笔记详情：正文 + 评论 + 配图落地，供「看图提表」用。

为什么要它：`last30days-cn` 的搜索只返回标题/摘要/互动数，而这类「限购额度
一览表」笔记的干货**全在配图里**，正文往往只有一句引子。要读到表，必须再打一
次详情接口拿 images_list，把原图下下来转成可读格式。

数据源：TikHub（api.tikhub.io，$0.001/次，非 200 不计费），key 取自环境变量
TIKHUB_API_KEY，取不到则从 ~/.zshrc 抽（与 run_alert.sh 同法，给 launchd 留路）。
纯标准库；转图用 macOS 自带 sips。

用法：
  python3 xhs_note.py 6aa77dbd000000002502c79e          # 正文 + 元信息
  python3 xhs_note.py https://xhslink.com/xxxx          # 分享链接同样可以
  python3 xhs_note.py <id> --images                     # 顺带下图并转 PNG
  python3 xhs_note.py <id> --comments 50                # 拉最新 50 条评论
  python3 xhs_note.py <id> --json                       # 原始响应，便于扒字段

注意：
- **必带 UA**，否则被 TikHub 前面的 Cloudflare 拦成 403 error code 1010。
- 上游响应 2s~30s+ 抖动，故 45s 超时 + 3 次退避重试（超时不计费，重试免费）。
- 评论接口对**无效 note_id 照常计费**（返回体里才写「服务异常」），故先跑详情
  确认笔记存在，--comments 再单独打。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

_BASE = "https://api.tikhub.io"
_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"
_TIMEOUT = 45
_RETRIES = 3
# 图片 CDN 认 Referer，直链裸取会 403
_IMG_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.xiaohongshu.com/"}


def _api_key() -> str:
    key = os.environ.get("TIKHUB_API_KEY")
    if key:
        return key
    zshrc = os.path.expanduser("~/.zshrc")
    try:
        with open(zshrc, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"\s*(?:export\s+)?TIKHUB_API_KEY=(.+)", line)
                if m:
                    return m.group(1).strip().strip("\"'")
    except OSError:
        pass
    sys.exit("未找到 TIKHUB_API_KEY（环境变量或 ~/.zshrc）。注册见 https://tikhub.io")


def _get(path: str, params: dict, key: str) -> dict | None:
    """打一次 TikHub，带退避重试；全失败返回 None。"""
    url = f"{_BASE}{path}?" + urllib.parse.urlencode(params)
    last = None
    for attempt in range(_RETRIES):
        try:
            req = urllib.request.Request(url)
            req.add_header("Authorization", f"Bearer {key}")
            req.add_header("User-Agent", _UA)
            req.add_header("Accept", "application/json")
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:200]
            last = f"HTTP {e.code}: {body}"
            if e.code in (401, 403, 404):  # 鉴权/风控/路径错，重试无意义
                break
        except Exception as e:  # noqa: BLE001 — 超时/连接重置都值得重试
            last = f"{type(e).__name__}: {e}"
        if attempt < _RETRIES - 1:
            time.sleep(1.5 * (attempt + 1))
    sys.stderr.write(f"[xhs] 请求失败 {path}: {last}\n")
    return None


def _target(ref: str) -> dict:
    """把用户给的参数分派成 note_id 还是 share_text。

    小红书 note_id 是 24 位十六进制；其余一律当分享链接交给上游解析
    （支持 xiaohongshu.com 长链与 xhslink.com/.cn 短链）。
    """
    ref = ref.strip()
    if re.fullmatch(r"[0-9a-f]{24}", ref):
        return {"note_id": ref}
    m = re.search(r"/(?:explore|discovery/item)/([0-9a-f]{24})", ref)
    if m:
        return {"note_id": m.group(1)}
    return {"share_text": ref}


# ---------------------------------------------------------------------------
# 详情
# ---------------------------------------------------------------------------

def fetch_note(ref: str, key: str) -> dict | None:
    """取笔记详情，返回上游 note 对象（含 desc / images_list / 计数）。"""
    payload = _get("/api/v1/xiaohongshu/app_v2/get_image_note_detail", _target(ref), key)
    if not payload:
        return None
    try:
        item = payload["data"]["data"][0]
        note = item["note_list"][0]
    except (KeyError, IndexError, TypeError):
        sys.stderr.write("[xhs] 响应里没有笔记对象（笔记可能已删除/不可见）\n")
        return None
    note.setdefault("user", item.get("user", {}))
    return note


def _topics(note: dict) -> list:
    tags = note.get("hash_tag") or note.get("ats") or []
    return [t.get("name", "") for t in tags if isinstance(t, dict) and t.get("name")]


def _when(note: dict) -> str:
    ts = note.get("time") or note.get("timestamp") or note.get("last_update_time")
    if not ts:
        return "—"
    ts = int(ts)
    if ts > 10**12:  # 毫秒
        ts //= 1000
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def show_note(note: dict) -> None:
    user = note.get("user") or {}
    print(f"标题  {note.get('title') or '（无标题）'}")
    print(f"作者  {user.get('nickname') or user.get('name') or '—'}"
          f"   IP {note.get('ip_location') or '—'}   {_when(note)}")
    print(f"互动  {note.get('liked_count', 0)} 赞 / {note.get('collected_count', 0)} 收藏"
          f" / {note.get('comments_count', 0)} 评论 / {note.get('shared_count', 0)} 分享")
    topics = _topics(note)
    if topics:
        print("话题  " + " ".join("#" + t for t in topics))
    print(f"链接  https://www.xiaohongshu.com/explore/{note.get('id', '')}")
    imgs = note.get("images_list") or []
    if imgs:
        print(f"配图  {len(imgs)} 张（--images 下载并转 PNG）")
    print("\n--- 正文 ---")
    print(note.get("desc") or "（无正文）")


# ---------------------------------------------------------------------------
# 评论
# ---------------------------------------------------------------------------

def _extract_comments(node, depth: int = 0) -> list:
    """从响应里挖评论列表。

    与 last30days-cn 里解析搜索结果同样的理由：TikHub 的 OpenAPI 把所有端点的
    200 响应都标成同一个通用 ResponseModel，没有字段约定，故不写死路径。
    """
    if depth > 6:
        return []
    if isinstance(node, list):
        hits = [x for x in node
                if isinstance(x, dict) and "content" in x and "user" in x]
        if hits:
            return hits
        for x in node:
            found = _extract_comments(x, depth + 1)
            if found:
                return found
    elif isinstance(node, dict):
        for v in node.values():
            found = _extract_comments(v, depth + 1)
            if found:
                return found
    return []


def fetch_comments(ref: str, key: str, want: int) -> list:
    """按时间倒序拉评论，翻页直到够数或没有下一页。每页一次计费。"""
    out, cursor, index, page_area = [], "", 0, "UNFOLDED"
    for _ in range(10):  # 上限兜底，别让翻页把 $0.001/次 叠上去
        params = dict(_target(ref), sort_strategy="latest_v2",
                      index=str(index), pageArea=page_area)
        if cursor:
            params["cursor"] = cursor
        payload = _get("/api/v1/xiaohongshu/app_v2/get_note_comments", params, key)
        if not payload:
            break
        data = payload.get("data") or {}
        inner = data.get("data") if isinstance(data.get("data"), dict) else data
        batch = _extract_comments(data)
        if not batch:
            break
        out.extend(batch)
        if len(out) >= want:
            break
        cursor = str(inner.get("cursor") or "")
        index = inner.get("index") or len(out)
        page_area = inner.get("pageArea") or page_area
        if not cursor:
            break
        time.sleep(0.5)
    return out[:want]


def show_comments(comments: list) -> None:
    print(f"\n--- 评论（{len(comments)} 条，最新优先）---")
    for c in comments:
        user = c.get("user") or {}
        like = c.get("like_count") or c.get("liked_count") or 0
        text = re.sub(r"\s+", " ", str(c.get("content") or "")).strip()
        print(f"[{like:>4}赞] {user.get('nickname') or '—'}: {text}")
        for sub in (c.get("sub_comments") or c.get("sub_comment_list") or []):
            su = sub.get("user") or {}
            st = re.sub(r"\s+", " ", str(sub.get("content") or "")).strip()
            print(f"         └ {su.get('nickname') or '—'}: {st}")


# ---------------------------------------------------------------------------
# 配图
# ---------------------------------------------------------------------------

def save_images(note: dict, out_dir: str) -> list:
    """下载原图并转 PNG（小红书发的是 webp，多数看图工具不吃）。

    转换用 macOS 自带 sips；转失败就保留 webp 原件，不当作致命错误。
    """
    os.makedirs(out_dir, exist_ok=True)
    note_id = note.get("id", "note")
    paths = []
    for i, img in enumerate(note.get("images_list") or []):
        url = img.get("original") or img.get("url_size_large") or img.get("url")
        if not url:
            continue
        raw = os.path.join(out_dir, f"{note_id}_{i}.webp")
        try:
            req = urllib.request.Request(url, headers=_IMG_HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp, open(raw, "wb") as f:
                f.write(resp.read())
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"[xhs] 图 {i} 下载失败: {e}\n")
            continue
        png = os.path.join(out_dir, f"{note_id}_{i}.png")
        try:
            subprocess.run(["sips", "-s", "format", "png", raw, "--out", png],
                           check=True, capture_output=True)
            os.remove(raw)
            paths.append(png)
        except Exception:  # noqa: BLE001 — 非 macOS 或 sips 不吃，留 webp
            paths.append(raw)
    return paths


def main() -> None:
    ap = argparse.ArgumentParser(
        description="小红书笔记详情（TikHub，$0.001/次）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ref", help="note_id（24 位十六进制）或分享链接")
    ap.add_argument("--comments", type=int, metavar="N", default=0,
                    help="额外拉 N 条最新评论（每页一次计费）")
    ap.add_argument("--images", action="store_true", help="下载配图并转 PNG")
    ap.add_argument("--out", default="xhs_images", metavar="DIR", help="配图落点")
    ap.add_argument("--json", action="store_true", help="输出原始 note 对象")
    args = ap.parse_args()

    key = _api_key()
    note = fetch_note(args.ref, key)
    if not note:
        sys.exit(1)

    if args.json:
        print(json.dumps(note, ensure_ascii=False, indent=2))
        return

    show_note(note)

    if args.images:
        paths = save_images(note, args.out)
        print("\n--- 配图 ---")
        for p in paths:
            print(p)
        if paths:
            print("（表格类笔记的数据在图里，交给能看图的工具/模型读）")

    if args.comments:
        comments = fetch_comments(args.ref, key, args.comments)
        if comments:
            show_comments(comments)
        else:
            print("\n--- 评论 ---\n（没取到评论；该笔记可能关闭评论或无评论）")


if __name__ == "__main__":
    main()
