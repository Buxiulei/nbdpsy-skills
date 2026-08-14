#!/usr/bin/env python3
"""公众号稿件中文本土化表达终审：正文喂 DeepSeek，输出逐条修改建议。

**只出建议、绝不改稿**——采纳哪几条是编辑决策（agent 逐条判断、过度润色的不采），
DeepSeek 在这条流水线上是「母语外审」，不是定稿人。

用法:
    python3 zh_review.py <稿子.md>            # 自动剥 frontmatter 与「## 配图」区块
    python3 zh_review.py <稿子.md> --timeout 300

长稿分段: 正文超 2500 汉字就按行首 `## ` 切小节、打包成 ≤2500 汉字的段逐段送审再拼接，
每段标注覆盖范围。分段后每段各有一行总评（原来的单次调用只有一行），这是分段的代价。

**绝不静默只审半篇**: 读响应的 finish_reason，为 "length" 说明这一段的建议被输出长度上限
截断了——脚本当场点名「审到哪一节为止」、结论降级 partial 并以 exit 2 收场。
2026-08-14 实测过：4000 tokens 的上限会让一篇 4000 汉字的稿子只审到一半，而旧版照样 exit 0，
运营拿着半篇建议当全篇用。

凭据: DEEPSEEK_API_KEY（环境变量 > 用户级 secrets > 工作区 .env，与其它密钥同一套解析）；
基址可用 DEEPSEEK_BASE_URL 覆盖（默认 https://api.deepseek.com）。

输出: 审核意见原文（markdown，stdout）。
退出码: 0 = 全篇审完；2 = 审了但有段落被截断（partial，见输出里的 ⚠️）；1 = 网络/凭据/参数失败。
"""
import argparse
import os
import re
import sys
from pathlib import Path

import nbdpsy_common

DEFAULT_BASE = "https://api.deepseek.com"
MODEL = "deepseek-chat"
# 8000 而非 4000：2026-08-14 实测一段 2265 汉字的正文能审出 4000+ tokens 的建议，
# 卡 4000 会让每篇长稿都判 partial——天天报红等于没报。deepseek-chat 上限 8192。
MAX_TOKENS = 8000
MAX_HANZI_PER_CHUNK = 2500          # 超过就分段：单段建议量塞得进 MAX_TOKENS 才不会被截断

PROMPT = """你是资深中文编辑，母语普通话，长期给微信公众号做文字终审。请对下面这篇公众号文章做**中文本土化表达审核**，只关注语言，不评价观点与结构：

1. 翻译腔／欧化句式（如「作为一个…」「的一个」滥用、被动语态生硬、定语过长）
2. 不地道的搭配与生造词
3. 学术表述转口语时的别扭处（保留术语准确性的前提下更顺口的说法）
4. 标点与格式（中文语境该用全角、引号层级、破折号用法）
5. 语气不统一处（本文基调：对读者说话、温和聪明、不说教）

输出格式：逐条列出，每条＝「原句（截取）→ 建议改法 → 一句话理由」。只列真有问题的，鸡蛋里挑骨头的不要。最后给一行总评：这篇的中文水平几分（10分制）、最值得改的前三条编号。若全文已很地道，直接说「无需修改」并给出总评。"""

_HANZI = re.compile(r"[一-鿿]")
# 行首锚定：正文里写到「## 配图」四个字的句子不能被误切成半篇（和 md2wechat 同一判据）
_ILLUSTRATION_HEADING = re.compile(r"(?m)^##\s*配图\s*$")
_SECTION_HEADING = re.compile(r"(?m)^##(?!#)\s")
# 审核输出里被引用的原句——用来回推截断时审到了哪儿
_QUOTED = re.compile(r"[「『“\"']([^」』”\"'\n]{6,80})[」』”\"']")
PREAMBLE_LABEL = "（开头，无小标题）"


def count_hanzi(text: str) -> int:
    return len(_HANZI.findall(text))


def extract_body(md_text: str) -> str:
    """剥 frontmatter 与「## 配图」区块，只留给读者看的正文。"""
    text = md_text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            text = parts[2]
    m = _ILLUSTRATION_HEADING.search(text)
    if m:
        text = text[:m.start()]
    return text.strip()


def split_sections(body: str):
    """按行首 `## ` 切小节，返回 [{"heading", "text"}]；第一节前的开头单独成节。"""
    starts = [m.start() for m in _SECTION_HEADING.finditer(body)]
    if not starts:
        return [{"heading": "", "text": body}]
    out = []
    if body[:starts[0]].strip():
        out.append({"heading": "", "text": body[:starts[0]]})
    bounds = starts + [len(body)]
    for i, start in enumerate(starts):
        chunk = body[start:bounds[i + 1]]
        out.append({"heading": chunk.splitlines()[0].strip(), "text": chunk})
    return out


def pack_chunks(sections, limit=MAX_HANZI_PER_CHUNK):
    """把小节贪心打包成 ≤limit 汉字的段。单节自己就超 limit 的，独占一段（不硬切句子）。"""
    chunks, current, current_hanzi = [], [], 0
    for sec in sections:
        n = count_hanzi(sec["text"])
        if current and current_hanzi + n > limit:
            chunks.append(current)
            current, current_hanzi = [], 0
        current.append(sec)
        current_hanzi += n
    if current:
        chunks.append(current)
    return chunks


