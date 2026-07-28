#!/usr/bin/env python3
"""把一篇过长的正文按 H2 边界拆成「系列篇」（路线② 专用，2026-07-28 老板定案）。

老板原话：「一个长文可以根据字数拆成好几篇 2000 字左右短文，分上中下，或者一二三四，系列篇。」

为什么按 H2 边界而不是按字数硬切：一个章节被劈成两半，读者两篇都读不懂。
所以字数是**目标**不是**切点**——切点永远落在 H2 上，字数用来决定"在哪几个 H2 上切"。
脚本做机械活（分组 / 均衡 / 编号 / 起标题），**承接段与预告段留 TODO 给 agent 写**
（那是内容判断，脚本写不了；参考样本 B 的首句「上一篇我们聊到了「无效化环境」」就是这东西）。

用法:
    split_longform.py --md body.md                    # 按 2000 字/篇自动定篇数
    split_longform.py --md body.md --target 1600      # 改目标字数
    split_longform.py --md body.md --parts 3          # 强制拆 3 篇
    split_longform.py --md body.md --out DIR          # 指定输出目录

输出 <out>/body-01.md … body-NN.md（各自带 frontmatter，可直接喂 typeset_longimage.py）
+ 一份 JSON 报告（每篇字数 / 章节数 / 标题 / 需要补的 TODO 数）。
"""
import argparse
import json
import pathlib
import re
import sys

CN_NUM = '一二三四五六七八九十'
TODO_LINK = '<!-- TODO 承接段：用一两句话说清上一篇讲到哪儿了，再引出这一篇。' \
            '写完删掉本行注释。参考：「上一篇我们聊到了「无效化环境」——…」 -->'
TODO_NEXT = '<!-- TODO 预告段：用一句话说下一篇要讲什么，给个往下追的理由。写完删掉本行注释。 -->'


