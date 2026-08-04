#!/usr/bin/env python3
"""用后端 gpt-image 锚点法给一篇公众号稿子出「一致性」配图（经运营工具 op API）。

与小红书轮播共用同一个后端与同一把凭据，差别只有三处：**横版 16:9**、**一篇只有
1 张封面 + 0~3 张正文插图**、**封面要裁成 2.35:1**。其余（锚点法、任务台账、失败处置）完全同源，
所以行为契约请直接照 `nbdpsy-xiaohongshu-creator/scripts/gen_images.py` 理解。

服务端：nbdpsy-server（mcp.nbdpsy.com）`/api/op/consistent-images`，gpt-image-2 锚点法 +
自动去水印后处理。**gpt-image-2 只有三种物理尺寸**，服务端按 `aspect_ratio` 归一：竖版类
（3:4/4:5/2:3/9:16）→1024×1536、方版 1:1→1024×1024、横版类（4:3/3:2/16:9）→**1536×1024**。
本脚本**恒传 `16:9`** 拿横版——公众号是横向阅读，竖图塞进正文会把版面撑爆。
单次 prompts ≤99（超出 422）；任务台账为进程内存（server 重启后 --job 复查 404=台账丢，
生图可安全重新发起、会重新扣额度；终态留存 2h）。

一致性原理（与小红书同）：先出封面过风格闸门（`--cover-only`），运营确认配色/人物/图内中文无误后，
把这张封面当**锚点参考图**（`--anchor-url`）喂给正文插图——每张独立锚定生成，整篇调性统一。
封面没确认就把插图一起出 = 风格跑偏后整篇全废。

**封面 2.35:1**：微信封面官方比例是 2.35:1，而 gpt-image 出的是 16:9（1536×1024）。
下载后用 Pillow **居中裁剪**成 1536×654 存 `cover.jpg`，未裁的原图另存 `cover-raw.jpg` 便于重裁。
所以写封面提示词时**视觉重心要居中**——上下两条各 185px 会被裁掉。正文插图不裁，原样 16:9。
落盘统一转 JPEG（微信正文图硬上限单张 1MB，PNG 原图常超），质量阶梯降到达标为止。

流程：本地解析 md「## 配图」区块（`### 封面` / `### 插图N` 定位 + 区间内第一个完整 ``` 围栏块为
提示词，判据与小红书 `### PN` 同源）→ POST {base}/api/op/consistent-images（带 aspect_ratio=16:9，
不传 draft_id，后端自动开临时容器；202 拿 job_id + session_id）→ 轮询
GET {base}/api/op/drafts/{session_id}/jobs/{job_id} 到终态 → done 后逐张下载并转码
（result.urls 顺序与提交的 prompts 对齐，相对 /uploads/… 公开免鉴权）。

用法：
    python3 gen_gzh_images.py --md post.md --cover-only              # 只出封面（风格闸门第一步）
    python3 gen_gzh_images.py --md post.md --anchor-url <URL>        # 出全部（封面+插图，各自锚定）
    python3 gen_gzh_images.py --md post.md --pages 1-3 --anchor-url <URL>  # 只出指定插图/重试失败张
    python3 gen_gzh_images.py --md post.md --job <id> [--session <id>]     # 复查已入队任务并补下载
        [--images-dir DIR] [--api-base URL] [--no-wait] [--wait-timeout N] [--dry-run]

稿子里没有「## 配图」区块 → 直接报错并指路 `references/gzh-illustration-spec.md`，
**绝不替运营现编提示词**（编出来的图没人对过风格档案，出了也是废图）。

凭据：复用 `NBDPSY_XHS_API_KEY`（与小红书生图/发布、视频搬运同一把，**不新增凭据**）；
base 用 `NBDPSY_VIDEO_API_BASE`（可选，默认 https://mcp.nbdpsy.com），均由 nbdpsy_common
三层解析；`--api-base` 可覆盖。⚠️ 注意这把 key 与本 skill 其余脚本用的
`NBDPSY_WECHAT_API_KEY` 是**两把独立的 key**，走的也是两个服务——生图走 mcp.nbdpsy.com，
发文走 database.nbdpsy.com。

输出契约：stdout 纯 JSON。
{"outcome": "done|partial|failed|pending|unknown", "session_id", "job_id",
 "images": [{"slot": "cover|illus", "label": "封面|插图1", "url": 绝对URL|null,
             "path": 本地路径|null, "raw_path": 封面原图路径|null, "error": null|文案}],
 "anchor_url": <cover-only 时=封面的绝对URL，方便直接取用；否则=本次所用锚点>,
 "error", "hint", "warnings"}。
exit：done=0；partial/failed=1（hint 教「--pages 只重出失败张 + 带同一 --anchor-url」）；
pending/unknown=0（任务已入队仍在跑，hint 教 --job 复查，**绝不重发**以免重复生成/烧额度）。
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

# 同目录 vendored 副本
import nbdpsy_common

TERMINAL_STATUSES = {"done", "failed"}
STATE_FILE = ".gen_gzh_images_state.json"

# 出图比例：公众号恒横版。服务端按此归一到 gpt-image-2 的 1536×1024。
ASPECT_RATIO = "16:9"
# 微信封面官方比例（gpt-image 出的 16:9 居中裁到它）
COVER_RATIO = 2.35
# 微信正文图硬上限：单张 1MB（md2wechat.MAX_IMAGE_BYTES 同值）
MAX_IMAGE_BYTES = 1024 * 1024
# JPEG 质量阶梯：从高到低试，第一个落在 1MB 内的就用
JPEG_QUALITIES = (92, 86, 80, 72, 64)

# 配图区块的两种标题：`### 封面` 与 `### 插图N`（N 从 1 起）。后面可带 · 说明，同小红书 `### PN`。
_HEADING = re.compile(r"^###\s+(封面|插图\s*(\d+))\b")

_NO_PILLOW_HINT = (
    "缺少 Pillow（图像库），无法裁封面/转 JPEG。请先安装：\n"
    "    pip install Pillow\n"
    "（仓库根 requirements.txt 已含 pillow，也可跑 setup.py 一键装齐）")

_NO_SECTION_HINT = (
    "稿子里没有「## 配图」区块（也没找到任何 `### 封面` / `### 插图N` 标题），无法出图。"
    "请先按 references/gzh-illustration-spec.md 在 md 里写好配图区块："
    "`### 封面` 与 `### 插图1`…各带一个 ``` 围栏提示词。"
    "⛔ 不要让脚本或 agent 现编提示词——提示词要按当前运营的风格档案写，编的没人兜底。")


# ---------------- 提示词解析 ----------------

def _first_fenced_block(block_lines):
    """取一段行里第一个完整 ``` 围栏块内容（strip 首尾空行）。
    开围栏行可带语言标记（```text 等），闭围栏为纯 ```；开而未闭 / 无围栏 → 返回 None。"""
    in_fence = False
    collected = []
    for line in block_lines:
        is_fence = line.strip().startswith("```")
        if is_fence and not in_fence:
            in_fence = True
            continue
        if is_fence and in_fence:
            return "\n".join(collected).strip()
        if in_fence:
            collected.append(line)
    return None


