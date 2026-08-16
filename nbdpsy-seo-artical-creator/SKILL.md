---
name: nbdpsy-seo-artical-creator
description: >-
  为 NBDpsy 心理咨询官网（www.nbdpsy.com）创作面向 SEO + GEO 的心理科普 pillar 长文，
  复用最初四篇 pillar（CPTSD / 依恋修复 / 职场倦怠 / 留学生心理）验证过的「查证优先 → GEO 化结构 →
  合规校验 → 生成即发布（默认署名胡佰亿）」全流程。只要用户提到「写博客长文 / pillar / SEO 文章 / GEO 内容 /
  心理科普长文 / 新增一篇支柱文章 / 把某个心理主题写成官网文章 / 给博客补内容 / 长尾关键词文章」，
  即使没说"SEO"或"pillar"字样，也应使用本 skill；它同时覆盖把 pillar 改写为公众号/头条/知乎分发稿。
  本 skill 是 NBDpsy 专用（绑定其博客发布 API、品牌话术与合规红线），不适用于其它站点的泛化写作。
---

# SEO/GEO 心理科普 Pillar 长文创作

> **约定**：以下 `{SKILL_DIR}` 指本文件所在目录（skill 根目录）。「内容工作区」指草稿产物目录，实际路径用 `python3 {SKILL_DIR}/scripts/nbdpsy_common.py workspace` 查询——解析顺序：`NBDPSY_WORKSPACE` 环境变量最优先；未设时若当前目录下存在 `seo-geo/content`（如在 NBDpsy 仓库根）则用之（向后兼容）；否则 `~/nbdpsy-content`。

为 NBDpsy 官网博客产出**可被搜索引擎收录、且被 AI 引擎引用**的心理科普长文。本 skill 把首批四篇 pillar（均已纯汉字 4300–4900 字发布上线）跑通的方法固化下来，让"写下一篇"不必从零摸索。

**项目背景一句话**：NBDpsy 是咨询师全员北大硕士/博士的**纯线上**华人心理咨询工作室。全站 URL 数过少是收录近零的根本约束——本 skill 的使命就是持续"加优质内容"，而非投机取巧。这是 YMYL（健康）领域，**只做白帽，绝不编造**。

## 何为 GEO，为什么结构这么定

SEO 让网页被搜索引擎收录；GEO（Generative Engine Optimization）让内容被 ChatGPT / 豆包 / 元宝 / 文心等 AI 引擎**抓取后愿意引用**。Princeton 的 GEO 研究实证：带出处的统计数据使被引概率 +41%，专家引语 +28%。所以下面每条结构要求都有它的"为什么"——答案前置是因为正文前 1/3 是 AI 引用热区；带出处统计、专家引语、满属性 schema 都是为了让 AI 判定"这段可信、可引"。**理解动机后可灵活发挥，不要机械套模板。**

## 完整流程（七步，每步都有验证闸门）

```
1. 选题与定位      → 验证：长尾词有真实搜索量 + 契合 NBDpsy 定位；署名咨询师的已先调研其背景/方法论/
                     流派/适应症场景；与已有 pillar 重复时已写明二次创作的差异化切口（不因重复就弃题）
2. 查证优先(研究)  → 验证：≥3 真实统计 + ≥2 专家引语 + ≥6 参考文献，逐条打开网页核实可达且口径正确；
                     素材清单落盘 $WS/drafts/{slug}.sources.md（本步交付物，第 4 步的唯一对账依据）
3. GEO 化撰写      → 验证：对照 references/pillar-spec.md 硬性清单逐条自检；文内引用只写【引: ...】简称标记；
                     内链在列完 H2 骨架时就定好嵌入点（禁导航节/延伸阅读块/排比连嵌，见第 3 步「内链」一节）
4. 引用落地(专职)  → 输入：草稿 + {slug}.sources.md（缺清单文件即打回第 2 步，不许联网自查顶替）
                     验证：标记全部换成 [[n]](url) + 参考文献区与 citations 生成；全文「【引:」残留数=0（实跑机检）
5. 发布前统一预检  → 验证：preflight.py 一条命令机检 pillar-spec 全部可判定项，**必须全绿（无 fail）**；manual 项逐条自查
6. 生成即发布      → 验证：preflight 全绿后才可 publish_post.py；输出 published 含本篇（默认署名胡佰亿）；slug 已存在则 skipped 不覆盖
7. 提醒管理员复查  → 验证：发布后给出网页 URL 提醒管理员核查；有问题后台下架/改；可选三平台分发
```

> **第 4 步是 2026-07-26 老板定案新增的职责分离**：写作只写人类可读的引用简称，编号 / URL / 参考文献区 / frontmatter `citations` 由专职引用 agent 统一落地。**成品标准一字未改**——发布态仍是 `[[n]](url)` 与 `citations` 逐字一致、≥3 带出处统计 / ≥2 专家引语 / ≥6 参考文献、preflight 全绿。变的只是写作过程。

多步任务先维护一份任务清单，每步完成后勾掉。

---

### 开跑前 · 环境自检（首次使用或报错时）

```bash
python3 {SKILL_DIR}/scripts/env_check.py --profile seo --install
```

ready=true 才开跑。缺 Python 包会自动补装；缺发布凭据按提示：`python3 {SKILL_DIR}/scripts/nbdpsy_common.py doctor` 查看缺项 → 向管理员索要『凭据配置包』→ secret import 一键导入。日常使用无需重复跑。

### 第 1 步 · 选题与定位

好的 pillar 选题 = **高意图长尾词** × **契合 NBDpsy 能为之背书的领域**。首批四篇的选法可作模板：

| Pillar | 主关键词意图 | 为何契合 NBDpsy |
|--------|------------|----------------|
| 复杂性创伤 CPTSD | "CPTSD 是什么 / 和 PTSD 区别 / 自救" | 创伤是北大背景咨询师的专业纵深 |
| 依恋修复 | "回避型依恋怎么办 / 焦虑型自救" | 亲密关系是高频咨询主诉 |
| 职场倦怠 burnout | "职场倦怠怎么办 / 想辞职是不是倦怠" | 覆盖在职成年来访 |
| 留学生心理 | "留学生抑郁怎么办 / 中文心理咨询" | **纯线上=可服务海外华人**，独特卖点 |

选题自检：①主关键词是用户真会搜的问句式短语（不是机构黑话）；②NBDpsy 在该领域有真实专业资历可署名（E-E-A-T 不可伪造）；③与已上线 pillar 不撞车，但可互相内链（四篇彼此 `/blog/{slug}` 交叉引用，织成主题网）。

