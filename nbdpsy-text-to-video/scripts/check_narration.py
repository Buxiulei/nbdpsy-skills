#!/usr/bin/env python3
"""口播稿闸门 —— 硬卡字数，软提醒十四律里**可枚举**的那几条。

## 为什么有这个脚本

`references/narration-spec.md` §九 把「每页/每镜 ≤100 汉字」定成**唯一的硬闸门**，
但 2026-08-17 体检发现：**全仓没有任何脚本读它**。SKILL.md 写了「定稿前必须走完审校
流程」，可没有任何东西能抓出漏做——老板原话是「不能是一个死链，永远闲置不被调用」。

§九 自称「脚本层管不了长度」。**这句只对了一半**：管不了的是**秒数**（同引擎同音色
页间语速仍浮动 20%，99 字落在慢页 27 秒、快页 22 秒），但**字数**本身 `len()` 就能判，
而 §九 的闸门本来就定在字数上。所以这个闸门是能落到脚本里的，落在这里。

## 🩸 100 是**合成阶段**的闸门，⛔ 不是写稿阶段的字数目标

它拦的是「**这一页念不完**」这个物理事实（页面停留时间，有 H1 九页语速实测背书），
⛔ 拦的不是「这件事说太多」。**写稿阶段只给内容判据（narration-spec §八 结构骨架 ＋
§一 十四律），⛔ 不给这个数**——先算字数再想说什么，写出来的是"排得下的短句"，
不是把事说清楚的话。超了在这里**拆页**，⛔ 不是砍内容。

> **页数变多是可以的；为了少几页而把话说半截，不可以。**

（口径与 tpl-oneline 的「12 字是排版量具不是写稿上限」同源；两处都是我们按老板
2026-08-17「不要为了缩减字数而刻意删减，把事情说清楚才是第一位」推的，⛔ 不是他逐条点的。）

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
# 附结构自证（§八 骨架三段；三值必须是成稿里的**逐字原句**）
python3 check_narration.py --script-file narration.md --intent-file intent.json
```

stdout = 纯 JSON（可被别的脚本消费），stderr = 人读的明细。
exit 0 = 硬闸门过（可能带 warn）｜exit 1 = 有镜超字数**或结构自证不过**｜exit 2 = 输入/文件错误。

⚠️ 不传 `--intent-file` 时，输出 JSON 里**没有 `intent` 键**，stderr 明写「未做结构自证」。
⛔ 别把它读成「自证通过」——**「没做」与「做了没问题」在本仓必须分得开**（同 `hero_fill_min`
在竖版恒 `null` 而非 `False` 的口径：`False` 会被读成"判过了没问题"）。
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
          warn: bool = True, allow_empty: bool = False) -> dict:
    """items = [(镜号标签, 旁白原文)]。返回结构化结果，不负责退出码。

    🩸 **三态，不是两态**（2026-08-17 补）：命中超标 / 确认没超标 / **根本没读到口播**。
    第三态必须与第二态分开——字段名一改（`narration_text` → 别的）或 shots.json 结构一漂，
    每镜都读成空串 ⇒ 全算 0 汉字 ⇒ **全部放行**，闸门恒绿且一声不吭。
    实测过：两镜各 300 字、字段名写成 `narration`，旧版判 `ok=True` 全放行。
    ⛔ 「没找到」不许冒充「没超标」。真是一条无口播的片子，显式传 `allow_empty`。
    """
    shots, over, warns, got_text = [], [], [], False
    for label, text in items:
        n = hanzi_count(text)
        rec = {"label": label, "hanzi": n,
               "over": 0 if limit is None else max(0, n - limit)}
        shots.append(rec)
        if (text or "").strip():
            got_text = True
        if limit is not None and n > limit:
            over.append({**rec, "text": text})
        if warn:
            for f in soft_findings(text):
                warns.append({"label": label, **f,
                              "sentence": _sentence_of(text, f["hit"])})
    # ⚠️ 判「有没有读到」看**原串是否为空**，⛔ 不看汉字数是否为 0——
    # 「n1」「TODO」这类非汉字文案是读到了、只是 0 汉字，合法通过。
    # 拿汉字数当判据会把它们误报成观测失败（写这行时实测栽过，靠既有测试抓到）。
    # 单镜空是合法的（无旁白镜靠 subtitle 兜底）；**全镜皆空**才是观测失败的信号。
    blind = bool(shots) and not got_text and not allow_empty
    return {"ok": (not over) and not blind, "limit": limit, "shots": shots,
            "over": over, "warnings": warns, "blind": blind,
            "total_hanzi": sum(s["hanzi"] for s in shots)}


# ---------- 结构自证（§八 骨架三段，写完稿回头粘原句） ----------

INTENT_KEYS = ("hook", "scene", "closing")
"""§八 结构骨架三段，与 content-reviewer `checklist-video.md` 判-9 同一组判据。

