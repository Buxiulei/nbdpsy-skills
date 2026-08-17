#!/usr/bin/env python3
"""口播稿闸门 —— 硬卡字数，软提醒十四律里**可枚举**的那几条。

## 为什么有这个脚本

`references/narration-spec.md` §九 把「每页/每镜 ≤100 汉字」定成**唯一的硬闸门**，
但 2026-08-17 体检发现：**全仓没有任何脚本读它**。SKILL.md 写了「定稿前必须走完审校
流程」，可没有任何东西能抓出漏做——老板原话是「不能是一个死链，永远闲置不被调用」。

§九 自称「脚本层管不了长度」。**这句只对了一半**：管不了的是**秒数**（同引擎同音色
页间语速仍浮动 20%，99 字落在慢页 27 秒、快页 22 秒），但**字数**本身 `len()` 就能判，
而 §九 的闸门本来就定在字数上。所以这个闸门是能落到脚本里的，落在这里。

## 硬 / 软的分界（⛔ 别把软的改成硬的）

- **硬闸门**：汉字数 > 100 → **exit 1**。这条是 §九 的原文，客观可判，没有例外。
- **软提醒**：十四律里能用正则枚举的三条（书面连接词 / 破折号 / 完整引语）→ **只报不拦**。
  理由不是"不重要"，是**存在合理例外**（「该」作动词、「因此」口语里也说）。
  硬拦会变成恒红闸门，人就开始绕过去——**恒红的闸门等于没有闸门**（本仓 2026-08 教训）。
  软提醒的定位是：把可疑句子连镜号带原句摆到人眼前，判还是人判。

## 用法

```bash
# 微电影/字卡线：查 shots.json（v1 的 shots / v3 的 beats 都认）
python3 check_narration.py --shots <workdir>/shots.json
# 轮播放映线：查分页口播稿（Markdown 的 ## P1 分页，或 JSON 数组）
python3 check_narration.py --script-file narration.md
# 单条速查
python3 check_narration.py --text "这一镜的旁白……" --label P03
```

stdout = 纯 JSON（可被别的脚本消费），stderr = 人读的明细。
exit 0 = 硬闸门过（可能带 warn）｜exit 1 = 有镜超字数｜exit 2 = 输入/文件错误。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HARD_LIMIT = 100
"""§九：每页/每镜 ≤100 汉字。⚠️ 别顺手收到 92——§九 已裁决过：收到 92 会在密图页逼着
删限定句，与第十一律「限定永远最后动」正面冲突，闸门体系内部不能自打架。"""

HANZI = re.compile(r"[一-龥]")
"""数**汉字**，不是 len(str)：标点、英文、数字都不该计入（§九 的口径就是汉字数）。"""


# ---------- 软提醒规则（十四律里可枚举的三条） ----------

# 第三律：⛔ 书面连接词：不但／而且／既能／又能／综上／因此／其中／该（做代词用）
WRITTEN_CONNECTIVES = ["不但", "而且", "既能", "又能", "综上", "因此", "其中"]

# 「该」单列：第三律限定的是「该（做代词用）」，作动词/助动词的「该」是正常口语，必须放行。
# ⛔ 见「该」就叫 = 见字就叫的闸门，会把「该睡了」「你不该这么想」全报成违规。
GAI_VERBAL_PREFIX = "应不就活早本也都还才真可正倒"
"""这些字打头的「该」是助动词用法：应该/不该/就该/活该/早该/本该/也该/还该/才该…"""
GAI_VERBAL_NEXT = set("干去走做说来回睡吃怎什知想听看问叫让给拿放试改停走留写读练打买用管")
"""「该」后面跟这些字是动词/疑问用法：该干嘛/该去了/该怎么办/该知道…"""

DASH = "——"
"""第五律：破折号禁用（TTS 当停顿念、字幕层已不显示，两头不讨好）。
⚠️ 规范原文是「一律改逗号/句号/冒号」，**没有写任何例外**，所以本检查不做上下文豁免。
它是 warn 不是闸门——真有例外，人看一眼放过即可，不会卡住产线。"""

QUOTE = re.compile(r"「([^」]*)」")
"""第八律：禁直接引语，一律转述。
⚠️ 例外来自 §三 的实测：**单字引号（`「不」`）不触发 TTS 角色扮演**，所以只报 ≥2 字的完整引语。"""


def hanzi_count(text: str) -> int:
    return len(HANZI.findall(text or ""))


def _gai_is_pronoun(text: str, i: int) -> bool:
    """判断 text[i] 这个「该」是不是第三律禁的代词用法。

    放行（返回 False）：应该/不该/该干嘛/该怎么办 这类动词、助动词用法。
    拦下（返回 True）：该机构/该研究/该患者 这类「该+名词」的书面代词用法。
    """
    prev = text[i - 1] if i > 0 else ""
    # ⚠️ 必须先判 prev 非空：`"" in "任意字符串"` 恒为 True，漏了这一步
    # 句首的「该机构」会被静默放行（写这行时实测栽过，靠证伪测试才抓到）。
    if prev and prev in GAI_VERBAL_PREFIX:
        return False
    nxt = text[i + 1] if i + 1 < len(text) else ""
    if nxt in GAI_VERBAL_NEXT or not nxt:
        return False
    return True


def soft_findings(text: str) -> list[dict]:
    """十四律软提醒：返回 [{rule, 律, hit, why}]。⛔ 调用方不许据此 exit 1。"""
    out: list[dict] = []
    for w in WRITTEN_CONNECTIVES:
        if w in text:
            out.append({"rule": "书面连接词", "law": "第三律", "hit": w,
                        "why": f"⛔ 书面连接词「{w}」；口语衔接改用 所以说／你发现没／说白了／但问题是／更要命的是"})
    for m in re.finditer("该", text):
        if _gai_is_pronoun(text, m.start()):
            out.append({"rule": "书面连接词", "law": "第三律", "hit": "该",
                        "why": "「该」疑似作代词用（该机构/该研究）；作动词（该睡了/不该这样）不算违规，请人判"})
            break      # 同一镜报一次就够，不刷屏
    if DASH in text:
        out.append({"rule": "破折号", "law": "第五律", "hit": DASH,
                    "why": "破折号禁用：TTS 当停顿念、字幕层已不显示，两头不讨好；改逗号/句号/冒号"})
    for m in QUOTE.finditer(text):
        if hanzi_count(m.group(1)) >= 2:
            out.append({"rule": "完整引语", "law": "第八律", "hit": m.group(0),
                        "why": "完整引语会触发 TTS 角色扮演，一律转述掉；单字引号（「不」）不触发、不算违规"})
    return out


def check(items: list[tuple[str, str]], *, limit: int = HARD_LIMIT,
          warn: bool = True) -> dict:
    """items = [(镜号标签, 旁白原文)]。返回结构化结果，不负责退出码。"""
    shots, over, warns = [], [], []
    for label, text in items:
        n = hanzi_count(text)
        rec = {"label": label, "hanzi": n, "over": max(0, n - limit)}
        shots.append(rec)
        if n > limit:
            over.append({**rec, "text": text})
        if warn:
            for f in soft_findings(text):
                warns.append({"label": label, **f,
                              "sentence": _sentence_of(text, f["hit"])})
    return {"ok": not over, "limit": limit, "shots": shots,
            "over": over, "warnings": warns,
            "total_hanzi": sum(s["hanzi"] for s in shots)}


def _sentence_of(text: str, hit: str) -> str:
    """把命中处所在的那一句摘出来——报"哪个词"没用，得让人看见原句才判得动。"""
    i = text.find(hit[0] if hit == "该" else hit)
    if i < 0:
        return text[:40]
    left = max((text.rfind(p, 0, i) for p in "。！？；\n"), default=-1)
    right = min((r for r in (text.find(p, i) for p in "。！？；\n") if r >= 0), default=len(text))
    return text[left + 1:right + 1].strip() or text[:40]


# ---------- 输入解析 ----------

def from_shots(path: Path) -> list[tuple[str, str]]:
    """shots.json → [(镜号, 旁白)]。v1 的 `shots` 与 v3 的 `beats` 同构，两者都认
    （与 build_manifest.py 同一套读法，⛔ 别在这里长出第二种解析）。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    shots = data.get("shots") or data.get("beats") or []
    if not shots:
        raise RuntimeError(f"{path} 里 shots/beats 为空")
    out = []
    for i, s in enumerate(shots):
        label = f"第{s.get('index', i + 1)}镜"
        out.append((label, (s.get("narration_text") or "").strip()))
    return out


