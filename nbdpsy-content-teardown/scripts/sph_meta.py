#!/usr/bin/env python3
"""视频号（微信 Channels）单条作品的元数据探针。

拆解一条视频号爆款时，**能自动拿到的只有元数据与封面**：昵称、文案、四个互动数、
发布时间、封面图。正片视频流微信外拿不到（见下），必须人工录屏。

用法：
    python3 sph_meta.py <视频号分享链接或裸ID> [--out DIR] [--timeout 秒]

三种入参形态都吃（内部一律归一成 sph id）：
    https://weixin.qq.com/sph/ARreWpEs3x
    https://channels.weixin.qq.com/finder-preview/pages/sph?id=ARreWpEs3x
    ARreWpEs3x

产出（默认落 ./teardown-out/sph-<id>/）：
    sph_meta.json   整形后的元数据（另存一份原始 api body 在 raw_feed_info.json）
    cover.jpg       封面图**立刻下载**
    page.png        整页截图（存证：数字与页面样子对得上）

**封面链接是短命的**：api body 里 sceneInfo.expiredTime 就是这条封面/视频 CDN 链的到期
时刻，实测只有约 2 小时（不是一天）。所以 cover.jpg 是**必做**不是可选——等到要用时再回
头下载，链接早就 403 了。sph_meta.json 里会写 coverExpireAt 让你知道手里的链还剩多久。

**正片流拿不到**：finder-preview 这个预览页只吐元数据 + 封面，视频流走微信自家的鉴权
（`dynamicExportId` + 只在微信客户端内生效的 token），headless 浏览器里没有可下载的
media 请求。所以拆视频号只能人工录屏，流程见 SKILL.md。

退出码：0 成功；2 未装 playwright（打印安装命令）；1 其他失败（一律 fail-loud，
绝不静默产出半份文件）。
"""
import argparse
import datetime
import json
import re
import sys
from pathlib import Path

# 页面本体（前端），api 请求也是打到这个域下
PAGE_URL = "https://channels.weixin.qq.com/finder-preview/pages/sph?id={sph_id}"
# 要截获的接口：整条作品的元数据只在这一个响应里（POST，返回 201 不是 200，别按状态码筛）
FEED_API_MARK = "/api/feed/get_feed_info"
# 用 iPhone UA：视频号预览页对桌面 UA 会走另一套引导下载 App 的壳，元数据接口不发
IPHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
BEIJING = datetime.timezone(datetime.timedelta(hours=8))
# 视频号 id 形态：ARxxxxxxxx 一类的短 id（字母数字混排）。放宽到 6-40 位避免误杀新形态。
ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,40}$")

RECORD_HINT = "⚠️ 视频号正片流微信外拿不到，需人工录屏。录屏获取流程见 SKILL.md"


def normalize_sph_id(raw: str) -> str:
    """把三种入参形态归一成 sph id（纯函数，不打网络）。

    认三种：weixin.qq.com/sph/<id> 短链、channels.weixin.qq.com/...?id=<id> 完整链、裸 id。
    认不出就抛 ValueError——**绝不猜**：猜错会去抓另一条作品，拆解结论全错还看不出来。
    """
    if not raw or not raw.strip():
        raise ValueError("没给视频号链接或 id")
    s = raw.strip().strip('"').strip("'")

    # 形态一：分享短链 https://weixin.qq.com/sph/ARxxxx（可能带 ?/# 尾巴）
    m = re.search(r"/sph/([A-Za-z0-9_-]+)", s)
    if m:
        return m.group(1)
    # 形态二：完整预览链 ...pages/sph?id=ARxxxx（顺带吃 &id= 与其它参数在前的情况）
    m = re.search(r"[?&]id=([A-Za-z0-9_-]+)", s)
    if m:
        return m.group(1)
    # 形态三：裸 id
    if ID_RE.match(s):
        return s
    raise ValueError(
        f"认不出这是什么：{s[:120]}\n"
        "只接受三种形态：https://weixin.qq.com/sph/ARxxxx ／ "
        "https://channels.weixin.qq.com/finder-preview/pages/sph?id=ARxxxx ／ 裸 id ARxxxx"
    )