## 为什么是「粘原句」而不是「答一句话」

2026-08-17 实证（博客长文线自陈）：**规格里"能拿来跑通一件事"的部分（参数、命令、
阈值）会被精准读取；"指导判断"的部分（十条、结构骨架）不会**——因为它不阻塞任何一步，
不读也能交差。同一天该线写三稿，`narration-spec` 上墙十条**一次没读**，
却把「12 字」实现成了量字脚本——**因为 12 字是个可执行的数**。

⇒ 让判断类规范获得同样的质地，唯一的办法是**让答案可被机器比对**：
- ⛔ 「钩子是开头那个反直觉的说法」——描述，无法比对，随手写一句就过了；
- ⭕ 「钩子＝『对自己好一点，压根不是放过自己』」——**原句，脚本能直接查它在不在稿里、是不是第一句**。

副作用是好的：**要求粘原句会逼写手写完后真的回去找那一句；找不到＝他没写钩子。
这一步本身就是审查**，比问「你写钩子了吗」强得多（后者会得到真诚的、且是错的回答）。

## ⭕ 一个设计时没预料到的能力：它还拦「串篇」

2026-08-18 实测：某线连着写四篇的 intent，**在 B 篇的 intent 里填了 C 篇的句子**，
闸门当场 `EXIT=1`「scene：这句不在稿里」。

⇒ **逐字比对顺带验了「我是不是在对着这篇稿说话」**——⛔ 不只是「有没有写钩子」。
**串行写多份时张冠李戴**是高发错（人写第三份时脑子里还是第二份），而它必然对不上。
**这条写下来是因为它不写就没人知道**：看见闸门名字只会以为它管结构骨架。

## 🩸 它的射程：只验「有没有」，⛔ 验不了「好不好」