不确定选哪个主题时，**先问用户**，或用你的网络搜索能力看几个候选词的搜索结果丰富度后给推荐，不要自己闷头定。

**署名咨询师 → 动笔前必须先调研本人（2026-08-01 运营定案）**

文章默认署名胡佰亿；**一旦 `author_name` 换成某位在职咨询师，这篇就不再是"通用科普换个名字"**——署名意味着这篇代表那个人的专业判断。E-E-A-T 里的 Expertise / Authoritativeness 是绑在具体的人身上的：读者点进作者页看到的是精神分析取向的受训年表，正文却全程讲 CBT 的行为实验，这种错位既伤专业可信度，咨询师本人也没法转发。所以**动笔前先把人调研清楚**，再决定文章的理论支柱、解释路径与行动建议往哪边倒。

调研走生产库只读查询（`counselors.profile_sections` 是咨询师自己填的档案，官网详情页渲染的就是它）：

```bash
# 1) 先按姓名/工号找到人（display_name 是姓名字段，不是 name）
ssh nbdpsy "PGPASSWORD='Psychology@2024' psql -h localhost -U root -d psychology_counseling -c \"SELECT id, emp_no, display_name, title, experience_years, is_accepting FROM counselors ORDER BY id;\""

# 2) 看这位有哪些段（顶层键：notes/methods/training/highlight/experience/philosophy/specialties/unsupported/testimonials）
ssh nbdpsy "PGPASSWORD='Psychology@2024' psql -h localhost -U root -d psychology_counseling -t -A -c \"SELECT jsonb_object_keys(profile_sections) FROM counselors WHERE emp_no='EMP20260709001';\""

# 3) 逐段取（整份 jsonb_pretty 可能 40KB+，必须分段，别一次全拉）
ssh nbdpsy "PGPASSWORD='Psychology@2024' psql -h localhost -U root -d psychology_counseling -t -A -c \"SELECT jsonb_pretty(profile_sections->'methods') FROM counselors WHERE emp_no='EMP20260709001';\""
```

必看的段与它们各自决定什么：

| 段 | 内容 | 决定文章的什么 |
|---|---|---|
| `highlight` | 一句话简介（学历 + 流派 + 擅长） | 快速定位这个人，先看它 |
| `methods` | 方法论 / 流派清单（name + desc） | **理论支柱与行动建议的取向**——文章给的方法必须是他真会用的 |
| `specialties` | 擅长议题与适应症场景（title + desc） | 选题落在哪个场景，共情段与场景化描写往哪写 |
| `philosophy` | 理念与风格 | 语气取向（是"陪你看见"还是"给你工具"） |
| `training` / `experience` | 受训年表 / 时长、资质编号、工作履历 | 需要交代作者权威性时的**可核实事实** |
| `unsupported` | **明确不接的议题** | **选题红线**——选题落进这里说明人题不匹配，换人署名或换选题 |

**E-E-A-T 纪律（三条，违反任一即不合格）**：

- 以上都是**可核实的资历事实**，可用于确立文章的专业视角与理论取向，也可在正文里以"作者的受训背景是……"这类方式点出；
- **绝不可编造该咨询师的原话、来访者案例、或档案里没有的头衔**。文中不得出现「我的来访者曾……」这类**无法核实**的第一人称案例——这是 R4「绝不得把虚构引语安到咨询师名下」的同一条红线，只是这次连"案例"一并禁掉；
- 档案字段本身可能是**截断的**（生产实例：某咨询师 `philosophy.description` 末尾不完整）——**只用完整的那部分，严禁替他补全后半句**。你补的那半句会挂着他的真名上线。

**选题与已有文章重复时：不弃题，做二次创作（2026-08-01 运营定案）**

以前撞车就换题，结果是热门主题全站只能有一篇、后来的咨询师想写就没得写。**新规则：重复不是弃题的理由，而是二次创作的起点**——依据署名咨询师自身的特质／方法论／流派／适应症场景，把同一个主题重新切一遍。同一个现象在精神分析和 CBT 里的解释路径本来就不同，这不是洗稿，是两篇真的不一样的文章。

差异化维度四选一或组合，**且必须在动笔前的 brief 里写明这一篇的切口是哪个**：

1. **流派不同**——同一现象，精神分析视角 vs CBT 视角 vs 正念视角，理论支柱与给出的行动建议整套换掉；
2. **适应症场景不同**——同一心理机制，落在亲密关系 vs 职场 vs 原生家庭；
3. **切入问题不同**——已有文答的是"是什么／怎么办"，新文答"我为什么会这样"；
4. **独占概念不同**——一个理论概念只许一篇拿来做主轴，其它篇最多一句带过并内链过去。

切口定了之后还要过三道形态检查，防"切口不同、成品照样撞车"：**主关键词不同**（不能是同一个词的近义写法）、**H2 骨架不同**、**对比表主题不同**。最后**新旧两篇互相内链**（占 R9 的站内链接名额）——目标是织成一个主题集群、彼此喂流量，而不是两篇争同一批搜索词、把自己的排名蚕食掉。

### 第 2 步 · 查证优先（这是 GEO 的命门，也是最易翻车处）

**先查证、后动笔。** 全文需要 ≥3 处带出处真实统计、≥2 处真实专家引语、≥6 条真实参考文献。每一个数字、每一条引用：

- 用你的**网络搜索能力**找权威源（DSM-5-TR / ICD-11 官方页、PubMed/DOI、CDC/WHO、领域奠基著作）。
- **逐条打开网页核实**，确认 URL 可达**且内容真的是你引用的口径**——不是标题像就行。
- **严禁编造数字、DOI、PMID 或专家原话。** 宁可少写一条，不可伪造一条。这是 YMYL 红线，一旦被发现编造，E-E-A-T 直接归零。
- **已知陷阱**：NCBI（PubMed/PMC）对机器访问限速，打开网页核实时可能拿不到全文。因为是「生成即发布」、数字会带着胡佰亿署名直接上线，拿不准的引文数字**宁可不写也不要硬猜**；若确需保留，在 frontmatter 标注"待人工核对 PMID xxx"并在提醒管理员时点名复核。
- 专家引语用**已发表文献/公开演讲里真专家的原话或紧密转述**（如 van der Kolk《身体从未忘记》、Jonice Webb 童年情感忽视、Judith Herman 三阶段康复）。文章默认署名胡佰亿（真人），**绝不得把虚构引语安到他或任何 NBDpsy 咨询师名下**。

