#!/usr/bin/env python3
"""确定性评测打分：对一个 run 的 outputs/ 目录核验 8 条断言，输出 grading.json。
用法: grade.py <outputs_dir> <source_pillar.md> <grading_out.json>
两个 run（with_skill / without_skill）用同一套断言，对照即一目了然。
"""
import json, re, sys, subprocess, pathlib

SKILL = pathlib.Path(__file__).resolve().parent.parent
CN = r'[一-龥]'

def hanzi(s): return len(re.findall(CN, s))

def strip_fences(text):
    out, infence = [], False
    for ln in text.splitlines():
        if ln.lstrip().startswith('```'):
            infence = not infence; continue
        if not infence: out.append(ln)
    return '\n'.join(out)

def frontmatter_and_body(text):
    m = re.match(r'^---\n(.*?)\n---\n(.*)$', text, re.S)
    return (m.group(1), m.group(2)) if m else ('', text)

def body_section(body, header_re):
    # 取 header 到下一个 ## 之间
    lines, grab, buf = body.splitlines(), False, []
    for ln in lines:
        if re.match(header_re, ln): grab = True; continue
        if grab and re.match(r'^## ', ln): break
        if grab: buf.append(ln)
    return '\n'.join(buf)

def strip_tags(s):
    # 去掉可见标签行（# 紧跟非空格，区别于 markdown 标题 "# "）
    return '\n'.join(ln for ln in s.splitlines() if not re.match(r'^\s*#\S', ln))

def numbers(s):
    # 先去掉千分位分隔符（17,337 / 17，337 → 17337），再抽取，避免逗号导致的伪"新数字"
    s = re.sub(r'(?<=\d)[,，](?=\d)', '', s)
    return set(re.findall(r'\d+(?:\.\d+)?', s))

POST_BODY_RE = r'^## *(发布文案|正文)'

def is_post(p):
    n = p.name.lower()
    return p.suffix == '.md' and not (n.startswith('00') or '总览' in p.name or 'overview' in n or 'index' in n)

def main():
    outdir, src_path, out_json = sys.argv[1], sys.argv[2], sys.argv[3]
    outdir = pathlib.Path(outdir)
    posts = sorted([p for p in outdir.glob('*.md') if is_post(p)])
    texts = {p.name: p.read_text(encoding='utf-8') for p in posts}
    src = pathlib.Path(src_path).read_text(encoding='utf-8')
    src_nums = numbers(src)
    WHITELIST = {'12356', '4001619995', '24'}  # 危机热线，非来自正文统计

    exp = []

    # A1 5–8 篇
    n = len(posts)
    exp.append({"text": "拆出 5–8 篇短文", "passed": 5 <= n <= 8,
                "evidence": f"共 {n} 篇：{', '.join(p.name for p in posts)}"})

    # A2 每篇正文 210–450 汉字
    counts = {}
    for name, t in texts.items():
        _, body = frontmatter_and_body(t)
        sec = body_section(body, POST_BODY_RE)
        sec = strip_fences(sec) if sec else strip_fences(body)
        counts[name] = hanzi(strip_tags(sec))
    bad2 = {k: v for k, v in counts.items() if not (210 <= v <= 450)}
    exp.append({"text": "每篇正文纯汉字数落在 210–450", "passed": not bad2,
                "evidence": "字数: " + ", ".join(f"{k}={v}" for k, v in counts.items()) +
                            (f"；超界: {bad2}" if bad2 else "")})

    # A3 每篇 6–9 页轮播
    pages = {}
    for name, t in texts.items():
        p = len(re.findall(r'^### *P', t, re.M))
        if p == 0:  # 基线可能用别的页标记，退化为数"提示词"出现次数
            p = len(re.findall(r'提示词', t))
        pages[name] = p
    bad3 = {k: v for k, v in pages.items() if not (6 <= v <= 9)}
    exp.append({"text": "每篇配图轮播 6–9 页", "passed": not bad3,
                "evidence": "页数: " + ", ".join(f"{k}={v}" for k, v in pages.items()) +
                            (f"；超界: {bad3}" if bad3 else "")})

    # A4 合规闸门 exit 0
    r = subprocess.run([sys.executable, str(SKILL / "scripts/check_compliance.py"), str(outdir)],
                       capture_output=True, text=True)
    exp.append({"text": "check_compliance.py 退出码 0（无违禁词 + 危机声明在位）",
                "passed": r.returncode == 0,
                "evidence": (r.stdout + r.stderr).strip().replace('\n', ' | ')[:400]})

    # A5 品牌基底复用（每篇出现品牌锚点）
    anchors = ('#A8B5C4', '风格基底', '莫兰迪')
    miss5 = [name for name, t in texts.items() if not any(a in t for a in anchors)]
    exp.append({"text": "每篇配图提示词复用固定品牌基底", "passed": not miss5,
                "evidence": "缺品牌锚点的篇: " + (", ".join(miss5) if miss5 else "无（全部复用）")})

    # A6 5–10 个标签
    tags = {}
    for name, t in texts.items():
        fm, _ = frontmatter_and_body(t)
        m = re.search(r'hashtags:\s*\[(.*?)\]', fm, re.S)
        if m: c = len([x for x in m.group(1).split(',') if x.strip()])
        else: c = len(re.findall(r'#[^\s#，,]+', t))
        tags[name] = c
    bad6 = {k: v for k, v in tags.items() if not (5 <= v <= 10)}
    exp.append({"text": "每篇有 5–10 个话题标签", "passed": not bad6,
                "evidence": "标签数: " + ", ".join(f"{k}={v}" for k, v in tags.items()) +
                            (f"；超界: {bad6}" if bad6 else "")})

    # A7 文字入图（提示词含引号包裹的中文）
    miss7 = []
    for name, t in texts.items():
        if not re.search(r'文字[:：].*[""""].*' + CN, t) and not re.search(r'[""]' + CN, t):
            miss7.append(name)
    exp.append({"text": "图中文字直接写进提示词（引号包裹的中文文案）", "passed": not miss7,
                "evidence": "未检出文字入图的篇: " + (", ".join(miss7) if miss7 else "无（全部文字入图）")})

    # A8 不新增未验证事实：正文数字都能在源长文找到
    offenders = {}
    for name, t in texts.items():
        _, body = frontmatter_and_body(t)
        sec = strip_tags(strip_fences(body_section(body, POST_BODY_RE) or body))
        novel = (numbers(sec) - src_nums) - WHITELIST
        # 去掉 ICD/DSM 版本号已含在源；剩余即可疑
        if novel: offenders[name] = sorted(novel)
    exp.append({"text": "不新增未验证事实：正文统计数字均见于源长文", "passed": not offenders,
                "evidence": "可疑新数字: " + (json.dumps(offenders, ensure_ascii=False) if offenders else "无（全部可溯源）")})

    passed = sum(1 for e in exp if e["passed"])
    grading = {
        "expectations": exp,
        "summary": {"passed": passed, "failed": len(exp) - passed, "total": len(exp),
                    "pass_rate": round(passed / len(exp), 2)},
    }
    pathlib.Path(out_json).write_text(json.dumps(grading, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"{outdir.name}: {passed}/{len(exp)} 通过  (pass_rate={grading['summary']['pass_rate']})")
    for e in exp:
        print(f"  [{'✓' if e['passed'] else '✗'}] {e['text']}")

if __name__ == "__main__":
    main()
