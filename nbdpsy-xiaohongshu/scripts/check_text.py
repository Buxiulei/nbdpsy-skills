#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小红书正文机检：只报确定错的，模糊的交给审稿 agent。

判据全部来自李牧阳写手 checklist 原文（三版 docx，她亲手写的），不掺自推规则：

  合规层  「不能带"医疗" "疗法" "催眠"字样」
  文风层  「单字 claude 说中文的时候很喜欢用单字 但是没有人用单字
           实际上 比如说"更狠" "很稳" 不要用单字」
          「三重排比 除非真的有文学价值 必须排比不可」
          豁免原话：「这一条有豁免的情况 那就是陈述事实和信息 像说明书一样
                     一个东西包含 abcde 构造这种 类似的 可以如实陈列
                     禁掉的三重排比是无病呻吟式的排比」
  长句    「减少零散的短句…短句不能连段，短句不能充斥文章」（10/23 的 c 条）
  交付    「正文带 Markdown 加粗，发布时必被剥」（提取-06 §4.1）

分级：
  FAIL  确定错，退出码 1。只有两类：禁词、正文 Markdown 加粗。
  WARN  疑似，交人判。三重排比（事实列举是合法豁免，脚本不替你判）、
        单字/两字收句候选、短句连段。
  INFO  读数，不判。汉字数、段落长度分布。

用法：
    python3 check_text.py 正文.md [更多.md ...]
    python3 check_text.py --selfcheck 自检表.md 正文.md