**本步交付物：素材清单必须落盘成文件**（不是记在对话里）

把核实通过的素材列成清单写进 **`$WS/drafts/{slug}.sources.md`**——与草稿 `$WS/drafts/{slug}.md` **同目录、同名**，只是扩展名换成 `.sources.md`（`WS` 见开头工作区约定：`WS=$(python3 {SKILL_DIR}/scripts/nbdpsy_common.py workspace)`）。查证轮一结束就落盘，**清单没落盘 = 第 2 步没做完**。

每条**固定五个字段**（字段名照抄，别改别减）：

| 字段 | 说明 |
|------|------|
| `简称` | 写作态标记 `【引: 作者/机构 年份, 文献简称】` 里用的那个简称，与正文逐字一致 |
| `作者或机构` | 第一作者姓氏（英文文献）或中文全名；机构文献写机构名（WHO / APA / 中国心理学会） |
| `年份` | 四位数字；不确定写 `n.d.` |
| `URL` | **逐字最终形态**——引用 agent 直接抄进正文，**不许再"整理"**（去 utm、换 http/https、补删尾斜杠都算改动，会让 `CITE-MATCH` 失配）。不要只记"某某官网" |
| `口径原文` | 核实时页面上看到的那句原话/数据原文，用来证明"引的就是它说的" |

排版用 markdown 表格或"每条一个小节"都行，只要五个字段齐、一条一条分得开。

> **`.sources.md` 是工作文件，不是待发布稿。** `publish_post.py` 的批量模式（`--drafts-dir`、以及不带参数的默认全目录）**已排除 `*.sources.md`**（2026-07-26 加，实测清单被跳过、正常草稿照发、exit 0），所以清单**就该留在 drafts 目录里**，别为了让批量跑绿把它挪走或删掉——它是审查端复核"引的是不是它说的"的唯一依据，也是引用落地步的输入。

**为什么非落盘不可**：第 4 步「引用落地」由**独立于写作的引用 agent** 执行（在 nbdpsy-content-pipeline 里是真的另派子代理），它**没有本轮对话历史，只能读文件**。清单不落盘 → 引用 agent 拿不到对账依据 → 每条都只能自己联网现查，而那正是整套流程里**编造风险最高**的路径。这份文件就是反编造防线的地基。

素材如何落进 frontmatter `citations` 与文末参考文献区，可参考 `assets/example-pillar-cptsd.md`（首篇 CPTSD 范文，示范的是发布态的**结构**；**文内数字标注的形态以 `references/pillar-spec.md`「发布态」节的正例为准**，别照范文正文学）。

### 第 3 步 · GEO 化撰写

打开 **`references/pillar-spec.md`**，对照其硬性清单逐条写。骨架记忆点：

- **H1 之后第一段就是 TL;DR**（80–120 字，能独立回答标题问题）——AI 引用最爱抓这段。
- **共情先于科普**：面向受困扰的成年人，第二段先接住情绪，再讲知识。这是心理科普与普通 SEO 文的关键差异。
- H2 用**用户搜索短语**作小标题；段落 ≤150 字；至少一张 **markdown 对比表**（如 PTSD vs CPTSD）。
- 带出处统计、专家引语就地写**引用简称标记**（见下），**不写链接、不写编号**。
- 文末 **5–8 个 FAQ**（Q 用真实搜索短语、A 第一句直答）+ **≥6 条参考文献**（参考文献区由第 4 步生成，撰写时不必手写）。
- 正文自然嵌 **2–4 处站内链接**（`/services/*`、`/counselors`、相邻 pillar 的 `/blog/{slug}`），锚文本用精确关键词，禁"点击这里"。**怎么嵌见下面单独一节——这是个先规划的动作，不是写完再补。**

**内链：列完 H2 骨架就定嵌入点，别写完再补（强制，2026-08-02 运营定案）**

写完再补，补出来的必然是一块「相关阅读」——这正是运营打回过的东西（原话：「这是干啥？？莫名其妙，与前文不连贯」）。所以把它提前成**动笔前的一个动作**：

1. **列出要链的那几篇**（相邻 pillar、同主题簇的姊妹篇、对应的 `/services/*`），一般 2–4 条。
2. **拿每一条去 H2 骨架里找它天然对应的位置**——找**对位结构**优先：正文里那些**分阶段 / 分类型 / 分场景**的小节，往往一一对应着要链的那几篇。
   - 实例（本站 `yue-taobi-shejiao-yue-haipa`）：正文有「循环四站」一节（事前 / 注意力内转 / 安全行为 / 事后复盘），要链的三篇正好对上第一、二、四站 → 三条链接分别写进那三站的机制描述里，读者读到那一站正好可以点进去深入。
   - 没有对位结构时：就近嵌在**首次提到该话题**的那一句上。
   - **实在找不到自然位置的那一条，就别链**——内链是给读者的岔路口，不是配额任务。宁可只嵌 2 条（R9 下限）也不要硬塞。
3. **动笔时把链接写成那句话的一部分**，让它承接所在段落正在讲的论点；⛔ 不是在段末附加一句"另见 X"。

三条硬禁令（审核清单第 14、16 条会拦）：

- ⛔ **不得为「相关阅读 / 系列导航」单开 H2 章节。**
- ⛔ **也不许整块缩成 `> **延伸阅读**：A、B、C`** ——缩小的导航块还是导航块，读者照样被切出论证。
- ⛔ **不许三处用同一句式排比连嵌**（「…的机制另有专文：X」×3）——那是把导航节拆散摊在正文里，一眼就看得出是推荐位。每处措辞随所在段落的语境走。

**提到站内其它文章就必须给可点击链接，给不出就别提**：正文一旦出现「站内另有专文」「另有一篇专门讲」这类说法，必须当场给出 `[锚文本](/blog/{slug})`；内链预算已满、或站内确实没有对应文章 → **把那句话改写掉**（`可变比率强化的机制这里不展开，只借用这一条结论`），⛔ 不要留一个没有出口的指路。

完整判据与更多正反例见 `references/pillar-spec.md`「不许用「导航节」打断论证主线」与 R9。

**引用怎么写（2026-07-26 老板定案：写作只写简称，链接由专职引用 agent 落地）**

