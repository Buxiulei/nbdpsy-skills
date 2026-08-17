#!/usr/bin/env python3
"""用后端 gpt-image 锚点法给一篇小红书笔记出「一致性」轮播配图（经运营工具 op API）。

服务端：nbdpsy-server（mcp.nbdpsy.com）`/api/op/consistent-images`，gpt-image-2 锚点法 +
自动去水印后处理（2026-07-23 起生效，端到端回归已通过）。已知行为：出图实际 1024×1536（2:3 竖版，
非严格 3:4，小红书可直接用、feed 预览按 3:4 裁剪，重要构图勿贴上下边）；单次 prompts ≤99（超出 422）；
任务台账为进程内存（server 重启后 --job 复查 404=台账丢，生图可安全重新发起、会重新扣额度；终态留存 2h）。

一致性原理：先出 post-01 的 P1 封面过风格闸门（`--cover-only`），运营确认配色/人物/比例/图内
中文无误后，把这张 P1 当**锚点参考图**（`--anchor-url`）喂给之后**所有篇所有页**——每页独立锚定
生成，既不重画 P1 也不整批漂移，整个号调性统一。P1 未确认就批量出 = 风格跑偏后 30~70 张全废。

流程：本地解析 post-NN.md「## 配图轮播」每页提示词（判据同后端 extract_slide_prompts：行首
`### P<数字>` 定位页 + 页区间内第一个完整 ``` 围栏块）→ POST {base}/api/op/consistent-images
（不传 draft_id，后端自动开临时容器；202 拿 job_id + session_id）→ 轮询
GET {base}/api/op/drafts/{session_id}/jobs/{job_id} 到终态 → done 后逐页下载
（result.urls 顺序与提交的 prompts 对齐，相对 /uploads/… 公开免鉴权）。

两道闸门写在本脚本里（2026-08-14 起，此前都只是文档里的一句话）：
  **R4 结构闸门（跑前）**：frontmatter 必须有 `读者`（三段式）与 `故事线`、每个 `### PN` 块第一行必须有
  `**论点行**：…`（围栏之外）；再加三条写作方法论的机器判据——**术语必定义**、**禁卖方视角**
  ——缺一即**拒跑**，⛔ 不出图、不烧额度。判据见 `references/illustration-spec.md` §1-b
  （先挑版式再填点＝版式退化成填页容器，这是病根）。
  **闸门 A 生产端（跑后）**：封面页 P1 出成后**自动**落盘同名 `P01.meta.json` 产出凭证
  （job/session 直接来自服务端回执，⛔ 不再手抄），发布脚本逐张校验，无凭证拒发。
  凭证里的 `style_profile` 取 `00-overview.md` 的风格档案留痕行，也可用 `--style-profile` 显式给；
  `gates` 记这次三条方法论闸门到底走没走（发布端/审查端可核，跳过留名可追责）。

用法：
    python3 gen_images.py --note post-01.md --cover-only            # 只出 P1 封面（风格闸门第一步）
    python3 gen_images.py --note post-01.md --anchor-url <URL>      # 出该篇全部页（各页锚定同一 anchor）
    python3 gen_images.py --note post-01.md --pages 2-9 --anchor-url <URL>  # 出指定页（批量/失败页重试）
    python3 gen_images.py --note post-01.md --job <id> [--session <id>]     # 复查已入队任务并补下载
        [--images-dir DIR] [--api-base URL] [--no-wait] [--wait-timeout N] [--dry-run]
        [--skip-term-gate]   # 逃生口，默认关闭；用了凭证里记 term_gate_skipped=true

凭据：复用 NBDPSY_XHS_API_KEY（nbdpsy-server apikey，与小红书发布 / 视频同一把，接入包同一把，无需另发）；
base 用 NBDPSY_VIDEO_API_BASE（可选，默认 https://mcp.nbdpsy.com，与小红书发布/视频同服务同凭据），
均由 nbdpsy_common 三层解析；`--api-base` 可覆盖。缺凭据找管理员要「运营接入配置包」secret import。

输出契约：stdout 纯 JSON。
{"outcome": "done|partial|failed|pending|unknown", "session_id", "job_id",
 "pages": [{"page": "P1", "url": 绝对URL|null, "path": 本地路径|null, "error": null|文案}],
 "anchor_url": <cover-only 时=P1 的绝对URL，方便直接取用；否则=本次所用锚点>,
 "cover_receipt": <本次落盘的封面凭证路径；没出封面页时为 null>,
 "error", "hint", "warnings"}。
exit：done=0；partial/failed=1（hint 教「--pages 只重出失败页 + 带同一 --anchor-url」）；
pending/unknown=0（任务已入队仍在跑，hint 教 --job 复查，**绝不重发**以免重复生成/烧额度）。
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 同目录 vendored 副本
import nbdpsy_common
# 闸门 A 的判据（具名版式白名单、凭证路径）只有一份真源，在 publish_note 里——
# 出图端写凭证、发布端校验凭证，必须用同一份，⛔ 别在这里另抄一份常量。
import publish_note as pn

TERMINAL_STATUSES = {"done", "failed"}
STATE_FILE = ".gen_images_state.json"

# 页标题：行首 ### + 空白 + P<数字>（与后端 extract_slide_prompts / 配图轮播计数契约一致；
# 「## 视频参考图提示词」节用 **P1** 加粗标记，不是 ### PN，天然不会被这里匹配到）。
_PAGE_HEADING = re.compile(r"^###\s+(P\d+)\b")
# R4 结构闸门（illustration-spec §1-b）：每个 `### PN` 块的第一行 `**论点行**：…`（围栏之外），
# frontmatter 里一行 `故事线: …`。两种冒号都认（模板写半角、旧自检文案写全角，读的时候别在这上面卡人）。
_CLAIM_LINE = re.compile(r"^\s*\*\*论点行\*\*\s*[:：]\s*(.*)$")
_STORYLINE_LINE = re.compile(r"^\s*故事线\s*[:：]\s*(.+)$", re.M)
# 风格档案留痕行（00-overview.md 开头，格式见 SKILL.md「开跑前 · 读风格档案」）：
#   风格档案：图文 v3（本人档案，读取于 2026-07-28）
_TRACE_LINE = re.compile(r"^风格档案\s*[:：]\s*(.+)$", re.M)


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


def _claim_before_fence(block_lines):
    """取页块内、**绘图提示词围栏之前**的论点行内容（围栏内是喂模型的提示词，论点行在围栏外）。
    找不到 / 冒号后为空 → None。"""
    for line in block_lines:
        if line.strip().startswith(("```", "~~~")):
            break
        m = _CLAIM_LINE.match(line)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return None


def _page_text(block_lines):
    """取页块里的「页面文字」——**要画进图的字**，也就是读者真会看到的那几行。

    ⛔ 不含绘图提示词围栏（那是喂模型的，读者看不到）；⛔ 不含 `>` 引用块
    （那是"判断与理由"，按笔记自己的约定写给人看、不入图）。两种写法都认：
      `**页面文字**` 起一段 `- …` 条目；或单行式 `**页面文字**：主标题「…」；副题「…」`。
    没有这个块（别的笔记形态）→ 返回空串，术语闸门对该页天然不判（没字给读者看，无从判起）。"""
    out = []
    started = False
    for line in block_lines:
        s = line.strip()
        if not started:
            if s.startswith("**页面文字**"):
                started = True
                rest = s[len("**页面文字**"):].lstrip()
                if rest[:1] in ("：", ":"):      # 单行式：冒号后整行都是页面文字
                    out.append(rest[1:].strip())
            continue
        if s.startswith(("```", "~~~")):          # 进围栏＝页面文字块结束
            break
        if s.startswith("**"):                   # 下一个加粗小标题（**绘图提示词** 等）＝结束
            break
        if s.startswith(">"):                    # 判断与理由，不是要画进图的字
            continue
        out.append(line)
    return "\n".join(out).strip()


def extract_pages(md_text):
    """逐页提取绘图提示词、论点行与页面文字，判据同后端 extract_slide_prompts。
    与后端唯一差异：无围栏的页 prompt=None（不静默丢弃）——后端会静默跳过缺围栏页导致页序错位，
    这里保留下来交给 validate_complete 拦截并列出缺页。
    返回 [{"page": "P1", "prompt": str|None, "claim": str|None, "page_text": str}, ...]。"""
    if not md_text or not md_text.strip():
        return []
    lines = md_text.splitlines()
    heads = []
    for idx, line in enumerate(lines):
        m = _PAGE_HEADING.match(line)
        if m:
            heads.append((m.group(1), idx))
    pages = []
    for k, (label, start) in enumerate(heads):
        end = heads[k + 1][1] if k + 1 < len(heads) else len(lines)
        block = lines[start + 1:end]
        pages.append({"page": label, "prompt": _first_fenced_block(block),
                      "claim": _claim_before_fence(block), "page_text": _page_text(block)})
    return pages


def extract_storyline(md_text):
    """取 frontmatter 里的「故事线」字段（整组论证链，与「版式序列」并排）。没有 → None。"""
    m = re.match(r"^---\n(.*?)\n---", md_text or "", re.S)
    if not m:
        return None
    mm = _STORYLINE_LINE.search(m.group(1))
    return mm.group(1).strip().strip('"').strip("'") if mm else None


def validate_complete(all_pages):
    """完整性校验：至少一页，且每个 ### PN 页都有围栏提示词。缺则抛 ValueError 列出缺页。"""
    if not all_pages:
        raise ValueError("未找到任何 `### PN` 配图页——检查笔记「## 配图轮播」区块是否规范（页标题须是 ### P1 …）")
    missing = [p["page"] for p in all_pages if p["prompt"] is None]
    if missing:
        raise ValueError(
            f"以下页缺绘图提示词围栏（``` 代码块），无法出图：{', '.join(missing)}"
            "（后端会静默跳过缺围栏页导致页序错位，故在此拦截；请补全围栏后重试）")