文件有 `## 正文` 节时只查该节（标题可带「二、」序号与「（工序②）」后缀）；
没有就整篇当正文。--selfcheck 校验 03-审稿.md 要求的逐条自检表：20 条判据
齐全，且每行引句（表头含「引句/引文/原文」的列；没这列时取末列里的「」引文）
去空白后能在正文里逐字找到。
退出码：0 通过 / 1 有确定错误 / 2 用法或文件读不了。
"""

import pathlib
import re
import sys

HAN = re.compile(r"[\u4e00-\u9fff]")
BAN = ("医疗", "疗法", "催眠")          # 写手 checklist v2 合规层，原话见模块 docstring
SHORT_SENT = 20    # 短句阈值，出自提取-06 §6 的量尺；她的原话只说「短句不能连段」
SHORT_RUN = 3      # 连续 3 句以上短句 = 短句连段（同上，实现参数，非她的原话）
SOLO_OK = set("的了吧吗呢啊呀嘛哦嗯噢啦哇哈哟是好对行不没有我你他她它去来说看走")  # 合法独用单字，压低误报
SOLO_OK |= {"好的", "好吧", "是啊", "对啊", "嗯嗯", "哈哈", "可以", "没事", "真的", "是吧", "行吧"}  # 正常口语词
SOLO_OK |= {"这时", "那时", "后来", "最后", "结果", "其实", "所以", "但是", "然后", "接着",
            "总之", "当然", "于是", "因此", "不过", "而且", "已经", "现在", "当时", "那天"}  # 常见状语/转折词
SOLO_UNIT = set("元岁斤次天年月周分秒人个条张页")   # 数值单位不是单字收句
BODY_HEAD = re.compile(
    r"^##[ \t]*(?:[一二三四五六七八九十]+、|\d+[、.][ \t]*)?[ \t]*正文"
    r"(?:[（(][^）)\n]*[）)])?[ \t]*$"
)   # 认 `## 正文` / `## 二、正文（工序②）`
NEXT_HEAD = re.compile(r"^##[ \t]")
SENT_SPLIT = re.compile(r"[。！？!?；;\n]")
# 破折号/省略号/斜杠只用于「链式短句」这一种形状（很累——很挤——很冷——还是开了电脑），
# ⛔ 不并入段落级短句统计：刘琼篇「还有作业——给自己写一封信，像写给一个你心疼的朋友」
# 是正常用法，按句号切分不该被算成两个短句（2026-10-28 实测误报）。
DASH_CHAIN = re.compile(r"[—…/]+")
DASH_SEG_MAX = 6     # 链里每个片段 ≤6 汉字才算蹭字数的短句链；长片段是正常破折号用法
DASH_SEG_MIN = 3     # 至少 3 段才叫「链」
CLAUSE = re.compile(r"[^，,、。！？；;：:\n]+")
QUOTE = re.compile(r"[「『“`]([^」』”`]+)[」』”`]")   # 自检表里被引的原文


def body_of(text):
    """有 `## 正文` 节就只取该节，否则整篇当正文。

    标题允许序号前缀与括号后缀（实测常见 `## 二、正文（工序②）`），
    但 `## 正文自检表` 这类只是提到「正文」字样的标题不算。
    """
    lines = text.splitlines(keepends=True)
    start = next((i + 1 for i, ln in enumerate(lines)
                  if BODY_HEAD.match(ln.rstrip("\r\n"))), None)
    if start is None:
        return text
    end = next((j for j in range(start, len(lines))
                if NEXT_HEAD.match(lines[j])), len(lines))
    return "".join(lines[start:end])


def paragraphs(body):
    ps, cur = [], []
    for line in body.splitlines():
        if line.strip():
            cur.append(line.strip())
        elif cur:
            ps.append("".join(cur))
            cur = []
    if cur:
        ps.append("".join(cur))
    return ps


def snippet(text, needle, width=12):
    i = text.find(needle)
    if i < 0:
        return text[: width * 2]
    return text[max(0, i - width): i + len(needle) + width]


def solo_hits(text):
    """分句整体只有 1–2 个汉字、且独立成句 → 疑似单字收句候选。

    她的反例「更狠」「很稳」「没废」都是两个字，与单字同判；数值单位
    （1999 元／三岁）与「好的」「是啊」这类正常口语不报。
    """
    hits = []
    for m in CLAUSE.finditer(text):
        tok = m.group().strip()
        if not tok or len(tok) > 2 or len(HAN.findall(tok)) != len(tok):
            continue
        if tok in SOLO_OK or tok[-1] in SOLO_UNIT:
            continue
        hits.append(tok)
    return hits


def dash_chain(text):
    """破折号/省略号/斜杠串起来的短句链，返回命中的链片段列表。

    判据来自 10/23 的 c) 条「短句不能连段，短句不能充斥文章」：
    「很累——很挤——很冷——还是开了电脑」是它要抓的形状；
    「还有作业——给自己写一封信，像写给一个你心疼的朋友」是正常破折号用法，⛔ 不抓。
    区分靠两件事：链里至少 DASH_SEG_MIN 段，且除最后一段外每段都 ≤ DASH_SEG_MAX 汉字
    （最后一段是链的出口，常常是完整句子）。
    """
    hits = []
    for sent in SENT_SPLIT.split(text):
        if not DASH_CHAIN.search(sent):
            continue
        segs = [s for s in DASH_CHAIN.split(sent) if HAN.search(s)]
        if len(segs) < DASH_SEG_MIN:
            continue
        if all(len(HAN.findall(s)) <= DASH_SEG_MAX for s in segs[:-1]):
            hits.append("——".join(s.strip() for s in segs))
    return hits


def short_runs(text):
    """返回 (连段列表, 各句汉字数)。连段 = (起始句序号, 连续短句数)。"""
    sents = [s for s in SENT_SPLIT.split(text) if HAN.search(s)]
    lens = [len(HAN.findall(s)) for s in sents]
    runs, i = [], 0
    while i < len(lens):
        if lens[i] < SHORT_SENT:
            j = i
            while j < len(lens) and lens[j] < SHORT_SENT:
                j += 1
            if j - i >= SHORT_RUN:
                runs.append((i + 1, j - i))
            i = j
        else:
            i += 1
    return runs, lens


def _similar(a, b):
    """两分句结构相似：首二字同、尾二字同，或首/尾字同且长度差 ≤2。"""
    if a[:2] == b[:2] or a[-2:] == b[-2:]:
        return True
    return abs(len(a) - len(b)) <= 2 and (a[0] == b[0] or a[-1] == b[-1])


def parallel_hits(text):
    """连续 ≥3 个结构相似的分句 → 疑似修辞排比（事实列举请人工豁免）。

    她的反例「病是一层，身份是一层，羞耻是最里面的一层」靠尾二字「一层」命中；
    「我怕被看见，我怕被评价，我怕最后什么都没留下」靠首二字「我怕」命中——
    第一人称开头的排比一样是 AI 指纹，不按人称代词豁免。
    """
    hits = []
    for sent in re.split(r"[。！？!?；;\n]", text):
        cs = [c.strip() for c in re.split(r"[，,、：:]", sent) if len(c.strip()) >= 2]
        run = 1
        for i in range(1, len(cs)):
            run = run + 1 if _similar(cs[i - 1], cs[i]) else 1
            if run == SHORT_RUN:
                hits.append(sent.strip())
    return hits


def check_file(path):
    text = pathlib.Path(path).read_text(encoding="utf-8")
    body = body_of(text)
    paras = paragraphs(body)
    fails, warns = [], []

    for word in BAN:
        for idx, p in enumerate(paras, 1):
            if word in p:
                fails.append(f'禁词「{word}」｜第 {idx} 段：…{snippet(p, word)}…')

    bold = len(re.findall(r"\*\*", body))
    if bold:
        fails.append(f"Markdown 加粗 ** 出现 {bold} 个标记、{bold // 2} 组（发布前会被剥离，正文不要写）")

    for idx, p in enumerate(paras, 1):
        for tok in solo_hits(p):
            warns.append(f"疑似单字收句「{tok}」｜第 {idx} 段：…{snippet(p, tok)}…")
        for sent in parallel_hits(p):
            warns.append(f"疑似三重排比｜第 {idx} 段：…{snippet(p, sent[:8])}…"
                         f"（若是「包括：」式事实列举，按 checklist 豁免）")
        for chain in dash_chain(p):
            warns.append(f"短句链（破折号串短句）｜第 {idx} 段：…{snippet(p, chain[:8])}…")
        runs, lens = short_runs(p)
        for start, n in runs:
            warns.append(f"短句连段｜第 {idx} 段第 {start} 句起连续 {n} 句不足 {SHORT_SENT} 汉字")

    han = len(HAN.findall(body))
    lens = [len(HAN.findall(p)) for p in paras]
    all_sents = [s for s in SENT_SPLIT.split(body) if HAN.search(s)]
    short_n = sum(1 for s in all_sents if len(HAN.findall(s)) < SHORT_SENT)

    print(f"=== {path} ===")
    for line in fails:
        print(f"FAIL  {line}")
    for line in warns:
        print(f"WARN  {line}")
    avg = han / len(paras) if paras else 0
    print(f"INFO  正文汉字 {han}｜段落 {len(paras)}｜平均段长 {avg:.0f}｜"
          f"最长段 {max(lens) if lens else 0}｜短句 {short_n}/{len(all_sents)}")
    verdict = (f"{len(fails)} 项确定错误，{len(warns)} 项需人工确认"
               if fails else f"无确定错误（{len(warns)} 项需人工确认）")
    print(f"结论：{verdict}")
    print()
    return len(fails)


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def selfcheck(table_path, body_path):
    """校验逐条自检表：20 条判据齐全，且每行引句去空白后能在正文里逐字找到。"""
    table = pathlib.Path(table_path).read_text(encoding="utf-8")
    body = re.sub(r"\s+", "", body_of(pathlib.Path(body_path).read_text(encoding="utf-8")))
    rows = [ln.strip() for ln in table.splitlines() if ln.strip().startswith("|")]
    rows = [ln for ln in rows if not re.fullmatch(r"\|[\s:|-]*\|", ln)]
    print(f"=== 自检表 {table_path} × 正文 {body_path} ===")
    if not rows:
        print("FAIL  自检表里没有 Markdown 表格")
        print("结论：1 项确定错误")
        print()
        return 1
    head = _cells(rows[0])
    num_col = next((i for i, h in enumerate(head) if h in ("#", "编号", "序号")), 0)
    quoted = next((i for i, h in enumerate(head) if any(k in h for k in ("引句", "引文", "原文"))), None)
    quote_col = quoted if quoted is not None else len(head) - 1
    fails, nums, hit = [], [], 0
    for i, ln in enumerate(rows[1:], 1):
        cells = _cells(ln)
        m = re.search(r"\d+", cells[num_col] if num_col < len(cells) else "")
        if not m:
            fails.append(f"自检表第 {i} 行：读不出判据编号")
            continue
        n = int(m.group())
        nums.append(n)
        if not 1 <= n <= 20:
            fails.append(f"判据 {n}：编号超出 1–20")
        cell = cells[quote_col] if quote_col < len(cells) else ""
        qs = [cell.strip("「」『』“”` ")] if quoted is not None else QUOTE.findall(cell)
        qs = [q for q in qs if q]
        if not qs:
            fails.append(f"判据 {n}：引句为空")
        elif any(re.sub(r"\s+", "", q) in body for q in qs):
            hit += 1
        else:
            fails.append(f"判据 {n}：引句在正文里找不到：「{qs[0]}」")
    missing = sorted(set(range(1, 21)) - set(nums))
    dup = sorted({n for n in nums if nums.count(n) > 1})
    if missing:
        fails.append("缺判据编号：" + "、".join(map(str, missing)))
    if dup:
        fails.append("判据编号重复：" + "、".join(map(str, dup)))
    if len(rows) - 1 != 20:
        fails.append(f"判据行数 {len(rows) - 1}，应恰好 20 行")
    for line in fails:
        print(f"FAIL  {line}")
    print(f"INFO  判据 {len(set(nums))}/20｜引句命中正文 {hit}/{len(nums)}")
    print(f"结论：{len(fails)} 项确定错误" if fails else "结论：全部通过")
    print()
    return len(fails)


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if len(argv) > 1 else 2
    if argv[1] == "--selfcheck":
        if len(argv) != 4:
            print("用法：python3 check_text.py --selfcheck <自检表.md> <正文.md>")
            return 2
        missing = [p for p in argv[2:] if not pathlib.Path(p).is_file()]
        if missing:
            for p in missing:
                print(f"ERROR 读不了（不存在或不是文件）：{p}")
            return 2
        return 1 if selfcheck(argv[2], argv[3]) else 0
    missing = [p for p in argv[1:] if not pathlib.Path(p).is_file()]
    if missing:
        for p in missing:
            print(f"ERROR 读不了（不存在或不是文件）：{p}")
        return 2
    total = sum(check_file(p) for p in argv[1:])
    if len(argv) > 2:
        print(f"合计：{len(argv) - 1} 篇，{total} 项确定错误")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
