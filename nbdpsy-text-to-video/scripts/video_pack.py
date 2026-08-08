#!/usr/bin/env python3
"""把成片打包成「多平台成品包」：逐平台规格判定 + 合规扫词 + 上传优化转码 + 封面 + 上传清单。

覆盖三个投放口：**视频号 / 小红书 / 公众号**。三家都吃 MP4，但限制各不相同，
最紧的那条（公众号 200MB）决定了「一份文件三平台通传」的天花板。

三条已知的硬坑：
  1. **H.264 是唯一三家都稳的编码**——h265 在视频号 Chrome 上传直接失败（官方建议改用
     iPhone/Mac Safari，但转码更省事）；视频号官方另明文「暂不支持上传 HDR 视频」。
  2. **我们的成片码率天生偏低**：即梦素材原始 ~10Mbps，合成 CRF 20 后只剩 ~600kbps。
     肉眼直接看没问题（CRF 20 是视觉近无损），但**平台会二次压缩，低码率源在转码器手里更吃亏**。
     `--for-upload` 就是为这一步准备的。
  3. **放大到 1080p 不会凭空长出细节**（即梦 Seedance 2.5 只出 480p/720p，源就是 720p）。
     它值得做的理由是另两条：平台按 1080p 档处理、二次压缩更温和；手机端不必客户端拉伸。
     ⛔ 别把它当"变高清"卖给运营。

用法:
    python3 video_pack.py --video final.mp4 --title "标题" --text 文案.txt --out 成品包/
    python3 video_pack.py ... --for-upload   # 上传优化：短边升到 1080 + 提码率（推荐发布前跑）
    python3 video_pack.py ... --fix          # 只修不合规编码（h265/HDR → H.264/SDR），不动分辨率
    python3 video_pack.py ... --cover-at 3.5 # 指定抽封面的秒数（默认 2.0）

输出: stdout 纯 JSON。三平台**全部**可发才 ok=true；否则 exit 1，但 platforms 里逐家给判定
——某家超限不代表另两家不能发，别一刀切放弃。
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

GB = 1024 ** 3
MB = 1024 ** 2

# 逐平台限制。视频号那三条来自官方帮助中心已核原文；小红书与公众号的官方页在登录墙后，
# 数字取第三方一致口径中**最严**的一档——宁可本地多拦一次，也别到上传现场才失败。
PLATFORMS = {
    "视频号": {"min_dur": 3, "max_dur": 8 * 3600, "max_bytes": 2 * GB,
               "ratio": (0.33, 3.0), "strict_codec": True},
    "小红书": {"min_dur": 1, "max_dur": 15 * 60, "max_bytes": 10 * GB,
               "ratio": None, "strict_codec": False},
    "公众号": {"min_dur": 2, "max_dur": 60 * 60, "max_bytes": 200 * MB,
               "ratio": None, "strict_codec": False},
}

HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}
HDR_PRIMARIES = {"bt2020"}
BAD_CODECS = {"hevc", "h265"}

# 上传优化目标：短边升到 1080（不足才升，够了不动），码率给足以扛平台二次压缩
UPLOAD_SHORT_EDGE = 1080
UPLOAD_CRF = 18
UPLOAD_MAXRATE = "8M"
UPLOAD_BUFSIZE = "16M"

# 绝对化/疗效承诺用语。**只放高置信词**——误报会让运营养成忽略警告的习惯，那比不扫更糟。
# 「治疗」「症状」这类中性专业词不进表。
FORBIDDEN_WORDS = [
    "包治", "根治", "根除", "彻底治愈", "治愈率", "100%", "百分之百",
    "保证有效", "一定能好", "永不复发", "药到病除", "立竿见影",
]
OFF_PLATFORM = ["加微信", "私信我", "扫码加", "加我好友", "vx", "V信"]


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def probe(video: Path) -> dict:
    r = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=codec_name,width,height,pix_fmt,color_transfer,color_primaries:"
             "format=duration,size", "-of", "json", str(video)])
    if r.returncode != 0:
        raise SystemExit(json.dumps(
            {"ok": False, "error": f"ffprobe 读不出视频信息：{r.stderr.strip()[:200]}"},
            ensure_ascii=False))
    d = json.loads(r.stdout)
    st = (d.get("streams") or [{}])[0]
    fmt = d.get("format") or {}
    dur = float(fmt.get("duration") or 0)
    size = int(fmt.get("size") or 0)
    return {
        "codec": st.get("codec_name"),
        "width": st.get("width"),
        "height": st.get("height"),
        "pix_fmt": st.get("pix_fmt"),
        "color_transfer": st.get("color_transfer"),
        "color_primaries": st.get("color_primaries"),
        "duration": dur,
        "size": size,
        "bitrate_kbps": round(size * 8 / dur / 1000) if dur else 0,
    }


def is_hdr(info: dict) -> bool:
    return (info.get("color_transfer") in HDR_TRANSFERS
            or info.get("color_primaries") in HDR_PRIMARIES)


def judge(info: dict) -> tuple:
    """逐平台判定。返回 (platforms 明细, 可转码修复的通用问题)。"""
    fixable = []
    if info["codec"] in BAD_CODECS:
        fixable.append({"kind": "codec", "msg":
                        f"编码 {info['codec']}：视频号在 Chrome 上传 h265 会失败——转 H.264"})
    if is_hdr(info):
        fixable.append({"kind": "hdr", "msg": "HDR 视频：视频号官方明文不支持——转 SDR"})

    ratio = info["width"] / info["height"] if info.get("width") and info.get("height") else None
    out = {}
    for name, lim in PLATFORMS.items():
        issues = []
        if info["duration"] < lim["min_dur"]:
            issues.append(f"时长 {info['duration']:.1f}s 短于下限 {lim['min_dur']}s")
        if info["duration"] > lim["max_dur"]:
            issues.append(f"时长 {info['duration'] / 60:.1f}min 超上限 {lim['max_dur'] / 60:.0f}min")
        if info["size"] > lim["max_bytes"]:
            issues.append(f"体积 {info['size'] / MB:.0f}MB 超上限 {lim['max_bytes'] / MB:.0f}MB")
        if lim["ratio"] and ratio and not (lim["ratio"][0] <= ratio <= lim["ratio"][1]):
            issues.append(f"宽高比 {ratio:.3f} 不在 {lim['ratio'][0]}~{lim['ratio'][1]}")
        if lim["strict_codec"]:
            issues += [f["msg"] for f in fixable]
        out[name] = {"ok": not issues, "issues": issues}
    return out, fixable


def encode(src: Path, dst: Path, info: dict, upgrade: bool) -> None:
    """转码。upgrade=True 时把短边升到 1080 并给足码率（上传优化）；否则只统一编码与色彩。"""
    vf = []
    if upgrade:
        w, h = info["width"], info["height"]
        short = min(w, h)
        if short < UPLOAD_SHORT_EDGE:
            # 短边升到 1080，长边按比例（-2 保证偶数，H.264 要求）
            vf.append(f"scale={UPLOAD_SHORT_EDGE}:-2:flags=lanczos" if w <= h
                      else f"scale=-2:{UPLOAD_SHORT_EDGE}:flags=lanczos")
    cmd = ["ffmpeg", "-y", "-i", str(src)]
    if vf:
        cmd += ["-vf", ",".join(vf)]
    cmd += ["-c:v", "libx264", "-preset", "slow" if upgrade else "medium",
            "-crf", str(UPLOAD_CRF) if upgrade else "20",
            "-profile:v", "high", "-pix_fmt", "yuv420p",
            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
    if upgrade:
        cmd += ["-maxrate", UPLOAD_MAXRATE, "-bufsize", UPLOAD_BUFSIZE]
    cmd += ["-c:a", "aac", "-b:a", "192k" if upgrade else "160k",
            "-movflags", "+faststart", str(dst)]
    r = run(cmd)
    if r.returncode != 0:
        raise SystemExit(json.dumps(
            {"ok": False, "error": f"转码失败：{r.stderr.strip()[-300:]}"}, ensure_ascii=False))


def scan_text(text: str) -> list:
    hits = []
    for w in FORBIDDEN_WORDS:
        if w in text:
            hits.append({"kind": "forbidden_word", "word": w,
                         "msg": f"含绝对化用语「{w}」——视频号医疗健康公约严禁，属账号级风险"})
    for w in OFF_PLATFORM:
        if w in text:
            hits.append({"kind": "off_platform", "word": w,
                         "msg": f"含引导脱离平台的表述「{w}」——视频号公约红线"})
    return hits


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="多平台成品包（视频号 / 小红书 / 公众号）")
    ap.add_argument("--video", required=True, help="成片 mp4")
    ap.add_argument("--title", required=True, help="标题/短标题")
    ap.add_argument("--text", help="文案文件（纯文本）")
    ap.add_argument("--out", required=True, help="成品包输出目录")
    ap.add_argument("--cover", help="指定封面图；不给则从视频抽帧")
    ap.add_argument("--cover-at", type=float, default=2.0, help="抽封面的秒数（默认 2.0）")
    ap.add_argument("--for-upload", action="store_true",
                    help="上传优化：短边升到 1080 + 提码率（发布前推荐；不增细节，见文件头说明）")
    ap.add_argument("--fix", action="store_true", help="只修不合规编码（h265/HDR），不动分辨率")
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
    final = out / "video.mp4"

    info = probe(src)
    before = dict(info)
    _, fixable = judge(info)

    transcoded = False
    if args.for_upload or (fixable and args.fix):
        encode(src, final, info, upgrade=args.for_upload)
        info = probe(final)
        transcoded = True
    else:
        shutil.copy2(src, final)

    platforms, fixable = judge(info)

    text = ""
    hits = scan_text(args.title)
    if args.text:
        p = Path(args.text)
        if not p.is_file():
            print(json.dumps({"ok": False, "error": f"文案文件不存在：{p}"}, ensure_ascii=False))
            return 1
        text = p.read_text(encoding="utf-8-sig").strip()
        (out / "文案.txt").write_text(text, encoding="utf-8")
        hits += scan_text(text)
    (out / "标题.txt").write_text(args.title.strip(), encoding="utf-8")

    cover = out / "cover.jpg"
    if args.cover:
        shutil.copy2(args.cover, cover)
        cover_from = "指定图"
    else:
        r = run(["ffmpeg", "-y", "-ss", str(args.cover_at), "-i", str(final),
                 "-frames:v", "1", "-q:v", "2", str(cover)])
        cover_from = f"抽帧 @{args.cover_at}s" if r.returncode == 0 and cover.is_file() else None

    all_ok = all(v["ok"] for v in platforms.values())
    ok = all_ok and not hits

    rows = "\n".join(
        f"| {n} | {'✅' if v['ok'] else '❌'} | {'—' if v['ok'] else '；'.join(v['issues'])} |"
        for n, v in platforms.items())
    ratio = info["width"] / info["height"]
    upgrade_note = ""
    if transcoded and args.for_upload:
        upgrade_note = (f"\n> 已做上传优化：{before['width']}×{before['height']} "
                        f"{before['bitrate_kbps']}kbps → {info['width']}×{info['height']} "
                        f"{info['bitrate_kbps']}kbps。**放大不增加细节**（源即 720p），"
                        "目的是让平台按 1080p 档转码、减少二次压缩损失。\n")

    (out / "上传清单.md").write_text(f"""# 上传清单 · {args.title}

