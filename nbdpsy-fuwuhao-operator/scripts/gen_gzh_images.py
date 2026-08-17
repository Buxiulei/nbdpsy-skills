#!/usr/bin/env python3
"""用后端 gpt-image 锚点法给一篇公众号稿子出「一致性」配图（经运营工具 op API）。

与小红书轮播共用同一个后端与同一把凭据，差别只有三处：**横版 16:9**、**一篇只有
1 张封面 + 按正文字数配的正文插图（每 ~500 汉字一张）**、**封面要裁成 2.35:1**。其余（锚点法、任务台账、失败处置）完全同源，
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

**封面 2.35:1**：微信封面官方比例是 2.35:1，而 gpt-image 出的是 16:9（标称 1536×1024）。
下载后用 Pillow **居中裁剪**成 2.35:1 存 `cover.jpg`，未裁的原图另存 `cover-raw.jpg` 便于重裁。
⚠️ **裁剪按拿到的图现算，不认死 1536**：服务端去水印工作流会做非整数缩小（实测 ×0.855），
所以到手常是 1313×876 而非 1536×1024，裁后是 1313×559 而非 1536×654。`crop_box()` 一律用
`im.width/im.height` 现算目标高（`round(w / 2.35)`），**比例恒定、绝对像素随实际宽度走**——
谁都别把 1536/654 写死回去，那样缩过的图会被裁错或拉伸。
所以写封面提示词时**视觉重心要居中**——上下两条各 185px 会被裁掉。正文插图不裁，原样 16:9。
落盘统一转 JPEG（微信正文图硬上限单张 1MB，PNG 原图常超），质量阶梯降到达标为止。

流程：本地解析 md「## 配图」区块（`### 封面` / `### 插图N` 定位 + 区间内第一个完整 ``` 围栏块为
提示词，判据与小红书 `### PN` 同源）→ POST {base}/api/op/consistent-images（带 aspect_ratio=16:9，
不传 draft_id，后端自动开临时容器；202 拿 job_id + session_id）→ 轮询
GET {base}/api/op/drafts/{session_id}/jobs/{job_id} 到终态 → done 后逐张下载并转码
（result.urls 顺序与提交的 prompts 对齐，相对 /uploads/… 公开免鉴权）。

**出图 provider（2026-08-17 加）**：`--provider openai`（**默认**，即上文全部内容）走 gpt-image-2；
`--provider html` 改走兄弟 skill 的确定性 HTML 渲染（`nbdpsy-xiaohongshu-creator/scripts/render_cover.py`），
零额度、秒出、改文案不动版式——OpenAI 额度耗尽后的主力路径。
两者**共用同一个「## 配图」区块结构**（`### 封面` / `### 插图N` + 各一个 ``` 围栏），
差别只在**围栏里装什么**：openai 装自然语言提示词，html 装**结构化 JSON**。
⛔ **不做自动推断**：绝不「看着像 JSON 就当 JSON、不像就当提示词」。provider 说了算，
`--provider html` 下围栏解析不出 JSON 就点名报错并指路（怎么改 / 怎么退回 openai）。
理由是本仓反复踩过的坑——自动推断一旦猜错，是最难查的一类 bug（图出来了、只是出错了）。

用法：
    python3 gen_gzh_images.py --md post.md --cover-only              # 只出封面（风格闸门第一步）
    python3 gen_gzh_images.py --md post.md --anchor-url <URL>        # 出全部（封面+插图，各自锚定）
    python3 gen_gzh_images.py --md post.md --pages 1-3 --anchor-url <URL>  # 只出指定插图/重试失败张
    python3 gen_gzh_images.py --md post.md --job <id> [--session <id>]     # 复查已入队任务并补下载
        [--images-dir DIR] [--api-base URL] [--no-wait] [--wait-timeout N] [--dry-run]
    python3 gen_gzh_images.py --md post.md --provider html                # HTML 渲染出全部（同步、零额度）
    python3 gen_gzh_images.py --md post.md --provider html --cover-only   # 只渲封面
    （--provider html 是同步渲染，没有任务队列，故 --anchor-url/--job/--no-wait 等异步参数在这条路上会被拒）

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
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# 同目录 vendored 副本
import nbdpsy_common

TERMINAL_STATUSES = {"done", "failed"}
STATE_FILE = ".gen_gzh_images_state.json"

# 出图比例：公众号恒横版。服务端按此归一到 gpt-image-2 的 1536×1024。
ASPECT_RATIO = "16:9"
# 正文插图张数上限。张数本身按「每 ~500 汉字一张」由写稿侧算好写进「## 配图」区块，
# 这里只兜住离谱的量——超过这个数，读者是在图册里找正文。
MAX_ILLUS = 10

# 微信封面官方比例（gpt-image 出的 16:9 居中裁到它）
COVER_RATIO = 2.35
# 微信正文图硬上限：单张 1MB（md2wechat.MAX_IMAGE_BYTES 同值）
MAX_IMAGE_BYTES = 1024 * 1024
# JPEG 质量阶梯：从高到低试，第一个落在 1MB 内的就用
JPEG_QUALITIES = (92, 86, 80, 72, 64)

# 配图区块的两种标题：`### 封面` 与 `### 插图N`（N 从 1 起）。后面可带 · 说明，同小红书 `### PN`。
_HEADING = re.compile(r"^###\s+(封面|插图\s*(\d+))\b")

# ---- provider 白名单 ----
# 显式白名单（不是「猜」）：传别的值由 argparse choices 直接顶回并列出合法值。
PROVIDERS = ("openai", "html")

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


def guard_openai_fences(selected):
    """反方向的对称校验：openai 路径上拦住「明显是写给 html provider 的结构化 JSON」。

    为什么必须拦：那段 JSON 会被**原样当成提示词**发给 gpt-image-2，模型照着
    `{"template":"still-life","icons":[...]}` 这串字符去画——图必然是废图、白烧一次额度，
    而且回执一切正常（有 URL、有落盘、outcome=done）。这是「静默走错路」的典型形态，
    比直接报错难查一百倍。

    判据**故意收得很紧**（防过度拦截，那会把正常提示词挡在门外）：
    必须①整段是合法 JSON ②解析出来是对象 ③带 html 数据的招牌键——三条全中才拦。
    ⛔ 只是围栏里出现花括号、或提示词里嵌了 JSON 片段，一律放行。

    招牌键取 `template`（封面）与 `layout`（插图）**两个**：html 的封面 JSON 用 template、
    插图 JSON 用 layout，只认 template 等于这道闸门对插图全员失效——而插图恰恰是量最大的那批。
    自然语言提示词整段恰好是「带 layout 键的合法 JSON 对象」的概率为零，判据一样紧。"""
    for item in selected:
        text = (item.get("prompt") or "").strip()
        if not text.startswith("{"):        # 提示词几乎不可能以 { 开头，先便宜地挡掉绝大多数
            continue
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            continue                        # 解析不了 = 就是自然语言提示词，放行
        if not isinstance(data, dict) or not ({"template", "layout"} & set(data)):
            continue                        # 不是对象、或没有招牌键 = 判据不满足，放行
        keys = "/".join(list(data)[:4])
        raise ValueError(
            f"`### {item['label']}` 的围栏是 html provider 的结构化字段（含 {keys}），"
            "不能当自然语言提示词喂给 gpt-image-2——模型会照着这串字符去画，"
            "出来必然是废图还白烧一次额度。"
            "请加 `--provider html` 用 HTML 渲染出图，"
            "或把围栏改回自然语言提示词（见 references/gzh-illustration-spec.md）。")


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


def build_warnings(selected, cover_only, anchor_url, provider="openai"):
    """provider 默认值 openai 保证既有调用点行为一字不变。
    html 路径没有「锚点」这个概念（版式由模板定死、天然一致），故不发那条锚点警告——
    发了等于教运营去做一件在这条路径上不存在的事。"""
    w = []
    if provider == "openai" and not cover_only and not anchor_url and any(i["slot"] == "illus" for i in selected):
        w.append("未带锚点参考图（--anchor-url），整篇一致性无保障；正常流程应先 --cover-only 出封面"
                 "过风格闸门，运营确认后用返回的 anchor_url 再出插图")
    n_illus = sum(1 for i in selected if i["slot"] == "illus")
    if n_illus > MAX_ILLUS:
        w.append(f"本次 {n_illus} 张正文插图，超过上限 {MAX_ILLUS} 张——"
                 "再多就成图册了，读者要在图里找正文")
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


# ---------------- HTML 渲染 provider（--provider html） ----------------
# 为什么有这条路（2026-08-17 立）：OpenAI 额度耗尽且无法充值，出图要能整体切到确定性 HTML 渲染。
# 渲染脚本是**兄弟 skill 的地盘**（nbdpsy-xiaohongshu-creator），本文件只负责
# 「解析配图区块 → 调它 → 核产物 → 出回执」四件事，⛔ 绝不在这里复制一份版式实现（两份必然漂移）。

# 渲染脚本按相对路径推导：<本 skill 目录>/../nbdpsy-xiaohongshu-creator/scripts/render_cover.py
# （__file__ 在 <skill>/scripts/ 下，故上溯两级到 skills 根再往兄弟目录拐）
_RENDER_REL = ("nbdpsy-xiaohongshu-creator", "scripts", "render_cover.py")
# 测试接缝：本仓无法在单测里改兄弟 skill 的文件，留个环境变量以便指向替身脚本验证成功路径。
_RENDER_ENV = "NBDPSY_RENDER_COVER"

# 渲染脚本必须认得的参数。**存在 ≠ 可用**：它可能还是给小红书竖版封面写的那版（只有
# --data/--out/--template），不认 --canvas/--template 就会被 argparse 顶回一句 unrecognized arguments。
# 与其让 agent 对着晦涩的 usage 猜，不如出图前先探一次 --help，点名说清缺哪个参数。
#
# ⚠️ 按**本次真正要用的**参数探，不是一律要求全齐：渲染脚本是分批落地的
# （2026-08-17 skill 线订正：真源已有 --canvas 与 --template，安装副本尚未装上）。一律要求全齐会把
# 「只出封面」这种今天就能跑的活也一并拦死——闸门该拦的是缺的那件事，不是顺带拦住能干的事。
_RENDER_FLAGS_ALWAYS = ("--data", "--out", "--canvas")
# 2026-08-17 skill 线定案：CLI 一律用 --template，⛔ 不新增 --layout——
# 「同一件事有两个名字」比名字不贴切更糟。⚠️ 注意区分层级：
# 围栏 JSON 里插图仍用 `layout` 键（数据字段），传给渲染脚本的 flag 统一是 --template。
_RENDER_FLAG_FOR_SLOT = {"cover": "--template", "illus": "--template"}

# 正文插图的三种版式。三种讲的是三件不同的事，⛔ 不替运营挑默认值（挑错了整张图白出）。
_HTML_LAYOUTS = ("compare", "steps", "define")
# 画布比例：封面用微信官方的 2.35:1。html 路径**直接按此比例渲染**，
# 不像 openai 路径要先出横版再居中裁——所以也就没有 cover-raw.jpg。
CANVAS_COVER = "2.35:1"
# ⚠️ 插图在两条链路上**故意叫两个名字**，这不是 bug，别"修"成一个：
#   · openai 路径 → 文件头的 `ASPECT_RATIO = "16:9"`，那是出图 API 的入参名，外部契约，改不了；
#   · html  路径 → 下面的 `CANVAS_ILLUS_HTML = "3:2"`，那是我们自己的脚本，用真实比例。
# 两者指向**同一个客观画布**（到手都是 3:2），差别只在"跟谁说话"。
# 2026-08-17：html 路径的插图**传真实比例 `3:2`**，⛔ 不沿用 `16:9` 那个错名。
# 分界线在「这个名字是谁的契约」：`16:9` 是出图 API 那边的 aspect_ratio 参数名，我们改不了，
# 只能在 openai 分支里照它的规矩喊；而 render_cover.py 是我们自己的脚本，没有任何理由
# 继承一个从第一天起就名不副实的名字。**错名的传染范围到此为止。**
# 否则会变成「传 16:9 / 出 3:2 / 闸门按 3:2 判」三者各说各话——三个数都对得上产物，
# 却没有一处能自证，下一个人读到哪一处都会怀疑是别处错了。
CANVAS_ILLUS_HTML = "3:2"

# canvas 名 → 产物**实际**期望宽高比。⚠️ 这张表是显式映射，⛔ 不许按 canvas 名字面去算比例。
# 因为 `16:9` 是传给出图 API 的 `aspect_ratio` **参数名**，不是到手画布的真实比例：
# gpt-image-2 横版标称 1536×1024 本身就是 **3:2**（1536/1024=1.5），去水印等比缩小到
# 1313×876 仍是 3:2。规格文档那行「16:9」与产物从第一天起就不一致，只是此前没有闸门去量它。
# 2026-08-17 实测在产 42 张（6 cover + 6 cover-raw + 30 illus）：
#   cover.jpg      1313×559 → 2.3488 ✅ 合 2.35
#   illus/raw      1313×876 → 1.4989 ✅ 合 3:2，**零例外**
# 照字面 16:9（1.7778）卡，会把每一张插图都判红——而且是最难自证的那种恒报红闸门：
# 文档白纸黑字写着 16:9，查的人会先怀疑图错了，不会怀疑闸门。
CANVAS_EXPECTED_RATIO = {
    CANVAS_COVER: 2.35,        # 微信封面官方比例
    ASPECT_RATIO: 3 / 2,       # openai 路径的叫法：名字 16:9，真身 3:2 —— 见上。
                               # 直接引用文件头那个常量，⛔ 别再写一遍 "16:9" 字面量：
                               # 同一个值写两处，改的时候必然只改一处
    CANVAS_ILLUS_HTML: 3 / 2,  # 同一个真身，html 路径用真名。两行同值不是重复：
                               # 左边是两条链路各自的「叫法」，右边是同一个客观事实
}
# 产物核验：比例容差。渲染落到整数像素，除不尽会有零点几像素的误差，故不苛求精确相等。
# 实测两类的偏差都在 0.0012 以内，±0.01 够宽也够紧。
RATIO_TOLERANCE = 0.01
# 四角判白边：读四角 RGB 求和，>740（≈ 每通道 247）即疑似白边。
# 这是实测坑——模板只给 body 设背景色、没给 html 设，截图边缘就会露出浏览器默认白底。
# 渲染「成功」了但图是废的，只有像素能看出来（沿用本仓纪律：渲染成功 ≠ 渲染对了）。
CORNER_WHITE_SUM = 740
# 单张渲染超时：起 chromium + 等字体落位 + 截图，正常几秒；给足余量但不无限等。
RENDER_TIMEOUT = 180


def render_script_path():
    """渲染脚本的预期路径（不保证存在，存在性由 require_render_script 判）。"""
    override = os.environ.get(_RENDER_ENV)
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent.parent.joinpath(*_RENDER_REL)


def needed_render_flags(selected):
    """本次真正会传给渲染脚本的参数集合（封面与插图都传 --template（值不同））。"""
    flags = set(_RENDER_FLAGS_ALWAYS)
    for item in selected:
        flags.add(_RENDER_FLAG_FOR_SLOT[item["slot"]])
    return sorted(flags)


def require_render_script(needed):
    """出图前确认渲染脚本**存在且认得本次要传的参数**，两道都不过就明确失败。
    ⛔ 绝不因为「让流程跑通」而在这里降级或假装成功——缺依赖就是缺依赖。"""
    script = render_script_path()
    if not script.is_file():
        raise ValueError(
            f"HTML 渲染脚本尚未就绪（预期路径 {script}），skill 线正在实现；"
            "当前可用 --provider openai（需额度）。"
            f"若脚本装在别处，可用环境变量 {_RENDER_ENV} 指过去。")
    try:
        proc = subprocess.run([sys.executable, str(script), "--help"],
                              capture_output=True, text=True, timeout=60)
    except Exception as e:  # noqa: BLE001 — 连 --help 都跑不起来，说明脚本本身坏了
        raise ValueError(
            f"HTML 渲染脚本跑不起来（{script}）：{e}。"
            "当前可用 --provider openai（需额度）。") from e
    helptext = (proc.stdout or "") + (proc.stderr or "")
    missing = [f for f in needed if f not in helptext]
    if missing:
        # 点名缺的那个参数**是给谁用的**，运营才知道该等 skill 线还是换 provider。
        # ⚠️ 2026-08-17 随 flag 统一到 --template，这里**删掉了原来的 --cover-only 绕行建议**：
        # 从前封面用 --template、插图用 --layout，缺 --layout 时封面确实照样能出，那句建议成立；
        # 现在两者共用 --template，缺了它封面和插图一起做不了，再劝人加 --cover-only 就是骗人
        # ——运营照做仍会失败，还会以为是自己用错了参数。改名要连着**依赖旧名的判断**一起改。
        who = "、".join(f"{f}（{'版式' if f == '--template' else '基础参数'}）"
                        for f in missing)
        raise ValueError(
            f"HTML 渲染脚本已存在（{script}），但**不认识**本次要传的参数：{who}。"
            "说明它还在分批落地中，与公众号横版契约尚未对齐。"
            "这不是本脚本能兜的事，请找 skill 线补齐；"
            "当前也可用 --provider openai（需额度）。")
    return script


def expected_ratio(canvas):
    """canvas 名 → 期望宽高比，**查表**不算数（见 CANVAS_EXPECTED_RATIO 的注释：
    canvas 名是 API 参数名，字面算出来的比例与真实产物对不上）。
    表里没有的名字直接报错，⛔ 不回落到「按名字算」——那正是这道闸门要防的那类静默错。"""
    if canvas not in CANVAS_EXPECTED_RATIO:
        raise ValueError(
            f"canvas {canvas!r} 不在期望比例映射表里（已知：{', '.join(CANVAS_EXPECTED_RATIO)}）。"
            "新增画布必须同时在 CANVAS_EXPECTED_RATIO 里登记**实测**比例，"
            "⛔ 不要按名字字面推算——16:9 这个名字的真身就是 3:2。")
    return CANVAS_EXPECTED_RATIO[canvas]


def _json_fence_hint(label):
    return (
        f"`### {label}` 的围栏是自然语言提示词，不能用 --provider html 出图；"
        "请改成结构化 JSON（封面示例："
        '{"template":"still-life","icons":["headphones","coffee","sprout"],'
        '"accent":"cord","baseline":true,"bg":"warm-paper"}；'
        '插图示例：{"layout":"compare", …}），'
        "或去掉 --provider html 用默认的 openai provider（需额度）。")


def parse_html_spec(item):
    """把一张配图的围栏解析成渲染数据 dict，并取出该走哪个版式参数。
    返回 (data, flag, value)：封面 → ('--template', 'still-life')；插图 → ('--template', 版式名)。

    ⛔ 全程不做推断：解析不了就报错指路，缺 template/layout 就点名，绝不替运营挑一个默认版式。"""
    label = item["label"]
    text = (item.get("prompt") or "").strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"{_json_fence_hint(label)}（JSON 解析报错：{e}）") from e
    if not isinstance(data, dict):
        raise ValueError(
            f"`### {label}` 的围栏解析出来是 {type(data).__name__}，不是 JSON 对象。"
            f"{_json_fence_hint(label)}")
    if item["slot"] == "cover":
        tpl = str(data.get("template") or "").strip()
        if not tpl:
            raise ValueError(
                f"`### {label}` 的 JSON 缺 `template` 字段（如 \"still-life\"）——"
                "版式名要显式写。⛔ 不替你挑默认版式：挑错了整张封面白出。")
        return data, "--template", tpl
    layout = str(data.get("layout") or "").strip()
    if not layout:
        raise ValueError(
            f"`### {label}` 的 JSON 缺 `layout` 字段——合法值：{' / '.join(_HTML_LAYOUTS)}。"
            "三种版式讲的是三件不同的事（对比 / 步骤 / 定义），⛔ 不替你猜。")
    if layout not in _HTML_LAYOUTS:
        raise ValueError(
            f"`### {label}` 的 `layout` 是 {layout!r}，不在合法值里：{' / '.join(_HTML_LAYOUTS)}")
    # ⚠️ 数据字段叫 `layout`，但传给渲染脚本的 flag 是 `--template`（2026-08-17 skill 线定案）：
    # 渲染脚本那边「选哪套版式」只有一个入口，⛔ 不给同一件事两个 flag 名。
    # 两层名字不同是有意的：JSON 里 `layout` 描述的是插图的版式语义（对比/步骤/定义），
    # CLI 的 `--template` 指的是"用哪个模板文件"，封面与插图共用这个入口。
    return data, "--template", layout


def html_data_path(images_dir, item):
    """数据文件与产物同名同目录（cover.jpg ↔ cover.json）——契约要求的「同名 .json 留痕」就是它，
    出了问题能直接看到当时喂进去的是什么，不用回头猜。
    ⚠️ 渲染脚本按**数据文件所在目录**解析 JSON 里的相对资源路径（头像等），
    所以它必须落在 images_dir，不能图省事塞进 /tmp。"""
    return images_dir / (Path(image_filename(item)).stem + ".json")


def render_one(script, data_path, out_path, canvas, flag, value):
    """调一次 render_cover.py。返回 (ok, payload, err)。
    payload = 渲染脚本 stdout 的 JSON——它自己量出来的坏消息（字体没落位、溢出等）都在 warnings 里，
    必须原样往上带，⛔ 不能吞（吞了就成了「恒绿的假闸门」）。"""
    cmd = [sys.executable, str(script), "--data", str(data_path),
           "--canvas", canvas, flag, value, "--out", str(out_path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=RENDER_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, {}, f"渲染超时（>{RENDER_TIMEOUT}s），命令：{' '.join(cmd)}"
    except Exception as e:  # noqa: BLE001
        return False, {}, f"渲染脚本调用失败：{e}"
    payload = {}
    lines = (proc.stdout or "").strip().splitlines()
    if lines:
        try:  # 约定 stdout 最后一行是结果 JSON；不是也不炸，退回读 stderr
            payload = json.loads(lines[-1])
        except (json.JSONDecodeError, ValueError):
            payload = {}
    if proc.returncode != 0 or payload.get("ok") is False:
        err = (payload.get("error") or (proc.stderr or "").strip()[:300]
               or f"渲染脚本退出码 {proc.returncode}，且没给出错误信息")
        return False, payload, err
    return True, payload, None


def verify_artifact(path, canvas, label):
    """产物核验：**渲染成功 ≠ 渲染对了**。返回 (fatal, warnings)。
    ⛔ 不静默放行（本仓纪律：能量出来的坏消息一律显式报）。

    fatal 与 warnings 的分界＝**这张图还能不能用**：
    - fatal（文件不存在 / 0 字节 / 打不开）＝压根没拿到图，按「这张失败」记进 rec.error 走 partial，
      与 openai 路径下载失败的处置同构。⛔ 绝不能让 0 字节文件顶着 outcome=done + path 交出去——
      下游会拿它去传微信（本仓纪律：绿必须是被验证过的绿）。
    - warnings（比例偏 / 四角白边 / 超 1MB）＝图拿到了但可能不对，交人判断，不替人否决。"""
    from PIL import Image
    w = []
    if not path.is_file():
        return f"渲染脚本报成功，但产物文件根本不存在（{path}）", w
    size = path.stat().st_size
    if size == 0:
        return f"产物是 0 字节空文件（{path}）", w
    try:
        im = Image.open(path).convert("RGB")
    except Exception as e:  # noqa: BLE001
        return f"产物打不开、不是有效图片（{path}）：{e}", w
    want = expected_ratio(canvas)
    got = im.width / im.height
    if abs(got - want) > RATIO_TOLERANCE:
        w.append(f"🔴 {label}：比例不符——canvas {canvas} 期望 {want:.4f}，"
                 f"实际 {im.width}×{im.height}（={got:.4f}），超出容差 ±{RATIO_TOLERANCE}。"
                 "微信按固定比例展示，比例错了会被切掉一截")
    corners = {"左上": (0, 0), "右上": (im.width - 1, 0),
               "左下": (0, im.height - 1), "右下": (im.width - 1, im.height - 1)}
    white = [name for name, xy in corners.items() if sum(im.getpixel(xy)) > CORNER_WHITE_SUM]
    if white:
        w.append(f"🔴 {label}：{'、'.join(white)} 角接近纯白（RGB 和 >{CORNER_WHITE_SUM}），疑似留白边。"
                 "已知根因＝模板只给 body 设了背景色、没给 html 设，截图边缘露出浏览器默认白底。"
                 "这是模板侧的事，反馈给 skill 线改模板，⛔ 别在这里裁掉了事")
    if size > MAX_IMAGE_BYTES:
        w.append(f"⚠️ {label}：{size // 1024}KB 超过微信正文图上限 1MB，放进正文会被拒收")
    return None, w


def summarize_outcome_html(images_out):
    """html 是**同步**渲染，没有 url 这一层，故只认 path：全有=done、部分=partial、全无=failed。
    （openai 那边先拿 URL 再下载，判据是两段式，不能共用。）"""
    ok = [p for p in images_out if p["path"]]
    if not ok:
        return "failed"
    return "done" if len(ok) == len(images_out) else "partial"


def html_retry_hint(failed, cover_only):
    if cover_only:
        return "封面没渲染出来，改完 JSON 重跑 --cover-only --provider html"
    nums = [f["label"][2:] for f in failed if f["slot"] == "illus"]
    if not nums:
        return "封面没渲染出来，重跑 --cover-only --provider html 单独补出（插图已好的不必重出）"
    return (f"部分图没渲染出来，用 --pages {','.join(nums)} --provider html 只重出失败的那几张"
            "（HTML 渲染零额度，重跑不心疼）")


def run_html(args, md, images_dir):
    """--provider html 主流程：解析配图区块（围栏=JSON）→ 逐张调 render_cover.py → 核产物 → 出回执。

    与 openai 路径最大的结构差异是**同步**：没有 job/session，也就没有 pending/unknown 这两种终态，
    因此不写状态文件、也没有 --job 复查。回执字段保持一致（多余的字段给 null），消费方不必分支。"""
    # 这些开关全是 openai 异步链路的概念，在同步渲染里没有对应物。
    # 静默忽略是本仓踩过的坑（参数静默回落），故一律显式报错。
    for flag, val in (("--anchor-url", args.anchor_url), ("--job", args.job),
                      ("--session", args.session), ("--no-wait", args.no_wait or None),
                      ("--wait-timeout", args.wait_timeout)):
        if val:
            sys.exit(f"{flag} 是 openai 异步出图链路的参数，--provider html 是同步渲染、没有这个概念"
                     "（没有任务队列，也就不存在锚点/复查/等待）。去掉它重试。")
    if not md:
        sys.exit("--provider html 出图需要 --md")
    if images_dir is None:
        sys.exit("无法确定落盘目录，请给 --md 或 --images-dir")

    items = extract_items(md.read_text(encoding="utf-8"))
    validate_complete(items)
    selected = select_items(items, args.cover_only, args.pages)
    warnings = build_warnings(selected, args.cover_only, args.anchor_url, provider="html")

    # **先把所有围栏解析完再渲染任何一张**：解析失败是配置问题，半途报错会留下一半图，
    # 运营还得自己分辨哪几张是新的（fail fast）。
    specs = []
    for item in selected:
        data, flag, value = parse_html_spec(item)
        # ⚠️ 插图取 `3:2`，而 openai 路径同一件事传的是 `16:9`——**两处不一致是有意的**，
        # 原因见 CANVAS_ILLUS_HTML 定义处。⛔ 看到不一致别顺手"统一"，那会把 3:2 改回错名。
        canvas = CANVAS_COVER if item["slot"] == "cover" else CANVAS_ILLUS_HTML
        specs.append((item, data, flag, value, canvas))

    if args.dry_run:
        run_dry_html(md, images_dir, specs, warnings)
        return

    _require_pillow()          # 产物核验要读像素，缺 Pillow 先说，别渲染完才发现核不了
    script = require_render_script(needed_render_flags(selected))
    for w in warnings:
        print(f"⚠ {w}", file=sys.stderr)
    print(f"HTML 渲染：{md.name} {len(specs)} 张"
          f"（{', '.join(i['label'] for i, *_ in specs)}）→ {script.name} …", file=sys.stderr)

    images_dir.mkdir(parents=True, exist_ok=True)
    images_out = []
    for item, data, flag, value, canvas in specs:
        label = item["label"]
        # raw_path 固定 None：html 直接按目标比例渲染，不存在 openai 那边「未裁原图」的概念
        rec = {"slot": item["slot"], "label": label,
               "url": None, "path": None, "raw_path": None, "error": None}
        data_path = html_data_path(images_dir, item)
        data_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        out_path = images_dir / image_filename(item)
        ok, payload, err = render_one(script, data_path, out_path, canvas, flag, value)
        if not ok:
            rec["error"] = err
            print(f"  ⚠ {label} 渲染失败：{err}", file=sys.stderr)
        else:
            # 渲染脚本自己量出来的坏消息原样上带（字体没落位 / 溢出 / 裁切带等）
            for w in payload.get("warnings") or []:
                warnings.append(f"{label}：{w}")
            fatal, verify_warns = verify_artifact(out_path, canvas, label)
            warnings.extend(verify_warns)
            if fatal:  # 没拿到能用的图 = 这张就是失败，⛔ 不留 path 冒充成功
                rec["error"] = fatal
                print(f"  ⚠ {label} 产物核验不过：{fatal}", file=sys.stderr)
            else:
                rec["path"] = str(out_path)
                print(f"  ✓ {label} → {out_path.name}（{canvas}）", file=sys.stderr)
        images_out.append(rec)

    outcome = summarize_outcome_html(images_out)
    out = {"outcome": outcome, "session_id": None, "job_id": None,
           "images": images_out, "anchor_url": None,
           "error": None, "hint": None, "warnings": warnings,
           "provider": "html"}
    if outcome != "done":
        out["hint"] = html_retry_hint([r for r in images_out if not r["path"]], args.cover_only)
        if outcome == "failed":
            out["error"] = "全部图未渲染出来（见各条 error）"
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(1 if outcome in ("partial", "failed") else 0)


def run_dry_html(md, images_dir, specs, warnings):
    """html 的 dry-run：打印将要执行的渲染命令与解析出的字段，不起浏览器、不写文件。
    顺带把渲染脚本的就绪情况报出来——这是这条路最常见的卡点。"""
    needed = needed_render_flags([i for i, *_ in specs])
    try:
        script = str(require_render_script(needed))
        ready, ready_msg = True, None
    except ValueError as e:
        script, ready, ready_msg = str(render_script_path()), False, str(e)
    cmds = []
    for item, data, flag, value, canvas in specs:
        out_path = images_dir / image_filename(item)
        cmds.append({
            "label": item["label"],
            "canvas": canvas,
            "data_file": str(html_data_path(images_dir, item)),
            "data_keys": sorted(data),
            "cmd": f"python3 {script} --data {html_data_path(images_dir, item)} "
                   f"--canvas {canvas} {flag} {value} --out {out_path}",
        })
    print(json.dumps({
        "outcome": "dry_run",
        "provider": "html",
        "md": str(md),
        "render_script": script,
        "render_script_ready": ready,
        "render_script_hint": ready_msg,
        "images_dir": str(images_dir),
        "renders": cmds,
        "warnings": warnings,
    }, ensure_ascii=False, indent=2))


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
        guard_openai_fences(selected)  # 拦「写给 html 的结构化 JSON 被当提示词发出去」
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
        # 只给标称值：真实尺寸取决于服务端去水印的等比缩小（实测 ×0.855），裁剪时按到手的图现算
        "cover_crop": f"居中裁成 {COVER_RATIO}:1（标称 1536x1024 → 1536x"
                      f"{round(1536 / COVER_RATIO)}；服务端缩图时按实际宽度等比走，"
                      f"如 1313x876 → 1313x{round(1313 / COVER_RATIO)}）",
        "payload_preview": payload,
        "warnings": warnings,
    }, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(
        description="用后端 gpt-image 锚点法给公众号稿子出横版配图（封面 2.35:1 + 正文插图 16:9，异步）")
    ap.add_argument("--md", type=Path, help="稿子文件（长文/公众号分发稿，须含「## 配图」区块）")
    # 显式白名单：传别的值 argparse 直接顶回并列出合法值。默认 openai = 现有行为一字不变。
    ap.add_argument("--provider", choices=PROVIDERS, default="openai",
                    help="出图方式：openai=gpt-image-2 锚点法（默认，需额度）；"
                         "html=确定性 HTML 渲染（零额度，围栏内容须为结构化 JSON）")
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

    # ---- provider 分流：html 走确定性渲染（同步、零额度、不碰凭据也不碰网络）----
    # 放在这里是为了让下面 openai 那一整条路**一行都不用改**（默认行为零变化的最省事保证）。
    if args.provider == "html":
        try:
            run_html(args, md, images_dir)
        except ValueError as e:  # 解析/依赖类失败：没入队、没花钱，判 failed 是安全的
            print(f"  → 失败: {e}", file=sys.stderr)
            print(json.dumps({"outcome": "failed", "session_id": None, "job_id": None,
                              "images": [], "anchor_url": None, "error": str(e),
                              "hint": None, "warnings": [], "provider": "html"},
                             ensure_ascii=False))
            sys.exit(1)
        return

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
        guard_openai_fences(selected)  # 拦「写给 html 的结构化 JSON 被当提示词发出去」（白烧额度且回执正常）
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