# ---------------------------------------------------------------- 三条写作方法论 · 机器判据
# 2026-08-17 老板令：三条方法论必须**被执行**，不是**被写下**——"不要是死链，永远闲置不被调用"。
# 验收口径＝「如果下一个执行者完全不看规格，他会不会被拦住？」所以三条各自落成一道判据，
# 挂在 R4 结构闸门（出图必经）上，跟故事线/论点行同一处生效、同一种报错风格（报错给"怎么改"）。
# ⚠️ 这里**不做通用可读性扫描**：中文只有"字面难度"量表（甲乙丙丁词表），而"六个成分"四个字都简单、
#    读者照样接不住——问题在**语义脱离处境**，不在字面难度。所以判据一律**窄而准**，只挡三种具体病。

# —— 闸 1（方法论③「下笔前先钉死读者是谁」）——
_READER_LINE = re.compile(r"^\s*读者\s*[:：]\s*(.+)$", re.M)
_READER_SPLIT = re.compile(r"[｜|]")
_READER_SLOTS = ("身份阶段", "痛点", "最容易误解或焦虑的点")
_READER_MIN_CHARS = 6
# 空泛词表：这些值当"读者"用等于没定义读者。两道误伤控制，都是被真实句子逼出来的：
#   ① 只对**第 1 段（身份阶段）**判——「所有人都在评价我」这类话在痛点/焦虑点里是**读者的真实原话**；
#   ② 只在答案**短**（≤_READER_SPECIFIC_MIN 字）时判——实证：本仓黄金范例首版写
#      「刚被上级随口批评、还没跟**任何人**说起这事的 28 岁职场女性」被误拦，
#      而这恰恰是全仓最具体的一个读者定义。空泛词出现在一句长描述**里面**是正常中文，
#      只有当它**本身就是那个答案**（短到只剩这个词）时才是"没定义读者"。
_READER_VAGUE = ("所有人", "任何人", "每个人", "人人", "大众", "公众", "普通人", "广大网友",
                 "对心理感兴趣", "心理爱好者", "关注心理健康的人", "所有读者", "泛人群",
                 "通用人群", "男女老少", "不限")
_READER_SPECIFIC_MIN = 14   # 超过这个长度的身份描述，已经具体到不可能是"给谁看都行"

# —— 闸 2（方法论①「术语只能定义或删除，不许悬空」）——
# 窄而准：只放**读者不查就不懂**的真专业黑话。可增补，但每加一个都要过这一条判据；
# ⛔ 别把"情绪""焦虑""压力"这类读者自己天天说的词塞进来——那不是术语，是废话检测器误伤。
DOMAIN_TERMS = ("解离", "内感受", "述情障碍", "认知重构", "暴露疗法", "心理弹性", "共情疲劳",
                "边缘型", "双相", "躯体化", "闪回", "过度警觉", "依恋回避", "情绪粒度",
                "元认知", "接纳承诺", "图式", "投射性认同")
_DEF_PHRASES = ("就是", "指的是", "说白了", "也就是", "换句话说", "意思是")
# 术语出现在文献名/数据出处里不算"拿黑话砸读者"（那是引用，不是叙述）
_CITATION_HINTS = ("数据来源", "参考文献", "文献", "出处", "数据口径")
_DEF_WINDOW = 60          # 定义句式要紧跟术语，不能"这页某处有个冒号"就算数

# —— 闸 3（方法论②「不要从卖方/知识体系视角写」）——
_SELLER_PHRASES = ("我们提供", "我们的服务", "我们的课程", "我们的方法", "我们的咨询师",
                   "我们专注于", "我们致力于", "本文将介绍", "本篇将介绍", "本篇带你",
                   "本文带你", "这篇带你", "带你了解")
# 2026-08-17 干跑实证：纯词表挡不住同义替换（「本机构擅长处理这类困扰」「NBDpsy 的咨询师可以
# 陪你走一段」「专业心理咨询在这件事上是有用的」全部过闸）。改成**主语判据**：句子的主语是不是
# 我方——我方词 + 能力/供给动词同现即命中。判据来自方法论②：读者不关心你提供什么。
_WE_SUBJECTS = ("我们", "本机构", "本中心", "本工作室", "本平台", "NBDpsy", "nbdpsy",
                "咨询师", "心理咨询", "专业帮助", "专业支持", "本篇", "本文", "这篇")
_SUPPLY_VERBS = ("提供", "擅长", "专注", "致力", "帮你", "帮您", "能帮", "可以帮", "陪你",
                 "陪您", "介绍", "带你", "教你", "让你学会", "解决你", "为你", "替你解决",
                 "是有用的", "有帮助", "能处理", "可处理", "能改善", "服务")
# 「教你」「让你学会」前面带否定时是**读者的处境**（"没人教你怎么…"），不是卖方腔——不拦
_SELLER_GUARDED = ("教你", "让你学会")
_SELLER_NEGATION = ("没", "谁", "未", "无人", "从来", "不曾")


def extract_reader(md_text):
    """取 frontmatter 里的「读者」字段原值（三段式）。没有 → None。
    尾部 YAML 注释（`   # …`）剥掉——本仓 frontmatter 普遍在行尾挂注释，留着会被当成第三段的答案。"""
    m = re.match(r"^---\n(.*?)\n---", md_text or "", re.S)
    if not m:
        return None
    mm = _READER_LINE.search(m.group(1))
    if not mm:
        return None
    return re.split(r"\s#", mm.group(1).strip(), maxsplit=1)[0].strip().strip('"').strip("'")