同日实证：某 81 屏稿钩子/场景/收尾**三样俱全**、逐条都能过，仍被判不合格——
真因是**句子被切碎**，那是三问照不到的地方。**⛔ 别指望它治"读起来不通顺"，
也别因为它没治好就去加第四问第五问——那就真变成填表了。**
"""


def _norm(s: str) -> str:
    """比对前只去空白（含换行）。⛔ 不去标点——要求粘的是原句，标点是原句的一部分；
    连标点都对不上，说明粘的时候改了字，那正是该报出来的事。"""
    return re.sub(r"\s+", "", s or "")


def _sentence_span(s: str) -> int:
    """声明值里含几个句子（末尾那个句末标点不算跨句）。⚠️ 只数 。！？——
    逗号在口播里是停顿不是句界，数进来会把正常的一句报成跨句。"""
    return len(re.findall(r"[。！？]", (s or "").strip().rstrip("。！？"))) + 1


def _depunct(s: str) -> str:
    """只用于**失败后的二次定位**：去掉标点再比一次，好把「压根没写」与「写了但粘歪了」
    分开报。⛔ 不能拿它当主判据——那等于默许凭记忆敲一句近似的就过闸。"""
    return re.sub(r"[^\w]", "", _norm(s), flags=re.UNICODE)


def check_intent(items: list[tuple[str, str]], intent: dict) -> dict:
    """比对结构自证。items = [(标签, 文本)]，intent = {hook/scene/closing: 原句}。

    位置判据：hook 在前 2 项内、closing 在后 3 项内、scene 不限位置（中段道理的载体，
    落在哪一镜都合法）。⚠️ **项数 < 5 时不判位置**——前 2 与后 3 会重叠，
    判了就是恒真/恒假，属于本仓「恒报红的闸门等于没报」的同族。
    """
    n = len(items)
    judge_pos = n >= 5
    out = {"provided": True, "judge_position": judge_pos, "items_count": n, "fail": []}
    for key in INTENT_KEYS:
        raw = (intent.get(key) or "").strip()
        if not raw:
            out[key] = {"declared": False}
            out["fail"].append(f"{key}：未声明")
            continue
        needle = _norm(raw)
        at = next((lb for lb, tx in items if needle and needle in _norm(tx)), None)
        rec = {"declared": True, "text": raw, "found": at is not None, "at": at}
        if at is None:
            # 严格没中就再宽松比一次（去标点），把「压根没写」与「写了但粘歪了」分开报。
            # ⚠️ 不分开的话报错只有一句「不在稿里」，写手会以为自己漏写，**转头去补一句**——
            # 那就写重了。报错的精度直接决定人会不会走错路。
            loose = _depunct(raw)
            near = next((lb for lb, tx in items if loose and loose in _depunct(tx)), None)
            rec["near"] = near
            spans = _sentence_span(raw)
            rec["sentences"] = spans
            if near is not None:
                out["fail"].append(
                    f"{key}：{near} 里有这句，但字面对不上（多半是标点）——从成稿原样复制")
            elif spans > 1:
                # 🔴 第三种失败：值跨了多句。此前它和「稿里真没有」共用一句报错，
                # 实测（2026-08-17 需求方）第一反应是「脚本坏了」——**而那个反应会让人
                # 去改脚本或绕过闸门**。跨句在任何模式下都必然找不到（比对按单条做），
                # 所以这条提示放在通用路径上，⛔ 不分模式。
                out["fail"].append(
                    f"{key}：你给的值含 {spans} 个句子。比对是按**单条**（句/页/镜）做的，"
                    f"跨条的文本必然找不到——请只粘其中一句")
            else:
                out["fail"].append(f"{key}：这句不在稿里")
        elif judge_pos:
            idx = [lb for lb, _ in items].index(at)
            ok = idx < 2 if key == "hook" else (idx >= n - 3 if key == "closing" else True)
            rec["position_ok"] = ok
            if not ok:
                where = "前 2 项内" if key == "hook" else "后 3 项内"
                out["fail"].append(f"{key}：在 {at}，不在{where}")
        out[key] = rec
    out["ok"] = not out["fail"]
    return out


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


SENT_END = re.compile(r"(?<=[。！？])")
"""连续稿切句：只认句末三标点。⛔ 不切逗号——第五律已把破折号赶走、逗号在口播里是停顿
不是句界，按逗号切会把一句话拆成半句，`closing 在后 3 句内` 这类位置判据立刻失真。"""


def from_continuous(path: Path) -> list[tuple[str, str]]:
    """连续稿（不分页的一整篇口播）→ [(第N句, 句子)]。

    ## 为什么要有这个入口

    2026-08-17 实测（博客长文线）：**oneline 线的稿子两种模式都跑不了**——
    `--script-file` 要 `## P1` 页标题（连续稿没有），`--text` 把整篇当一镜必爆 100 字上限。
    根因是形态不匹配：**分页形态（轮播/微电影）一页一镜，oneline 是一整篇连续文本**，
    分屏是 `build_oneline.py` 事后按 TTS cues 自动断的，**写稿阶段根本没有"页"**。

    🔴 **⛔ 别用"硬拆成页"糊弄过去**：oneline 若按屏分页每页 ≤12 字，
    `≤100 汉字/镜` 这道闸**全过**——闸在，但对这条线**恒绿**。
    本仓判据：**恒绿的闸门比没有闸门更糟**，它会让人以为查过了。
    ⇒ 所以连续模式**显式关掉字数硬闸**（`limit=None`），⛔ 不是把它调大到永远不会触发。
    """
    text = path.read_text(encoding="utf-8")
    # 去掉 markdown 标题行与注释行：它们不是口播内容，混进来会污染句序与位置判据
    body = "\n".join(ln for ln in text.splitlines()
                     if not ln.lstrip().startswith(("#", "<!--", ">")))
    sents = [s.strip() for s in SENT_END.split(body) if s.strip()]
    if not sents:
        raise RuntimeError(f"{path} 里没读到任何句子（连续稿要有 。！？ 断句）")
    # 🔴 切句失败会伪装成「一篇短稿」而不是报错：整篇没有句末标点时全篇算 1 句，
    # 此时三句自证都能在那唯一一句里「找到」，且项数 <5 连位置都不判 ⇒ **全过**。
    # ⛔ 这是恒绿。所以句数少到不像一篇口播稿时，显式把观测本身摆到人眼前。
    if len(sents) < 3:
        raise RuntimeError(
            f"{path} 只切出 {len(sents)} 句——**多半是断句失败**（全篇缺 。！？，"
            f"或标点用了半角 . ! ?），⛔ 不是稿子真的只有这么几句。"
            f"\n   真是一两句的短稿，用 --text 查；连续稿请先补上中文句末标点。")
    return [(f"第{i + 1}句", s) for i, s in enumerate(sents)]


def from_script(path: Path) -> list[tuple[str, str]]:
    """分页口播稿 → [(页号, 文本)]。解析复用 slideshow_video._parse_script（唯一真源）。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import slideshow_video
    return [(f"P{i + 1:02d}", t) for i, t in enumerate(slideshow_video._parse_script(path))]