- **只从第 2 步查证轮落盘的素材清单 `$WS/drafts/{slug}.sources.md` 里引**——清单外的说法不许凭记忆写。需要一条清单里没有的证据，回第 2 步补查并补进清单文件，别先写了指望后面有人补链接。
- 文内标记统一写成 `【引: 作者/机构 年份, 文献简称】`：

  ```
  复杂性创伤的核心特征是自我组织的持续紊乱【引: Herman 1992, Trauma and Recovery】，
  这一点在 ICD-11 的诊断标准里得到确认【引: WHO 2019, ICD-11 6B41】。
  ```

  **为什么用 `【引: ` 前缀而不是普通全角括号**：正文里本来就有大量正常的全角括号（「（约 6.8%）」「（下称 CPTSD）」），拿普通括号当标记**必然误伤**；`【引: ` 这个组合在中文正文里不会自然出现，可靠可解析。
- 字段约定：**作者/机构**=第一作者姓氏（英文文献）或中文全名，机构文献写机构名（WHO / APA / 中国心理学会）；**年份**=四位数字，不确定写 `n.d.`；**文献简称**=能定位到唯一一篇的最短写法（书名/文章名/标准号），不必写全名。需要页码/章节：`【引: Herman 1992, Trauma and Recovery, 第 3 章】`。
- 同一文献多处引用 → **每处都照写同样的标记**（大小写、写法差异引用 agent 能认出来），去重与编号是第 4 步的事。
- **写作 agent 不管这四件事**：不编号、不抄 URL、不维护文末「## 参考文献」区、不填 frontmatter `citations`——全部由第 4 步统一落地。（旧流程要求撰写时就写终态 `[[n]](url)` 且与 `citations` 逐字一致，中途增删一条文献后其后编号全漂移、`CITE-MATCH` 报错返工，逼得 agent 倾向少引，最后又被硬闸卡住。2026-07-26 拆开。）
- **生命周期**：`【引: ...】` 是**中间态，绝不进成品**。第 4 步跑完正文里一个 `【引:` 都不该剩；成品残留 = 引用落地没跑或没跑完，审查端判 FAIL。

产出写到**内容工作区 drafts 目录**下的 `{slug}.md`（工作区路径见开头约定），**YAML frontmatter + 正文**，frontmatter 字段见 `references/pillar-spec.md`（title/slug/excerpt/**category_slug**/**tags**/meta_description/faq/**citations（第 4 步生成，撰写时留空）**/internal_links/target_keywords/author_name）。`author_name` 默认 `胡佰亿`。**`category_slug` 必须按主题从 pillar-spec 的「固定分类清单」六选一**（创伤与疗愈/情绪与自我/亲密与家庭/职场心理/留学生心理/心理科普兜底），别一律落 psych-101——分类是官网筛选导航与 SEO 主题聚类的骨架；`tags` 每篇 3–6 个自由词。slug 用拼音 ASCII 连字符分隔。

### 第 4 步 · 引用落地（专职引用 agent，2026-07-26 新增）

**位置：撰写完成之后、preflight 之前。** 由**独立于写作的引用 agent** 执行——它这一步只干引用，**不顺手改正文措辞**。

- **输入**（两个文件，缺一不可）：带 `【引: ...】` 标记的草稿 `$WS/drafts/{slug}.md` **+ 第 2 步落盘的素材清单 `$WS/drafts/{slug}.sources.md`**。
- **输出**：终态 `[[n]](url)` 正文 + 文末「## 参考文献」区 + frontmatter `citations`。

> **⛔ 缺 `{slug}.sources.md` = 停下，打回第 2 步补查证并落盘，不许开工。**
> **绝不改走"自己联网把每条现查一遍"**——下面打回规则 2 的联网核实口子，是留给「清单里漏了、但确实存在」的**个别漏网条目**的，不是给「根本没有清单」用的。整篇现查 = 全篇没有对账依据，等于把编造风险最高的分支设成默认路径，防线名存实亡。

> **单跑本 skill 时的降级**（流水线里是真派独立子代理；单跑只有一个实例，做不到"两个 agent"）：由**同一实例切换角色**执行，但必须先把第 3 步产出**落盘**（草稿 `$WS/drafts/{slug}.md`）、确认清单文件 `$WS/drafts/{slug}.sources.md` 在位，再以「只读这两个文件」的心态**从头重新扫描一遍**——**不得凭撰写时的记忆直接填 URL**。每一条 URL 都要能在 `.sources.md` 里指着看到；记忆里的 URL 正是错配与编造的主要来源。

1. **扫描**：提取全文所有 `【引: ...】`，解析出（作者/机构, 年份, 简称, 可选页码/章节）。

   ```bash
   WS=$(python3 {SKILL_DIR}/scripts/nbdpsy_common.py workspace)
   python3 {SKILL_DIR}/scripts/cite_scan.py "$WS/drafts/{slug}.md"
   ```

   stdout 纯 JSON：`markers`（**已按正文首次出现顺序去重排好**，含 author/year/short/locators/count/first_line/n_suggested）+ `malformed`（写坏的标记：缺年份、没闭合、跨行——先回写作端修好再往下走）。代码块内的示例标记不计入。
2. **对账**：逐条对回第 2 步落盘的素材清单 `$WS/drafts/{slug}.sources.md`（`简称` / `作者或机构` / `年份` / `URL` / `口径原文`）。对不上按下面的**打回规则**三选一处置。
3. **去重编号（两阶段：脚本出初稿 → 对回清单定稿）**：
   1. **机械分组（初稿）**：`cite_scan.py` 按「作者+年份+简称归一后相同」把标记分组，`n_suggested` 是**按正文首现顺序给出的候选编号**——是初稿，不是定稿。
   2. **对回清单归并（唯一依据）**：逐条对回素材清单，**以清单里的同一条记录（同一 URL）为唯一归并依据**。脚本 key 不同、但落在清单同一条记录上的（如 `【引: Herman 1992, Trauma and Recovery】` 与 `【引: Judith Herman 1992, 创伤与复原】`）**必须手工合并**为同一个 n；合并后**重新连号**，保证 1..N 连续无空号。

   **n 按正文首次出现顺序从 1 递增**——不是按字母序、不是按年份序、也不是按参考文献区的排版顺序。

   > **为什么不能直接用 `n_suggested`**：脚本只认字符串，不认识"这两个写法是同一本书"。跳过第 2 阶段 → 同一本书被拆成两个 n → 参考文献区出现**重复条目**、R6「≥6 条」被**灌水虚高**，而三道机检**全绿不拦**（它们只校验 n 在 1..N 界内、URL 与 `citations` 逐字一致、每条被正文标注过，唯独不校验"两条是不是同一本书"）。这道人工归并是唯一防线。