def _reader_answer(seg):
    """取一段里的**答案**：`身份阶段（…）` 取括号内，没括号就去掉标签前缀取剩下的。
    （标签本身不算答案——`身份阶段（他）` 整段 6 字、答案只有 1 字，那就是没答。）"""
    m = re.search(r"[（(]([^）)]*)[）)]\s*$", seg)
    if m:
        return m.group(1).strip()
    return re.sub(r"^\s*(身份阶段|身份／阶段|身份/阶段|身份|阶段|痛点|"
                  r"最容易误解或焦虑的点|误解或焦虑的点|误解点|焦虑点)\s*[:：]?\s*", "", seg).strip()


def check_reader(md_text):
    """闸 1（方法论③）：`读者` 三段式必填——**收到写作请求不许立刻动笔**，先答三个问题。
    返回问题列表（空＝过）。"""
    tmpl = "\n      读者: 身份阶段（…）｜痛点（…）｜最容易误解或焦虑的点（…）"
    raw = extract_reader(md_text)
    if not raw:
        return ["frontmatter 缺 `读者` 字段——⛔ 收到写作请求不许立刻动笔，先答三个问题："
                "**谁会看到这篇（身份/阶段）？他最痛的是什么？他最容易误解、忽略或焦虑的点是什么？**"
                "答完抄进 frontmatter（三段用 `｜` 分隔）：" + tmpl
                + "\n      例：读者: 身份阶段（刚被上级批评、还没把这事跟任何人说的 28 岁职场女性）"
                  "｜痛点（一句话就僵住、事后反复回放，骂自己玻璃心）"
                  "｜最容易误解或焦虑的点（以为这是性格缺陷，怕被说矫情所以更晚开口）"]
    segs = [s.strip() for s in _READER_SPLIT.split(raw) if s.strip()]
    if len(segs) != 3:
        return [f"`读者` 只切出 {len(segs)} 段，须**三段**（用 `｜` 分隔）——"
                "少一段就是少答了一个决定这篇怎么写的问题：不知道他的痛点，写出来的是知识；"
                "不知道他最容易误解的点，写出来的话会被他按自己的旧解释接住。" + tmpl
                + f"\n      现有值：{raw}"]
    problems = []
    for i, seg in enumerate(segs):
        slot = _READER_SLOTS[i]
        ans = _reader_answer(seg)
        n = len(re.sub(r"\s", "", ans))
        if n < _READER_MIN_CHARS:
            problems.append(
                f"`读者` 第 {i + 1} 段（{slot}）只答了 {n} 字（须 ≥{_READER_MIN_CHARS} 字）："
                "写到能在脑子里看见一个具体的人——他在什么处境里、走到哪一步、卡在什么地方。"
                f"\n      现有值：{seg}")
            continue
        # 空泛值只判身份阶段那一段、且只在答案短到"整个答案就是这个词"时判，见 _READER_VAGUE 上方注释
        if i == 0 and n <= _READER_SPECIFIC_MIN:
            vague = [v for v in _READER_VAGUE if v in ans]
            if vague:
                problems.append(
                    f"`读者` 第 1 段（身份阶段）是空泛值「{vague[0]}」——**空泛值＝没定义读者**："
                    "读者是「所有人」，就等于你不知道谁会看到这篇，"
                    "也就无从判断哪一句会被他误解、哪一句能戳中他，写出来的必然是给谁看都行、"
                    "给谁看都不疼的通稿。"
                    "\n      改法：写清**身份 + 阶段**（他是谁 + 走到哪一步，写到能想象出一个具体的人），"
                    "例：身份阶段（刚查出 CPTSD、还没决定要不要咨询的 28 岁职场女性）。"
                    f"\n      现有值：{seg}")
    return problems


def _defined_at(text, end):
    """术语在 text[:end] 处结束，看它**后面紧跟的**有没有定义。四种句式都认：
    紧跟 `（…）` 括号解释 / 紧跟 `：…` 冒号解释 / 窗口内出现「就是·指的是·说白了·也就是·换句话说·意思是」。
    ⚠️ 窗口只有 _DEF_WINDOW 字：不许"这一页某处有个冒号"就算定义过了——那样闸门恒真＝等于没有。"""
    tail = text[end:end + _DEF_WINDOW]
    if re.match(r"^\s*[（(][^）)]{4,}[）)]", tail):
        return True
    if re.match(r"^\s*[：:]\s*\S{4,}", tail):
        return True
    return any(k in tail for k in _DEF_PHRASES)


def _checkable_page_text(page_text):
    """去掉《文献名》与出处行——术语出现在文献名/数据来源里不算悬空（误伤控制）。"""
    text = re.sub(r"《[^》]*》", " ", page_text or "")
    return "\n".join(l for l in text.splitlines()
                     if not any(h in l for h in _CITATION_HINTS))


def _prompt_visible_text(prompt):
    """从绘图提示词里取**会被画进图的那些字**——即「」/『』/引号内的内容。

    2026-08-17 干跑实证：术语闸原本只扫「页面文字」块，于是把术语全塞进围栏里
    （`标题「解离的神经机制」`）就能过闸——**但围栏里引号内的字正是图上实际出现的字**，
    读者照样要面对未定义的黑话。提示词的其余部分（画风、构图、配色）是喂模型的，不扫。"""
    if not prompt:
        return ""
    return "\n".join(re.findall(r"[「『\"“]([^」』\"”]{1,60})[」』\"”]", prompt))


def find_undefined_terms(all_pages):
    """闸 2（方法论①）：扫每页**页面文字 + 绘图提示词里引号内的图内文字**，只判**首次出现**那一页。
    返回 [(页, 术语), …]（空＝过）。⛔ 提示词里的画风/构图/配色描述不扫（那是喂模型的）。"""
    hits, seen = [], set()
    for pg in all_pages:
        text = _checkable_page_text(pg.get("page_text"))
        in_img = _checkable_page_text(_prompt_visible_text(pg.get("prompt")))
        text = (text + "\n" + in_img).strip() if in_img else text
        if not text:
            continue
        for term in DOMAIN_TERMS:
            if term in seen:
                continue
            spots = [m.start() for m in re.finditer(re.escape(term), text)]
            if not spots:
                continue
            seen.add(term)      # 只判首次出现那一页，后面几页照常用不再拦
            if not any(_defined_at(text, s + len(term)) for s in spots):
                hits.append((pg["page"], term))
    return hits


def find_seller_voice(all_pages):
    """闸 3（方法论②）：扫**论点行**与 **P1 封面文字（hero 所在块）**里的卖方腔。
    返回 [(页, 位置, 命中词), …]（空＝过）。"""
    hits = []
    for pg in all_pages:
        spots = [("论点行", pg.get("claim") or "")]
        if pg["page"] == "P1":
            spots.append(("封面页面文字（hero 所在块）", pg.get("page_text") or ""))
        for where, text in spots:
            for phrase in _SELLER_PHRASES:
                if phrase in text:
                    hits.append((pg["page"], where, phrase))
            for phrase in _SELLER_GUARDED:
                for m in re.finditer(re.escape(phrase), text):
                    lead = text[max(0, m.start() - 8):m.start()]
                    if not any(n in lead for n in _SELLER_NEGATION):
                        hits.append((pg["page"], where, phrase))
                        break
            # 主语判据（挡同义替换）：我方词 + 供给/能力动词在同一句里同现＝卖方视角。
            # 按句切分再判，避免跨句误伤（"你以为咨询师会…" 与 "我们提供…" 不是一回事）。
            for sent in re.split(r"[。！？；\n]", text):
                if any(w in sent for w in _WE_SUBJECTS) and any(v in sent for v in _SUPPLY_VERBS):
                    if any(n in sent for n in _SELLER_NEGATION):
                        continue        # "没人教你…" "谁替你解决" ＝ 读者处境，不拦
                    pair = next((f"{w}…{v}" for w in _WE_SUBJECTS if w in sent
                                 for v in _SUPPLY_VERBS if v in sent), "我方主语+供给动词")
                    if not any(h[0] == pg["page"] and h[1] == where for h in hits):
                        hits.append((pg["page"], where, pair))
                    break
    return hits