def from_script(path: Path) -> list[tuple[str, str]]:
    """分页口播稿 → [(页号, 文本)]。解析复用 slideshow_video._parse_script（唯一真源）。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import slideshow_video
    return [(f"P{i + 1:02d}", t) for i, t in enumerate(slideshow_video._parse_script(path))]


def _err(m: str) -> None:
    print(m, file=sys.stderr, flush=True)


def report(res: dict) -> None:
    """人读的明细打 stderr。超字数的一定报清楚：哪一镜、多少字、超了多少。"""
    for s in res["shots"]:
        mark = "❌" if s["over"] else "✅"
        tail = f"，超 {s['over']} 字" if s["over"] else ""
        _err(f"  {mark} {s['label']}：{s['hanzi']} 汉字（上限 {res['limit']}）{tail}")
    if res["warnings"]:
        _err(f"\n⚠️ 十四律软提醒 {len(res['warnings'])} 处（**只提醒不拦**，人判）：")
        for w in res["warnings"]:
            _err(f"  · {w['label']} [{w['law']}·{w['rule']}] 命中「{w['hit']}」——{w['why']}")
            _err(f"    原句：{w['sentence']}")
    if not res["ok"]:
        _err(f"\n⛔ 拒跑：{len(res['over'])} 镜超过 {res['limit']} 汉字。")
        _err("处置按 narration-spec 第十一律的删除次序：**修辞 → 场景 → 例子**，")
        _err("限定句（反向事实、样本量、时间范围）永远最后一个动，动不了就砍整页。")


def main() -> None:
    p = argparse.ArgumentParser(
        description="口播稿闸门：硬卡 ≤100 汉字/镜，软提醒十四律可枚举项")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--shots", help="shots.json 路径（微电影/字卡线）")
    g.add_argument("--script-file", help="分页口播稿（轮播放映线，md 或 json）")
    g.add_argument("--text", help="单条旁白直接查")
    p.add_argument("--label", default="单条", help="配合 --text 的标签")
    p.add_argument("--max-hanzi", type=int, default=HARD_LIMIT,
                   help=f"汉字上限（默认 {HARD_LIMIT}，来自 narration-spec §九；⛔ 别为了让稿子过而调大）")
    p.add_argument("--no-warn", action="store_true", help="关掉十四律软提醒（不影响硬闸门）")
    a = p.parse_args()

    try:
        if a.shots:
            items = from_shots(Path(a.shots))
        elif a.script_file:
            items = from_script(Path(a.script_file))
        else:
            items = [(a.label, a.text)]
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        _err(f"⛔ 读不到口播稿：{e}")
        sys.exit(2)

    res = check(items, limit=a.max_hanzi, warn=not a.no_warn)
    report(res)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    sys.exit(0 if res["ok"] else 1)


if __name__ == "__main__":
    main()