def parse_count(fmt) -> int | None:
    """把 '2089' / '1.2万' / '3.5亿' 这类展示串转成整数；转不动返回 None（**不返回 0**）。

    分不清「没有」和「没解析出来」会长出很合理的错结论，所以解析不了就诚实留空，
    原始展示串一律另存 *Fmt 字段。
    """
    if fmt is None:
        return None
    s = str(fmt).strip()
    if not s:
        return None
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([万亿]?)", s)
    if not m:
        return None
    n = float(m.group(1))
    n *= {"": 1, "万": 10000, "亿": 100000000}[m.group(2)]
    return int(round(n))


def beijing_str(epoch) -> str:
    """秒级时间戳 → 北京时间字符串；不是数字就返回 None。"""
    if not isinstance(epoch, (int, float)) or epoch <= 0:
        return None
    return datetime.datetime.fromtimestamp(int(epoch), BEIJING).strftime("%Y-%m-%d %H:%M:%S")


def shape_meta(body: dict, sph_id: str = None) -> dict:
    """api body（get_feed_info 的 JSON）→ sph_meta.json 的内容（纯函数，不打网络）。

    errCode 非 0 直接抛：那种 body 里 feedInfo 是空壳，整形出来是一份「全是 None 的元数据」，
    落盘后没人看得出是抓失败了。
    """
    if not isinstance(body, dict):
        raise ValueError(f"api 响应不是 JSON 对象：{type(body).__name__}")
    if body.get("errCode"):
        raise ValueError(f"接口返回错误 errCode={body.get('errCode')} errMsg={body.get('errMsg')!r}；"
                         "常见原因：作品已删 / id 写错 / 该作品不允许微信外预览")
    data = body.get("data") or {}
    feed = data.get("feedInfo") or {}
    author = data.get("authorInfo") or {}
    scene = data.get("sceneInfo") or {}
    if not feed:
        raise ValueError("api 响应里没有 feedInfo，拿不到任何元数据（可能作品已删或需要微信内打开）")

    createtime = feed.get("createtime")
    expire = scene.get("expiredTime")
    counts = {
        "favCount": ("favCountFmt", "收藏"),
        "likeCount": ("likeCountFmt", "点赞"),
        "forwardCount": ("forwardCountFmt", "转发"),
        "commentCount": ("commentCountFmt", "评论"),
    }
    meta = {
        "id": sph_id,
        "pageUrl": PAGE_URL.format(sph_id=sph_id) if sph_id else None,
        "nickname": author.get("nickname"),
        "authorAvatar": author.get("headImgUrl"),
        "description": feed.get("description"),
        # 原值（秒）+ 北京时间字符串，两个都留：换算过的给人看，原值给对账
        "createtime": createtime,
        "createtimeBeijing": beijing_str(createtime),
        "coverUrl": feed.get("coverUrl"),
        # 封面/视频 CDN 链的到期时刻——cover.jpg 必须当场下载就是因为它
        "coverExpireAt": expire,
        "coverExpireAtBeijing": beijing_str(expire),
        "videoStream": None,
        "videoStreamNote": RECORD_HINT,
    }
    for key, (fmt_key, _label) in counts.items():
        meta[key] = parse_count(feed.get(fmt_key))
        meta[fmt_key] = feed.get(fmt_key)
    return meta


def download(url: str, dest: Path, timeout: int = 60) -> int:
    """下封面。失败直接抛——半份产物比没有产物更坑（后面拆解会以为封面就长这样）。"""
    import requests
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": IPHONE_UA})
    if resp.status_code >= 400:
        raise ValueError(f"下载封面失败 HTTP {resp.status_code}：{resp.text[:160]}")
    data = resp.content
    if not data:
        raise ValueError("下载封面失败：响应体是空的（链接多半已过期，重跑一次本脚本重新取链）")
    dest.write_bytes(data)
    return len(data)