def extract_items(md_text):
    """逐张提取绘图提示词。判据与小红书 extract_pages 同源：行首 `### 封面` / `### 插图N` 定位，
    区间内第一个完整围栏块为提示词。无围栏的那张 prompt=None（不静默丢弃，交 validate_complete 拦）。
    返回 [{"slot": "cover"|"illus", "num": None|int, "label": "封面"|"插图1", "prompt": str|None}, ...]，
    按文档序。"""
    if not md_text or not md_text.strip():
        return []
    lines = md_text.splitlines()
    heads = []
    for idx, line in enumerate(lines):
        m = _HEADING.match(line)
        if m:
            num = int(m.group(2)) if m.group(2) else None
            slot = "illus" if num else "cover"
            label = f"插图{num}" if num else "封面"
            heads.append((slot, num, label, idx))
    items = []
    for k, (slot, num, label, start) in enumerate(heads):
        end = heads[k + 1][3] if k + 1 < len(heads) else len(lines)
        items.append({"slot": slot, "num": num, "label": label,
                      "prompt": _first_fenced_block(lines[start + 1:end])})
    return items


def validate_complete(items):
    """完整性校验：至少一张、封面必须在、每张都有围栏提示词。缺则抛 ValueError 点名缺哪张。"""
    if not items:
        raise ValueError(_NO_SECTION_HINT)
    if not any(i["slot"] == "cover" for i in items):
        raise ValueError("配图区块里没有 `### 封面`——公众号封面是必需的（信息流里就靠它），"
                         "请补一个 `### 封面` 标题 + 围栏提示词")
    missing = [i["label"] for i in items if i["prompt"] is None]
    if missing:
        raise ValueError(
            f"以下配图缺绘图提示词围栏（``` 代码块），无法出图：{', '.join(missing)}"
            "（缺围栏会让服务端返回的图与提交顺序错位，故在此拦截；补全围栏后重试）")
    nums = [i["num"] for i in items if i["slot"] == "illus"]
    if len(set(nums)) != len(nums):
        raise ValueError(f"插图编号有重复：{sorted(nums)}——每张插图编号唯一，改完重试")


