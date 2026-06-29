---
name: seo-artical-creator
description: >-
  为 NBDpsy 心理咨询官网（www.nbdpsy.com）创作面向 SEO + GEO 的心理科普 pillar 长文，
  复用最初四篇 pillar（CPTSD / 依恋修复 / 职场倦怠 / 留学生心理）验证过的「查证优先 → GEO 化结构 →
  合规校验 → 生成即发布（默认署名胡佰亿）」全流程。只要用户提到「写博客长文 / pillar / SEO 文章 / GEO 内容 /
  心理科普长文 / 新增一篇支柱文章 / 把某个心理主题写成官网文章 / 给博客补内容 / 长尾关键词文章」，
  即使没说"SEO"或"pillar"字样，也应使用本 skill；它同时覆盖把 pillar 改写为公众号/头条/知乎分发稿。
  本 skill 是 NBDpsy 专用（绑定其 blog_posts 表、品牌话术与合规红线），不适用于其它站点的泛化写作。
---

# SEO/GEO 心理科普 Pillar 长文创作

为 NBDpsy 官网博客产出**可被搜索引擎收录、且被 AI 引擎引用**的心理科普长文。本 skill 把首批四篇 pillar（均已纯汉字 4300–4900 字入库）跑通的方法固化下来，让"写下一篇"不必从零摸索。

**项目背景一句话**：NBDpsy 是咨询师全员北大硕士/博士的**纯线上**华人心理咨询工作室。全站 URL 数过少是收录近零的根本约束——本 skill 的使命就是持续"加优质内容"，而非投机取巧。这是 YMYL（健康）领域，**只做白帽，绝不编造**。

## 何为 GEO，为什么结构这么定

SEO 让网页被搜索引擎收录；GEO（Generative Engine Optimization）让内容被 ChatGPT / 豆包 / 元宝 / 文心等 AI 引擎**抓取后愿意引用**。Princeton 的 GEO 研究实证：带出处的统计数据使被引概率 +41%，专家引语 +28%。所以下面每条结构要求都有它的"为什么"——答案前置是因为正文前 1/3 是 AI 引用热区；带出处统计、专家引语、满属性 schema 都是为了让 AI 判定"这段可信、可引"。**理解动机后可灵活发挥，不要机械套模板。**

## 完整流程（六步，每步都有验证闸门）

```
1. 选题与定位      → 验证：长尾词有真实搜索量 + 契合 NBDpsy 定位 + 与已有 pillar 不重复
2. 查证优先(研究)  → 验证：≥3 真实统计 + ≥2 专家引语 + ≥6 参考文献，逐条 WebFetch 核实可达且口径正确
3. GEO 化撰写      → 验证：对照 references/pillar-spec.md 硬性清单逐条自检
4. 合规 + 字数校验 → 验证：纯汉字 3000–5000（脚本计数）+ 链接全可达 + 敏感词扫描 + 危机声明在位
5. 生成即发布      → 验证：脚本插入 status='published' + 署名胡佰亿 + published_at；slug 已存在则跳过
6. 提醒管理员复查  → 验证：发布后给出网页 URL 提醒管理员核查；有问题后台下架/改；可选三平台分发
```

多步任务先建 TodoWrite 看板，每步勾掉。

---

### 第 1 步 · 选题与定位

好的 pillar 选题 = **高意图长尾词** × **契合 NBDpsy 能为之背书的领域**。首批四篇的选法可作模板：

| Pillar | 主关键词意图 | 为何契合 NBDpsy |
|--------|------------|----------------|
| 复杂性创伤 CPTSD | "CPTSD 是什么 / 和 PTSD 区别 / 自救" | 创伤是北大背景咨询师的专业纵深 |
| 依恋修复 | "回避型依恋怎么办 / 焦虑型自救" | 亲密关系是高频咨询主诉 |
| 职场倦怠 burnout | "职场倦怠怎么办 / 想辞职是不是倦怠" | 覆盖在职成年来访 |
| 留学生心理 | "留学生抑郁怎么办 / 中文心理咨询" | **纯线上=可服务海外华人**，独特卖点 |

选题自检：①主关键词是用户真会搜的问句式短语（不是机构黑话）；②NBDpsy 在该领域有真实专业资历可署名（E-E-A-T 不可伪造）；③与已上线 pillar 不撞车，但可互相内链（四篇彼此 `/blog/{slug}` 交叉引用，织成主题网）。

不确定选哪个主题时，**先问用户**，或用 WebSearch 看几个候选词的搜索结果丰富度后给推荐，不要自己闷头定。

### 第 2 步 · 查证优先（这是 GEO 的命门，也是最易翻车处）

**先查证、后动笔。** 全文需要 ≥3 处带出处真实统计、≥2 处真实专家引语、≥6 条真实参考文献。每一个数字、每一条引用：

