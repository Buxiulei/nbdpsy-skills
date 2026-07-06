# 长文审查清单（心理科普 pillar）

> 审查对象：nbdpsy-seo-artical-creator 产出的 pillar 长文 Markdown（含 frontmatter）。
> 立场：预设有问题，逐条找证据；不确定按 FAIL。

## 确定性检查（先跑，JSON 输出与 exit code 原样记入报告）

路径说明：`../nbdpsy-seo-artical-creator/` 指安装后与 nbdpsy-content-reviewer 同级的兄弟 skill 目录；命令在本 skill 目录下执行，或换算为绝对路径。

| 命令 | 预期 | exit 语义 |
|------|------|-----------|
| `python3 ../nbdpsy-seo-artical-creator/scripts/count_hanzi.py <文件>` | 纯汉字 3000–5000 | JSON 输出；区间外 exit 2 |
| `python3 ../nbdpsy-seo-artical-creator/scripts/check_links.py <文件>` | dead 为空 | JSON 输出；有 dead 链接 exit 1（`suspect` 不算 dead，但须逐条人工点开定性后写入报告） |
| `python3 ../nbdpsy-seo-artical-creator/scripts/lint_markdown.py <文件> --citations <citations 条数>` | ok=true，无违规 | JSON 输出；bold-flanking（加粗渲染兼容性）或 citation-marker（文内引用覆盖率）任一违规 exit 1（`--citations` 取 frontmatter `citations` 数组条数） |

**渲染可见层抽查**（文章已发布、拿到线上 URL 时必做，不能只查 Markdown 源文件——源文件语义正确不代表渲染正确，这正是本次生产事故的漏检点）：抓取线上渲染页，剔除 `<script>` 与所有 HTML 标签后统计残留的可见 `**`，必须为 0：

```bash
curl -s https://www.nbdpsy.com/blog/<slug> | python3 -c "import sys,re;h=sys.stdin.read();h=re.sub(r'<script[\s\S]*?</script>','',h);print(re.sub(r'<[^>]+>','',h).count('**'))"
```

输出非 0 = 渲染层加粗失败，FAIL。

## 判断性检查（逐条 PASS/FAIL + 证据 + 位置）

1. **带出处统计 ≥3 个，且文内每个数字能在参考文献找到对应源**。逐个数字反查：正文出现的每一处统计（百分比/倍数/样本量），都要在参考文献区找到对应条目，且该条目内容确实支撑这个口径——标题像不算，要点开核对。找不到对应源的数字 = FAIL 并逐个列出。
2. **专家引语 ≥2 条，抽 1 条网络搜索核实非编造**。任选（优先选最可疑的）一条引语 WebSearch 原话或紧密转述的出处；搜不到、或搜到的原话与文内明显不符 = FAIL。凡把引语安到胡佰亿或任何 NBDpsy 咨询师名下的虚构引语，直接 FAIL。
3. **正文数字标注 `[[n]](url)` 与文末参考文献逐条对应且 URL 一致**：文末参考文献区每条至少被正文标注一次（无未标注文献），正文每个 `[[n]]` 都能落到参考文献区对应序号且 URL 一致（无孤儿标注）。**缺任何一条对应关系、或正文存在无标注的统计/引语，即 FAIL**——「正文提到来源名称」不算标注，必须是可点击的 `[[n]](url)` 数字标记。列出不对应的条目。
4. **TL;DR 在文首，80–120 字**。数一遍字数，超界或缺失 = FAIL。
5. **FAQ 5–8 条在文末**。数条数，位置不在文末或条数超界 = FAIL。
6. **≥1 张对比表**（Markdown 表格，真对比——两列以上、有信息增量，不是排版凑数）。
7. **站内内链 2–4 处，且 slug 真实存在**。逐个内链核对目标 `/blog/{slug}` 真的是已上线/已入库文章（对照站点或 drafts 目录），编造的 slug = FAIL。
8. **危机声明在文末**：必须含希望24热线 **4001619995** 与全国统一心理援助热线 **12356** 两个号码（参考口径：`本文不构成医疗建议；如处于心理危机请拨打希望24热线 4001619995 或全国统一心理援助热线 12356`）。缺任一号码或不在文末 = FAIL。
9. **全篇无「治疗/诊断/治愈/医院/医生」自我描述**。禁止用这五个词描述 NBDpsy 自身服务（合规口径=「咨询/干预/评估/陪伴」）；学术名词与对研究文献的转述（如"心理治疗研究显示…"、PTSD、CBT）可保留——逐处出现位置判定属哪种，拿不准 = FAIL。
10. **署名与 E-E-A-T 一致**：作者为胡佰亿（或用户明确指定的其他真人），frontmatter 与文内署名一致，不得虚构作者头衔/资历。
    - **约定**：若 frontmatter 无 `author` 字段但 `review_status` 注明「发布脚本兜底署名（默认胡佰亿）」等待发布流程时，该项按约定标注 PASS（备注约定依据），不按"不确定=FAIL"硬判。