def parse_illus_spec(spec):
    """解析 --pages（插图编号）：'1-3' / '1,3' / '1-2,4' 混合 → 升序去重的编号列表。"""
    nums = set()
    for tok in spec.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if "-" in tok:
            a, _, b = tok.partition("-")
            a, b = a.strip(), b.strip()
            if not (a.isdigit() and b.isdigit()):
                raise ValueError(f"编号区间格式非法：{tok!r}（应形如 1-3）")
            lo, hi = int(a), int(b)
            if lo < 1 or hi < lo:
                raise ValueError(f"编号区间非法：{tok!r}（须 1 ≤ 起 ≤ 止）")
            nums.update(range(lo, hi + 1))
        else:
            if not tok.isdigit() or int(tok) < 1:
                raise ValueError(f"编号格式非法：{tok!r}")
            nums.add(int(tok))
    if not nums:
        raise ValueError("--pages 未解析出任何插图编号")
    return sorted(nums)


def select_items(items, cover_only, spec):
    """按 --cover-only / --pages 选张，保持文档序。
    --cover-only 只出封面；--pages 只出指定插图（不含封面）；都不给则全出。
    请求了不存在的插图编号 → 报错（防手滑）。"""
    if cover_only:
        return [i for i in items if i["slot"] == "cover"]
    if spec:
        wanted = parse_illus_spec(spec)
        available = {i["num"] for i in items if i["slot"] == "illus"}
        missing = [n for n in wanted if n not in available]
        if missing:
            have = sorted(available)
            raise ValueError(
                f"请求的插图不存在：{', '.join('插图' + str(n) for n in missing)}"
                f"（本篇共 {len(have)} 张插图：{', '.join('插图' + str(n) for n in have) or '无'}）")
        wset = set(wanted)
        return [i for i in items if i["slot"] == "illus" and i["num"] in wset]
    return list(items)


def build_warnings(selected, cover_only, anchor_url):
    w = []
    if not cover_only and not anchor_url and any(i["slot"] == "illus" for i in selected):
        w.append("未带锚点参考图（--anchor-url），整篇一致性无保障；正常流程应先 --cover-only 出封面"
                 "过风格闸门，运营确认后用返回的 anchor_url 再出插图")
    n_illus = sum(1 for i in selected if i["slot"] == "illus")
    if n_illus > 3:
        w.append(f"本次 {n_illus} 张正文插图，超出公众号建议的 0~3 张——长文配图贵精不贵多，"
                 "每个小标题都塞图反而打断阅读")
    return w


def image_filename(item):
    """封面 → cover.jpg；插图N → illus-0N.jpg（两位数，与编号对应）。"""
    if item["slot"] == "cover":
        return "cover.jpg"
    return f"illus-{item['num']:02d}.jpg"


# ---------------- 图像后处理（裁剪 / 转码） ----------------

def crop_box(w, h, ratio):
    """居中裁到目标宽高比，返回 (left, top, right, bottom)。纯函数、无 Pillow 依赖，便于单测。
    原图更宽（w/h > ratio）→ 裁两侧；否则裁上下。"""
    if w <= 0 or h <= 0 or ratio <= 0:
        raise ValueError(f"非法尺寸或比例：{w}x{h} ratio={ratio}")
    if w / h > ratio:
        new_w = round(h * ratio)
        left = (w - new_w) // 2
        return (left, 0, left + new_w, h)
    new_h = round(w / ratio)
    top = (h - new_h) // 2
    return (0, top, w, top + new_h)