- 用 **WebSearch** 找权威源（DSM-5-TR / ICD-11 官方页、PubMed/DOI、CDC/WHO、领域奠基著作）。
- 用 **WebFetch 逐条打开**，确认 URL 可达**且内容真的是你引用的口径**——不是标题像就行。
- **严禁编造数字、DOI、PMID 或专家原话。** 宁可少写一条，不可伪造一条。这是 YMYL 红线，一旦被发现编造，E-E-A-T 直接归零。
- **已知陷阱**：NCBI（PubMed/PMC）对机器访问限速，WebFetch 可能拿不全文。因为是「生成即发布」、数字会带着胡佰亿署名直接上线，拿不准的引文数字**宁可不写也不要硬猜**；若确需保留，在 frontmatter 标注"待人工核对 PMID xxx"并在提醒管理员时点名复核。
- 专家引语用**已发表文献/公开演讲里真专家的原话或紧密转述**（如 van der Kolk《身体从未忘记》、Jonice Webb 童年情感忽视、Judith Herman 三阶段康复）。文章默认署名胡佰亿（真人），**绝不得把虚构引语安到他或任何 NBDpsy 咨询师名下**。

把核实通过的素材先列成清单（数字+出处URL+口径），再进入撰写。可参考 `assets/example-pillar-cptsd.md`（首篇 CPTSD 范文）看素材如何落进正文与 `citations`。

### 第 3 步 · GEO 化撰写

打开 **`references/pillar-spec.md`**，对照其硬性清单逐条写。骨架记忆点：

- **H1 之后第一段就是 TL;DR**（80–120 字，能独立回答标题问题）——AI 引用最爱抓这段。
- **共情先于科普**：面向受困扰的成年人，第二段先接住情绪，再讲知识。这是心理科普与普通 SEO 文的关键差异。
- H2 用**用户搜索短语**作小标题；段落 ≤150 字；至少一张 **markdown 对比表**（如 PTSD vs CPTSD）。
- 带出处统计就地嵌可点链接；专家引语注明出处。
- 文末 **5–8 个 FAQ**（Q 用真实搜索短语、A 第一句直答）+ **≥6 条参考文献**。
- 正文自然嵌 **2–4 处站内链接**（`/services/*`、`/counselors`、相邻 pillar 的 `/blog/{slug}`），锚文本用精确关键词，禁"点击这里"。

产出写到 `seo-geo/content/drafts/{slug}.md`，**YAML frontmatter + 正文**，frontmatter 字段见 `references/pillar-spec.md`（title/slug/excerpt/meta_description/faq/citations/internal_links/target_keywords/author_name）。`author_name` 默认 `胡佰亿`。slug 用拼音 ASCII 连字符分隔。

### 第 4 步 · 合规 + 字数校验（发布前必须全绿）

```bash
# 纯汉字字数（区间 3000–5000，脚本直接给判定）
bash scripts/count_hanzi.sh seo-geo/content/drafts/{slug}.md

# 参考文献/内链 URL 可达性初筛（HTTP 层，便宜地揪死链；语义正确性仍须第2步的 WebFetch 保证）
bash scripts/check_links.sh seo-geo/content/drafts/{slug}.md
```

人工/语义自检清单：

- **敏感词红线**：不得用「治疗 / 诊断 / 治愈 / 医院 / 医生」描述本工作室服务；合规口径=「咨询 / 干预 / 评估 / 陪伴」。学术名词（PTSD、CBT、EMDR、转述文献）可保留。
- **不夸大**：禁「彻底摆脱」「100%」「根治」之类。
- **危机声明**必须在文末固定出现：`本文不构成医疗建议；如处于心理危机请拨打希望24热线 4001619995 或全国统一心理援助热线 12356`。
- 字数若不达标 → **返工补内容**（首批四篇都经过"字数返工闭环"才达 3000+），不要靠注水凑数。

字数与链接全绿、合规自检通过后，才进入发布。

### 第 5 步 · 生成即发布（默认署名胡佰亿）

用脚本把文章插入 `blog_posts` 并**直接发布**：默认 `status='published'` + `author_name=胡佰亿` + `published_at=NOW()`（剥掉正文首行 `# 标题` 避免与页面 hero 重复 H1；slug 已存在则**跳过不覆盖**——线上可能已被管理员编辑过）。

> **为什么默认发布**：本项目采用「发布优先、事后复查」——AI 生成即上线、署名胡佰亿，管理员上网页核查，有问题再后台下架/改。这把人工环节从"发布前闸门"挪到"发布后兜底"，提速，但要求 ① 管理员及时核查 ② AI 自己的查证/复审必须更严（数字会带着真人署名一起上线）。如确需先压草稿，加 `--draft`。

