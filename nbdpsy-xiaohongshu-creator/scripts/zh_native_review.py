#!/usr/bin/env python3
"""中文本土化表达审核（DeepSeek 独立审核员）。

用法：
    python3 zh_native_review.py <note.md>          # 审一篇稿（标题+发布文案+图内文字）
    python3 zh_native_review.py --text "一句话"     # 审任意文本片段

诞生背景（2026-08-06 运营两次点名）：
- 「强烈9分」——「什么叫亲密关系的强烈？？？这完全不符合中文的表达习惯」（七篇返工）
- 「爱轰炸期的奶茶？？这是什么鬼」「开局猛烈投喂不等于爱得深？这是什么表达？」
自审会漏（写的人闻不出自己的术语腔），所以引入独立模型专职审核。
产线纪律：写稿后、出图前必过本审核；issues 逐条处理（改，或在报告里写明驳回理由）；
审核输出原样贴报告。

费用口径：deepseek-chat，单篇约 2-3k token，可忽略。
"""
import json
import os
import re
import sys
from pathlib import Path

import requests

API = "https://api.deepseek.com/chat/completions"


def load_key() -> str:
    """解析顺序与 nbdpsy_common 同源：环境变量 → 工作区 .env → 用户级 secrets → 本机 NBDpsy 仓库兜底。"""
    k = os.environ.get("DEEPSEEK_API_KEY")
    if k:
        return k
    candidates = (Path.cwd() / ".env",
                  Path.home() / ".config/nbdpsy/secrets.env",
                  Path("/home/roots/NBDpsy/.env"))
    for envfile in candidates:
        try:
            for line in envfile.read_text().splitlines():
                if line.startswith("DEEPSEEK_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"')
        except (FileNotFoundError, PermissionError):
            continue
    print("缺 DEEPSEEK_API_KEY：本环节降级为人工自审（按 xiaohongshu-spec §1「中文本土化表达」清单逐句过并在报告留痕）；"
          "要启用机器审核，请管理员把 DEEPSEEK_API_KEY 加进凭据配置包或写入 ~/.config/nbdpsy/secrets.env", file=sys.stderr)
    sys.exit(2)


SYSTEM = """你是一位中文母语的资深编辑，专门审心理科普类小红书文案的「中文本土化表达」。你的唯一职责：找出不像中国人日常说话的句子。判据五条：

1. 光杆形容词冒充名词/概念名：如「强烈 9 分」「把强烈和安全分开」——形容词没有着落点（强烈的是什么？）。已被大众口语名词化的词（焦虑、内耗、上头、心动、安全感）不算。
2. 术语直译腔与圈内黑话：如「爱轰炸」「高唤起」「情绪价值供给」——普通读者第一眼看不懂的词。判据：一个不看心理学内容的人能否秒懂；不能就要求换成人话，或就地用半句话讲明白。
3. 生造比喻与错位语域：如「猛烈投喂」「供糖稳定」「开局」「峰值」——把工程/游戏/饲养词硬套进感情话题，读着别扭。
4. 翻译腔句式：抽象名词堆叠、「进行」「实现」「化」滥用、欧化长定语（「的」链超两层）、机械被动句。
5. 朗读测试：整句读一遍，问「跟朋友发微信语音会这么说吗」——不会就是问题句。

注意边界：
- 网感词若与语境融洽可放行（小红书语境「上头」「内耗」「破防」是正常口语）。
- 不审事实、不审合规、不审排版，只审表达。
- 不夸大：正常的句子不要硬挑毛病；宁可漏报一条轻微的，不可把好句子改坏。
- 每条问题必须给出可直接替换的改句，改句必须口语、自然、意思不变。

输出严格 JSON（不要 markdown 代码块），格式：
{"verdict":"pass"或"fail","issues":[{"loc":"标题/正文/P2图内…","original":"原句","problem":"哪条判据+一句话原因","fix":"可直接替换的改句"}],"summary":"一句话总评"}
issues 为空数组时 verdict 必须是 pass。"""


def extract(md_path: Path) -> str:
    """抽稿件的表达层文本：标题 + 发布文案 + 各页图内/页面文字（不含绘图提示词）。"""
    text = md_path.read_text(encoding="utf-8")
    parts = []
    m = re.search(r"^title:\s*(.+)$", text, re.M)
    if m:
        parts.append(f"【标题】{m.group(1).strip()}")
    m = re.search(r"^##\s*发布文案[^\n]*\n(.*?)(?=^##\s|\Z)", text, re.S | re.M)
    if m:
        parts.append("【发布文案】\n" + m.group(1).strip())
    for pm in re.finditer(r"^###\s*(P\d[^\n]*)\n(.*?)(?=^###\s|\Z)", text, re.S | re.M):
        page, body = pm.group(1), pm.group(2)
        fm = re.search(r"\*\*(?:页面文字|图内文字)\*\*\n(.*?)(?=\*\*|```)", body, re.S)
        if fm:
            parts.append(f"【{page.strip()} 图内文字】\n" + fm.group(1).strip())
    return "\n\n".join(parts)


def review(content: str) -> dict:
    r = requests.post(API, timeout=120, headers={"Authorization": f"Bearer {load_key()}"},
        json={"model": "deepseek-chat", "temperature": 0.2,
              "response_format": {"type": "json_object"},
              "messages": [{"role": "system", "content": SYSTEM},
                           {"role": "user", "content": content}]})
    r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--text":
        content = sys.argv[2]
    elif len(sys.argv) == 2:
        content = extract(Path(sys.argv[1]))
        if not content:
            print("没抽到可审文本（缺 title/发布文案/图内文字块）")
            return 2
    else:
        print(__doc__)
        return 2
    res = review(content)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0 if res.get("verdict") == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