def _require_pillow():
    try:
        from PIL import Image  # noqa: F401
    except ImportError as e:
        raise ValueError(_NO_PILLOW_HINT) from e


def save_jpeg(im, dst, max_bytes=MAX_IMAGE_BYTES):
    """按质量阶梯存 JPEG，第一个落在 max_bytes 内的就用；全都超则留最低质量那份并返回它的大小。
    返回 (quality, size)。微信正文图硬上限 1MB，超了 md2wechat 会在上传前失败。"""
    im = im.convert("RGB")
    dst.parent.mkdir(parents=True, exist_ok=True)
    quality = size = None
    for q in JPEG_QUALITIES:
        im.save(dst, "JPEG", quality=q, optimize=True, progressive=True)
        quality, size = q, dst.stat().st_size
        if size <= max_bytes:
            break
    return quality, size


def process_cover(raw_bytes, images_dir):
    """封面：原图（16:9）存 cover-raw.jpg，居中裁成 2.35:1 存 cover.jpg。
    返回 (cover_path, raw_path, warnings)。"""
    from PIL import Image
    import io
    warnings = []
    im = Image.open(io.BytesIO(raw_bytes))
    raw_path = images_dir / "cover-raw.jpg"
    save_jpeg(im, raw_path)
    box = crop_box(im.width, im.height, COVER_RATIO)
    cover = im.crop(box)
    cover_path = images_dir / "cover.jpg"
    _, size = save_jpeg(cover, cover_path)
    if size > MAX_IMAGE_BYTES:
        warnings.append(f"封面压到最低质量仍有 {size // 1024}KB（>1MB），微信正文图会拒收；"
                        "作封面（永久素材，上限 10MB）没问题，若还要放进正文请另行压缩")
    print(f"  封面裁剪：{im.width}×{im.height} → {cover.width}×{cover.height}（2.35:1）",
          file=sys.stderr)
    return cover_path, raw_path, warnings


def process_illus(raw_bytes, dst):
    """正文插图：不裁，原样 16:9 转 JPEG 落盘。返回 warnings。"""
    from PIL import Image
    import io
    im = Image.open(io.BytesIO(raw_bytes))
    _, size = save_jpeg(im, dst)
    if size > MAX_IMAGE_BYTES:
        return [f"{dst.name} 压到最低质量仍有 {size // 1024}KB（>1MB），微信正文图会拒收，请手动压缩"]
    return []


# ---------------- API 调用（与小红书 gen_images 同源） ----------------

def abs_url(u, api_base):
    """相对 /uploads/… 拼成公网绝对 URL（免鉴权可直接下载）；已是 http(s) 原样；空/非串 → None。"""
    if not (isinstance(u, str) and u.strip()):
        return None
    return u if u.startswith(("http://", "https://")) else api_base + "/" + u.lstrip("/")


def send_request(method, url, key, payload=None, timeout=60):
    """带 Bearer 鉴权调 op API。网络异常向上抛，由调用方统一转 failed/unknown。"""
    import requests
    headers = {"Authorization": f"Bearer {key}"}
    return requests.request(method, url, json=payload, headers=headers, timeout=timeout)


def api_error(resp):
    """错误契约（nbdpsy-server）：400/401/403/404 键是 error；409/422 键是 detail。双键兼容取值。"""
    try:
        data = resp.json()
        msg = data.get("error") or data.get("detail") or resp.text[:200]
    except Exception:
        msg = resp.text[:200]
    return f"HTTP {resp.status_code}: {msg}"


def sandbox_hint(exc):
    """网络被拦时给 agent 可执行的下一步（Claude 沙盒拦网是已知场景）。"""
    s = str(exc)
    if any(k in s for k in ("Host not allowed", "ProxyError", "Connection refused",
                            "ConnectionError", "timed out", "Max retries")):
        return ("网络请求失败。若在 Claude Code 沙盒内被拦（典型报错 Host not allowed），"
                "先跑 `python3 scripts/nbdpsy_common.py sandbox allow` 写入放行名单并重启 "
                "Claude Code；单次命令也可用 Bash 工具参数 dangerouslyDisableSandbox 重试。"
                f"原始错误：{s[:200]}")
    return s[:300]