⚠️ 三个平台**都没有内容发布 API**，只能人工上传。视频号：channels.weixin.qq.com
{upgrade_note}
## 规格
- {info['codec']} / {info['pix_fmt']} / {info['width']}×{info['height']}（宽高比 {ratio:.3f}）
- 时长 {info['duration']:.1f}s ／ 体积 {info['size'] / MB:.1f}MB ／ 码率 {info['bitrate_kbps']} kbps

## 逐平台判定
| 平台 | 可发 | 问题 |
|---|---|---|
{rows}

## 合规
{'✅ 未命中绝对化用语与脱离平台表述' if not hits else chr(10).join('- ❌ ' + h['msg'] for h in hits)}

## 上传前必读
- **视频号文案发布后终生只能改一次、每次 ≤20 字**——粘贴前通读，一次到位
- 逐条打**原创声明**（影响推荐权重与被引用能力）
- 视频号行业类目**不要**选医疗健康相关
""", encoding="utf-8")

    print(json.dumps({
        "ok": ok,
        "package": str(out),
        "video_info": info,
        "transcoded": transcoded,
        "upgraded": bool(transcoded and args.for_upload),
        "before": before if transcoded else None,
        "platforms": platforms,
        "fixable_issues": fixable if not transcoded else [],
        "compliance_hits": hits,
        "cover": cover_from,
        "files": sorted(p.name for p in out.iterdir()),
        "hint": ("成品包就绪，人工上传。" if ok else
                 "有问题未解决：编码类加 --fix 或 --for-upload；时长/体积超限与合规命中必须回源头改。"),
    }, ensure_ascii=False, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
