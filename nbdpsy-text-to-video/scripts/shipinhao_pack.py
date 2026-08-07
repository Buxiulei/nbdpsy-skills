#!/usr/bin/env python3
"""把成片打包成「视频号成品包」：规格硬验 + 合规扫词 + 封面抽帧 + 上传清单。

视频号**没有任何内容发布 API**（2026-08-07 实调：服务号 token 调视频号接口回 48001
api unauthorized），发布只能人工在 channels.weixin.qq.com 做。本脚本管的是「人工上传前
把该拦的拦住」——上传现场发现问题最贵：文案发出去只能改一次、每次 ≤20 字。

两类硬拦（依据均为视频号官方格式说明）：
  1. **编码/色彩**：官方明文「暂不支持上传 HDR 视频」；h265（HEVC）在 Chrome 上传会失败
     （官方建议改用 iPhone/Mac Safari——但我们直接转 H.264 更省事）。`--fix` 可自动转码。
  2. **绝对化用语**：《视频号医疗健康行业公约》严禁「包治」「100%」「根除」类表述。
     心理科普踩这条最容易，且是账号级风险，故默认扫、命中即非零退出。

用法:
    python3 shipinhao_pack.py --video final.mp4 --title "标题" --text 文案.txt --out 成品包/
    python3 shipinhao_pack.py --video final.mp4 ... --fix          # 规格不合格时自动转码修复
    python3 shipinhao_pack.py --video final.mp4 ... --cover-at 3.5 # 指定抽封面的秒数

输出: stdout 纯 JSON（ok / issues / fixed / package）。有硬问题时 exit 1。
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

# 视频号官方硬规格
MIN_DURATION_S = 3
MAX_DURATION_S = 8 * 3600
MAX_BYTES = 2 * 1024 * 1024 * 1024
MIN_RATIO, MAX_RATIO = 0.33, 3.0

# HDR 判据：这几个传递函数/色域即 HDR，官方明文不支持
HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}
HDR_PRIMARIES = {"bt2020"}
BAD_CODECS = {"hevc", "h265"}

# 绝对化/疗效承诺用语。**只放高置信词**——误报会让运营养成忽略警告的习惯，
# 那比不扫更糟。「治疗」「症状」这类中性专业词不进表。
FORBIDDEN_WORDS = [
    "包治", "根治", "根除", "彻底治愈", "治愈率", "100%", "百分之百",
    "保证有效", "一定能好", "永不复发", "药到病除", "立竿见影",
]
# 引导脱离平台（视频号公约红线）
OFF_PLATFORM = ["加微信", "私信我", "扫码加", "加我好友", "vx", "V信"]


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def probe(video: Path) -> dict:
    r = run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries",
        "stream=codec_name,width,height,pix_fmt,color_transfer,color_primaries:format=duration,size",
        "-of", "json", str(video),
    ])
    if r.returncode != 0:
        raise SystemExit(json.dumps(
            {"ok": False, "error": f"ffprobe 读不出视频信息：{r.stderr.strip()[:200]}"},
            ensure_ascii=False))
    d = json.loads(r.stdout)
    st = (d.get("streams") or [{}])[0]
    fmt = d.get("format") or {}
    return {
        "codec": st.get("codec_name"),
        "width": st.get("width"),
        "height": st.get("height"),
        "pix_fmt": st.get("pix_fmt"),
        "color_transfer": st.get("color_transfer"),
        "color_primaries": st.get("color_primaries"),
        "duration": float(fmt.get("duration") or 0),
        "size": int(fmt.get("size") or 0),
    }


def check_spec(info: dict) -> list:
    """返回硬问题列表。每条带 fixable 标记——能靠转码解决的与不能的，处置完全不同。"""
    issues = []
    if info["codec"] in BAD_CODECS:
        issues.append({"kind": "codec", "fixable": True,
                       "msg": f"编码是 {info['codec']}，视频号在 Chrome 上传 h265 会失败——转成 H.264"})
    if (info.get("color_transfer") in HDR_TRANSFERS
            or info.get("color_primaries") in HDR_PRIMARIES):
        issues.append({"kind": "hdr", "fixable": True,
                       "msg": "是 HDR 视频，视频号官方明文不支持——转成 SDR"})
    if info["duration"] < MIN_DURATION_S:
        issues.append({"kind": "too_short", "fixable": False,
                       "msg": f"时长 {info['duration']:.1f}s 不足 {MIN_DURATION_S}s 下限"})
    if info["duration"] > MAX_DURATION_S:
        issues.append({"kind": "too_long", "fixable": False,
                       "msg": f"时长 {info['duration'] / 3600:.1f}h 超过 8h 上限"})
    if info["size"] > MAX_BYTES:
        issues.append({"kind": "too_big", "fixable": False,
                       "msg": f"文件 {info['size'] / 1024**3:.2f}GB 超过 2GB 上限"})
    if info["width"] and info["height"]:
        ratio = info["width"] / info["height"]
        if not (MIN_RATIO <= ratio <= MAX_RATIO):
            issues.append({"kind": "ratio", "fixable": False,
                           "msg": f"宽高比 {ratio:.3f} 不在 {MIN_RATIO}~{MAX_RATIO}"})
    return issues


def transcode(src: Path, dst: Path) -> None:
    """转 H.264 + SDR。-crf 20 视觉无损；yuv420p 保证各端可播。"""
    r = run([
        "ffmpeg", "-y", "-i", str(src),
        "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
        "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(dst),
    ])
    if r.returncode != 0:
        raise SystemExit(json.dumps(
            {"ok": False, "error": f"转码失败：{r.stderr.strip()[-300:]}"}, ensure_ascii=False))


def grab_cover(video: Path, dst: Path, at: float) -> bool:
    r = run(["ffmpeg", "-y", "-ss", str(at), "-i", str(video),
             "-frames:v", "1", "-q:v", "2", str(dst)])
    return r.returncode == 0 and dst.is_file()


def scan_text(text: str) -> list:
    hits = []
    for w in FORBIDDEN_WORDS:
        if w in text:
            hits.append({"kind": "forbidden_word", "word": w,
                         "msg": f"文案含绝对化用语「{w}」——视频号医疗健康公约严禁，属账号级风险"})
    for w in OFF_PLATFORM:
        if w in text:
            hits.append({"kind": "off_platform", "word": w,
                         "msg": f"文案含引导脱离平台的表述「{w}」——视频号公约红线"})
    return hits


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="视频号成品包：规格硬验 + 合规扫词 + 封面 + 上传清单")
    ap.add_argument("--video", required=True, help="成片 mp4")
    ap.add_argument("--title", required=True, help="视频标题/短标题")
    ap.add_argument("--text", help="文案文件（纯文本）；不给则只验视频")
    ap.add_argument("--out", required=True, help="成品包输出目录")
    ap.add_argument("--cover", help="指定封面图；不给则从视频抽帧")
    ap.add_argument("--cover-at", type=float, default=2.0, help="抽封面的秒数（默认 2.0）")
    ap.add_argument("--fix", action="store_true", help="规格不合格时自动转码修复")
    args = ap.parse_args(argv)

    for tool in ("ffprobe", "ffmpeg"):
        if not shutil.which(tool):
            print(json.dumps({"ok": False, "error": f"缺依赖 {tool}"}, ensure_ascii=False))
            return 1

    src = Path(args.video)
    if not src.is_file():
        print(json.dumps({"ok": False, "error": f"视频不存在：{src}"}, ensure_ascii=False))
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    info = probe(src)
    issues = check_spec(info)
    fixed = False
    final = out / "video.mp4"

    fixable = [i for i in issues if i["fixable"]]
    blocking = [i for i in issues if not i["fixable"]]

    if fixable and args.fix:
        transcode(src, final)
        info = probe(final)
        issues = check_spec(info)
        blocking = [i for i in issues if not i["fixable"]]
        fixed = True
    else:
        shutil.copy2(src, final)

    # 文案
    text = ""
    text_hits = []
    if args.text:
        p = Path(args.text)
        if not p.is_file():
            print(json.dumps({"ok": False, "error": f"文案文件不存在：{p}"}, ensure_ascii=False))
            return 1
        text = p.read_text(encoding="utf-8-sig").strip()
        (out / "文案.txt").write_text(text, encoding="utf-8")
        text_hits = scan_text(text)
    title_hits = scan_text(args.title)
    (out / "标题.txt").write_text(args.title.strip(), encoding="utf-8")

    # 封面
    cover = out / "cover.jpg"
    if args.cover:
        shutil.copy2(args.cover, cover)
        cover_from = "指定图"
    else:
        cover_from = f"抽帧 @{args.cover_at}s" if grab_cover(final, cover, args.cover_at) else None

    compliance = text_hits + title_hits
    ok = not blocking and not compliance and not (fixable and not args.fix)

    checklist = out / "上传清单.md"
    checklist.write_text(f"""# 视频号上传清单 · {args.title}