def create_job(api_base, key, prompts, anchor_url):
    """建一致性生图任务（横版 16:9，不传 draft_id，后端自动开临时容器）。返回 (job_id, session_id)。"""
    payload = {"prompts": prompts, "aspect_ratio": ASPECT_RATIO}
    if anchor_url:
        payload["anchor_url"] = anchor_url
    if len(prompts) > 99:
        raise ValueError(f"单次最多 99 条提示词（服务端硬上限，超出 422），本次 {len(prompts)} 条——用 --pages 分两次提交")
    resp = send_request("POST", f"{api_base}/api/op/consistent-images", key, payload, timeout=60)
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    data = resp.json()
    return data.get("job_id"), data.get("session_id")


def poll_job(api_base, key, session_id, job_id, timeout, interval=10.0, max_transient=3):
    """轮询到终态或超时；瞬时故障（网络异常/5xx）连续容忍 max_transient 次——
    一次抖动绝不能把仍在跑的任务判成终态。401/403/404 是永久错误立即抛。
    超时返回最后一次视图（不算失败，可 --job 复查）。"""
    deadline = time.monotonic() + timeout
    url = f"{api_base}/api/op/drafts/{session_id}/jobs/{job_id}"
    transient = 0
    while True:
        try:
            resp = send_request("GET", url, key)
        except Exception as e:  # 网络抖动 → 瞬时
            transient += 1
            if transient > max_transient:
                raise
            print(f"  轮询瞬时失败（{transient}/{max_transient}）: {e}", file=sys.stderr)
            time.sleep(interval)
            continue
        if resp.status_code >= 500:  # 服务端瞬时故障
            transient += 1
            if transient > max_transient:
                raise ValueError(api_error(resp))
            print(f"  轮询瞬时失败（{transient}/{max_transient}）: {api_error(resp)}", file=sys.stderr)
            time.sleep(interval)
            continue
        if resp.status_code == 404:  # 任务台账失效（进程内存台账，server 重启即丢；终态只留 2h）
            return {"status": "gone"}
        if resp.status_code >= 400:  # 401/403 永久错误
            raise ValueError(api_error(resp))
        transient = 0
        view = resp.json()
        status = view.get("status")
        print(f"  job {job_id}: {status}", file=sys.stderr)
        if status in TERMINAL_STATUSES or time.monotonic() >= deadline:
            return view
        time.sleep(interval)


def _error_for(errors, i, label):
    """从 result.errors 里为第 i 张（label）找失败文案，形态宽容：
    ①与 urls 等长的消息数组（该位为空=成功）②仅失败记录的对象数组（按 index/page 匹配）
    ③按下标/label 索引的对象 ④整段字符串。找不到 → None。"""
    if not errors:
        return None
    if isinstance(errors, list):
        if i < len(errors) and isinstance(errors[i], str) and errors[i].strip():
            return errors[i]
        for e in errors:
            if isinstance(e, dict) and (e.get("index") == i or e.get("page") == label):
                return e.get("error") or e.get("message") or json.dumps(e, ensure_ascii=False)
        return None
    if isinstance(errors, dict):
        for k in (str(i), i, label):
            if k in errors and errors[k]:
                v = errors[k]
                return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
        return None
    if isinstance(errors, str):
        return errors
    return None


def fetch_image(url_abs):
    """下载单张图的原始字节（/uploads/ 公开免鉴权）。失败向上抛，由调用方记 error 不炸整体。"""
    import requests
    resp = requests.get(url_abs, timeout=120)
    resp.raise_for_status()
    return resp.content