4. **替换**：每处标记替换为 `[[n]](url)`，URL **逐字照抄**素材清单里那一条，**不做任何"整理"**——去掉 utm、换 http/https、补/删尾斜杠都算改动，会让 `CITE-MATCH` 失配。
5. **生成**：
   - 文末 `## 参考文献` 有序列表，序号与正文 n 一致；**条目格式以 `references/pillar-spec.md`「文内引用规范（强制 · 两态）→ 发布态」节的正例为准**（`assets/example-pillar-cptsd.md` 只示范发布态的**结构**：frontmatter `citations` + 文末参考文献区，文内数字标注形态别照它的正文学）；
   - **标记里的页码/章节要有归宿，不许静默丢弃**：写作态 `【引: Herman 1992, Trauma and Recovery, 第 3 章】` 里的 `第 3 章` **不进正文标注**（正文只留 `[[n]](url)`），而是写进**参考文献区该条目末尾**，如 `3. Herman, J. (1992). Trauma and Recovery, 第 3 章. https://…`。同一文献多处引用而页码/章节不同（`cite_scan.py` 的 `locators` 会列全）→ 仍是同一个 n，把它们并列写在该条目末尾（`第 3 章、第 7 章`）；
   - frontmatter `citations` 数组，`citations[n-1].url` 与正文 `[[n]](url)` **逐字一致**——这正是 preflight `CITE-MATCH` 校验的那条。
6. **自检（必须实跑，不许自报）**：三条命令逐条跑完，把结论贴进对话；

   ```bash
   python3 {SKILL_DIR}/scripts/cite_scan.py "$WS/drafts/{slug}.md" --expect-empty      # 残留必须为 0，非 0 → exit 1
   python3 {SKILL_DIR}/scripts/lint_markdown.py "$WS/drafts/{slug}.md" --citations <参考文献条数>
   python3 {SKILL_DIR}/scripts/preflight.py "$WS/drafts/{slug}.md"                     # 含 CITE-MATCH
   ```

   - **全文 `【引:` 残留数必须 = 0**（`cite_scan.py --expect-empty` 输出 `total: 0` 且 exit 0）；
   - `lint_markdown.py` 的 citation-marker 无违规（1..N 每条参考文献都被正文标注过至少一次）；
   - **preflight 门槛分级**（引用 agent **不许改正文措辞**，所以不能拿"preflight 全绿"当它的出门条件——preflight 还判 R1 字数、R10 结构、加粗、title 长度等一堆与引用无关的项，那些只有写作端能修）：
     - **引用职责内 · 必须 pass**：`CITE-MATCH`（citation-integrity）、`RENDER-cite`（citation-marker），加上上面 `cite_scan.py --expect-empty` 的残留=0。这几项 fail 一律由引用 agent 自己修到 pass，不得往下走。
       > 注意 `CITE-MATCH` 在正文一个 `[[n]](url)` 都没有时会**空过**（没东西可比对），拦不住"标记没换成标注"；真正兜住这件事的是 `RENDER-cite` 与残留=0。三项要一起看，别只盯 `CITE-MATCH` 绿就收工。
     - **⚠️ 两项「引用 agent 修不动」的 fail，一律打回写作端，⛔ 绝不许靠联网现查凑数**（2026-07-26 补，实测暴露的死锁）：
       - **`R3`（带出处统计 ≥3）**：它数的是**正文里写了几句统计**（且须与 `[[n]](url)` 同行）。写作端只写了 2 句统计时，引用 agent 再怎么标注也到不了 3——**它不许改正文措辞**。此时**打回写作端补统计**，别自己想办法。
       - **`R6`（参考文献 ≥6）**：按步骤 3 做**同一 URL 合并**后条数会**下降**（6 条并成 5 条是常态），可能刚好跌破 6。此时**打回写作端 / 回第 2 步补真实素材**——⛔ **绝不许用「打回规则 2」的联网现查去凑够 6 条**。那个口子只对「写作时引了、清单漏收的**个别**条目」开；拿它填 R6 缺口，等于**为了让机检变绿去现找文献**，正是本方案要防的编造路径。
       > 由此反推：**第 2 步的素材清单要留余量**——预计同一文献会有多种写法时，清单条数按「**合并后仍 ≥6**」来备（一般备 8 条以上），别卡着 6 条整。合并降到 5 条才回头补，那时补的每一条都是在机检压力下现找的。
     - **引用职责外 · 照原样记入报告并打回写作端**：`R1` 字数、`R2` 答案前置、`R5` / `R5-body` FAQ、`R7-abs` / `R7-med` 敏感词、`R8` 危机声明、`R9` 内链、`R10` / `R10-para` 结构、`F1-*`（title / meta_description / author 等 frontmatter 项）、`F2`、`RENDER-bold` 等。这些 fail **不得由引用 agent 改正文去消除**——原样抄进第 7 项报告，写作端修完再回来。
     - 发布口径不变：**第 5 步仍要求 preflight 无 fail 才能发**。这里的分级只决定「这一步谁修什么」，成品硬闸一字未改。
   - 联网那轮 `--online`（测参考文献 URL 可达性）由第 5 步负责，引用 agent 至少保证**离线轮里引用职责内的项全 pass**。
7. **报告**：在对话里给出 ① **n ↔ 文献 ↔ URL 对照表**（含手工合并掉的重复条目：哪两个写法并成了同一个 n）；② 本轮**新增**的条目，逐条标注「**引用阶段新增、未经查证轮**」；③ **打回写作端**的条目及理由；④ preflight 里**引用职责外的 fail 原样清单**（不自行修改，交写作端）。

**打回规则（对不上素材清单时，三选一，绝不静默）**

1. 清单里有、只是**简称写法不同**（`Herman 1992` ↔ `Judith Herman 1992, 创伤与复原`）→ **认出来对上即可**，不必打回。
2. 清单里没有，但引用 agent **联网核实确认真实存在**（打开页面确认口径与正文说法一致）→ 补进参考文献，**并把这一条按五个字段补写回 `$WS/drafts/{slug}.sources.md`**（别只留在对话里），同时在报告里标注「**本条为引用阶段新增，未经第 2 步查证轮**」，供审查端重点复核。**这条口子只对个别漏网条目开**——若整篇都对不上，说明清单文件不对（或根本没有），回第 2 步，不要靠它兜底。
3. 联网也查不到 / 查到的口径对不上 → **打回写作端**，报告里写明「**查了哪个源、用什么关键词、返回为空**」，由写作端换一条有出处的说法或删掉该断言。