def gates_report(md_text, all_pages, skip_term_gate=False):
    """跑三条方法论闸门，返回 (gates, problems)——**不抛**。
    gates 是可证伪的凭据：reader / term / seller_view 三个布尔，进封面产出凭证，
    发布端与审查端据此核「这次到底走没走」。术语闸被 --skip-term-gate 跳过 → term=False + 记原因
    （**可追责，不是静默绕过**）。"""
    problems = []

    reader_problems = check_reader(md_text)
    problems += reader_problems

    if skip_term_gate:
        undefined = []
    else:
        undefined = find_undefined_terms(all_pages)
        if undefined:
            problems.append(
                "以下术语在页面文字里**首次出现却没给定义**："
                + "、".join(f"{p}「{t}」" for p, t in undefined)
                + "——判断句：『删掉这句，读者会少一个事实还是少一个论据？都不是，那它就是废话』。"
                  "术语只能**定义或删除**，不许悬空。两条路选一条："
                  "\n      ① **在同页加一句人话定义**：术语后面紧跟 `（…）` 或 `：…`，"
                  "或用「就是 / 指的是 / 说白了 / 换句话说」把它讲开；"
                  "\n      ② **换成读者自己会说的词**：他不会说「解离」，他会说「像是从自己身体里飘出去了」。"
                  "\n      ⛔ 逃生口 `--skip-term-gate` 默认关闭；用了会在封面凭证里记 "
                  "`term_gate_skipped=true`（可追责，不是静默绕过）。")

    seller = find_seller_voice(all_pages)
    if seller:
        problems.append(
            "以下位置是**卖方视角**："
            + "、".join(f"{p} {w}「{ph}」" for p, w, ph in seller)
            + "——用户不关心你提供什么，用户关心**我的问题有没有被看见**。"
              "论点行与封面 hero 要写**读者的处境或困惑**（他此刻正在经历什么、卡在哪里），"
              "不是我们的供给、也不是知识体系的目录。"
              "\n      改法：把「我们/本篇 + 动词」翻成读者的第一人称处境——"
              "「本篇带你了解复杂性创伤」→「一句『方案再改改』就在工位上僵住，那不是玻璃心」。")

    gates = {"reader": not reader_problems,
             "term": not (skip_term_gate or undefined),
             "seller_view": not seller}
    if skip_term_gate:
        gates["term_gate_skipped"] = True
        gates["term_gate_skip_reason"] = "--skip-term-gate（人工声明本篇术语已在别处交代或属常识）"
    return gates, problems


def gates_for_note(note, skip_term_gate=False):
    """`--job` 复查路径用：按当前稿件重跑三闸**只取结论、不拦人**（图已经出完了，拦也没用），
    结论照实写进补写的凭证。拿不到稿件 → None（凭证里 gates=null＝**没跑过**，⛔ 不等于通过）。"""
    if not note:
        return None
    try:
        md = Path(note).read_text(encoding="utf-8")
    except OSError:
        return None
    return gates_report(md, extract_pages(md), skip_term_gate)[0]


def validate_structure(md_text, all_pages, skip_term_gate=False):
    """R4 结构闸门（illustration-spec §1-b，2026-08-14 起写成代码；2026-08-17 并入三条写作方法论）：
    **frontmatter 有「读者」「故事线」+ 每页有论点行 + 术语必定义 + 禁卖方视角**，
    缺一即拒跑——这是闸门，不是提醒。跑过返回 gates（进封面凭证）。

    为什么拦在出图之前：先挑版式再填点，版式就从"表达论点的手段"退化成"填页容器"，
    图越满越云里雾里。论点行写不出＝这页不该存在，出了图也是废图（还烧额度）。
    三条方法论同理——写给"所有人"看的稿、悬空的黑话、卖方腔的 hero，出成图也是废图。
    """
    problems = []
    storyline = extract_storyline(md_text)
    if not storyline:
        problems.append(
            "frontmatter 缺 `故事线` 字段——一句话写清这一篇 6–9 页在论证什么"
            "（现象→机制→纠错→怎么办 这类推进），与 `版式序列` 并排写："
            "\n      故事线: 现象（…）→ 机制（…）→ 纠错（…）→ 怎么办（…）"
            "\n      不写会怎样：没有推进的一组图＝把几页并列的知识摞在一起，"
            "读者看完记不住任何一条（老板 2026-08-14 原话「云里雾里」就是这么来的）。")
    elif storyline.count("→") < 2 and len([x for x in re.split(r"[；;]", storyline) if x.strip()]) < 2:
        # 2026-08-17 干跑实证：只查字段在不在时，「故事线: 讲清楚解离」照样过闸——
        # 那不是故事线，是主题。**推进**至少要看得出两步（→ 或 分号分段）。
        problems.append(
            f"`故事线` 不成推进：现值「{storyline[:40]}」只是主题不是论证路径。"
            "\n      判据：至少两步推进（用 → 连接，或用分号分段），"
            "让人看得出这 6–9 页**从哪走到哪**："
            "\n      故事线: 现象（打翻常识）→ 机制（身体在干嘛）→ 纠错（错在哪）→ 怎么办（今天能做的）")
    no_claim = [p["page"] for p in all_pages if not p["claim"]]
    if no_claim:
        problems.append(
            f"以下页缺论点行：{', '.join(no_claim)}——每个 `### PN` 块的**第一行**（绘图提示词围栏之外）"
            "写 `**论点行**：这张图要让读者带走的那句话`。"
            "\n      判据：一句能独立成立的话（有主语有谓语有主张）；"
            "页标题、版式名、名词短语都不算（illustration-spec §1-b① 有三条反例）；"
            "\n      ⛔ 写不出来的页直接毙掉，不许先占位后面再想。")
    # 2026-08-17 干跑实证：只查"有没有写"时，「解离」「机制」「aaa。」「待补」全部过闸——
    # 而上面这段报错自己写着"页标题、版式名、名词短语都不算"。判据没兑现＝那三行是空话。
    # 这里只做**机器判得准**的最低门槛（成色仍归审查端）：够长 + 不是纯名词短语 + 不是占位词。
    _CLAIM_MIN = 8
    _PLACEHOLDERS = ("待补", "待定", "TODO", "todo", "占位", "xxx", "XXX", "aaa", "AAA", "同上")
    # ⚠️ 中文谓语没法用词表穷举（实测「没人教你怎么跟这种情绪相处，你只好骂自己」被误伤）。
    # 改成**反向判据**：只挡"明确像纯名词短语"的——无句内标点、无虚词、且短。三者其一不满足就放行。
    # 宁可放过也不误伤：成色本来就归审查端，闸门只负责挡住"根本没在写句子"的那几种。
    _FUNCTION_WORDS = ("是", "不", "了", "在", "会", "就", "都", "也", "还", "被", "把", "让",
                       "没", "有", "要", "能", "可以", "却", "才", "并", "而", "从", "给", "对",
                       "你", "我", "他", "她", "它", "谁", "怎么", "为什么", "多少")
    thin = []
    for p_ in all_pages:
        c = (p_.get("claim") or "").strip()
        if not c:
            continue                      # 缺失已在上面报过，不重复
        if any(ph in c for ph in _PLACEHOLDERS):
            thin.append((p_["page"], c, "是占位词，不是论点"))
        elif len(re.sub(r"[\s，。！？、：；「」（）()]", "", c)) < _CLAIM_MIN:
            thin.append((p_["page"], c, f"太短（实字 <{_CLAIM_MIN}），像标题或名词短语不像一句话"))
        elif (not re.search(r"[，。！？、；：]", c)
              and not any(w in c for w in _FUNCTION_WORDS)
              and len(c) <= 10):   # 只在**极短**时才敢判名词短语：12 字的动宾短语
                                    # （「画出解离那一刻的身体感受」）不能误伤，宁放勿伤
            thin.append((p_["page"], c, "整句无标点、无虚词且短——是名词短语不是一句话"))
    if thin:
        problems.append(
            "以下页的论点行不是「一句话」：\n      "
            + "\n      ".join(f"{pg}「{c}」——{why}" for pg, c, why in thin)
            + "\n      判据（报错里一直写着，2026-08-17 起真查）：论点行是**这张图要让读者带走的那句话**，"
            "要有主张、能独立成立；⛔ 页标题、版式名、名词短语、占位词都不算。"
            "\n      ⭕ 对照：「深呼吸是在帮倒忙」「呼吸乱掉是结果不是原因」；"
            "⛔ 反例：「解离」「解离的神经机制」「待补」。"
            "\n      ⚠️ 机器只能判到这一层（够不够长、有没有谓语）；"
            "**这句话是不是真的值得读者带走，归审查端人工判**。")
    gates, gate_problems = gates_report(md_text, all_pages, skip_term_gate)
    problems += gate_problems
    if problems:
        raise ValueError(
            "R4 结构闸门未过（缺失即拒跑，⛔ 不是提醒）：\n  - " + "\n  - ".join(problems)
            + "\n  填写顺序是硬顺序：①读者 → ②故事线 → ③逐页论点行 → ④版式序列 → ⑤按版式填点。")
    return gates


