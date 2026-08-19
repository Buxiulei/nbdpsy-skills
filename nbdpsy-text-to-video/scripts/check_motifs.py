#!/usr/bin/env python3
"""动效可辨性量具：六件 motif 到底看不看得出区别。

    check_motifs.py --html 工作目录/card-oneline.html --cues 工作目录/narration.mp3.cues.json

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 **量的时刻必须落在入场动画进行中，⛔ 不是入场之后。**

🩸 2026-08-19 审稿代理量「入场后 0.88s 的文字包围盒」，得出「六种里只有 wipe 可辨、
depth 所有指标低于 still 基线」——⚠️ **而 0.88s 时所有入场动画早已结束**
（最长的 depth 也只有 .55s）。那一刻量到的是**停留期**，
而模板硬契约⑤**明确要求停留期完全静止可读**（「观众要读的是字，不是特效」）。
⇒ **它量的正是"契约要求它们必须一样"的那一段。**

⚠️ 但**结论方向仍然是对的**：入场只有 0.3s、屏却停 6–9s
⇒ 观众 **95% 的时间**看到的确实是同一个静止画面。
⇒ 正解是**把可辨窗拉长、把峰值幅度加大**，⛔ 不是把停留期也动起来。

🩸 **照它给的参数改会把 tilt 改坏**：它建议「tilt 提到 2–3 度」，
而模板里 tilt 的起始角**本来就是 16 度**——它量到 0.3 度是因为量在动画之后。
⇒ **按错误量测给出的参数，会把一个 16 度的动效"提"到 3 度。**
⚠️ **别人给的建议值，要先回去看它是从哪个量测推出来的。**

## 本量具怎么量

对每个 motif 取**入场进度 35%** 那一刻（缓动 `power2.out` 在这里离峰值最近又已明显偏离终态），
读该屏元素的 `getBoundingClientRect` 与 computed style，算四个指标：

| 指标 | 怎么算 | 谁该高 |
|---|---|---|
| `dy` | 与终态包围盒的**垂直**偏移(px) | rise / tilt |
| `dx` | 水平偏移(px) | drift |
| `clip` | computed `clipPath` 裁掉的百分比 | wipe |
| `rotx` | 从 `matrix3d` 解出的 **rotateX 角度**(度) | tilt |
| `blur` | computed filter 里的 blur(px) | depth |

🩸 **`wipe` 和 `tilt` 的特征指标我一开始选错了**（第一版量具当场报它们"区分不开"）：
- `wipe` 用 `clipPath` 裁剪，**裁剪是视觉的，`getBoundingClientRect` 一点不变**（实测 dw=0.1px）；
- `tilt` 试过 `dy`（差一点不过）与 `dh`（**0.4px**）都不行：`getBoundingClientRect` 对 3D 变换
  返回的是**投影后**的包围盒，透视近端放大与远端缩小互相抵消 ⇒ 高度几乎不变。
  ⇒ 只能**从 `matrix3d` 直接解角度**。
⚠️ **量不出来先怀疑指标选错了，⛔ 别先去改被量的东西**——
差一点就把两个本来做对了的动效"加强"了。

**判据**：每件的**特征指标**必须显著高于 `still` 的同名指标
（`still` 只有 opacity 在动 ⇒ 四项全 ≈0，天然是基线）。
⛔ 不设绝对阈值——画幅/字号会变，比基线才是稳的。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROGRESS = 0.35
"""量在入场进度的百分之几。