def finalize(view, selected, images_dir, api_base):
    """把终态 view.result 的 urls/errors 映射到每张并下载+后处理。
    返回 ([{"slot","label","url","path","raw_path","error"}], warnings)，与 selected 对齐
    （第 i 个 prompt ↔ 第 i 张）。"""
    result = view.get("result") or {}
    urls = result.get("urls") or []
    errors = result.get("errors")
    out, warnings = [], []
    for i, item in enumerate(selected):
        label = item["label"]
        rec = {"slot": item["slot"], "label": label,
               "url": None, "path": None, "raw_path": None, "error": None}
        u = abs_url(urls[i] if i < len(urls) else None, api_base)
        if u:
            rec["url"] = u
            try:
                raw = fetch_image(u)
                if item["slot"] == "cover":
                    path, raw_path, w = process_cover(raw, images_dir)
                    rec["path"], rec["raw_path"] = str(path), str(raw_path)
                    warnings.extend(w)
                else:
                    dst = images_dir / image_filename(item)
                    warnings.extend(process_illus(raw, dst))
                    rec["path"] = str(dst)
            except Exception as e:  # noqa: BLE001 — 图在服务端仍可用，--job 复查可补下
                rec["error"] = f"下载/处理失败（图在服务端仍可用，--job 复查可补下）：{sandbox_hint(e)}"
                print(f"  ⚠ {label} {rec['error']}", file=sys.stderr)
        else:
            rec["error"] = _error_for(errors, i, label) or "服务端未返回该张图 URL（生成失败）"
            print(f"  ⚠ {label} 生成失败：{rec['error']}", file=sys.stderr)
        out.append(rec)
    return out, warnings


def summarize_outcome(images_out):
    """有图有落盘=done；部分成功=partial；一张 URL 都没拿到=failed。"""
    have_url = [p for p in images_out if p["url"]]
    ok = [p for p in images_out if p["url"] and p["path"]]
    if not have_url:
        return "failed"
    return "done" if len(ok) == len(images_out) else "partial"


def retry_hint(failed, anchor_url, cover_only):
    if cover_only:
        return "封面没出成，调提示词后重跑 --cover-only（这是风格闸门第一步，确认后再出插图）"
    nums = [f["label"][2:] for f in failed if f["slot"] == "illus"]
    tail = f" --anchor-url {anchor_url}" if anchor_url else ""
    if not nums:  # 只有封面失败
        return "封面没出成，重跑 --cover-only 单独补出（插图已好的不必重出）"
    return f"部分图没出成，用 --pages {','.join(nums)}{tail} 只重出失败的那几张（带同一锚点保持一致性）"


def gone_envelope(sid, jid):
    """任务台账失效（server 重启，终态只留 2h）。与删除不同，生图重发是安全的（只多扣一次额度），
    故落 failed 语义引导重新发起，而非 unknown 的「勿重发」。"""
    return {"outcome": "failed", "session_id": sid, "job_id": jid, "images": [],
            "anchor_url": None,
            "error": "任务台账已失效（server 可能重启，终态只留 2 小时）",
            "hint": "生图可安全重新发起（代价只是重新扣一次额度）；已生成的图仍在服务端但 URL 无从查",
            "warnings": []}


def pending_envelope(sid, jid, anchor, warnings):
    return {
        "outcome": "pending", "session_id": sid, "job_id": jid,
        "images": [], "anchor_url": anchor, "error": None,
        "hint": f"任务已入队仍在生成（每张约 50s），稍后用 --job {jid} --session {sid} 复查并补下载，勿重发",
        "warnings": warnings,
    }


def emit_result(images_out, sid, jid, cover_only, anchor, warnings):
    """打印终态结果信封并按 outcome 退出（done=0 / partial|failed=1）。"""
    outcome = summarize_outcome(images_out)
    # cover-only 时把封面的绝对 URL 直接回给 agent，方便下一步出插图时当锚点
    cover = next((r for r in images_out if r["slot"] == "cover" and r["url"]), None)
    out_anchor = cover["url"] if (cover_only and cover) else anchor
    out = {"outcome": outcome, "session_id": sid, "job_id": jid,
           "images": images_out, "anchor_url": out_anchor,
           "error": None, "hint": None, "warnings": warnings}
    if outcome != "done":
        out["hint"] = retry_hint([r for r in images_out if not r["path"]], anchor, cover_only)
        if outcome == "failed":
            out["error"] = "全部图未出成（服务端未返回图 URL；可能触发额度/限流，见各条 error）"
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(1 if outcome in ("partial", "failed") else 0)


# ---------------- 状态文件 / dry-run / main ----------------

def resolve_images_dir(md, images_dir):
    if images_dir:
        return Path(images_dir)
    if md:
        # 放在稿子同目录下，md 里 `![](images/<stem>/cover.jpg)` 相对引用即可被 md2wechat 解析
        return md.parent / "images" / md.stem
    return None