def capture(sph_id: str, out_dir: Path, timeout: float = 60.0) -> dict:
    """开无头 chromium 打开预览页，截获 get_feed_info 的 JSON + 整页截图。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("未安装 playwright。装它：\n"
              "  pip install playwright\n"
              "  python3 -m playwright install chromium", file=sys.stderr)
        sys.exit(2)

    url = PAGE_URL.format(sph_id=sph_id)
    bodies = []
    errors = []

    print(f"→ 打开预览页：{url}", file=sys.stderr)
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as e:
            if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
                print("playwright 装了但缺 chromium 内核。装它：\n"
                      "  python3 -m playwright install chromium", file=sys.stderr)
                sys.exit(2)
            raise
        ctx = browser.new_context(user_agent=IPHONE_UA, viewport={"width": 390, "height": 844})
        page = ctx.new_page()

        def on_response(resp):
            if FEED_API_MARK not in resp.url:
                return
            try:
                bodies.append(resp.json())
                print(f"  截获 {FEED_API_MARK}（HTTP {resp.status}）", file=sys.stderr)
            except Exception as e:  # 响应体读不出来也要留痕，别静默丢
                errors.append(f"{resp.status} {e}")

        page.on("response", on_response)
        page.goto(url, wait_until="networkidle", timeout=int(timeout * 1000))
        page.wait_for_timeout(3000)  # networkidle 之后接口偶尔才回，多等一拍
        out_dir.mkdir(parents=True, exist_ok=True)
        shot = out_dir / "page.png"
        page.screenshot(path=str(shot), full_page=True)
        print(f"  整页截图 → {shot}", file=sys.stderr)
        browser.close()

    if not bodies:
        detail = f"（有 {len(errors)} 次响应体读取失败：{errors[:2]}）" if errors else ""
        raise ValueError(
            f"页面打开了但没截到 {FEED_API_MARK} 的响应{detail}。\n"
            "可能原因：id 写错 / 作品已删 / 网络被拦（沙盒或代理）/ 页面结构变了。"
            f"先人工在浏览器里打开 {url} 看是不是还有内容。")
    return bodies[-1]


def main():
    ap = argparse.ArgumentParser(description="视频号作品元数据探针（元数据+封面+截图；正片需人工录屏）")
    ap.add_argument("target", help="视频号分享链接（weixin.qq.com/sph/xxx 或完整预览链）或裸 id")
    ap.add_argument("--out", help="产物目录（默认 ./teardown-out/sph-<id>）")
    ap.add_argument("--timeout", type=float, default=60.0, help="打开页面的超时秒数（默认 60）")
    args = ap.parse_args()

    try:
        sph_id = normalize_sph_id(args.target)
    except ValueError as e:
        print(f"✗ {e}", file=sys.stderr)
        sys.exit(1)
    print(f"→ 视频号 id：{sph_id}", file=sys.stderr)

    out_dir = Path(args.out) if args.out else Path("teardown-out") / f"sph-{sph_id}"

    try:
        body = capture(sph_id, out_dir, args.timeout)
        (out_dir / "raw_feed_info.json").write_text(
            json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
        meta = shape_meta(body, sph_id)

        cover = meta.get("coverUrl")
        if not cover:
            raise ValueError("api 响应里没有 coverUrl，封面下不了（作品可能已删）")
        # 立刻下载：封面链约 2 小时过期，晚一步就 403
        size = download(cover, out_dir / "cover.jpg")
        meta["coverLocal"] = "cover.jpg"
        meta["coverBytes"] = size
        print(f"  封面 → {out_dir / 'cover.jpg'}（{size} 字节，链接到期 {meta.get('coverExpireAtBeijing')}）",
              file=sys.stderr)

        (out_dir / "sph_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except SystemExit:
        raise
    except Exception as e:
        print(f"✗ 抓取失败：{e}", file=sys.stderr)
        sys.exit(1)

    print(f"\n✓ 元数据 → {out_dir / 'sph_meta.json'}", file=sys.stderr)
    print(f"  作者：{meta.get('nickname')}｜发布：{meta.get('createtimeBeijing')}", file=sys.stderr)
    print(f"  点赞 {meta.get('likeCountFmt')}／收藏 {meta.get('favCountFmt')}／"
          f"转发 {meta.get('forwardCountFmt')}／评论 {meta.get('commentCountFmt')}", file=sys.stderr)
    print(RECORD_HINT, file=sys.stderr)
    # stdout 出纯 JSON，方便 agent 直接接管道
    print(json.dumps(meta, ensure_ascii=False))


if __name__ == "__main__":
    main()