> **⛔ 绝不编造 URL、绝不拿"标题像"的网页凑数、绝不静默删掉标记让句子失去出处。** 这是 YMYL 红线——数字会带着胡佰亿的真人署名一起上线。
> 第 3 类打回后正文可能掉一条统计/引语，导致 ≥3 带出处统计 / ≥2 专家引语 / ≥6 参考文献不够——**补的是真实素材（回第 2 步再查），不是把闸放松**：成品硬闸一字不改。

### 第 5 步 · 发布前统一预检（一条命令，必须全绿）

产出/每次修订后，跑**统一预检管道** `preflight.py`——它一条命令逐项机检 pillar-spec 全部**可判定**项（R1 字数 / R2 答案前置 / R3 带出处统计块 / R5 FAQ / R6 参考文献 / R7 敏感词两级 / R8 危机声明 / R9 内链 / R10 结构 + frontmatter 完备 F1/F2 + 中文加粗与文内引用渲染合规），**任一 fail 即拦住发布**：

```bash
# 先查询内容工作区实际路径（在 NBDpsy 仓库根运行时为 seo-geo/content）
WS=$(python3 {SKILL_DIR}/scripts/nbdpsy_common.py workspace)

# 统一预检：stdout 纯 JSON {"ok","summary","checks":[{id,rule,status,detail,fix?}]}；任一 fail → exit 1
python3 {SKILL_DIR}/scripts/preflight.py "$WS/drafts/{slug}.md"

# 联网核验轮（联网抽测 R6 参考文献 URL 可达性 + R9 内链 /blog/ 目标 slug 存在性；网络失败宽容降级 warn）
python3 {SKILL_DIR}/scripts/preflight.py "$WS/drafts/{slug}.md" --online
```

- **status 语义**：`fail` 拦发布（逐条按 `fix` 修正后重跑到无 fail）；`warn` 提示不拦（如医疗口径词、超 150 字段落、首段略长等）但**须逐条人工裁决并在对话中明示结论（与 manual 同等待遇，不得默默放行）**；`manual` 是**机器无法判定、必须人工逐条自查**的项（R4 专家引语真实性、R6 引文可达性与数字口径、R2 直答段的语义质量、R5 Q/A 语义一致性）——自查后在对话中**明示结论**，不得跳过。
- **全绿（无 fail）才允许进入第 6 步发布。** 无 fail 但有 warn 时，preflight 打印「✓ 无 fail（N 个 warn 待人工裁决）」而非「✓ 全绿」——须把这 N 个 warn 逐条裁决完并明示结论。manual 项尤其是查证类（数字/引文/专家引语真实性）会带着胡佰亿真人署名一起上线，编造伤害最大，务必逐条人工核实。
- **发布前须至少完整跑一次 `--online` 轮且无 fail**：离线轮测不到 R6 参考文献可达性与 R9 内链 `/blog/` slug 是否真实存在（`--online` 才会联网分级：死链 404/5xx → fail，反爬/网络失败 → warn）。
- 字数**区间外双向都算失败**（R1，区间 4000–6000）：不足 → 按缺口补真实内容（首批四篇都经过"字数返工闭环"才达标），不靠注水凑数；超出 → 压缩低信息密度段落，不砍参考文献/危机声明。
- **`CITE-MATCH` fail、citation-marker 违规、或正文还剩 `【引:` → 回第 4 步引用落地重跑，别在这一步手工补 URL/改编号**——手工补正是编号漂移与 URL 抄错的老来源，引用只有一个出口。

> **局部调试**（可选）：preflight 内部已复用下列单脚本，主流程只需跑 preflight；单独排查某一维度时可直接调：`count_hanzi.py`（纯汉字计数）、`check_links.py`（URL 可达性初筛）、`lint_markdown.py --citations N --stats-min 3`（渲染合规 + 统计块）。

### 第 6 步 · 生成即发布（API 直发，默认署名胡佰亿）

> **硬性前置**：第 5 步 `preflight.py` **有 fail 禁止调用 `publish_post.py`**（且须至少完整跑过一次 `--online` 轮无 fail）。manual 项与 **warn 项**均须逐条人工裁决并在对话中明示结论后，才进入发布——**warn 与 manual 同等待遇，不得默默放行**。

用 `publish_post.py` 走官网博客发布 API（`POST /api/external/blog/posts`，Bearer API Key 鉴权）**直接发布**：默认 `status=published` + 署名胡佰亿 + 后端自动写 `published_at`（脚本会剥掉正文首行 `# 标题` 避免与页面 hero 重复 H1；slug 已存在则**跳过不覆盖**——线上可能已被管理员编辑过）。frontmatter → API 字段的完整映射见 `references/pillar-spec.md`「API 字段映射」。

> **为什么默认发布**：本项目采用「发布优先、事后复查」——AI 生成即上线、署名胡佰亿，管理员上网页核查，有问题再后台下架/改。这把人工环节从"发布前闸门"挪到"发布后兜底"，提速，但要求 ① 管理员及时核查 ② AI 自己的查证/复审必须更严（数字会带着真人署名一起上线）。如确需先压草稿，加 `--draft`。

> 发布需要 `NBDPSY_BLOG_API_KEY`。缺失时先跑 `python3 {SKILL_DIR}/scripts/nbdpsy_common.py doctor`（等价于开头「环境自检」提示的排查动作），
> 并让运营在管理后台「博客 → API Keys → 生成凭据配置包」取包、整段发来，
> 按 nbdpsy-content-pipeline 的「消化凭据配置包」配方写入后复跑。绝不回显 key 值。

1. **凭据自举**（首次缺失询问并记录，密钥绝不硬编码进 skill 或仓库）：

   ```bash
   python3 {SKILL_DIR}/scripts/nbdpsy_common.py secret ensure NBDPSY_BLOG_API_KEY
   ```

   无输出=已就绪；打印出 `NBDPSY_BLOG_API_KEY` 说明缺 key → 向用户询问（管理后台 manage.nbdpsy.com → 博客 → API Keys 可新建），拿到后记录：

   ```bash
   python3 {SKILL_DIR}/scripts/nbdpsy_common.py secret set NBDPSY_BLOG_API_KEY <用户提供的值>
   ```

   记录写入用户级 secrets 文件（Linux/macOS 为 `~/.config/nbdpsy/secrets.env`，chmod 600，在任何仓库之外）；解析顺序 ① 环境变量 → ② 工作区 `.env` → ③ 用户级 secrets 文件。**key 值绝不回显到日志/文件。**

