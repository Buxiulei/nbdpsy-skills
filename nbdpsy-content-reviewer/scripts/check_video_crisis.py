#!/usr/bin/env python3
"""判-6（片尾危机声明）的确定性量具：**声明在不在** + **豁免有没有可核的证据**。

    python3 check_video_crisis.py --workdir <视频工作目录>
    python3 check_video_crisis.py --workdir <dir> --exempt-quote "要不要等，只有你能答"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 **本脚本不判"这条片该不该有声明"**——那是语义判断，判据在 `checklist-video.md` 判-6a/6b。
   它只做两件确定性的事：
     ① 声明**在不在**口播稿里（两种数字写法都认）；
     ② 走豁免时，人引的那句**处置权句是不是真在口播稿里**。
   ⇒ **语义判断留给人，「人说的话是否属实」变成确定性检查。**
   这样脚本永远不冤枉人（它不会说"你这条不该豁免"），但**豁免必须留下可核的证据**。

🩸 **三个量具坑，全是 2026-08-22 定判-6 那天实撞的，本脚本逐个绕开**：

1. **中文数字写法**：`oneline-qiuqiu-chiyao` / `jianyao` 两条**涉药片**被 `grep "12356"` 判成
   "没有声明"，实际声明完整存在——口播稿写的是「号码是**一二三五六**」
   （TTS 要念出来，写阿拉伯数字会念成"一万两千三百五十六"）。
   ⇒ 两种写法都认。**照那个假缺失去补，会给一条合规片补出重复声明。**

2. **⛔ 不许 rglob 全目录**：`grep -rl "12356" brand-haohaoshenghuo/` 命中的是
   **`render_card.py`**——工作目录里拷的**脚本源码常量**，⛔ 不是那条片的内容；
   `slideshow-h1` 命中的是 `post-video.md`（**笔记正文**，视频口播里并没有）。
   一次全目录 grep 把 **12 条**片子误判成"有声明"。
   ⇒ 只读**明确列举的口播稿来源**（见 `NARRATION_SOURCES`）。

3. **「量不出来」≠「没有」**：找不到口播稿时退 **2**（量不出），⛔ 不退 1（没声明）。
   `benchmark-*`（对标样本，别人的片）就属于这一类；放映线的声明可能**烧在图上**，
   文本量具本来就够不着。**报「没有」会让人去给一条其实合规的片子补声明。**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

输出 JSON（stdout 只有 JSON，人话走 stderr）：
  {"verdict": "ok|needs_exemption|exempt|no_trigger|unmeasurable",
   "declaration_found": bool, "source": "<读的哪个文件>", "triggers": [...],
   "exempt_quote_found": bool|null, "ok": bool}

exit：
  0 = 判-6 这一关过了（有声明 / 豁免有据 / 未命中触发词）
  1 = **命中 6-a 触发词却没有声明，且没给可核的豁免依据** → 按 blocker 处置
  2 = **量不出来**（找不到口播稿）——⛔ 这不是"没有声明"，别照它去补
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ── 声明的两种写法 ──────────────────────────────────────────────────────────
# 字幕层通常是阿拉伯数字，口播稿是中文数字；**同一条片子两处写法可能不同**。
HOTLINE_PATTERNS = ("12356", "一二三五六", "幺二三五六")

# ⛔ 12356 不得标「24 小时」（官方口径每日 ≥18 小时）；全仓唯一可标 24 小时的是 010-82951332。
# 判据与 `nbdpsy-xiaohongshu-creator/scripts/compliance_core.py` 同源思路：不拿逗号当边界，
# 因为违规写法「12356（全国心理援助热线，24 小时）」正是靠逗号连接的。
H24 = re.compile(r"24\s*小时|二十四\s*小时")
SAFE_24H_NUMBER = re.compile(r"010-?\s*82951332")

# ── 6-a 触发词（**高召回**，宁可多判"要人看一眼"，⛔ 不做终判）────────────────
# ⚠️ 词表**判不出"提及"与"指向观众"的区别**：实测「创伤后应激」在 **7 条 brand 品牌片**
#    里全部命中——因为「聊创伤」这类账号在**自我介绍**时会说自己聊什么。
#    ⇒ 所以命中只产生 `needs_exemption`（要人给依据），⛔ 不直接判 FAIL。
TRIGGERS = {
    "诊断名词": ["抑郁症", "抑郁", "焦虑症", "双相", "躁郁", "PTSD", "CPTSD", "创伤后应激",
                 "强迫症", "进食障碍", "人格障碍", "精神分裂", "ADHD", "多动症",
                 "阿斯伯格", "惊恐发作", "解离", "依恋障碍", "心理障碍", "精神疾病"],
    "用药就医": ["吃药", "服药", "停药", "减药", "处方", "精神科", "复诊", "住院",
                 "剂量", "抗抑郁", "病历", "确诊", "诊断"],
    # ⚠️ 一律用「伤害自己」而非「伤害」：后者会命中「亲近曾经和伤害绑在一起」这种
    #    讲依恋机制的正常句子（`xigao-collage-01/script-2` 实测）。
    #    **词边界是必要条件，⛔ 不是充分条件。**
    "自伤自杀": ["自伤", "自残", "自杀", "轻生", "伤害自己", "活不下去", "不想活", "了结自己"],
    # 判-6a 点名的句式：「你身上这件事**有个名字**」——给标签的典型形状
    "命名句式": ["有个名字", "有一个名字", "这就是所谓"],
}

# ── 口播稿来源（**显式列举，⛔ 不 rglob 全目录**，见文件头坑 2）──────────────
#: (glob, 怎么取文本)。按顺序找，先命中先用。
NARRATION_SOURCES = (
    ("narration.txt", "text"),
    ("narration-v*.txt", "text"),
    ("script-*.txt", "text"),
    ("*/narration.txt", "text"),
    ("narration.mp3.cues.json", "cues"),
    ("*/narration.mp3.cues.json", "cues"),
    ("*.cues.json", "cues"),
    ("*/*.cues.json", "cues"),
    ("shots.json", "shots"),
)


def _from_cues(raw: str) -> str:
    data = json.loads(raw)
    cues = data.get("cues", data) if isinstance(data, dict) else data
    if not isinstance(cues, list):
        raise ValueError("cues 不是数组")
    return "\n".join(str(c.get("text", "")) for c in cues if isinstance(c, dict))


def _from_shots(raw: str) -> str:
    data = json.loads(raw)
    shots = data.get("shots", data) if isinstance(data, dict) else data
    if not isinstance(shots, list):
        raise ValueError("shots 不是数组")
    return "\n".join(str(s.get("narration_text", "")) for s in shots if isinstance(s, dict))


def read_narration(workdir: Path):
    """找口播稿并读出纯文本。返回 (来源文件, 文本)；一个都找不到 → (None, "")。

    ⚠️ 同一 glob 命中多个文件时**全部合并**（洗稿线 `script-1..4.txt` 是一条片的四段，
    只读第一段会把后面三段里的声明漏掉）。"""
    for pattern, kind in NARRATION_SOURCES:
        files = sorted(workdir.glob(pattern))
        if not files:
            continue
        texts, used = [], []
        for f in files:
            try:
                raw = f.read_text(encoding="utf-8", errors="ignore")
                texts.append(raw if kind == "text"
                             else _from_cues(raw) if kind == "cues" else _from_shots(raw))
                used.append(str(f.relative_to(workdir)))
            except Exception:
                continue          # 单个文件坏了不影响同批其它文件
        if texts:
            return ("、".join(used), "\n".join(texts))
    return (None, "")


def find_triggers(text: str) -> list:
    return [f"{group}:{w}" for group, words in TRIGGERS.items()
            for w in words if w in text]


def has_declaration(text: str) -> bool:
    return any(p in text for p in HOTLINE_PATTERNS)


def h24_violation(text: str) -> bool:
    """12356 被标了「24 小时」。⛔ 别误伤标准声明「…12356，或…010-82951332（24 小时）」
    ——那里的 24 小时归 010，所以整句里出现安全号码时不判。"""
    if not H24.search(text):
        return False
    return not SAFE_24H_NUMBER.search(text)


#: 比对「处置权句」时要抹掉的标点（**全角与半角成对收齐**）。
#: ⛔ 别写成正则字符类：里面同时要放中文引号和英文引号，转义在这一处炸过一次。
_PUNCT = set("，。、！？；：（）【】〔〕—－·…「」『』" + '“”‘’' + ",.!?;:()[]-" + '"' + "'")


def normalize(s: str) -> str:
    """比对「处置权句」时抹掉空白与标点差异——⚠️ 人从成片里抄那句话时，
    标点/换行几乎不可能与口播稿一字不差，拿原始串比会**恒红**，
    而恒红的闸门只会逼人把引文改成假的去凑。

    🩸 **全角/半角必须一起抹**（变异测试当场抓到）：首版字符类里只有全角「，」，
    人从成片抄那句话时输入法出了个**半角逗号**就判不匹配 —— 而报出来的红是
    「你引的句子不在正文里」，照它去查会以为**引错了句子**，实际只差一个标点的宽窄。
    ⚠️ 又一次「响错理由」。"""
    return "".join(c for c in s if not c.isspace() and c not in _PUNCT)


def check(workdir: Path, exempt_quote=None) -> dict:
    source, text = read_narration(workdir)
    if source is None:
        return {"verdict": "unmeasurable", "declaration_found": None, "source": None,
                "triggers": [], "exempt_quote_found": None, "ok": None,
                "reason": "没找到口播稿（narration*.txt / *.cues.json / shots.json）——"
                          "⛔ 这是「量不出来」不是「没有声明」，别照它去补声明。"
                          "放映线的声明可能烧在图上，对标样本本来就没有我们的口播稿"}
    declared = has_declaration(text)
    triggers = find_triggers(text)
    out = {"source": source, "declaration_found": declared, "triggers": triggers,
           "exempt_quote_found": None}
    if declared and h24_violation(text):
        return {**out, "verdict": "h24_violation", "ok": False,
                "reason": "🔴 12356 被标注了「24 小时」——官方口径是每日 ≥18 小时，"
                          "深夜照着打不通且手里没有备选号码。全仓唯一可标 24 小时的是 010-82951332"}
    if declared:
        return {**out, "verdict": "ok", "ok": True, "reason": "声明在位"}
    if exempt_quote:
        found = normalize(exempt_quote) in normalize(text)
        out["exempt_quote_found"] = found
        if found:
            return {**out, "verdict": "exempt", "ok": True,
                    "reason": f"走 6-b 豁免，处置权句已在口播稿里核到：「{exempt_quote}」"}
        return {**out, "verdict": "exempt_quote_missing", "ok": False,
                "reason": f"🔴 你引的处置权句**不在口播稿里**：「{exempt_quote}」——"
                          f"6-b 豁免要求正文真有那句把处置权交回观众的话。"
                          f"⛔ 引一句片子里没有的话，豁免不成立"}
    if triggers:
        return {**out, "verdict": "needs_exemption", "ok": False,
                "reason": "🔴 命中 6-a 触发词却没有危机声明，且没给豁免依据。"
                          "要么补声明，要么按 6-b 传 --exempt-quote「<把处置权交回观众的那句原话>」。"
                          "⚠️ 命中触发词**不等于**必须有声明（品牌片自我介绍时提到"
                          "「创伤后应激」也会命中）——但豁免要留下可核的证据"}
    return {**out, "verdict": "no_trigger", "ok": True,
            "reason": "没有声明，也没命中 6-a 触发词。⚠️ 词表是高召回不是全覆盖，"
                      "**仍要按 6-b 人工判一遍**（脚本过了不等于判-6 过了）"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="判-6 片尾危机声明的确定性量具")
    ap.add_argument("--workdir", required=True, help="视频工作目录")
    ap.add_argument("--exempt-quote", help='走 6-b 豁免时，把"处置权交回观众"的那句**原话**')
    a = ap.parse_args(argv)
    wd = Path(a.workdir)
    if not wd.is_dir():
        print(json.dumps({"verdict": "unmeasurable", "ok": None,
                          "reason": f"目录不存在：{wd}"}, ensure_ascii=False))
        return 2
    res = check(wd, a.exempt_quote)
    print(json.dumps(res, ensure_ascii=False))
    print(f"  [{res['verdict']}] {res['reason']}", file=sys.stderr)
    if res.get("source"):
        print(f"  口播稿取自：{res['source']}", file=sys.stderr)
    if res["verdict"] == "unmeasurable":
        return 2
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