⚠️ 视频号**没有发布 API**，本包只能人工上传：https://channels.weixin.qq.com

## 规格自检
- 编码 {info['codec']} / 像素格式 {info['pix_fmt']} / 色彩 {info.get('color_transfer') or 'bt709'}
- 分辨率 {info['width']}×{info['height']}（宽高比 {info['width'] / info['height']:.3f}，合规区间 0.33~3.0）
- 时长 {info['duration']:.1f}s ／ 体积 {info['size'] / 1024**2:.1f}MB
- 结论：{'✅ 规格合格' if not blocking else '❌ ' + '；'.join(i['msg'] for i in blocking)}

## 合规自检
{'✅ 未命中绝对化用语与脱离平台表述' if not compliance else chr(10).join('- ❌ ' + h['msg'] for h in compliance)}

## 上传前必读
- **文案发布后终生只能修改一次、每次 ≤20 字**——粘贴前通读一遍，一次到位
- 逐条打**原创声明**（影响推荐权重与被引用能力）
- 行业类目**不要**选医疗健康相关
- 上传顺序：视频 → 封面 → 标题 → 文案 → 原创声明 → 发表
""", encoding="utf-8")

    result = {
        "ok": ok,
        "package": str(out),
        "video_info": info,
        "fixed": fixed,
        "blocking_issues": blocking,
        "fixable_issues": [] if fixed else fixable,
        "compliance_hits": compliance,
        "cover": cover_from,
        "files": sorted(p.name for p in out.iterdir()),
        "hint": ("成品包就绪，人工上传到 channels.weixin.qq.com。" if ok else
                 "有问题未解决：fixable 的加 --fix 自动转码；blocking 与合规命中必须回源头改。"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