def parse_page_spec(spec, max_page=None):
    """解析 --pages：'2-9' / '3,5' / '2-4,7' 混合 / **开区间 '2-'（第 2 页到末页）**
    → 升序去重的页号列表。非法格式抛 ValueError。

    开区间是给「批量出 P2…末页、把已确认的封面 P1 排除在外」这条标准循环用的（SKILL.md 工序③）：
    批次里每篇页数不同，写死 `2-9` 会对 6 页的稿子越界报错，人一急就把 `--pages` 整个删掉
    → 封面被批量重出覆盖，恰好绕开风格闸门。所以这里必须认 `2-`。
    ⚠️ 开区间要知道本篇总页数，故 max_page 由 select_pages 传入；单独调用不给就报错，
    ⛔ 不许默认成某个页数——猜错了是静默出错页。
    """
    nums = set()
    for tok in spec.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if "-" in tok:
            a, _, b = tok.partition("-")
            a, b = a.strip(), b.strip()
            if not a.isdigit():
                raise ValueError(f"页区间格式非法：{tok!r}（应形如 2-9，或开区间 2- ＝第 2 页到末页）")
            lo = int(a)
            if b == "":                       # 开区间 N- ＝ 第 N 页到末页
                if max_page is None:
                    raise ValueError(
                        f"页区间 {tok!r} 是开区间（第 {lo} 页到末页），但此处不知道本篇总页数"
                        "——请改写成 2-9 这类闭区间")
                hi = int(max_page)
                if lo > hi:
                    raise ValueError(f"页区间 {tok!r} 的起始页超出本篇总页数（本篇共 {hi} 页）")
            elif not b.isdigit():
                raise ValueError(f"页区间格式非法：{tok!r}（应形如 2-9，或开区间 2- ＝第 2 页到末页）")
            else:
                hi = int(b)
            if lo < 1 or hi < lo:
                raise ValueError(f"页区间非法：{tok!r}（须 1 ≤ 起 ≤ 止）")
            nums.update(range(lo, hi + 1))
        else:
            if not tok.isdigit() or int(tok) < 1:
                raise ValueError(f"页号格式非法：{tok!r}")
            nums.add(int(tok))
    if not nums:
        raise ValueError("--pages 未解析出任何页")
    return sorted(nums)


def select_pages(all_pages, cover_only, spec):
    """按 --cover-only / --pages 选页，返回选中页 dict 列表（保持文档序）。
    请求了本篇不存在的页号 → 报错（防手滑选到越界页）。"""
    label_num = {p["page"]: int(p["page"][1:]) for p in all_pages}
    available = set(label_num.values())
    if cover_only:
        wanted = [1]
    elif spec:
        wanted = parse_page_spec(spec, max_page=max(available) if available else None)
    else:
        wanted = sorted(available)
    missing = [n for n in wanted if n not in available]
    if missing:
        raise ValueError(
            f"请求的页不存在：{', '.join('P' + str(n) for n in missing)}"
            f"（本篇共 {len(all_pages)} 页：{', '.join(p['page'] for p in all_pages)}）")
    wset = set(wanted)
    return [p for p in all_pages if label_num[p["page"]] in wset]


def build_warnings(selected, cover_only, anchor_url):
    w = []
    if not cover_only and len(selected) > 1 and not anchor_url:
        w.append("未带锚点参考图（--anchor-url），整套一致性无保障；正常流程应先 --cover-only 出封面过风格闸门，"
                 "运营确认后用返回的 anchor_url 再批量出图")
    if len(selected) > 10:
        w.append(f"本次 {len(selected)} 页超服务端建议上限 10 页/次，建议拆成多次 --pages 出")
    return w


def image_filename(label):
    """页 label（P1/P12）→ 落盘文件名 P01.png / P12.png（序号固定两位数，与页号对应）。"""
    return f"P{int(label[1:]):02d}.png"


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
    """建一致性生图任务（不传 draft_id，后端自动开临时容器）。返回 (job_id, session_id)。"""
    payload = {"prompts": prompts}
    if anchor_url:
        payload["anchor_url"] = anchor_url
    if len(prompts) > 99:
        raise ValueError(f"单次最多 99 条提示词（服务端硬上限，超出 422），本次 {len(prompts)} 条——用 --pages 分两次提交")
    resp = send_request("POST", f"{api_base}/api/op/consistent-images", key, payload, timeout=60)
    if resp.status_code >= 400:
        # 5xx（含 Cloudflare 530 源站不可达）：请求没入队、job_id 为 null——
        # 服务端零状态，直接重试提交是安全的，不会重复出图
        if resp.status_code >= 500:
            raise ValueError(f"{api_error(resp)}\n（HTTP {resp.status_code}：任务未入队，重试提交安全、不会重复出图）")
        raise ValueError(api_error(resp))
    data = resp.json()
    jid = data.get("job_id")
    if not jid:
        raise ValueError("服务端 200 但未返回 job_id（任务未入队）——重试提交安全、不会重复出图")
    return jid, data.get("session_id")


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


def _error_for(errors, i, page):
    """从 result.errors 里为第 i 页（label=page）找失败文案，形态宽容：
    ①与 urls 等长的消息数组（该位为空=成功）②仅失败记录的对象数组（按 index/page 匹配）
    ③按下标/页号索引的对象 ④整段字符串。找不到 → None。"""
    if not errors:
        return None
    if isinstance(errors, list):
        if i < len(errors) and isinstance(errors[i], str) and errors[i].strip():
            return errors[i]
        for e in errors:
            if isinstance(e, dict) and (e.get("index") == i or e.get("page") == page):
                return e.get("error") or e.get("message") or json.dumps(e, ensure_ascii=False)
        return None
    if isinstance(errors, dict):
        for k in (str(i), i, page):
            if k in errors and errors[k]:
                v = errors[k]
                return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
        return None
    if isinstance(errors, str):
        return errors
    return None


def download_image(url_abs, dst):
    """下载单页图（/uploads/ 公开免鉴权）。失败向上抛，由调用方记 error 不炸整体。"""
    import requests
    dst.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url_abs, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dst, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                if chunk:
                    f.write(chunk)