def _err(m: str) -> None:
    print(m, file=sys.stderr, flush=True)


def report(res: dict) -> None:
    """人读的明细打 stderr。超字数的一定报清楚：哪一镜、多少字、超了多少。"""
    if res["limit"] is None:
        # 连续稿：逐句报字数没有意义（没有「页」这个物理约束），报规模就够。
        # ⚠️ 但必须**明写字数闸没跑**，⛔ 别让人以为「没报超标＝字数查过了」。
        _err(f"  📄 连续稿 {len(res['shots'])} 句、{res['total_hanzi']} 汉字。")
        _err("  ⛔ 本模式**不判字数**——≤100 是分页形态「这一页念不完」的闸，连续稿没有页。")
    else:
        for s in res["shots"]:
            mark = "❌" if s["over"] else "✅"
            tail = f"，超 {s['over']} 字" if s["over"] else ""
            _err(f"  {mark} {s['label']}：{s['hanzi']} 汉字（上限 {res['limit']}）{tail}")
    if res["warnings"]:
        _err(f"\n⚠️ 十四律软提醒 {len(res['warnings'])} 处（**只提醒不拦**，人判）：")
        for w in res["warnings"]:
            _err(f"  · {w['label']} [{w['law']}·{w['rule']}] 命中「{w['hit']}」——{w['why']}")
            _err(f"    原句：{w['sentence']}")
    if res.get("blind"):
        _err(f"\n🚨 观测失败：{len(res['shots'])} 镜**全部**读到 0 汉字，闸门等于没跑。")
        _err("⛔ 这不是「都没超标」，是「根本没读到口播」——最可能是字段名不是 "
             "`narration_text`，或 shots.json 结构变了。")
        _err("先核一眼字段名；确属无口播的片子，显式加 --allow-empty。")
    elif not res["ok"]:
        _err(f"\n⛔ 拒跑：{len(res['over'])} 镜超过 {res['limit']} 汉字。")
        _err("**首选处置＝拆页**：把这一镜断成两镜/两页，内容一个字不少。")
        _err("  ⚠️ 本闸门拦的是「这一页念不完」，⛔ 不是「这件事说太多」——")
        _err("  页数变多是可以的；为了少几页而把话说半截，不可以。")
        _err("拆不动（一个连贯动作/一句话拆开就断气）才动刀，按 narration-spec")
        _err("第十一律的删除次序：**修辞 → 场景 → 例子**，限定句（反向事实、样本量、")
        _err("时间范围）永远最后一个动，动不了就砍整页。")
        _err("  ⛔ 别一上来就删场景——§八「道理让场景说」，场景删光就退回念论点了。")

    it = res.get("intent")
    if not it:
        _err("\n⚠️ 本次**未做结构自证**（没传 --intent-file）——钩子/场景/收尾有没有，"
             "这一轮谁也没查。")
        _err("  ⛔ 这不是「查过了没问题」。要查：写完稿回头把三句原句粘进一个 json 传进来。")
    elif it["ok"]:
        _err(f"\n✅ 结构自证过（§八 骨架三段都在稿里"
             f"{'、位置也对' if it['judge_position'] else '；项数 <5 未判位置'}）。")
    else:
        _err(f"\n⛔ 结构自证不过（§八 骨架三段，{len(it['fail'])} 项）：")
        for f in it["fail"]:
            _err(f"  · {f}")
        _err("  两种可能，**先分清是哪一种再动手**：")
        _err("  ① 这一项你压根没写 → 去读 narration-spec §八，补上它；")
        _err("  ② 写了，但粘进来时改了字 → 从成稿里原样复制，⛔ 别凭记忆敲。")
        _err("  ⚠️ 它只验「有没有」，⛔ 验不了「好不好」——三样俱全也可能是不合格的稿。")