2. **发布**：

   ```bash
   WS=$(python3 {SKILL_DIR}/scripts/nbdpsy_common.py workspace)
   python3 {SKILL_DIR}/scripts/publish_post.py --file "$WS/drafts/{slug}.md"
   ```

   - 默认 status=published、署名胡佰亿（frontmatter `author_name` 优先，其次 `--author`）；发布后百度/IndexNow 推送由后端自动完成，无需手动推。
   - **测试/演练一律加 `--draft`**（以草稿入库不上线）；`--dry-run` 只打印 payload 不发请求（输出 JSON 顶层带 `"dry_run": true`）。
   - 注意：`--api-base` 默认即生产地址，`--draft` 的草稿会**真实持久化到生产库**且 API 无删除端点、无自动清理——演练后需要时去管理后台手动删除；只想看请求内容用 `--dry-run`。
   - slug 已存在返回 skipped（**绝不覆盖线上**）；确要更新已有文章，显式加 `--update`（改走 `PUT /api/external/blog/posts/{slug}`，未发送的字段保持后端原值不变）。
   - 批量：`--drafts-dir <目录>`（与 `--file` 互斥）；两者都不给时默认发内容工作区 drafts 目录全部 `.md`，**但会自动排除第 2 步的素材清单 `*.sources.md`**（2026-07-26 加，那是工作文件不是待发布稿）——清单**留在 drafts 目录不用动**。
   - `--api-base` 覆盖 API 地址（默认取 `NBDPSY_API_BASE` 环境变量，缺省 `https://database.nbdpsy.com`）。

3. **核对输出 JSON**：stdout 汇总 `{"published": [...], "skipped": [...], "failed": [...]}`，有 failed 时脚本 exit 1（逐条排错后重发）。published 含本篇 → 给出线上地址 `https://www.nbdpsy.com/blog/<slug>`（新文章即刻可见；修改旧文受 ISR 缓存约 5 分钟生效）。

### 第 7 步 · 提醒管理员复查 / 可选分发

- **发布后立即提醒管理员上网页核查**：给出文章 URL `https://www.nbdpsy.com/blog/{slug}`，请管理员核对内容与署名是否妥当。（搜索引擎推送已由后端在发布时自动完成，无需手动推。）
- **有问题怎么办（管理员后台兜底）**：发现内容或署名有误，管理员在管理后台直接**下架**（状态改回 `draft` 或删除）或**修改**（改 `author_name` 署名、改正文）。不必回到本流程。
- **ISR 缓存**：新发布文章即刻可见；**修改已有文章**若网页未即时生效，是官网（marketing-web）的 ISR 缓存，约 5 分钟自动刷新（revalidate=300）；仍不生效再提醒管理员排查。
  - ⛔ **超过 5 分钟还不一致，就不再是缓存问题**：此时**第一嫌疑人是自己的查询/修改范围**（改漏了列、改漏了篇、正则太窄），不是缓存。必须先跑下节「存量文章批量修订」的全字段扫（S1-b）拿到 0 行，才允许把不一致归因给缓存/延迟——⛔ 起后台轮询「等它刷新」不算排查（2026-08-16 实证：库里没删干净时轮询会永远返回同一个数，看起来正像缓存没过期）。
- **可选：分发改写**。若要把 pillar 二次分发到公众号/头条/知乎，读 **`references/distribution-spec.md`**，每篇各出三版（gzh/toutiao/zhihu），写到**内容工作区 distribution 目录**的 `{slug}--{platform}.md`。核心纪律：**改写不改事实**、敏感词红线相同、每版嵌一次品牌锚句、保留危机声明。

---

## 存量文章批量修订（改已上线的文章，走这条，不走七步流程）

适用：不是写新文章，而是**把某段文案从已上线的存量文章里清掉或换掉**——换危机热线号码、改合规口径、换品牌说法（老板口径常是一句「全改吧」）。
七步流程管的是「新写一篇」，这条管的是「改一批」，**两者的失败模式完全不同**：写新文章的风险是编造，改存量的风险是**漏改后报绿**。

> ⛔ **本节的由来（2026-08-16 危机热线清理，一次假绿）**：工单说「文章正文里的热线」，于是只扫 `content_markdown`，77 篇报全绿；线上仍搜得到旧号码，又只查 `content_markdown` 得 0，遂判成「ISR 缓存残留」起轮询等刷新——旧号码根本没被删过，**它在 `faq` 字段里**。`faq` 会进 JSON-LD 的 **FAQPage**，是喂给搜索引擎与 AI 引擎的答案源，比正文更该先清。

**三条闸门（缺任一即视为未清理，⛔ 不许报「已清理」）**

1. **扫描按「这张表里所有能装它的列」，不按工单点名的那一列**。`blog_posts` 2026-08-16 实测有 15 列能装文案（`slug/title/excerpt/cover_image_url/content_markdown/status/author_name/meta_title/meta_description/source_type/source_url/reviewer_emp_no/citations/faq/video_url`）。一条 SQL 全扫并自报命中列，新增列自动纳入：

   ```bash
   # ⛔ 一律扫生产库：本地是旧快照，会给出方向相反的假象
   #   （2026-08-16 实测：本地 18 篇仍命中旧号码，生产库同一条 SQL 返回 0）
   ssh nbdpsy "PGPASSWORD='<生产库密码>' psql -h localhost -U root -d psychology_counseling -c \"
     SELECT id, slug,
            (SELECT string_agg(k, ',') FROM jsonb_each_text(to_jsonb(p)) AS e(k,v)
             WHERE v ~ '<正则>') AS hit_columns
     FROM blog_posts p
     WHERE to_jsonb(p)::text ~ '<正则>'
     ORDER BY id;\""
   ```

   **通过条件＝返回 0 行**；非 0 行时 `hit_columns` 直接指出漏在哪一列。`<正则>` 必须覆盖四类变体（纯数字 `4001619995`、连字符 `400-161-9995`、空格 `400 161 9995`、名称 `希望24|希望热线`），变体清单写进交付说明。
   代码侧同扫一遍**前端硬编码**（页脚这类全站每页可见处不在工单范围内，但一样露出）：
   `grep -rnE '<正则>' --include='*.tsx' --include='*.ts' --include='*.rs' --include='*.md' <仓库根> | grep -v node_modules`

