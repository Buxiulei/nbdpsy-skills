#!/usr/bin/env python3
"""公众号稿件中文本土化表达终审：正文喂 DeepSeek，输出逐条修改建议。

**只出建议、绝不改稿**——采纳哪几条是编辑决策（agent 逐条判断、过度润色的不采），
DeepSeek 在这条流水线上是「母语外审」，不是定稿人。

用法:
    python3 zh_review.py <稿子.md>            # 自动剥 frontmatter 与「## 配图」区块
    python3 zh_review.py <稿子.md> --timeout 300

凭据: DEEPSEEK_API_KEY（环境变量 > 用户级 secrets > 工作区 .env，与其它密钥同一套解析）；
基址可用 DEEPSEEK_BASE_URL 覆盖（默认 https://api.deepseek.com）。

输出: 审核意见原文（markdown，stdout）。网络/凭据失败 exit 1 并打人话错误。
"""
import argparse
import os
import sys
from pathlib import Path

import nbdpsy_common

DEFAULT_BASE = "https://api.deepseek.com"
MODEL = "deepseek-chat"

PROMPT = """你是资深中文编辑，母语普通话，长期给微信公众号做文字终审。请对下面这篇公众号文章做**中文本土化表达审核**，只关注语言，不评价观点与结构：

1. 翻译腔／欧化句式（如「作为一个…」「的一个」滥用、被动语态生硬、定语过长）
2. 不地道的搭配与生造词
3. 学术表述转口语时的别扭处（保留术语准确性的前提下更顺口的说法）
4. 标点与格式（中文语境该用全角、引号层级、破折号用法）
5. 语气不统一处（本文基调：对读者说话、温和聪明、不说教）

输出格式：逐条列出，每条＝「原句（截取）→ 建议改法 → 一句话理由」。只列真有问题的，鸡蛋里挑骨头的不要。最后给一行总评：这篇的中文水平几分（10分制）、最值得改的前三条编号。若全文已很地道，直接说「无需修改」并给出总评。"""


def extract_body(md_text: str) -> str:
    """剥 frontmatter 与「## 配图」区块，只留给读者看的正文。"""
    text = md_text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            text = parts[2]
    return text.split("## 配图")[0].strip()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="中文本土化表达终审（DeepSeek，只出建议不改稿）")
    ap.add_argument("input", help="稿子 markdown 文件")
    ap.add_argument("--timeout", type=float, default=300, help="请求超时秒数（长文默认 300）")
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
    try:
        resp = requests.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": PROMPT},
                    {"role": "user", "content": body},
                ],
                "temperature": 0.3,
                "max_tokens": 4000,
            },
            timeout=args.timeout,
        )
    except Exception as e:  # noqa: BLE001 —— 审核是幂等只读动作，失败直接重试即可
        print(f"DeepSeek 请求失败（可直接重试）：{e}", file=sys.stderr)
        return 1
    if resp.status_code >= 400:
        print(f"DeepSeek HTTP {resp.status_code}：{resp.text[:300]}", file=sys.stderr)
        return 1
    try:
        print(resp.json()["choices"][0]["message"]["content"])
    except (ValueError, KeyError, IndexError) as e:
        print(f"DeepSeek 响应解析失败：{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