def read_state(images_dir):
    p = images_dir / STATE_FILE
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def write_state(images_dir, sid, jid, selected, anchor):
    images_dir.mkdir(parents=True, exist_ok=True)
    (images_dir / STATE_FILE).write_text(
        json.dumps({"session_id": sid, "job_id": jid, "anchor_url": anchor,
                    "items": [{"slot": i["slot"], "num": i["num"], "label": i["label"]}
                              for i in selected]},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")


def _truncate(s, n=60):
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n] + "…"


def run_dry(args, md, images_dir, api_base):
    """离线打印将发送的 payload（提示词截断）与目标 URL，不打网络、不需要凭据。"""
    if not md:
        sys.exit("--dry-run 需要 --md")
    items = extract_items(md.read_text(encoding="utf-8"))
    try:
        validate_complete(items)
        selected = select_items(items, args.cover_only, args.pages)
        warnings = build_warnings(selected, args.cover_only, args.anchor_url)
    except ValueError as e:
        print(json.dumps({"outcome": "failed", "error": str(e),
                          "detected": [i["label"] for i in items]},
                         ensure_ascii=False, indent=2))
        sys.exit(1)
    payload = {"prompts": [_truncate(i["prompt"]) for i in selected],
               "aspect_ratio": ASPECT_RATIO}
    if args.anchor_url:
        payload["anchor_url"] = args.anchor_url
    print(json.dumps({
        "outcome": "dry_run",
        "target_url": f"{api_base}/api/op/consistent-images",
        "md": str(md),
        "detected": [i["label"] for i in items],
        "selected": [i["label"] for i in selected],
        "images_dir": str(images_dir) if images_dir else None,
        "filenames": [image_filename(i) for i in selected],
        "cover_crop": f"1536x1024 → 1536x{round(1536 / COVER_RATIO)}（2.35:1 居中裁）",
        "payload_preview": payload,
        "warnings": warnings,
    }, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(
        description="用后端 gpt-image 锚点法给公众号稿子出横版配图（封面 2.35:1 + 正文插图 16:9，异步）")
    ap.add_argument("--md", type=Path, help="稿子文件（长文/公众号分发稿，须含「## 配图」区块）")
    ap.add_argument("--cover-only", action="store_true", help="只出封面（风格闸门第一步）")
    ap.add_argument("--anchor-url", help="锚点参考图 URL（封面确认后的那张），插图据此锚定保持一致")
    ap.add_argument("--pages", help="只出指定插图：'1-3' / '1,3' / '1-2,4' 混合（不含封面）")
    ap.add_argument("--images-dir", type=Path, help="落盘目录（默认 <稿子同目录>/images/<稿子名>/）")
    ap.add_argument("--api-base", help="API base（默认 NBDPSY_VIDEO_API_BASE 或 https://mcp.nbdpsy.com）")
    ap.add_argument("--no-wait", action="store_true", help="提交后不等结果（稍后 --job 复查）")
    ap.add_argument("--wait-timeout", type=float, help="轮询等待上限秒数（默认 max(180, 张数×90)）")
    ap.add_argument("--dry-run", action="store_true", help="只打 payload 摘要与目标 URL，不发请求")
    ap.add_argument("--job", type=int, help="复查该已入队任务并补下载（配 --md 或 --images-dir 定位目录）")
    ap.add_argument("--session", help="--job 复查用的 session_id（缺省则从状态文件恢复）")
    args = ap.parse_args()

    md = args.md
    images_dir = resolve_images_dir(md, args.images_dir)
    api_base = (args.api_base or nbdpsy_common.video_api_base()).rstrip("/")

    # dry-run 离线，不需要凭据
    if args.dry_run:
        run_dry(args, md, images_dir, api_base)
        return

    key = nbdpsy_common.get_secret(nbdpsy_common.XHS_API_KEY)
    if not key:
        print(f"MISSING:{nbdpsy_common.XHS_API_KEY} 找管理员要「运营接入配置包」，"
              "secret import 导入后重试（生图与小红书发布 / 视频搬运同一把凭据，"
              "与本 skill 发文那把 NBDPSY_WECHAT_API_KEY 不是同一把）", file=sys.stderr)
        sys.exit(1)

    sid = jid = None  # 已入队的 session/job——之后任何异常都不能丢它，否则会诱发重复生成
    try:
        _require_pillow()  # 出图前就查，别烧完额度才发现裁不了图

        # ---- --job 复查已入队任务并补下载 ----
        if args.job is not None:
            if images_dir is None:
                raise ValueError("--job 复查需要 --md 或 --images-dir 以定位图片目录与状态文件")
            state = read_state(images_dir)
            jid = args.job
            sid = args.session or state.get("session_id")
            if not sid:
                raise ValueError("缺 --session，且状态文件里没有 session_id；请补 --session <id>")
            selected = state.get("items") or []
            anchor = state.get("anchor_url")
            if not selected:
                raise ValueError("状态文件缺张映射（items），无法对齐下载；请重新出图而非复查")
            cover_only = len(selected) == 1 and selected[0]["slot"] == "cover" and not anchor
            view = poll_job(api_base, key, sid, jid, timeout=0)  # 单次探测
            if view.get("status") == "gone":
                print(json.dumps(gone_envelope(sid, jid), ensure_ascii=False))
                sys.exit(1)
            if view.get("status") not in TERMINAL_STATUSES:
                print(json.dumps(pending_envelope(sid, jid, anchor, []), ensure_ascii=False))
                sys.exit(0)
            images_out, warns = finalize(view, selected, images_dir, api_base)
            emit_result(images_out, sid, jid, cover_only, anchor, warns)

        # ---- 正常出图 ----
        if not md:
            ap.error("出图需要 --md（或用 --job 复查已入队任务）")
        items = extract_items(md.read_text(encoding="utf-8"))
        validate_complete(items)
        selected = select_items(items, args.cover_only, args.pages)
        cover_only = args.cover_only
        anchor = args.anchor_url
        warnings = build_warnings(selected, cover_only, anchor)
        for w in warnings:
            print(f"⚠ {w}", file=sys.stderr)

        labels = [i["label"] for i in selected]
        print(f"提交出图：{md.name} {len(selected)} 张（{', '.join(labels)}）"
              f"比例 {ASPECT_RATIO} → {api_base} …", file=sys.stderr)
        jid, sid = create_job(api_base, key, [i["prompt"] for i in selected], anchor)
        if not jid or not sid:
            raise ValueError(f"建任务响应缺 job_id/session_id：job_id={jid} session_id={sid}")
        print(f"  已入队 job_id={jid} session_id={sid}", file=sys.stderr)
        write_state(images_dir, sid, jid, selected, anchor)

        if args.no_wait:
            print(json.dumps(pending_envelope(sid, jid, anchor, warnings), ensure_ascii=False))
            return

        timeout = args.wait_timeout if args.wait_timeout is not None else max(180, len(selected) * 90)
        view = poll_job(api_base, key, sid, jid, timeout=timeout)
        if view.get("status") == "gone":  # 极小概率：刚入队 server 就重启
            print(json.dumps(gone_envelope(sid, jid), ensure_ascii=False))
            sys.exit(1)
        if view.get("status") not in TERMINAL_STATUSES:  # 超时仍在跑
            print(json.dumps(pending_envelope(sid, jid, anchor, warnings), ensure_ascii=False))
            return
        images_out, warns = finalize(view, selected, images_dir, api_base)
        emit_result(images_out, sid, jid, cover_only, anchor, warnings + warns)

    except Exception as e:
        msg = sandbox_hint(e)
        if sid is not None and jid is not None:
            # 任务已在服务端入队，绝不判 failed——那会让 agent 重发同一批（重复生成/烧额度）
            print(f"  → 状态未知: {msg}", file=sys.stderr)
            print(json.dumps({
                "outcome": "unknown", "session_id": sid, "job_id": jid, "images": [],
                "anchor_url": args.anchor_url, "error": msg,
                "hint": f"任务可能仍在服务端跑，先用 --job {jid} --session {sid} 复查，勿直接重发以免重复生成",
            }, ensure_ascii=False))
            sys.exit(0)
        # 未入队的异常（解析/选张/建任务失败）才是真 failed
        print(f"  → 失败: {msg}", file=sys.stderr)
        print(json.dumps({"outcome": "failed", "session_id": None, "job_id": None,
                          "images": [], "error": msg}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