def split_frontmatter(text):
    m = re.match(r'^---\n(.*?)\n---\n?(.*)$', text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        mm = re.match(r'^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$', line)
        if mm:
            meta[mm.group(1)] = mm.group(2).strip().strip('"').strip("'")
    return meta, m.group(2)


def han(text):
    """可见字符数，**口径与 typeset_longimage.py 图上那行「全文N字」一致**——
    两处不一致的话，运营按 --target 2000 拆出来的篇，图上会写着「全文2400字」。
    剥掉 markdown 结构标记与空白，剩下的正文字符（含标点、含英文）全算。"""
    t = re.sub(r'<!--.*?-->', '', text, flags=re.S)
    t = re.sub(r'^\s*(#{1,6}\s+|[-*·○]\s+)', '', t, flags=re.M)   # 行首标记
    t = re.sub(r'^\s*\|[-:\s|]+\|\s*$', '', t, flags=re.M)        # 表格对齐行
    t = re.sub(r'[|*`]', '', t)                                   # 表格竖线与强调标记
    return len(re.sub(r'\s', '', t))


def split_sections(body):
    """按 H2 切段。第一个 H2 之前的内容是「引言」，恒归第 1 篇。"""
    lines = body.splitlines()
    sections, cur_title, cur = [], None, []
    for line in lines:
        if re.match(r'^##\s+(?!#)', line):          # 只认 H2，H3 留在章节内部
            if cur_title is not None or any(x.strip() for x in cur):
                sections.append((cur_title, '\n'.join(cur).strip()))
            cur_title, cur = line[3:].strip(), [line]
        else:
            cur.append(line)
    if cur_title is not None or any(x.strip() for x in cur):
        sections.append((cur_title, '\n'.join(cur).strip()))
    return [(t, b) for t, b in sections if b]


def group_sections(sections, parts):
    """把 section 均衡分成 parts 组，保持原顺序，绝不拆开单个 section。

    用动态规划求**全局最优**：代价 = Σ(每组字数 − 平均字数)²，平方项让长短两头都被惩罚，
    结果是各篇尽量一样厚。贪心在这里不够——它只看当前一步，会把小尾巴留给中间某一篇
    （同一篇文章拆 3 份：贪心 1257/821/1227，DP 872/1206/1227，方差降三成）。
    剩下的不均来自章节本身的原子性（章节不可再切），不是算法能解决的。
    章节数量级在几十，O(n²·parts) 的开销可以忽略。
    """
    sizes = [han(b) for _, b in sections]
    n = len(sizes)
    prefix = [0] * (n + 1)
    for i, s in enumerate(sizes):
        prefix[i + 1] = prefix[i] + s
    target = prefix[n] / parts

    INF = float('inf')
    dp = [[INF] * (parts + 1) for _ in range(n + 1)]
    cut = [[0] * (parts + 1) for _ in range(n + 1)]
    dp[0][0] = 0
    for i in range(1, n + 1):
        for k in range(1, min(parts, i) + 1):
            for j in range(k - 1, i):                       # 第 k 组 = section[j:i]
                if dp[j][k - 1] == INF:
                    continue
                cost = dp[j][k - 1] + (prefix[i] - prefix[j] - target) ** 2
                if cost < dp[i][k]:
                    dp[i][k], cut[i][k] = cost, j

    bounds, i, k = [], n, parts
    while k > 0:
        j = cut[i][k]
        bounds.append((j, i))
        i, k = j, k - 1
    return [sections[a:b] for a, b in reversed(bounds)]


def series_label(idx, total):
    """2 篇 = 上/下；3 篇 = 上/中/下；4 篇以上 = 一/二/三/四…"""
    if total == 2:
        return '上下'[idx]
    if total == 3:
        return '上中下'[idx]
    return CN_NUM[idx] if idx < len(CN_NUM) else str(idx + 1)


def main():
    ap = argparse.ArgumentParser(description='长文按 H2 边界拆成系列篇（路线②）')
    ap.add_argument('--md', required=True, help='整篇正文 markdown（已去引用、已口语化）')
    ap.add_argument('--target', type=int, default=2000, help='每篇目标字数（默认 2000，口径同图上「全文N字」）')
    ap.add_argument('--parts', type=int, help='强制篇数；不给则按 --target 自动定')
    ap.add_argument('--out', help='输出目录，默认与 --md 同级')
    args = ap.parse_args()

    md_path = pathlib.Path(args.md).expanduser()
    if not md_path.exists():
        print(json.dumps({'ok': False, 'error': f'找不到输入文件：{md_path}'}, ensure_ascii=False))
        return 1

    meta, body = split_frontmatter(md_path.read_text(encoding='utf-8'))
    sections = split_sections(body)
    total = han(body)

    if len(sections) < 2:
        print(json.dumps({
            'ok': False,
            'error': f'正文只有 {len(sections)} 个 H2 章节，没法按章节边界拆',
            'how_to_fix': ['先给正文分出 ## 二级标题再拆',
                           '或者本来就不长，别拆，直接 typeset_longimage.py 出一条']},
            ensure_ascii=False))
        return 1

    parts = args.parts or max(2, round(total / args.target))
    parts = min(parts, len(sections))                # 篇数不能多过章节数

    groups = group_sections(sections, parts)
    parts = len(groups)                              # 分组后可能少一组，以实际为准

    out_dir = pathlib.Path(args.out).expanduser() if args.out else md_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    base_title = meta.get('title', md_path.stem)
    theme = meta.get('theme', 'clean')
    xhs_id = meta.get('xhs_id', '')

    files, report, warnings = [], [], []
    for i, group in enumerate(groups):
        label = series_label(i, parts)
        title = f'{base_title}（{label}）'
        if len(title) > 20:
            warnings.append(f'第 {i + 1} 篇标题 {len(title)} 字，超小红书硬限 20 字：{title}')

        chunks = []
        if i > 0:
            chunks.append(TODO_LINK)
        chunks += [b for _, b in group]
        if i < parts - 1:
            chunks.append(TODO_NEXT)

        fm = [f'title: {title}', f'theme: {theme}']
        if xhs_id:
            fm.append(f'xhs_id: {xhs_id}')
        fm += [f'series_index: {i + 1}', f'series_total: {parts}']
        doc = '---\n' + '\n'.join(fm) + '\n---\n\n' + '\n\n'.join(chunks) + '\n'

        fp = out_dir / f'body-{i + 1:02d}.md'
        fp.write_text(doc, encoding='utf-8')
        files.append(str(fp))
        report.append({'part': i + 1, 'label': label, 'title': title,
                       'chars': han('\n\n'.join(b for _, b in group)),
                       'sections': [t for t, _ in group if t]})

    sizes = [r['chars'] for r in report]
    if max(sizes) > args.target * 1.6:
        warnings.append(f'最长一篇 {max(sizes)} 字，明显超目标——多半是某个 H2 章节本身就很长，'
                        f'章节内部不可再切；要更均匀就先把那一章拆成两个 H2')

    print(json.dumps({'ok': True, 'parts': parts, 'total_chars': total,
                      'target': args.target, 'files': files, 'report': report,
                      'warnings': warnings,
                      'next': '逐篇填掉 TODO 承接段/预告段并删注释，再跑 typeset_longimage.py'},
                     ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