def chunk_layout(chunk):
    """把一段的小节拼成待审文本，并记下每节在文本里的起点（截断定位要用）。"""
    parts, sections, cursor = [], [], 0
    for sec in chunk:
        text = sec["text"].strip()
        sections.append({"heading": sec["heading"] or PREAMBLE_LABEL,
                         "start": cursor, "text": text})
        parts.append(text)
        cursor += len(text) + 2                      # 与下面的 "\n\n" 连接对齐
    return "\n\n".join(parts), sections


def coverage_label(sections) -> str:
    first, last = sections[0]["heading"], sections[-1]["heading"]
    return first if first == last else f"{first} → {last}"


def last_covered_section(output: str, text: str, sections):
    """从被截断的输出里回推「审到哪一节为止」，定位不到返回 None。

    审核输出的格式是「原句（截取）→ 建议改法 → 理由」，原句是从正文逐字摘的——
    把输出里引到的最靠后的那句话在正文里定位，就知道审到哪儿了。宁可说定位不到，
    也不许猜一个节名糊过去：运营要照着这个决定「哪一段还得再跑一次」。
    """
    best = -1
    for frag in _QUOTED.findall(output):
        # 取首次出现而非末次：同一句话在多节里重复时宁可少报覆盖。少报只是让运营多跑一段，
        # 多报会让他以为后面审过了——两种错的代价差着量级。
        best = max(best, text.find(frag))
    for sec in sections:
        if sec["heading"] != PREAMBLE_LABEL and sec["heading"] in output:
            best = max(best, sec["start"])
    if best < 0:
        return None
    hit = sections[0]
    for sec in sections:
        if sec["start"] <= best:
            hit = sec
    return hit["heading"]


def review(text: str, note: str, *, base: str, key: str, timeout: float, requests):
    """送审一段，返回 (建议正文, finish_reason)。网络/协议失败抛 RuntimeError。"""
    try:
        resp = requests.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": PROMPT},
                    {"role": "user", "content": f"{note}{text}" if note else text},
                ],
                "temperature": 0.3,
                "max_tokens": MAX_TOKENS,
            },
            timeout=timeout,
        )
    except Exception as e:  # noqa: BLE001 —— 审核是幂等只读动作，失败直接重试即可
        raise RuntimeError(f"DeepSeek 请求失败（可直接重试）：{e}") from e
    if resp.status_code >= 400:
        raise RuntimeError(f"DeepSeek HTTP {resp.status_code}：{resp.text[:300]}")
    try:
        choice = resp.json()["choices"][0]
        return choice["message"]["content"], choice.get("finish_reason")
    except (ValueError, KeyError, IndexError) as e:
        raise RuntimeError(f"DeepSeek 响应解析失败：{type(e).__name__}: {e}") from e


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="中文本土化表达终审（DeepSeek，只出建议不改稿）")
    ap.add_argument("input", help="稿子 markdown 文件")
    ap.add_argument("--timeout", type=float, default=300, help="单次请求超时秒数（长文默认 300）")
    args = ap.parse_args(argv)

    p = Path(args.input)
    if not p.is_file():
        print(f"文件不存在：{p}", file=sys.stderr)
        return 1
    body = extract_body(p.read_text(encoding="utf-8-sig"))
    if not body:
        print("剥掉 frontmatter 与配图区块后正文是空的——文件给错了？", file=sys.stderr)
        return 1

    key = nbdpsy_common.get_secret("DEEPSEEK_API_KEY")
    if not key:
        print("缺凭据 DEEPSEEK_API_KEY：配到环境变量或用户级 secrets 后重试。", file=sys.stderr)
        return 1
    base = (os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_BASE).rstrip("/")

    try:
        import requests
    except ImportError:
        print("缺依赖 requests：在仓库根跑一次 python3 setup.py 后重试。", file=sys.stderr)
        return 1

    # 无论长短都先切小节：短稿照旧一次调用（打包成一段），但截断时才点得出「审到哪一节」。
    total = count_hanzi(body)
    chunks = pack_chunks(split_sections(body))
    if len(chunks) > 1:
        print(f"> 正文 {total} 汉字，超过单次送审上限 {MAX_HANZI_PER_CHUNK}，"
              f"已按小节拆成 {len(chunks)} 段逐段送审（每段各有一行总评）。\n")

    truncated = []
    for i, chunk in enumerate(chunks, 1):
        text, sections = chunk_layout(chunk)
        label = coverage_label(sections)
        note = ""
        if len(chunks) > 1:
            print(f"━━━ 审核段 {i}/{len(chunks)} · 覆盖「{label}」"
                  f"（{count_hanzi(text)} 汉字）━━━\n")
            note = (f"（以下是全文的第 {i}/{len(chunks)} 段，覆盖「{label}」。"
                    "只审这一段的语言，不必评价文章整体结构是否完整。）\n\n")
        try:
            content, finish = review(text, note, base=base, key=key,
                                     timeout=args.timeout, requests=requests)
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            return 1
        print(content)
        if finish == "length":
            covered = last_covered_section(content, text, sections)
            where = f"『{covered}』" if covered else "『无法从输出定位到具体小节』"
            print(f"\n⚠️ **因输出长度上限被截断，仅覆盖到{where}，其后未审**"
                  f"（本段覆盖「{label}」；该节自身可能也没审完）。"
                  "请把未覆盖的部分单独存成一个文件重跑本脚本。")
            truncated.append(i)
        print()

    if truncated:
        print(f"━━━ 结论：partial ━━━\n第 {'、'.join(map(str, truncated))} 段被输出长度上限截断，"
              f"共 {len(chunks)} 段，**这不是一份全篇审核**——别当全篇用。")
        return 2
    if len(chunks) > 1:
        print(f"━━━ 结论：done ━━━\n{len(chunks)} 段全部审完，无截断。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