2. **改的时候确认 payload 真的带上了那一列**。`publish_post.py --update` 走 `PUT`，**未发送的字段保持后端原值不变**——所以若本地 `drafts/{slug}.md` 的 frontmatter 里**没有 `faq` / `citations` 键**，`--update` 会跑得很绿而那两列一个字都没改到（这正是上面那次假绿最后一环）。改前先 dry-run 看 payload：

   ```bash
   # payload 打在 stderr（stdout 只有汇总 JSON），所以要 2>&1 >/dev/null 才看得到
   python3 {SKILL_DIR}/scripts/publish_post.py --file "$WS/drafts/{slug}.md" --update --dry-run \
     2>&1 >/dev/null | grep -oE '^  "[a-z_]+"' | tr -d ' "' | paste -sd' '
   ```

   2026-08-16 实测一篇完整草稿的输出：`title slug excerpt content_markdown category_slug tag_names author_name status meta_description citations faq`。
   目标字段不在这串键里 = 这次更新**改不到它**，⛔ 不许跑完就报完成——先把线上现值取回补进 frontmatter 再发（线上 `faq`/`citations` 怎么取见下条）。

3. **改完重跑闸门 1 到 0 行，并把命令原文与输出贴进交付说明**。只写「已清理/已全改」而给不出扫描输出的，按未清理处理（与判据「进度自报必须带实证句柄」同源）。
   验收若走线上渲染页，**扫原始 HTML 全文**（⛔ 不剔 `<script>`、⛔ 不剔标签：`meta_description` 只存在于 `<meta content="...">` 属性里，剔标签后命中恒为 0），且**先核对身份**——页面里的 `ld-post-{slug}` 与请求 slug 一致再采信 0 命中。

> ⚠️ **API 回读不能当全字段扫用**：`GET /api/external/blog/posts/{slug}` 的返回里**没有 `faq` 与 `citations`**（2026-08-16 核实读 handler 的 SELECT 列表就没这两列）——恰恰是最容易藏脏数据的两列。没有生产库访问权时，改用线上渲染页全文扫（FAQ 会渲染成可见 Q&A + FAQPage JSON-LD 两份）。

完整判据与「线上有、库里没有」的排查纪律见 `../nbdpsy-content-reviewer/references/checklist-article.md` 判据 10 的配套闸门 **S1 / S2**（唯一真源，本节是其在生产端的操作版）。

---

## 发布前双重复审（发布优先模式下尤其重要）

因为现在是「生成即发布」、上线前没有人工闸门，AI 自己的复审就是最后一道关。发布前务必：先自查 `references/pillar-spec.md` 全清单（R1 合规），再以"一个受困扰的真人读到这篇会不会被接住、会不会被误导"的视角通读（R2 质量）。两关都过再发布——**尤其是查证**：编造的数字/引文会带着胡佰亿的真人署名一起上线，伤害最大。

在两关自审之上，**建议再过一道独立对抗审查**：长文完成后、发布之前，交给加载 nbdpsy-content-reviewer skill 的独立审查者按其 `checklist-article.md` 清单审一遍，通过再执行第 6 步。在全自动流水线（nbdpsy-content-pipeline）中这道审查是发布前的必经闸门；单独使用本 skill 时可选但推荐。

## 关键文件

| 用途 | 路径 |
|------|------|
| 硬性内容规格 + frontmatter schema + API 字段映射 | `references/pillar-spec.md` |
| 三平台分发改写规格 | `references/distribution-spec.md` |
| 范文（首篇 CPTSD，对照学习） | `assets/example-pillar-cptsd.md` |
| **发布前统一预检管道**（一条命令机检全部可判定项，任一 fail 拦发布） | `scripts/preflight.py` |
| **写作态引用简称标记扫描**（第 4 步起步列表 + 收尾 `--expect-empty` 查残留，非 0 exit 1） | `scripts/cite_scan.py` |
| 纯汉字计数 + 区间判定（区间外 exit 2） | `scripts/count_hanzi.py` |
| 参考文献/内链可达性初筛（死链 exit 1） | `scripts/check_links.py` |
| API 发布（幂等 skipped，默认署名胡佰亿） | `scripts/publish_post.py` |
| 工作区解析 + 凭据管理 | `scripts/nbdpsy_common.py` |
| 历史项目记录（选题/状态/教训） | NBDpsy 仓库根 `seo-geo/PLAN.md`（仅在该仓库内运行时可参考） |

## 红线速记（违反任一即不合格）

1. 不编造数字 / DOI / PMID / 专家原话——查不到就不写（会带着胡佰亿真人署名上线，伤害最大）。引用落地步同理：**绝不编造 URL、绝不拿"标题像"的网页凑数、绝不静默删标记**，查不到就打回写作端。
2. 不用「治疗/诊断/治愈/医院/医生」自我描述；不夸大效果。
3. 危机声明（12356 + 010-82951332）必须在文末：「本文不构成医疗建议；如处于心理危机请拨打全国统一心理援助热线 12356 或北京心理危机研究与干预中心热线 010-82951332（24小时）；紧急情况拨打 110/120」。「24小时」只能标在 010-82951332 上。（号码真源=content-reviewer/references/checklist-article.md 判据10，下次并线先改那里再同步各处）
4. 发布脚本绝不覆盖已存在 slug（冲突返回 skipped；线上可能已被管理员改）；确要更新须显式 `--update`。
5. 发布直连生产 API；生产是唯一真实来源。发布后必须提醒管理员上网页核查。
6. **存量文案清理必须全字段扫**（见「存量文章批量修订」节 S1-b 的 `to_jsonb` 整行 SQL），并**贴出 0 行输出**才算完成——⛔ 不许只清工单点名的那一列（2026-08-16 实证：只扫 content_markdown 报 77 篇全绿，旧危机热线其实躲在 `faq` 列里，而 FAQ 会进 JSON-LD FAQPage 被搜索引擎与 AI 引擎当官方答案抓走）；⛔ 也不许用「缓存/ISR/还没刷新」解释线上与库里不一致——第一嫌疑人永远是自己的查询范围。

## 衔接下一级

发布成功后主动告知用户：「长文已发布（slug=<slug>）。可以继续拆小红书图文：
触发 nbdpsy-xiaohongshu-creator skill 并把 slug 传给它（它会自动拉取本文）。」
在全自动流水线（nbdpsy-content-pipeline）中：本级完成 = 长文通过对抗审查且发布成功，无需询问直接进下一级。