```bash
# 本地验证 SQL（--draft 不发布、--cleanup 插完即删，测试自清理）
python3 scripts/insert-pillar-drafts.py \
  --dsn "host=localhost user=root dbname=psychology_counseling" \
  --drafts-dir seo-geo/content/drafts --draft --cleanup

# 生产发布（webhook 失效须先手动 pull；从 .env 取推送凭据，脚本发布后自动推百度+IndexNow）
ssh nbdpsy bash -s <<'EOF'
set -e
cd /home/ubuntu/NBDpsy
git fetch origin master -q && git merge --ff-only origin/master
ENVF=后端服务/管理后端/.env
# 数据库密码请从生产 .env / 密码管理器注入，切勿硬编码（公开仓库已脱敏）
export PGPASSWORD="${PGPASSWORD:-$(grep -E '^DB_PASSWORD=' "$ENVF" | cut -d= -f2- | tr -d "\"'")}"
export SITE_URL=$(grep -E '^SITE_URL=' "$ENVF" | cut -d= -f2- | tr -d "\"'")
export BAIDU_PUSH_TOKEN=$(grep -E '^BAIDU_PUSH_TOKEN=' "$ENVF" | cut -d= -f2- | tr -d "\"'")
export INDEXNOW_KEY=$(grep -E '^INDEXNOW_KEY=' "$ENVF" | cut -d= -f2- | tr -d "\"'")
python3 .claude/skills/seo-artical-creator/scripts/insert-pillar-drafts.py \
  --dsn "host=localhost user=root dbname=psychology_counseling" --drafts-dir seo-geo/content/drafts
EOF
```

入库映射：author_name 优先用 frontmatter（缺省用 `--author`，默认胡佰亿）；citations/faq → JSONB；category_slug → category_id；tags 不插（留管理员后台补）。**脚本在发布后会自动把新文章 URL 推百度+IndexNow**（凭据取自上面导出的 env；缺凭据则跳过并提示，不影响已发布）。注意：经 admin 后台发布才走 seo.rs 的即时推送，本脚本走 SQL 发布、推送由脚本自身完成。

### 第 6 步 · 提醒管理员复查 / 可选分发

- **发布后立即提醒管理员上网页核查**：给出文章 URL `https://www.nbdpsy.com/blog/{slug}`，请管理员核对内容与署名是否妥当。（搜索引擎推送已由第 5 步脚本在发布后自动完成，无需手动推。）
- **有问题怎么办（管理员后台兜底）**：发现内容或署名有误，管理员在管理后台直接**下架**（状态改回 `draft` 或删除）或**修改**（改 `author_name` 署名、改正文）。不必回到本流程。
- **ISR 缓存**：新发布文章若网页未即时出现，多为 marketing-web 的 ISR 缓存，按 [[marketing-deploy-isr-chown]] 清缓存 + 重启 marketing-web。
- **可选：分发改写**。若要把 pillar 二次分发到公众号/头条/知乎，读 **`references/distribution-spec.md`**，每篇各出三版（gzh/toutiao/zhihu），写到 `seo-geo/content/distribution/{slug}--{platform}.md`。核心纪律：**改写不改事实**、敏感词红线相同、每版嵌一次品牌锚句、保留危机声明。

---

## 发布前双重复审（发布优先模式下尤其重要）

因为现在是「生成即发布」、上线前没有人工闸门，AI 自己的复审就是最后一道关。发布前务必：先自查 `references/pillar-spec.md` 全清单（R1 合规），再以"一个受困扰的真人读到这篇会不会被接住、会不会被误导"的视角通读（R2 质量）。两关都过再发布——**尤其是查证**：编造的数字/引文会带着胡佰亿的真人署名一起上线，伤害最大。

## 关键文件

| 用途 | 路径 |
|------|------|
| 硬性内容规格 + frontmatter schema | `references/pillar-spec.md` |
| 三平台分发改写规格 | `references/distribution-spec.md` |
| 范文（首篇 CPTSD，对照学习） | `assets/example-pillar-cptsd.md` |
| 纯汉字计数 + 区间判定 | `scripts/count_hanzi.sh` |
| 参考文献/内链可达性初筛 | `scripts/check_links.sh` |
| 幂等入库并发布（默认署名胡佰亿） | `scripts/insert-pillar-drafts.py` |
| 历史项目记录（选题/状态/教训） | `seo-geo/PLAN.md`（仓库根） |

## 红线速记（违反任一即不合格）

1. 不编造数字 / DOI / PMID / 专家原话——查不到就不写（会带着胡佰亿真人署名上线，伤害最大）。
2. 不用「治疗/诊断/治愈/医院/医生」自我描述；不夸大效果。
3. 危机声明（希望24 4001619995 + 12356）必须在文末。
4. 入库脚本绝不覆盖已存在 slug（线上可能已被管理员改）。
5. 数据/发布只在生产操作；生产是唯一真实来源。发布后必须提醒管理员上网页核查。