⚠️ 0.35 不是随便取的：`power2.out` 在 50% 时已走完 ~87%（实测 depth 的 blur
14px→1.75px），⇒ 量在 50% 会**低估**幅度。35% 处离峰值近、又确实在动画中。
⛔ 别改成 0（那是起始帧，任何动效都"很明显"，量了等于没量）。"""

FEATURE = {"rise": "dy", "tilt": "rotx", "drift": "dx", "wipe": "clip",
           "depth": "blur", "still": None}
"""每件的**特征指标**。⚠️ `still` 没有特征指标——它就是基线本身。"""

MIN_RATIO = 3.0
"""特征指标至少是 `still` 基线的几倍。⛔ 不设绝对阈值：画幅/字号一变，绝对值就没意义。
⚠️ 基线接近 0 时改用绝对下限（见 `ABS_FLOOR`），否则除零。"""

ABS_FLOOR = {"dy": 15.0, "dx": 15.0, "rotx": 5.0, "clip": 20.0, "blur": 2.0}
"""基线 ≈0 时的绝对下限（px / px / px / px-blur）。
审稿给的口径是「位移 >30px／倾斜 >15px」——这里取更低的 15px 作**不合格线**，
⚠️ 因为它量的是 0.88s、我量的是 35%，两把尺的读数不可直接比。"""

JS = """(progress) => {
  const secs = [...new Set(SEC)];
  const out = [];
  for (const si of secs) {
    const i = SCREENS.findIndex((s, k) => SEC[k] === si);
    if (i < 0) continue;
    const s = SCREENS[i], el = els[i], m = motifFor(si);
    const t0 = Math.max(0, s.start - LEAD), dur = ENTER[m];
    // 终态：入场结束后一点点（⚠️ 停留期有极缓呼吸，取刚结束那一刻最干净）
    tl.seek(t0 + dur + 0.02, false);
    const end = el.getBoundingClientRect();
    tl.seek(t0 + dur * progress, false);
    const mid = el.getBoundingClientRect();
    const f = getComputedStyle(el).filter || "";
    const bm = f.match(/blur\\(([\\d.]+)px\\)/);
    const cp = getComputedStyle(el).clipPath || "";
    // inset(0px 63.4% 0px 0px) → 取被裁掉的那一侧百分比；none/无 ⇒ 0
    const cm = cp.match(/inset\(([^)]*)\)/);
    let clip = 0;
    if (cm) {
      const pcts = (cm[1].match(/([\d.]+)%/g) || []).map(x => parseFloat(x));
      clip = pcts.length ? Math.max(...pcts) : 0;
    }
    // rotateX 角度：matrix3d 的 m22=cos θ、m23=−sin θ（GSAP 的 rotationX 走这条）
    const tf = getComputedStyle(el).transform || "";
    let rotx = 0;
    const mm = tf.match(/matrix3d\(([^)]*)\)/);
    if (mm) {
      const v = mm[1].split(",").map(Number);
      rotx = Math.abs(Math.atan2(Math.abs(v[6]), v[5]) * 180 / Math.PI);
    }
    out.push({ si, motif: m,
      dy: Math.abs(mid.top - end.top), dx: Math.abs(mid.left - end.left),
      rotx, clip, blur: bm ? +bm[1] : 0 });
  }
  return out;
}"""


def measure(html: Path, cues: list) -> list[dict]:
    from playwright.sync_api import sync_playwright
    probe = html.with_suffix(".motifprobe.html")
    probe.write_text(html.read_text(encoding="utf-8").replace(
        "__CUES__", json.dumps(cues, ensure_ascii=False)), encoding="utf-8")
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(args=["--force-device-scale-factor=1", "--hide-scrollbars"])
            pg = b.new_page(viewport={"width": 1080, "height": 1440})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(f"file://{probe.resolve()}")
            pg.wait_for_function("window.SEEK !== undefined", timeout=25000)
            rows = pg.evaluate(JS, PROGRESS)
            b.close()
        if errs:
            print(f"⚠️ 页面错误：{errs[:2]}", file=sys.stderr)
        return rows
    finally:
        probe.unlink(missing_ok=True)


def summarize(rows: list[dict]) -> dict:
    """按 motif 归并（取各指标的中位数），与 still 基线比。"""
    from statistics import median
    by = {}
    for r in rows:
        by.setdefault(r["motif"], []).append(r)
    agg = {m: {k: median([x[k] for x in v]) for k in ("dy", "dx", "rotx", "clip", "blur")}
           for m, v in by.items()}
    base = agg.get("still", {k: 0.0 for k in ("dy", "dx", "rotx", "clip", "blur")})
    verdicts = []
    for m, vals in sorted(agg.items()):
        feat = FEATURE.get(m)
        if feat is None:
            verdicts.append({"motif": m, "n": len(by[m]), "feature": "—",
                             "value": 0.0, "base": 0.0, "ok": True, "note": "基线本身"})
            continue
        v, b = vals[feat], base.get(feat, 0.0)
        ok = (v >= b * MIN_RATIO) if b > 0.5 else (v >= ABS_FLOOR[feat])
        verdicts.append({"motif": m, "n": len(by[m]), "feature": feat,
                         "value": round(v, 1), "base": round(b, 1), "ok": ok,
                         "note": f"基线 ×{MIN_RATIO:g}" if b > 0.5 else f"绝对下限 {ABS_FLOOR[feat]:g}"})
    return {"agg": agg, "verdicts": verdicts,
            "ok": all(v["ok"] for v in verdicts)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="动效可辨性量具（量入场进行中，⛔ 不量入场之后）")
    ap.add_argument("--html", required=True)
    ap.add_argument("--cues", required=True)
    a = ap.parse_args(argv)
    cues = json.load(open(a.cues, encoding="utf-8"))
    if isinstance(cues, dict):
        cues = cues.get("cues", cues)
    rows = measure(Path(a.html), cues)
    if not rows:
        print("❌ 一屏都没量到——⚠️ 这是「没查」不是「查过没问题」", file=sys.stderr)
        return 2
    res = summarize(rows)
    print(f"  量在入场进度 {PROGRESS:.0%}（⛔ 不是入场之后——那时契约⑤要求它们必须一样）\n")
    print("  motif   段数  特征   实测    still基线  判据")
    for v in res["verdicts"]:
        mark = "✅" if v["ok"] else "❌"
        print(f"  {mark} {v['motif']:6s} {v['n']:3d}  {v['feature']:5s} "
              f"{v['value']:7.1f}  {v['base']:7.1f}   {v['note']}")
    if not res["ok"]:
        bad = [v["motif"] for v in res["verdicts"] if not v["ok"]]
        print(f"\n⛔ {bad} 与 still 基线区分不开——**观众看到的就是淡入**。\n"
              f"   处置：加大该件的峰值幅度**并延长 duration**（可辨窗太短和幅度太小都会这样）；\n"
              f"   ⛔ 别去动停留期——契约⑤要求停留期静止可读。", file=sys.stderr)
        return 1
    print("\n✅ 六件全部与 still 基线区分得开")
    return 0


if __name__ == "__main__":
    sys.exit(main())