def main() -> None:
    p = argparse.ArgumentParser(
        description="口播稿闸门：硬卡 ≤100 汉字/镜，软提醒十四律可枚举项")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--shots", help="shots.json 路径（微电影/字卡线）")
    g.add_argument("--script-file", help="分页口播稿（轮播放映线，md 或 json）")
    g.add_argument("--continuous-file",
                   help="**不分页的一整篇口播稿**（oneline 字卡线）。按 。！？ 切句，"
                        "⛔ 关掉 ≤100 汉字硬闸（那是分页形态"
                        "「这一页念不完」的闸，连续稿没有页），保留十四律软提醒与结构自证")
    g.add_argument("--text", help="单条旁白直接查")
    p.add_argument("--label", default="单条", help="配合 --text 的标签")
    p.add_argument("--max-hanzi", type=int, default=HARD_LIMIT,
                   help=f"汉字上限（默认 {HARD_LIMIT}，来自 narration-spec §九；⛔ 别为了让稿子过而调大）")
    p.add_argument("--no-warn", action="store_true", help="关掉十四律软提醒（不影响硬闸门）")
    p.add_argument("--allow-empty", action="store_true",
                   help="确属「全片无口播」时才加；默认全镜皆空视为**观测失败**而非通过")
    p.add_argument("--intent-file",
                   help="结构自证 json：{\"hook\":\"…\",\"scene\":\"…\",\"closing\":\"…\"}，"
                        "三值都要是**成稿里的逐字原句**（脚本按字符串比对，只去空白不去标点）。"
                        "⛔ 别写描述——描述无法比对，等于没查。不传则本次不做这项检查，"
                        "输出里会明写「未自证」（⛔ 不是「自证通过」）")
    a = p.parse_args()

    limit = a.max_hanzi
    try:
        if a.shots:
            items = from_shots(Path(a.shots))
        elif a.script_file:
            items = from_script(Path(a.script_file))
        elif a.continuous_file:
            items = from_continuous(Path(a.continuous_file))
            limit = None            # 连续稿没有「页」，字数闸无意义——显式关掉，⛔ 不是调大
        else:
            items = [(a.label, a.text)]
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        _err(f"⛔ 读不到口播稿：{e}")
        sys.exit(2)

    res = check(items, limit=limit, warn=not a.no_warn, allow_empty=a.allow_empty)

    if a.intent_file:
        try:
            intent = json.loads(Path(a.intent_file).read_text(encoding="utf-8"))
        except Exception as e:
            print(json.dumps({"ok": False, "error": f"读不到 --intent-file：{e}"},
                             ensure_ascii=False))
            _err(f"⛔ 读不到结构自证文件：{e}")
            sys.exit(2)
        res["intent"] = check_intent(items, intent)
        # 声明了就得对得上：自证不过与超字数同级拦停。
        # ⛔ 不传 --intent-file 则 res 里没有 intent 键——「没做」与「做了没问题」必须分得开。
        res["ok"] = res["ok"] and res["intent"]["ok"]

    report(res)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    sys.exit(0 if res["ok"] else 1)


if __name__ == "__main__":
    main()