def finalize(view, selected_pages, images_dir, api_base):
    """把终态 view.result 的 urls/errors 映射到每页并下载。
    返回 [{"page","url","path","error"}]，与 selected_pages 对齐（第 i 个 prompt ↔ 第 i 页）。"""
    result = view.get("result") or {}
    urls = result.get("urls") or []
    errors = result.get("errors")
    out = []
    for i, pg in enumerate(selected_pages):
        label = pg["page"]
        rec = {"page": label, "url": None, "path": None, "error": None}
        u = abs_url(urls[i] if i < len(urls) else None, api_base)
        if u:
            rec["url"] = u
            dst = images_dir / image_filename(label)
            try:
                download_image(u, dst)
                rec["path"] = str(dst)
            except Exception as e:  # noqa: BLE001 — 图在服务端仍可用，--job 复查可补下
                rec["error"] = f"下载失败（图在服务端仍可用，--job 复查可补下）：{sandbox_hint(e)}"
                print(f"  ⚠ {label} {rec['error']}", file=sys.stderr)
        else:
            rec["error"] = _error_for(errors, i, label) or "服务端未返回该页图 URL（生成失败）"
            print(f"  ⚠ {label} 生成失败：{rec['error']}", file=sys.stderr)
        out.append(rec)
    return out


def summarize_outcome(pages_out):
    """有图有落盘=done；部分成功=partial；一张 URL 都没拿到=failed。"""
    have_url = [p for p in pages_out if p["url"]]
    ok = [p for p in pages_out if p["url"] and p["path"]]
    if not have_url:
        return "failed"
    return "done" if len(ok) == len(pages_out) else "partial"


def retry_hint(failed_labels, anchor_url, cover_only):
    if cover_only:
        return "封面页未出成，调提示词后重跑 --cover-only（这是风格闸门第一步，确认后再批量出）"
    nums = ",".join(str(int(l[1:])) for l in failed_labels)
    tail = f" --anchor-url {anchor_url}" if anchor_url else ""
    return f"部分页未出成，用 --pages {nums}{tail} 只重出失败页（带同一锚点保持一致性）"


def gone_envelope(sid, jid):
    """任务台账失效（server 重启，终态只留 2h）。与删除不同，生图重发是安全的（只多扣一次额度），
    故落 failed 语义引导重新发起，而非 unknown 的「勿重发」。"""
    return {"outcome": "failed", "session_id": sid, "job_id": jid, "pages": [],
            "anchor_url": None,
            "error": "任务台账已失效（server 可能重启，终态只留 2 小时）",
            "hint": "生图可安全重新发起（代价只是重新扣一次额度）；已生成的图仍在服务端但 URL 无从查",
            "warnings": []}


def pending_envelope(sid, jid, anchor, warnings):
    return {
        "outcome": "pending", "session_id": sid, "job_id": jid,
        "pages": [], "anchor_url": anchor, "error": None,
        "hint": f"任务已入队仍在生成（每页约 50s），稍后用 --job {jid} --session {sid} 复查并补下载，勿重发",
        "warnings": warnings,
    }


def emit_result(pages_out, sid, jid, cover_only, anchor, warnings, cover_receipt=None):
    """打印终态结果信封并按 outcome 退出（done=0 / partial|failed=1）。"""
    outcome = summarize_outcome(pages_out)
    # cover-only 时把 P1 的绝对 URL 直接回给 agent，方便下一步批量出图直接当锚点
    out_anchor = pages_out[0]["url"] if (cover_only and pages_out and pages_out[0]["url"]) else anchor
    out = {"outcome": outcome, "session_id": sid, "job_id": jid,
           "pages": pages_out, "anchor_url": out_anchor,
           "cover_receipt": str(cover_receipt) if cover_receipt else None,
           "error": None, "hint": None, "warnings": warnings}
    if outcome != "done":
        failed_labels = [p["page"] for p in pages_out if not p["path"]]
        out["hint"] = retry_hint(failed_labels, anchor, cover_only)
        if outcome == "failed":
            out["error"] = "全部页未出成（服务端未返回图 URL；可能触发额度/限流，见各页 error）"
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(1 if outcome in ("partial", "failed") else 0)


# ---------------------------------------------------------------- 闸门 A · 封面产出凭证（自动落盘）

def parse_style_trace(text):
    """从 00-overview.md 的风格档案留痕行解析 (套名, 版本)。格式见 SKILL.md：
        风格档案：图文 v3（本人档案，读取于 2026-07-28）
    2026-07-28 前的存量格式整行没有套名（`风格档案：v3（…）`）→ **按「图文」判**（那时只有轮播这条线有档案）。
    解析不出 → None。"""
    m = _TRACE_LINE.search(text or "")
    if not m:
        return None
    rest = re.split(r"[（(]", m.group(1).strip())[0].strip()
    toks = rest.split()
    if len(toks) >= 2 and toks[1].lower().startswith("v"):
        return (toks[0], toks[1][1:])
    if toks and toks[0].lower().startswith("v"):
        return ("图文", toks[0][1:])       # 存量格式：无套名按「图文」判
    return None


def resolve_style_profile(note, override):
    """本批风格档案（套名 + 版本）：命令行 `--style-profile "图文 v3"` 优先，
    否则读 `00-overview.md` 的留痕行（笔记同目录 → 上一级）。都拿不到 → None（凭证里就缺这一项，
    发布时闸门 A 会拒——那是对的：审查端要按这一版档案判封面，缺了没法判）。"""
    if override:
        toks = str(override).split()
        if len(toks) >= 2:
            return {"套名": toks[0], "version": toks[1].lstrip("vV")}
        return {"套名": str(override).strip(), "version": ""}
    if not note:
        return None
    for d in (Path(note).parent, Path(note).parent.parent):
        f = d / "00-overview.md"
        if f.is_file():
            hit = parse_style_trace(f.read_text(encoding="utf-8"))
            if hit:
                return {"套名": hit[0], "version": hit[1]}
    return None


def cover_prompt_excerpt(prompt, limit=600):
    """封面提示词摘要：压空白后截断，但**保证色值与具名版式不被截掉**——
    这两样正是闸门 A 校验的实质（没有色值＝没按本批调色板出；没有具名版式＝版式工程没走）。"""
    s = " ".join((prompt or "").split())
    if len(s) <= limit:
        return s
    head = s[:limit]
    keep = []
    m = re.search(r"#[0-9A-Fa-f]{6}\b", s)
    if m and m.group(0) not in head:
        keep.append(s[max(0, m.start() - 20):m.end() + 20].strip())
    for layout in pn.COVER_LAYOUTS:
        i = s.find(layout)
        if i >= 0 and layout not in head:
            keep.append(s[max(0, i - 20):i + len(layout) + 20].strip())
            break
    return head + ("…… " + " …… ".join(keep) if keep else "……")


def write_cover_receipt(cover_path, prompt, sid, jid, anchor, style_profile,
                        cover_only=False, run_pages="all", gates=None):
    """封面页出图成功后**自动**落盘同名 `.meta.json`（闸门 A 的生产端）。

    为什么必须是脚本写、不是人抄：手抄的凭证只证明"有人抄了一遍"，抄错抄漏都发现不了；
    脚本写的 job/session 直接来自服务端回执，与这次出图强绑定。
    返回 (凭证路径, [告警…])。告警不阻断出图——但会在发布时被闸门 A 拦下，所以当场就说清楚。
    """
    warns = []
    excerpt = cover_prompt_excerpt(prompt)
    if not re.search(r"#[0-9A-Fa-f]{6}\b", excerpt or ""):
        warns.append("封面提示词里没有色值（#RRGGBB）：这张没按本批风格档案的调色板出，"
                     "发布时闸门 A 会拒——回 illustration-spec §2-b 重写封面提示词再出")
    if not any(v in (excerpt or "") for v in pn.COVER_LAYOUTS):
        warns.append(f"封面提示词里没有具名版式（{'/'.join(pn.COVER_LAYOUTS)}）：封面版式工程没走，"
                     "发布时闸门 A 会拒")
    if not style_profile:
        warns.append("拿不到风格档案套名与版本（00-overview.md 缺「风格档案：{套名} v{N}（…）」留痕行）："
                     "凭证里这一项会缺，发布时闸门 A 会拒——补留痕行后重出封面，"
                     "或出图时显式传 --style-profile \"图文 v3\"")
    if not cover_only:
        warns.append(
            f"这张封面是**批量顺带**产出的（本次 --pages {run_pages or 'all'}），"
            "没走「单出封面 → 看缩略图 → 确认」这一步：凭证记 cover_only=false，"
            "发布时闸门 A 会拒——要么 `gen_images.py --note <稿件> --cover-only` 重新单出，"
            "要么看过图后 `publish_note.py --confirm-cover <封面图路径> --confirmed-by \"<姓名>\"` "
            "补确认戳")
    if gates and not all(gates.get(k) for k in ("reader", "term", "seller_view")):
        off = [k for k in ("reader", "term", "seller_view") if not gates.get(k)]
        warns.append(f"三条方法论闸门有未通过项（{'/'.join(off)}）已如实记进凭证 gates："
                     + ("术语闸被 --skip-term-gate 跳过，凭证记 term_gate_skipped=true（可追责）"
                        if gates.get("term_gate_skipped") else
                        "这份稿件现在过不了闸门（可能是出图后又改了稿），发布前先修稿再重出"))
    meta = {
        "cover_file": cover_path.name,
        "source": "gen_images",
        "job_id": jid,
        "session_id": sid,
        "anchor_url": anchor,
        # 「单出确认」（2026-08-14 复验 S4 证据 3）：凭证只能证明"这张图是工序③出的"，
        # 证明不了"有人看过它"。批量出 P2…P8 时顺带重出的 P1 同样拿得到合法凭证，
        # 于是被覆盖掉的已确认封面照样能发。故把这次出图的实况一起记进凭证，交闸门 A 判。
        "cover_only": bool(cover_only),
        "run_pages": str(run_pages or "all"),   # 这一跑实际请求的页："1" / "2-8" / "1,3" / "all"
        # 三条写作方法论闸门这次到底走没走（2026-08-17）：三个布尔进凭证，发布端/审查端可核。
        # ⚠️ null ＝ **本次没跑过**（--job 复查拿不到稿件时），⛔ 不等于通过。
        "gates": gates,
        "style_profile": style_profile or {},
        "prompt_excerpt": excerpt,
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
    }
    mp = pn.cover_meta_path(cover_path)
    mp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return mp, warns


def run_pages_spec(cover_only_flag, pages_arg, page_labels=None):
    """本次出图的「请求页」证据串，原样落进凭证 run_pages：
      传了 --pages → 原样记（"1" / "2-8" / "1,3"）；--cover-only → "1"；两者都没传（整篇全出）→ "all"；
      --job 复查没有 --pages 实参 → 按状态文件里的页 label 还原成 "2,3,4"。
    ⛔ --cover-only 不许记 "all"：那是凭证自己说谎（这一跑只请求了 P1）。"""
    if cover_only_flag:
        return "1"        # --cover-only 与 --pages 同给时以前者为准（select_pages 也是这个次序）
    if pages_arg:
        return str(pages_arg)
    if page_labels:
        return ",".join(str(int(l[1:])) for l in page_labels)
    return "all"


def is_cover_single(cover_only_flag, run_pages):
    """本次出图算不算「单出封面」：显式 --cover-only，或这一跑只请求了 P1 一页（--pages 1）。
    ⚠️ 判据是**这一跑请求了哪些页**，不是"产出里有没有 P1"——批量跑里 P1 出成了也不算单出。"""
    return bool(cover_only_flag) or str(run_pages).strip() in ("1", "P1")


def maybe_write_cover_receipt(pages_out, note, sid, jid, anchor, style_override,
                              cover_only=False, run_pages="all", gates=None):
    """本次出图里若包含 **P1（封面页）** 且落盘成功 → 写凭证。返回 (凭证路径|None, [告警…])。
    复查路径（--job）没给 --note 时拿不到提示词 → 不写，如实告警，别写一份没有 prompt_excerpt 的空凭证。
    cover_only/run_pages 记「这张封面是单出的还是批量顺带的」，交发布时的闸门 A 判（裁决 B）。"""
    p1 = next((p for p in pages_out if p["page"] == "P1" and p.get("path")), None)
    if not p1:
        return None, []
    if not note:
        return None, ["本次含封面页 P1，但没给 --note，拿不到封面提示词 → **未写产出凭证**："
                      "补跑 `gen_images.py --note <post-NN.md> --job <id> --session <id>` 生成凭证，"
                      "否则发布时闸门 A 会拒发"]
    prompt = next((p["prompt"] for p in extract_pages(Path(note).read_text(encoding="utf-8"))
                   if p["page"] == "P1"), None)
    return write_cover_receipt(Path(p1["path"]), prompt, sid, jid, anchor,
                               resolve_style_profile(note, style_override),
                               cover_only=is_cover_single(cover_only, run_pages),
                               run_pages=run_pages, gates=gates)


def resolve_images_dir(note, images_dir):
    if images_dir:
        return Path(images_dir)
    if note:
        return note.parent / "images" / note.stem  # 与 publish_note.collect_images 默认一致
    return None


def read_state(images_dir):
    p = images_dir / STATE_FILE
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def write_state(images_dir, sid, jid, page_labels, anchor):
    images_dir.mkdir(parents=True, exist_ok=True)
    (images_dir / STATE_FILE).write_text(
        json.dumps({"session_id": sid, "job_id": jid, "pages": page_labels, "anchor_url": anchor},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")


def _truncate(s, n=60):
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n] + "…"


def run_dry(args, note, images_dir, api_base):
    """离线打印将发送的 payload（提示词截断）与目标 URL，不打网络、不需要凭据。"""
    if not note:
        sys.exit("--dry-run 需要 --note")
    md_text = note.read_text(encoding="utf-8")
    all_pages = extract_pages(md_text)
    try:
        validate_complete(all_pages)
        # R4 结构闸门（含三条写作方法论）：干跑也走，先在这里现形，别等真跑才拒
        gates = validate_structure(md_text, all_pages, skip_term_gate=args.skip_term_gate)
        selected = select_pages(all_pages, args.cover_only, args.pages)
        warnings = build_warnings(selected, args.cover_only, args.anchor_url)
    except ValueError as e:
        print(json.dumps({"outcome": "failed", "error": str(e),
                          "pages_detected": [p["page"] for p in all_pages]},
                         ensure_ascii=False, indent=2))
        sys.exit(1)
    payload = {"prompts": [_truncate(p["prompt"]) for p in selected]}
    if args.anchor_url:
        payload["anchor_url"] = args.anchor_url
    print(json.dumps({
        "outcome": "dry_run",
        "target_url": f"{api_base}/api/op/consistent-images",
        "note": str(note),
        "pages_detected": [p["page"] for p in all_pages],
        "selected_pages": [p["page"] for p in selected],
        "images_dir": str(images_dir) if images_dir else None,
        "storyline": extract_storyline(md_text),
        "reader": extract_reader(md_text),
        "gates": gates,
        "claims": {p["page"]: p["claim"] for p in all_pages},
        "style_profile": resolve_style_profile(note, args.style_profile),
        "payload_preview": payload,
        "warnings": warnings,
    }, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(description="用后端 gpt-image 锚点法给小红书笔记出一致性轮播配图（异步）")
    ap.add_argument("--note", type=Path, help="笔记文件（post-NN.md，须含「## 配图轮播」）")
    ap.add_argument("--cover-only", action="store_true", help="只出 P1 封面（风格闸门第一步）")
    ap.add_argument("--anchor-url", help="锚点参考图 URL（P1 确认后的封面），各页据此锚定生成保持一致")
    ap.add_argument("--pages", help="只出指定页：'2-9' / '3,5' / '2-4,7' 混合 / "
                                    "'2-' 开区间＝第 2 页到末页（默认全部页）")
    ap.add_argument("--images-dir", type=Path, help="落盘目录（默认 <笔记同目录>/images/<笔记名>/）")
    ap.add_argument("--api-base", help="API base（默认 NBDPSY_VIDEO_API_BASE 或 https://mcp.nbdpsy.com）")
    ap.add_argument("--no-wait", action="store_true", help="提交后不等结果（稍后 --job 复查）")
    ap.add_argument("--wait-timeout", type=float,
                    help="轮询等待上限秒数（默认 max(600, 页数×90)）")
    ap.add_argument("--dry-run", action="store_true", help="只打 payload 摘要与目标 URL，不发请求")
    ap.add_argument("--job", type=int, help="复查该已入队任务并补下载（配 --note 或 --images-dir 定位目录）")
    ap.add_argument("--session", help="--job 复查用的 session_id（缺省则从状态文件恢复）")
    ap.add_argument("--style-profile", metavar='"套名 vN"',
                    help="本批风格档案（写进封面产出凭证）；不传则读 00-overview.md 的风格档案留痕行")
    ap.add_argument("--skip-term-gate", action="store_true",
                    help="跳过「术语必定义」闸门（默认关闭）；用了会在封面凭证记 "
                         "term_gate_skipped=true，可追责")
    args = ap.parse_args()

    note = args.note
    images_dir = resolve_images_dir(note, args.images_dir)
    api_base = (args.api_base or nbdpsy_common.video_api_base()).rstrip("/")

    # dry-run 离线，不需要凭据
    if args.dry_run:
        run_dry(args, note, images_dir, api_base)
        return

    key = nbdpsy_common.get_secret(nbdpsy_common.XHS_API_KEY)
    if not key:
        print(f"MISSING:{nbdpsy_common.XHS_API_KEY} 找管理员要「运营接入配置包」，"
              "secret import 导入后重试（与小红书发布 / 视频搬运同一把凭据）", file=sys.stderr)
        sys.exit(1)

    sid = jid = None  # 已入队的 session/job——之后任何异常都不能丢它，否则会诱发重复生成
    try:
        # ---- --job 复查已入队任务并补下载 ----
        if args.job is not None:
            if images_dir is None:
                raise ValueError("--job 复查需要 --note 或 --images-dir 以定位图片目录与状态文件")
            state = read_state(images_dir)
            jid = args.job
            sid = args.session or state.get("session_id")
            if not sid:
                raise ValueError("缺 --session，且状态文件里没有 session_id；请补 --session <id>")
            page_labels = state.get("pages") or []
            anchor = state.get("anchor_url")
            if not page_labels:
                raise ValueError("状态文件缺页映射（pages），无法对齐下载；请重新出图而非复查")
            selected = [{"page": l} for l in page_labels]
            cover_only = page_labels == ["P1"] and not anchor
            view = poll_job(api_base, key, sid, jid, timeout=0)  # 单次探测
            if view.get("status") == "gone":
                print(json.dumps(gone_envelope(sid, jid), ensure_ascii=False))
                sys.exit(1)
            if view.get("status") not in TERMINAL_STATUSES:
                print(json.dumps(pending_envelope(sid, jid, anchor, []), ensure_ascii=False))
                sys.exit(0)
            pages_out = finalize(view, selected, images_dir, api_base)
            # 复查路径的「单出」判据只认状态文件里那一跑请求的页集（page_labels）：
            # ⛔ 不认这次命令行上的 --cover-only——批量出完再拿 `--job … --cover-only` 复查一遍
            # 就能把凭证刷成"单出"，那是伪造。原始那跑出的是哪几页，文件里写着。
            receipt, rwarns = maybe_write_cover_receipt(
                pages_out, note, sid, jid, anchor, args.style_profile,
                cover_only=False,                                    # ⛔ 不认命令行 --cover-only
                run_pages=run_pages_spec(False, None, page_labels),  # 只认状态文件里那一跑的页集
                # 复查路径按当前稿件重跑三闸取结论（只记录不拦人）；拿不到稿件就记 null＝没跑过
                gates=gates_for_note(note, args.skip_term_gate))
            for w in rwarns:
                print(f"⚠ {w}", file=sys.stderr)
            emit_result(pages_out, sid, jid, cover_only, anchor, rwarns, receipt)

        # ---- 正常出图 ----
        if not note:
            ap.error("出图需要 --note（或用 --job 复查已入队任务）")
        md_text = note.read_text(encoding="utf-8")
        all_pages = extract_pages(md_text)
        validate_complete(all_pages)
        # R4 结构闸门：缺读者/故事线/论点行、术语悬空、卖方腔 → 拒跑，⛔ 不出图不烧额度
        gates = validate_structure(md_text, all_pages, skip_term_gate=args.skip_term_gate)
        selected = select_pages(all_pages, args.cover_only, args.pages)
        cover_only = args.cover_only
        anchor = args.anchor_url
        warnings = build_warnings(selected, cover_only, anchor)
        for w in warnings:
            print(f"⚠ {w}", file=sys.stderr)

        prompts = [p["prompt"] for p in selected]
        page_labels = [p["page"] for p in selected]
        print(f"提交出图：{note.name} {len(selected)} 页（{', '.join(page_labels)}）→ {api_base} …",
              file=sys.stderr)
        jid, sid = create_job(api_base, key, prompts, anchor)
        if not jid or not sid:
            raise ValueError(f"建任务响应缺 job_id/session_id：job_id={jid} session_id={sid}")
        print(f"  已入队 job_id={jid} session_id={sid}", file=sys.stderr)
        write_state(images_dir, sid, jid, page_labels, anchor)

        if args.no_wait:
            print(json.dumps(pending_envelope(sid, jid, anchor, warnings), ensure_ascii=False))
            return

        # 下限 600s 是 server 2026-08-06 回执点名要求的：上游超时后服务端会重试 2 次
        # （退避 5s/15s），"接了连接又挂住"的最坏情况能跨过原来的 360s 窗口——那时轮询
        # 提前放弃会误判成任务卡死，而服务端其实还在重试。宁可多等，不要误判。
        timeout = args.wait_timeout if args.wait_timeout is not None else max(600, len(selected) * 90)
        view = poll_job(api_base, key, sid, jid, timeout=timeout)
        if view.get("status") == "gone":  # 极小概率：刚入队 server 就重启
            print(json.dumps(gone_envelope(sid, jid), ensure_ascii=False))
            sys.exit(1)
        if view.get("status") not in TERMINAL_STATUSES:  # 超时仍在跑
            print(json.dumps(pending_envelope(sid, jid, anchor, warnings), ensure_ascii=False))
            return
        pages_out = finalize(view, selected, images_dir, api_base)
        # 闸门 A 生产端：封面页出成就**自动**落凭证，消灭手抄（手抄的凭证抄错抄漏无人发现）
        receipt, rwarns = maybe_write_cover_receipt(
            pages_out, note, sid, jid, anchor, args.style_profile,
            cover_only=cover_only,
            run_pages=run_pages_spec(cover_only, args.pages),
            gates=gates)
        for w in rwarns:
            print(f"⚠ {w}", file=sys.stderr)
        emit_result(pages_out, sid, jid, cover_only, anchor, warnings + rwarns, receipt)

    except Exception as e:
        msg = sandbox_hint(e)
        if sid is not None and jid is not None:
            # 任务已在服务端入队，绝不判 failed——那会让 agent 重发同一批（重复生成/烧额度）
            print(f"  → 状态未知: {msg}", file=sys.stderr)
            print(json.dumps({
                "outcome": "unknown", "session_id": sid, "job_id": jid, "pages": [],
                "anchor_url": args.anchor_url, "error": msg,
                "hint": f"任务可能仍在服务端跑，先用 --job {jid} --session {sid} 复查，勿直接重发以免重复生成",
            }, ensure_ascii=False))
            sys.exit(0)
        # 未入队的异常（解析/选页/建任务失败）才是真 failed
        print(f"  → 失败: {msg}", file=sys.stderr)
        print(json.dumps({"outcome": "failed", "session_id": None, "job_id": None,
                          "pages": [], "error": msg}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
