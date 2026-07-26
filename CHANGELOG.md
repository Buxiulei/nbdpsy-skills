# 更新日志

NBDpsy 内容创作 skills（`nbdpsy-content` 插件）的版本变更记录。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)：
**Feature = Minor（1.x.0）｜Bugfix = Patch（1.0.x）｜Breaking = Major（x.0.0）**。

> 每次发版：改 `.claude-plugin/plugin.json` + `.claude-plugin/marketplace.json` 的版本号（共 3 处），在本文件顶部追加一节，然后 `git push`。

---

## [1.37.0] — 2026-07-26

### 信息密度档位化：默认 200–400 字，**运营指明就按运营的来**

老板口径：「每一页的信息密度默认 200–400，但如果用户指明了，那就按照运营说的做——比如运营说低信息密度，
那就每一页不要超过 100 字；运营说每一页不超过 50 字，那也照做。」运营还会用「一页表达几个核心观点」
这类说法表达密度。

**五个结构化字段**（写进 `00-overview.md` 开头 + 每篇 post 的 frontmatter，缺一不可）：
`信息密度档位`（`默认` / `运营指定`）、`每页文字量`、`每页信息点`、`版式档`（`满版` / `少格` / `大字报`）、`运营原话`。

**归一化表**（运营自然语言 → 档位参数，见 `nbdpsy-xiaohongshu-creator/SKILL.md` 第 1 步）：
不说 = 200–400 字 / 6–10 点 / 满版档；「低信息密度」= ≤120 字 / 3–4 点 / 少格档；
「每页不超过 N 字」按 N 折算；「一页 M 个核心观点」= ≤M×40 字 / M 个；「一页只讲一件事」= ≤60 字 / 1 个 / 大字报档。

- **`版式档` 是第 5 个字段、创作端归一化时定死、审查端直接读不再自行推导**。理由：运营最自然的说法
  「一页 2–3 个核心观点」声明出来是 `2–3 个`，**横跨少格档（3–5）与大字报档（1–2）**，两端各推一次必然分叉。
  **声明值为区间时按下界落档**（`2–3` → 大字报档）——宁可豁免不可误判。
- **三档版式联动**：满版档 = 17 种版式全适用、满版铺陈；少格档 = 只用白名单 5 种（对比图/象限/流程/概念定义卡/程度光谱）、
  格内二次加密降级为「每格 1 图 + 1 句」、**不要求混用满 3 种**；大字报档 = 一个大主视觉 + 一句核心话（≤20 字）+ 至多一个副标注，
  **「一页只有 1–2 条 = FAIL」「17 种版式之一」「混用 3–5 种」三条整体停用**（整本同形态是运营点的菜）。
- **判据上下限不对称**：默认档的 400 是**我们自己的版式经验值**（且"高密度必崩"已于 2026-07-25 实测证伪），
  **超了绝不判 FAIL**；运营指定的数是**产品意图**，超了 = 没执行指令，**判 FAIL（major）**。两端都写了这个理由。
- **只约束内容页 P2…P(N-1)**：封面 P1 与末页 PN 始终精简、不受档位管。末页必须承载
  「行动建议 + 品牌一句 + 12356」（实测 48–67 字），不豁免会被自己的脚本判死。
- **与「材料让步方式 A/B/C」的优先级**：先定档位、再算素材承载力；**运营已指定密度时让步方式 B（减密度）停用**，
  只能走 A（减篇数）或 C（默认，减页数）。

创作端（`SKILL.md` 第 1 步与第 3 步、`illustration-spec.md` 第 2/3 节）与审查端
（`checklist-note.md` 判据 6）逐字同源；`count_xhs.py` 新增 `--density-max` / `--density-points`
做确定性检查（**仅运营指定档跑**，默认档没有硬上限、跑了必误判）。

### 发布文案提高 emoji 比例（3–6 → **8–14**），正文少用双引号

- **emoji**：目标区间由「全文 3–6 个」提高到「**每篇 ~300 字正文 8–14 个**」，FAIL 线上移到
  「超过 18 个，或 >2/3 的行有 emoji」。质量护栏原样保留：一处叠 ≥3 个、高唤起/带货款
  （🔥💥😱❗‼️💯🉐🎁）、花哨分隔线与装饰 bullet、**危机声明那段不挂 emoji**。
  调性说明改为「选温和款（🌱🫧🌙☁️💭🤍🌿）、避高唤起款；**数量可以多，气质要稳**」。
- **双引号收敛**（图内 + 正文）：只保留"真的是某人说出口/心里那句原话"的引号（气泡、独白）；
  用来强调、指代术语、打反讽的一律去掉。图内一页成对引号 ≤2 处。
  ⚠️ **提示词里用来标记"这段字要渲染进图"的那对引号是语法标记，绝对不动**——删了模型就不知道哪些字要入图。

### 画布声明对齐真实出图：3:4（1080×1440）→ **2:3（1024×1536）**

**这是 2026-07-26 那批一整轮返工的根因**：spec 要求提示词写「竖版 3:4 构图（1080×1440）」，
而后端 `/api/op/consistent-images` 实际出 1024×1536——模型按 3:4 规划版面、成图落到更高的 2:3 画布上，
内容被顶到上下边缘。无论提示词怎么写"留出底部安全区"都没用（5 页 5 败）。

- `render_preview.py` 的比例切换正则改为**同时认新旧两种标准句**（存量 post 里全是旧句，改窄了老笔记切换会静默失效）；
  按钮与 hint 文案改「小红书 2:3（1024×1536）」，**内部键值 `'3:4'`/localStorage 保持不动**（老用户缓存不失效）。
- **`check_images.py` 修 bug**：原判定 `3:4 ±2%`，而原生 1024×1536 偏差 11% → **撤销补边后每批图跑确定性检查都必然 exit 1**。
  改为接受 **2:3 与 3:4 两个合法比例**（各 ±2%），最短边下限 1080 → **1024**（否则原生图被误杀）。补了 6 条回归用例。
- **视频参考图（§6）保持 3:4 不变**——它喂给 `nbdpsy-text-to-video` 的 image2video（按 3:4 推算 834×1112），
  跟着轮播改会脱钩。

### 只有封面需要守安全区；崩字的真规律是**强制折行**

- **只有封面 P1 会被 feed 按 3:4 裁**（标题/副标题落在 y≈85–1450）；**P2–PN 在详情页轮播按完整比例展示，
  不设安全区、不为此让版面**。原模板那句「距上边缘 ≥150px、距下边缘 ≥200px」已作废。
- **别用提示词控制像素级边距**（2026-07-26 实测：注入安全区约束后底部留白中位数只从 21px 变成 17px）。
  封面避让靠**构图描述**（"标题压在上 1/4 区""底部留出大片空白不放文字"）。
- **崩字与文字块总量无关**（那条已于 2026-07-25 证伪），与**单个文字块是否被迫折行**强相关：
  窄竖 pill / 窄色带 / 小徽章里放 ≥5 字的词组 = 高危，模型会强行折成多行网格并在折行处重复或丢字。
  **同一处反复崩字不要重掷**——那是版式在逼模型出错。三招消因按有效性排序：
  ① 换掉反复出错的那几个字（等义改写，一次即净）② 消除强制折行（缩到 4 字内或容器改横贯单行）
  ③ 把被夹住的窄横带**整条移走**（实测"给它腾地方"无效，崩点坐标依然崩）。
- 全局硬要求下压到 22 条模板「要求」行：**图中全部文字使用简体中文，不得繁体或异体**（本批出现过 數 / 軟）。

### 批次锚点可审计

批次锚点落盘到 `{note_dir}/_shared/BATCH_ANCHOR.txt`，所有出图/重出统一
`--anchor-url "$(cat {note_dir}/_shared/BATCH_ANCHOR.txt)"`；审查端逐篇比对
`images/post-NN/.gen_images_state.json` 里的 `anchor_url`，对不上 = 该篇风格基准漂了。
**只适用于走路线 0（后端一致性出图）的批次**——手工/宿主出图与存量笔记豁免。

### 笔记数据分析：分析前先读响应里的字段口径

`nbdpsy-guide` 第 3 步⑥ 补口径说明：`exposure` 是 **T-1**（截至昨日）、`views` 是 **T**（实时）、
`cover_ctr` 是 **T-1÷T-1**（且分子是封面点击次数、排除视频下滑曝光）。三者口径不同，
`views/exposure` 与 `cover_ctr` 对不上是正常的，**偏差方向还会相反**（新笔记实算偏高、老笔记偏低），
别据此判定数据有误。想看曝光转化自己算 `views/exposure` 就好，**只是别叫它 CTR**。
其余 8 个指标的时间窗尚未逐个核实——**响应里没写就是没核实，别假设**。
（已给 server 提需求：把 `meta.field_notes` 升级为逐字段的 `meta.field_meta`，未核实的显式标 `unknown`。）

---

## [1.36.0] — 2026-07-26

### 小红书标题改版：从「纯场景钩子」到「核心议题词 + 场景钩子」，关键词优先占位

老板口径：标题应该更直白地表达内容核心，便于获取长尾搜索流量，而不只是一个场景。

**问题**：旧规则的标题只写场景钩子——四类钩子示例（「3 个迹象说明你可能…」「总说自己想太多？」「我后悔没早点知道这件事」「i 人必看」）**一个可搜索的议题词都没有**。读者在小红书**搜**「童年情感忽视」「追逃循环」「复杂性创伤」时，这批标题一条都命不中。推荐流曝光是平台给的、会波动；搜索流量是长尾的、复利的，而标题是它唯一的入口。

**新结构：「核心议题词（目标长尾关键词）＋ 场景钩子」——关键词优先占位，钩子退居后半段。**

- **四条硬判据**（`references/xiaohongshu-spec.md` §1「标题」重写）：20 字硬限不变；**前 10 字内必须完整出现该篇目标长尾词**；**字数不够时砍钩子、不砍关键词**（本次改版的核心取舍，无例外）；长尾词必须是源长文真实覆盖的议题，**不许硬蹭**
- 四类钩子保留为**后半段的可选修饰**，每类给出「改前（纯钩子）→ 改后（带关键词）」对照表；三个标准形态：冒号式 / 竖线式 / 疑问式
- **选词优先级**：非诊断议题词（童年情感忽视 / 追逃循环 / 情绪内耗）优先；诊断级术语（CPTSD / 回避型依恋）只在它本身就是读者搜法时进标题
- ⚠️ **唯一放松的护栏**：§1.5 P2 的「术语不得进标题」改为「术语可作**搜索入口**进标题」——**不得作落点、不得写成自测句式、正文仍最多出现一次**这三条一条没松。代价已在 spec 内写明（站内 CPTSD 集群日均浏览全站最低、零预约关联）

### 封面页主/副标题分工定死

`references/illustration-spec.md` 三层组件模板的文字层：**主标题 ＝ 核心议题词**（与发布标题同源、字号最大）、**副标题 ＝ 场景钩子**（那句共情句），**两者不得重复同一层意思**（主答"讲什么"、副答"关我什么事"）。第 5 节 P1 封面范例原本主副写反（主"总说自己想太多？"／副"也许是复杂性创伤"），已调换。咨询师推介笔记不适用（其封面主标题是姓名）。

### `00-overview.md` 新增「目标长尾词」字段（每篇必填 1–2 个）

SKILL.md 第 1 步：长尾词在**规划阶段**定死（不是写标题时临时想一个），来源只有源长文真实覆盖的议题、一套内彼此不重复，并**串起三处**——标题前 10 字 / 标签行 / 正文自然出现。第 1 步验证清单加了对应检查项。

### `count_xhs.py` 新增可选参数 `--title-keyword`

```bash
python3 scripts/count_xhs.py <post.md> --title-keyword "童年情感忽视"
```

- 传了才校验：关键词须**完整**落在标题前 10 字内（结束位置 ≤10），不满足 → `ok_title=false` + exit 2，原因写在新字段 `title_reason`；另新增 `title_keyword` / `title_keyword_pos`（0 基下标，未命中 -1）
- 大小写不敏感（`cptsd` 命中 `CPTSD`）；口径与 `title_chars` 一致（先剔 emoji 再定位）
- **不传该参数时行为与历史版本完全一致**（只校 20 字硬限），既有调用不会变红
- 唯一例外：传了关键词却没有 frontmatter title → 判 false（显式要求校验就不静默放行）；不传时仍按历史放行
- 单测 5 条（向后兼容 / 前置命中 + 大小写 / 挤到 10 字后 / 关键词缺失 / 无 frontmatter）

### 审查端同步

- `nbdpsy-content-reviewer/references/checklist-note.md`：确定性检查命令带上 `--title-keyword`；判据 0② 标题口径**反转**（纯场景钩子标题现在一律 FAIL，只剩议题词的"没钩子"标题不判 FAIL）；判据 0④「术语进标题 = FAIL」改为「术语**做落点**或标题写成自测句式 = FAIL」；判据 3 标签双写增加"必须含目标长尾词"
- `evals/evals.json` 两条 rubric 与 overview 字段同步；`assets/example-xhs-note.md` 标题与封面主副标题按新规范改写（改前「一句"方案再改改"，我在工位上僵住了」正是本次要淘汰的形态）

### 补充（同版）：撤销补边、成图纠错纪律、回撤线

- **不做补边，就用 1024×1536（2:3）竖版直发**（老板 2026-07-26 定案）：它在小红书是合法比例、
  详情页轮播按原比例完整显示；**裁切只影响 feed 封面缩略图这一页**，内容页与末页的危机声明、
  G2 分流句在详情页完整可见。因此只需 **P1 封面**构图时把标题主体放中部，**内容页不必为此让步版面**。
  `pad_to_3x4.py` 与其单测一并删除（不留死代码）。
  仍保留的结论：**别用提示词控制像素级边距**（实测底部留白中位 21px→17px 毫无改善），封面避让靠构图描述。
- **成图有问题时的唯一改法**：改初始提示词 + 带**原锚点图**整页重出；⛔ 绝不能把错图当参考图喂回去、
  或追加提示词在错图上迭代——① 一致性锚的是那张已确认的 P1，换锚会让整套基准漂掉；
  ② 模型会继承错图的错误特征、在错的基础上改是固化错误；③ 成图带着已渲染的中文与版式，
  当 anchor 会把定死的排版当风格基准传下去。**锚点图自始至终只有一张。** 审查端同步该处置口径。
- **标题改版补回撤线**：关键词前置换走了最值钱的前 10 字，推荐流点击率大概率下降。
  两条触发任一即退回混合策略：① 推荐流曝光跌到旧口径 1/3 且搜索来源占比没起来；
  ② 术语类标题搜索流量上来但**预约关联仍为零**（判据二须单独盯预约关联、不能只看流量）。


---

## [1.35.0] — 2026-07-25

### 材料不足时的三种让步方式，默认「减每篇页数」

上一版只实现了「减篇数」一种应对，把选择权收走了。现改为三选一、并给出各自的参数区间：

| | 让步什么 | 保全什么 | 参数 |
|---|---|---|---|
| **C · 减页数（默认）** | 每篇 6–9 页 → 4–6 页 | 篇数、每页密度 | 每页仍 6–10 信息点、200–400 字 |
| **A · 减篇数** | 5–8 篇 → 台账实撑数 | 每篇页数、每页密度 | 可少于 5 篇 |
| **B · 减密度** | 每页 6–10 点 → 4–6 点 | 篇数、每篇页数 | 文字 200–400 → 120–250 字 |

- **默认 C**（老板定案）：篇数与每页密度是产量与质量的底线，页数最可让；A/B 需运营点名才切换
- 无论走哪种，都要在 `00-overview.md` 开头写明一行「材料让步方式」
- **审查端（checklist-note 判据 6）先读该行再判**，按对应区间判、不按默认区间判 FAIL——
  否则走 B 的 4–6 个信息点会被误判「密度不足」、走 C 的 4 页会被误判「页数不够」
- 走 C 时 `count_xhs.py` 需显式传 `--page-min 4 --page-max 6`，否则按默认 6–9 误报
- 返工处置随让步方式分流：C 砍页、A 合并或砍篇、B 降该页密度

---

## [1.34.0] — 2026-07-25

### 根治「材料不够→图内灌水→删字→再加密」的返工震荡 + 出图并发按服务端升级对齐

**素材承载力核算（第 1 步新增硬闸）**：震荡的根因不在写作、在规划超发——
一篇笔记 6–9 页 × 每页 6–10 信息点，5–8 篇就是几百个信息点，而此前**没有任何环节
核算长文供不供得起**（原「原文太短才可少于 5」既无量化判据、又是事后补救）。现改为：

- 定篇数前先建**素材台账**（一页一行，写进 `00-overview.md`），每页必须填出
  **具体、独立、本篇专属**的长文出处；填不出/出处与本篇其他页或其他篇重复 → 该页划掉
- 某篇被划 ≥3 页 → 该篇材料不足，与相邻篇合并或砍掉
- **篇数 = 台账实际撑得住的数**，`5–8` 降级为上限与理想值、不再是产量指标；
  少于 5 篇属正确结果，在 overview 开头写明原因即可
- **主动少拆并说明理由 = 达标；凑够篇数但靠重复灌水 = 不达标**

**返工铁律**：删灌水必须靠**换材料**（用长文里本篇还没用过的小节填回），不靠删字——
只删不换会掉回字数下限又触发加密、来回震荡。**翻遍长文找不到可换材料 = 材料不足的确诊信号**，
退回规划步改台账与篇数，别在同一页硬凑。审查端（checklist-note 判据 6）同步该处置口径：
判到重复/灌水时 issue 须写明换材料而非删字，材料确实不足则直接建议合并或砍篇。

**出图并发**（服务端 2026-07-25 升级后对齐）：单篇内部已 10 路并发、6–9 页一波出完，
墙钟 7.5 分钟 → **约 50 秒**；篇级并发从「串行/≤6」改为**10 篇全开**（Tier 5 250 IPM，
10×10=100 并发≈120 张/分，占 48%）。429 已由服务端指数退避 3 次兜底，排障收窄为
**仅 outcome 明确报错才重出**。下标对齐与失败位留空语义不变。

---

## [1.33.4] — 2026-07-25

### 批量出图并发口径重写：从「拍脑袋 ≤6」改为「实证瓶颈 + 两个维度 + 降级信号」

1.33.2 写的「并发度 ≤6（只压测到 2 路留余量）」被实证调研推翻：**那个 6 没有任何服务端依据**，
与服务端 `BROWSER_CONCURRENCY=6` 撞名纯属巧合（那个闸只管发布/cookie 检测/导出/删除的
camoufox 浏览器，生图完全不经过它）。第 6 步「路线 0 · 后端一致性出图」第 2 条按调研结论重写：

- **写明瓶颈只有一层**：**OpenAI org 级 IPM（images per minute）配额，全服务所有运营共用同一把
  key、共享同一份配额**。其余各层实测都远未饱和——本机 32 核 62G（去水印并发实测 24 路仍富余）、
  隧道 7.26 MB/s（≈ 支撑 78 路）、服务端 uvicorn 单 worker 未设 `--limit-concurrency` 且生图走异步 IO。
  **反面提醒同时写入**：服务端对生图任务**没有任何并发上限**，提多少就并发轰多少上游，自律只能发生在 skill 这一层。
- **拆成两个维度分别给建议**（老板诉求是扛 20+ 运营并行）：
  - **单篇内部 = 没有可调项**。服务端 `generate_batch` 是 `for` 循环逐页 `await`（8 页 ≈ 7 分钟），
    客户端设什么并发都改不了——原文「单篇内串行」是在描述既成事实、不是参数，明确写清免得后来人白折腾。
  - **全局并行 job 数 = 全服务共享总量，不是每人各自 N**。给出公式 **可持续并发 ≈ 0.9 × IPM**
    （单页墙钟实测 46–76s 取 55s，每槽 ≈1.1 张/分钟）与 Tier 1/2/3/4 对照表（4 / 18 / 45 / 90+）。
- **不伪造确定数字**：我们在哪一档本机读不到（`/v1/models` 不返回 `x-ratelimit-*` 头），
  故写成**阶段性建议 + 爬坡方案**——**6 路起步 → 连续两批无降级信号爬到 10–12 → 不要一次开到 20**，
  别的运营同时出图时压到 ≤4 并错峰；并附管理员 30 秒查真值的入口
  （platform.openai.com/settings/organization/limits 的 `gpt-image-2` IPM），查到后按表取值。
  同时点明：6 路 ≈ 6.5 张/分钟，**若我们是 Tier 1（5 IPM）连 6 都已超限**，所以爬坡必须看信号不看感觉。
- **补齐降级信号与降到多少**：① `pages` 出现 `error`／某页 `url` 为空（**429 最典型的表现**——服务端
  无 429 退避重试，撞限额直接判该页失败、交付空位，而**整个 job 仍标记 `done` 不报错**，只能逐篇核对发现）
  ② 单页 p95 > 83s（基线 55s 的 1.5 倍）③ 同批 ≥2 篇同时出现失败页。**出现任一 → 并行篇数减半；
  降到 2 路仍复现 → 退回串行并报管理员查 IPM 档位**。并强调失败页只能用 `--pages` 补，
  整篇重跑会让已成功的页重新扣费、掉进「越重跑越限流」的循环。
- 同段落一并保留本次查证的一致性结论：服务端走**无状态 Images API（`images.edit`）**，风格一致性
  来自每张都传同一张锚点图，故调用顺序/并发与否都不影响一致性；服务端 `session_id` 只是产物目录标识
  （替换掉 1.33.2 里「每次调用现开临时容器」这个与代码不符的说法）。

**⚠️ 真正的提速杠杆在服务端、不在本 skill**（属于 nbdpsy-server 仓库的另一件事，本次未改）：
`generate_batch` 的逐页串行换成 `asyncio.gather` + **全局信号量**，一篇 8 页可从 ~7 分钟压到 ~1 分钟、
skill 侧零改动；顺序必须是**先加信号量再放开页内并行**，否则单个运营就能打出 30 job × 8 页 = 240 路轰上游。
另需补 429 分层退避、把 `x-ratelimit-remaining-images` 响应头打进日志（这是唯一能在 429 发生**之前**
预警的指标）、重新标定 `OPERATOR_PENDING_QUOTA=30`（当前 **admin 角色完全豁免**）。

---

## [1.33.3] — 2026-07-25

### 口径修正：取消「危机题材不许挂推介末页」+ 图内文字量放宽到 200–400

**① 危机议题笔记照样可以挂咨询师推介末页（题材否决闸门取消）**

老板口径：「危机相关笔记不会挂推介末页，这个取消掉。我们所有咨询师都是持证的心理咨询师，
可以应对危机干预！如果提示词里说了要推介，那就是要推介咨询师。」

- `nbdpsy-xiaohongshu-creator/references/counselor-note-spec.md` §6.2：前置判据从**两条减为
  一条**（只剩 `is_accepting=true`），删掉「本篇不是危机相关笔记」这条题材闸门；§6.7 与验证
  清单、红线速记第 6 条同步。
- `nbdpsy-xiaohongshu-creator/SKILL.md`：「两条前置闸门」改为「前置闸门只有一条」；红线 4
  末尾的题材禁令删除。
- `nbdpsy-xiaohongshu-creator/references/xiaohongshu-spec.md` **§1.5 G6 定义本身**：删掉
  「内容本身触及危机识别与转介的笔记，当篇不放商业 CTA」这半句。G6 是上面几处引用的**源规则**，
  不改这里会自相矛盾——下游说"可以挂"、G6 说"不放商业 CTA"，读到 G6 的 agent 仍会拒绝。

**⚠️ 明确保留（本次没删，以后也别拿这条改回去）**：① **危机声明 12356 照常在位**（科普笔记
既有规则不变，校验仍**不带** `--no-crisis`）；② **G6 的「声明与商业 CTA 不同页/不同屏」物理
分离保留**——推介页排在危机声明页之后本就天然满足，不需要额外限制。
**一句话：删的是「危机题材整篇不许挂推介」，留的是「声明与推介不挤在同一页」。**
G6 现在**只有排版分离一层含义**，spec 内已就近写明这个区别，防止后来者又把题材禁令加回来。

**② 内容页图内文字量建议值 200–300 → 200–400**

- `nbdpsy-content-reviewer/references/checklist-note.md` 判据 6 及其防误判条款同步为 200–400
  （仍是**建议值不是上限，任何情况下不得据此判 FAIL/major**，条款原样保留）。
- `nbdpsy-xiaohongshu-creator/references/illustration-spec.md`：出图侧还留着上一版的旧值
  **80–120**，一并对齐到 200–400——审查侧 checklist 明确要求「对照 illustration-spec 第 3 节」，
  两边不一致会让创作端按 80–120 出图、审查端按 200–400 判密度不足。
- 未动 `nbdpsy-seo-artical-creator` 与 `checklist-article.md` 里的 80–120：那是**长文 TL;DR
  首段字数**，与图内文字量是两个指标，不能一起改。

---

## [1.33.2] — 2026-07-25

### 出图提速：批量出图从「逐篇串行」放宽为「按篇并行」

- 第 6 步批量出图改为**按篇并行、单篇内串行**（并发度 ≤6，遇 429/限流降到 2 或退回串行）。
  依据：`POST /api/op/consistent-images` 只收 `prompts`+可选 `anchor_url`，**不接收
  draft_id/session_id**——session_id 由服务端每次现开临时容器，天然隔离。运营实测两个 job
  并发各 57s、墙钟 57s（串行应为 ~114s），分别拿到不同 session_id。6 篇 ~42 页由此从
  约 35 分钟压到约 6 分钟。并发上限只压测到 2 路，故建议值取 ≤6 留余量。

---

## [1.33.1] — 2026-07-25

### 修复：审查员两处误判口径（图内文字量当上限、查无出处不查权威源）

运营实测反馈的两类误判，均改在 `nbdpsy-content-reviewer/references/checklist-note.md`：

- **判据 6「内容页信息密度」**：建议值从「文字总量约 80–120 字」上调为 **「约 200–300 字」**
  （老板口径：字数太少会显得信息量不足）。并追加防误判条款——这是**版式建议值不是上限，
  任何情况下不得据此判 FAIL/major**；本条 FAIL 判据全部指向密度不足，密度偏高不在判据之列。
  明令禁止「数提示词里的引号文字块 → 超建议值 → 预测出图会错字/糊字/裁切 → 判 major」这条
  推理链：2026-07-25 已实测证伪（同批最密页 44 文字块 vs 中位页 23 块各出一张 1024×1536，
  图内中文逐字无误、手机端字号可读）。错字/糊字/裁切是**成图缺陷**，只能在图片审查阶段
  （`checklist-images.md`）对着实际 PNG 判定，笔记阶段对提示词预测出图质量属**越权推断**。
- **判据 1「事实可溯源」**：追加「判查无出处前必须查权威源，而不是查任务提示词里的摘要」——
  提示词给的事实清单常是节选，**节选之外 ≠ 不存在**。写明各类事实的权威源：科普结论与数字 →
  源 pillar 长文原文；咨询师资历/擅长/受训/执业经历/咨询小时数/同行与督导评价 →
  `fetch_counselor.py --emp <emp_no>` 实时返回（并列出 `profile_sections` 下的具体字段路径）。
  只有权威源里确实检索不到才写 blocker，且须写明查了哪个源、什么关键词、返回为空。
  起因：一批推介笔记里三条**真实存在的后台字段**（督导訾非评价、三个 styles 标签、
  个体 800+/家庭 200+ 小时）被当成编造，其中督导评价还被判成 blocker。

---

## [1.33.0] — 2026-07-25

### 新增：科普笔记末页咨询师推介页（系统头像直接合成）

科普笔记可在轮播**末尾追加 1 页**咨询师推介——素材是咨询师**自己上传到系统的头像**
（`avatar_url`），直接喂 gpt-image-2 合成，避免本地拼图错位。

- **新路径与既有「整篇推介笔记」口径分开**（counselor-note-spec 新增 §6，含两条路径对比表）：
  系统头像**上传即已授权**，**不逐次索取授权、不设「本人过目认可」发布闸门、不卡发布流程**
  （老板定案：事后有异议走下架笔记补救）。**§2 照片三铁律与本人认可闸门原样不变**，只管
  运营额外索取的照片；判据一句话「照片从哪来」。
- **取数**：`fetch_counselor.py` 新增 `--avatar-out <路径>`——`avatar_url` 是相对路径
  （`/static/avatars/xxx.jpg`），脚本自动拼 api_base 下载，目录入参自动命名
  `avatar-<emp_no>.<ext>`，JSON 追加 `avatar_local_path`；后台无头像时报错停下（不静默返
  空 anchor 白烧额度）。§0 字段表同步改口径（原写「仅参考，不作为发布素材」）。
- **出图两批 anchor 别混**：科普内容页 anchor=已确认的 P1，推介末页单出一批 anchor=头像
  图床直链（`publish_note.py --upload-images` 取直链）；**不用 compose_photo 本地拼图**。
- **末页文案就四件**：姓名（直呼其名，绝不加「老师」）+ 职称一行 ≤14 字 + 擅长方向药丸 2–4 个
  各 2–6 字 + 一句「怎么开始」≤16 字陈述句；价格默认不展示；品牌锚句不重复（只放右下角小字）。
  提示词骨架见 §6.5（比例参数写标准句，保预览页 3:4↔1:1 切换可用）。
- **合规**：这仍是科普笔记——**危机声明照常在位**（放推介页之前那一页，天然满足 G6 分离），
  校验**不带** `--no-crisis`；**危机相关笔记不加推介末页**（G6：触及危机识别与转介的当篇不
  放商业 CTA）；只对 `is_accepting=true` 的咨询师做。页数口径：内容页 6–8 + 推介 1 = 总 7–9，
  `count_xhs.py` 默认区间不用改。
- **视频衔接**：推介末页不写进「## 视频参考图提示词」节；做视频时须跳过末页
  （`parse_note.py` 无跳页开关，产出 shots.json 后删掉最后一镜）。
- 单测：`--avatar-out` 目录/文件路径命名、相对→绝对 URL 拼接、绝对 URL 不重复拼、无头像抛错、
  `--avatar-out` 单独配 `--list` 报错（全程请求层 monkeypatch，不打网）。

---

## [1.32.3] — 2026-07-25

### 发布排障：账号封禁语义 + 账号名跟随昵称（服务端行为对齐）

- 失败排障新增「账号被平台判违规处罚」判据：发布约 1 秒即返终态 `failed` 且 error 含
  封禁语义（发布被小红书阻断/违反社区规范/禁止发笔记/账号异常）＝平台处罚非技术故障；
  处理只有换号或 App 内核实，**勿重扫码（cookie 是好的）、勿重发（更强的高频封号信号）**。
  红线速记同步加第 7 条；账号管理节加专节。
- 账号管理节新增「账号名跟随小红书昵称」说明：每次 cookie 检测会把账号 name 同步成
  最新昵称，运营改名后 `--list-accounts` 显示会变，属预期行为；认账号拿不准用 id。

---

## [1.32.2] — 2026-07-24

### 推介笔记：照片只上封面，内页不再放照片

- 咨询师照片只出现在 P1 封面（运营口径定案）：出图仅 P1 传 `--anchor-url`，内页批次
  绝不带照片 anchor；P2 简历卡改纯信息图（提示词骨架去照片区，顶部改姓名条），密度
  8–10 信息点要求不变。
- 备选保真路线（compose_photo 本地合成）随之改挂封面：spec 附录改为封面底图留白模板
  （照片占顶部约 1/3，保真换构图的取舍已注明），脚本文档字符串/help 同步改口径。
- 流程与闸门同步：授权停等、成图本人认可、图审均改为围绕封面；图审新增硬判据
  「内页出现人物照片＝返工」。SKILL 速记同步。

---

## [1.32.1] — 2026-07-24

### 咨询师称呼规范：直呼其名

- 产出内容（正文/图内文字/标题）提及咨询师一律直呼其名或用她/他/TA，绝不加「老师」等
  称谓（运营口径定案）；修正 spec 展开正例与骨架表中的「黄老师」违例。

---

## [1.32.0] — 2026-07-24

### 咨询师推介场景按黄安麟篇实战反馈修订（骨架/长尾词/流派/字数/危机声明豁免）

**动机**：老板看真实产出（黄安麟推介笔记）后提五条反馈——推介是**介绍一个人**、不是科普文，此前照搬科普三段式跑偏了。逐条落实：

1. **危机声明不加**：推介笔记正文与末页图都不放「本文为心理科普…12356」——介绍一个人硬塞科普声明反而像在科普栏目里。`check_compliance.py` 加 `--no-crisis` 开关（跳过危机声明在位检查，极限词/医疗违禁/站外导流照扫）；spec 合规步骤改用 `--no-crisis`。
2. **删痛点铺垫**：`counselor-note-spec.md` §3 文案骨架从「科普三段式」整体重写为「**人物直入**」三部分——开头姓名+最硬资质直入（前 10 字立住信息），禁止「想找人聊聊又怕选错」类痛点铺垫、禁止「选咨询师其实是先认识一个人」类导语。
3. **议题展开＋埋长尾词**：擅长议题不能只列干词，每类展开成"是什么困扰＋怎么和你工作"并至少嵌 1 个后台真实覆盖的长尾词（原生家庭创伤→CPTSD/复杂性创伤、亲密关系→依恋修复/追逃循环…，绝不硬蹭）；标签 3–6 个里必含核心议题长尾词；简历卡图上药丸保持 2–6 字短词，长尾词由文案承载。
4. **写明受训流派**：主体新增「受训流派与工作方式」一段，写出系统受训的流派名（CBT/精神动力/整合取向，取材 profile_sections 的 training/methods）+ 一句白话解释。
5. **字数更长**：正文 300 字 → **400–800 字**。`count_xhs.py` 加 `--body-min/--body-max`（默认维持 210–450 兼容科普笔记）；spec 自检命令 `count_xhs.py <post.md> --body-min 400 --body-max 800 --page-min 4 --page-max 6`。

- **危机声明豁免链路穷尽同步**：`nbdpsy-xiaohongshu-creator/SKILL.md`（咨询师章节新增"三点差异"块 + 红线速记第 4 条注明"科普笔记适用/推介除外" + 关键文件表 `--no-crisis`）、`xiaohongshu-spec.md`（"危机声明惯例·每篇在位"与"F·危机声明排版位"均注明推介除外）、`nbdpsy-content-reviewer/references/checklist-note.md`（危机声明判据 4 注明推介笔记不判此条、其余判据照审）逐处补豁免注记。
- **G 系硬闸适用性**：counselor-note-spec §3 梳理一句——禁导流(G7)/极限词/医疗词/不编造(G4 精神)仍适用；**G1 最低出口律、G6 危机与 CTA 分离对推介场景不适用**（推介无危机声明可分离，结尾收藏/评论互动是自然选项非 G1 强求）。
- **测试**：`test_check_compliance.py` 加 2 例（`--no-crisis` 跳过危机声明但违禁词仍一票否决 / 干净推介文豁免通过而不带开关仍因缺声明 fail）；`test_count_xhs.py` 加 1 例（`--body-min/--body-max` 覆盖默认区间）。

未改 `count_xhs.py`/`check_compliance.py` 的既有默认行为（不传新参即旧口径），科普笔记闸不受影响。

### 生成产物统一「上图床拿 mcp 直链」交付运营（图文成图）+ 视频直链协同请求

**动机**：成图/成片做完后，运营要审看只能翻本地目录或找服务器路径，跨设备、发同事确认都不便；
图床（`publish_note.py --upload-images`，7 天免鉴权直链）本已就绪，把它接进交付收尾即可让运营「点开即看」。

- **`nbdpsy-xiaohongshu-creator/SKILL.md`**：第 6 步出图三条路线（路线 0 后端出图 / 有图像能力宿主 /
  无图像能力宿主）在图审 PASS 后**统一加收尾步**——每篇成图 `--upload-images {note_dir}/images/post-NN/`
  上图床（一篇一批，`urls` 按文件名页序对应 P01…PNN），把链接列表发运营「点开即看、7 天有效、过期重传」。
  明确两点：① 发布环节照旧读本地文件、不依赖图床链接；② 路线 0 的 `/uploads/opimg_*` 直链保存期不明
  （台账仅 2h），要交付查看统一转存图床。第 7 步路线 A 确认账号时/路线 B 人工交付时都把查看链接一并给运营。
- **`nbdpsy-xiaohongshu-creator/references/counselor-note-spec.md`**：§5「本人认可（硬闸）」补实操通道——
  简历卡成图 `--upload-images` 上图床后把链接发运营转咨询师本人过目（点开即看、无需传文件）；
  ⚠️ 注明**授权照片原图的图床链接只作 anchor_url 生图用、绝不当查看链接转发扩散**（真人肖像隐私红线），
  转给本人过目的只能是已重绘/合成的成图链接。
- **`nbdpsy-text-to-video/SKILL.md`**：交付章节补现状说明——成片暂以本地 MP4 交付（视频无图床上传端点），
  「视频产物公网直链」能力已向 nbdpsy-server 提协同需求，落地后改为链接交付；不改任何流程逻辑。
- **`nbdpsy-guide/SKILL.md`**：速查表加一行「运营说『把图发我看看 / 链接呢』→ 成图已上图床，直接把 mcp
  直链给 TA（7 天有效、过期重传），别甩本地目录/服务器路径」。
- **协同请求文档**（落在 NBDpsy 仓 `文档/2026-07-24-视频产物上传直链-协同请求.md`，仅此一份仓外产物）：
  请 nbdpsy-server 侧排期补 `POST /api/uploads/videos`（multipart 单文件 mp4，建议 ≥200MB/7 天，
  免鉴权 HMAC 直链目录同图床范式，复用 `/uploads/video/` 已有静态下发机制）。

纯文档接线，未改任何 `scripts/*.py` 代码（`--upload-images` 早已存在）；`pytest tests/` 仍 353 全绿。

---

## [1.31.1] — 2026-07-24

### pillar-spec R5 补注：正文 FAQ 节由前端展示层剥离

- 官网详情页曾双重渲染 FAQ（正文节 + FaqBlock），已在 marketing-web 渲染层修复
  （stripFaqSection，数据层不动）。R5 补注：正文仍必须写全 FAQ 节——下游拆小红书取材与
  preflight 校验都依赖它，别因页面上不直接显示就省略。

---

## [1.31.0] — 2026-07-24

### xiaohongshu-creator 落地「发布文案排版体系」（手机端实际渲染）

**动机**：小红书正文**不渲染 Markdown**（`publish_note.py` 发布前剥 `**/*/` 强调符），排版只能靠
换行/空行/emoji/全角符号；此前口吻规范只有一句「每段 2–4 行、配 1 个克制 emoji」太粗，写手容易
把加粗当强调（发布后被剥＝没排版）、或堆 emoji/花哨符号显成营销号——与治愈系心理科普调性冲突。
本次把这句粗规则展开成可执行的排版口径。

- **`references/xiaohongshu-spec.md` 新增 §1.6「发布排版规范（手机端实际渲染）」**：立治愈系"克制 > 热闹"
  总基调，六条细则——A 首行钩子排版（≤1.5 行、场景前置、句中断行）／B 分段与空行节奏（手机每行约
  20 字折行意识、每段 2–3 行、**强调靠金句独立成行不靠加粗**）／C emoji 三用法（序号·bullet／段末情绪／
  首行钩子）+ 心理类密度区间（全文 3–6 个、只选 🤍🌱🫂 温和款、禁 🔥💥❗）／D 分隔与装饰符白名单
  （禁花哨分隔线/装饰 bullet/彩色符号墙、破折号做解释改换行或括号）／E 结尾互动+标签行排版／F 危机
  声明排版位置（G6 单独成段、不点缀 emoji）；附 ⛔ 反面清单与 before/after「裸排 vs 优化排版」对照示例。
- **`SKILL.md` 第 2 步挂接**：写文案要求新增"写完必须按 §1.6 重排再落盘"；验证清单加「排版已按 §1.6 重排」项。
- **`assets/example-xhs-note.md` 黄金范例「## 发布文案」块按 §1.6 重排**：首行句中断行、金句独立成行、
  破折号全部改换行/逗号、强调不再靠加粗。**内容语义不变、汉字数不变**（`count_xhs.py` body_chars 恒
  447，emoji/符号不计数），`count_xhs.py` 与 `check_compliance.py` 仍全绿。
- **`references/counselor-note-spec.md` §3 文案骨架**：一句话挂接引用同一 §1.6 排版规范（不复制规则）。
- **`nbdpsy-content-reviewer/references/checklist-note.md`**：新增判据 9「发布文案排版按 §1.6 规范」——
  无排版/整坨文字墙=FAIL、emoji 超密度/营销号式花哨=FAIL、强调错位（靠加粗）=FAIL、危机声明/标签排版
  =FAIL；边界说明排版不数汉字、不拿配图的赭红/粗黑当 FAIL 理由。

---

## [1.30.0] — 2026-07-24

### seo-artical-creator 新增发布前统一预检管道 `preflight.py`

**动机**：pillar-spec 十条硬性要求此前分散在多个脚本与人工自觉之间，2026-07 真实事故=R3
「带出处统计块」被静默跳过发布（有文章引 8 篇实证研究却零数据点）。系统性解法=把**全部可机检项
进一条管道**，任一 fail 拦住发布；不可机检项明确标 manual 逐条自查，绝不做假阳性闸门。

- **新脚本 `scripts/preflight.py`**：一条命令逐项机检 R1 字数 / R2 答案前置 / R3 带出处统计块 /
  R5 FAQ / R6 参考文献 / R7 敏感词两级 / R8 危机声明 / R9 内链 / R10 结构 + frontmatter 完备
  F1（title/slug/excerpt/meta_description/category/tags/target_keywords/author）/ F2 标签对齐 +
  中文加粗与文内引用渲染合规。stdout 纯 JSON `{ok,summary,checks:[{id,rule,status,detail,fix?}]}`，
  status ∈ pass|fail|warn|manual，任一 fail → exit 1。`--online` 抽测 R6 参考文献 URL 可达性与
  R9 内链 /blog/ 目标 slug 存在性（网络失败宽容降级 warn）。内部复用 count_hanzi / lint_markdown /
  publish_post.parse_frontmatter，不 subprocess 套娃；引文可达性/数字口径/专家引语真实性列为
  manual，绝不假装能测。
- **`lint_markdown.py` 统计判据扩展**：RE_STAT 增加学术统计形态——相关/效应量（r/d/β/η²）、
  比值（OR/HR/RR/g）、置信区间（95% CI）；样本量（N=224）单独不算。修复「恋爱脑」一文正文含
  r=.42/r=−.29 等学术统计却被 R3 漏计的盲点。同步更新既有测试并补充学术形态/样本量用例。
- **SKILL.md 管道化改造**：第 4 步统一改跑 preflight，**全绿（无 fail）才允许发布**；第 5 步加硬性
  前置「preflight 未全绿禁止调用 publish_post.py」；原单脚本保留为局部调试；关键文件表补 preflight.py。
- **`references/pillar-spec.md`** R3 行补一句：统计形态含百分比/倍数/相关与效应量（r/d/OR 等）。
- **测试 `tests/test_preflight.py`**：最小合格文档全绿 + 逐项违规（每条 R 规则、frontmatter 六分类/
  meta 长度/tags 数量、敏感词两级分开测、F2 warn 不拦发布）。

---

## [1.29.2] — 2026-07-24

### 咨询师简历卡：AI 直出转正 + 高密度硬要求（运营定案）

- 实测 gpt-image-2 吃照片 anchor 的人物还原度与版式融合俱佳，**AI 直出改为默认路线**：照片
  `--upload-images` 上图床取直链 → `gen_images --pages <简历页> --anchor-url <直链>` 直出；
  **成图必须经咨询师本人过目认可后才可发布**（并入其自审环节，硬闸）；compose_photo 本地合成
  降级为像素级保真备选。
- **简历卡密度硬要求**：8–10 信息点、2–3 区块满版、图文双通道（教育/资质/受训/执业数据/擅长
  方向药丸组/风格句，全部取材 profile_sections）——「名片式」几条内容视为不合格；提示词骨架
  重写为金标准颗粒度，一张装不下拆两张同 anchor。

---

## [1.29.1] — 2026-07-24

### 咨询师推介：价格默认不展示（运营口径定案）

- 简历图与介绍文案默认均不含价格（大部分推介不露价、先建立信任），**生成前必须问运营
  「这篇要不要展示价格」**，明确要求才加；要加只能用两个公开字段实时值。spec 五处 + SKILL
  红线速记同步。

---

## [1.29.0] — 2026-07-24

### xiaohongshu-creator 新增「咨询师推介笔记」场景（不从长文拆分）

给某一位咨询师做一条图文推介笔记，取材于官网免鉴权公开 API，卖点是「这个人可信、可托付」。
新增 `references/counselor-note-spec.md`（字段口径 / 照片三铁律 / 文案骨架 / 4–6 页轮播 / P2 底图留白模板）、
两个脚本、SKILL 新章节与触发词、guide 速查表一行，测试 +7（288→295）。

- **脚本 `scripts/fetch_counselor.py`**：`--list` 出全部咨询师概览、`--emp <emp_no>` 出单人详情
  （含 `profile_sections` 全文）。风格照抄同目录 `fetch_post.py`。
- **脚本 `scripts/compose_photo.py`**：把运营提供的真实照片**本地几何合成**（等比裁剪 + 圆角 +
  品牌色描边）进 P2 简历卡底图的留白区，不联网、不调模型。`env_check.py` 的 xhs profile 把 Pillow
  列为该场景**可选模块**（缺失只 warn 不阻塞就绪，`--install` 仍自动补装）。

**为什么设 `contracted_price` 红线**：咨询师详情响应里带一个 `contracted_price`（签约价）——这是
工作室与咨询师之间的**结算价、属用户隐私口径**，与对外标价是两码事。一旦误当"优惠价"写进笔记，
既泄露内部结算、又与官网标价冲突。故 `fetch_counselor.py` 在返回前**显式 `del contracted_price`**，
任何产物绝不出现；对外价格只用 `price_per_session`（¥N / 次）与 `communication_price`（预沟通 ¥N / 免费）。

**为什么设照片三铁律**：真人肖像的合规与失真风险远高于插画。①**授权先行**——出图前必须拿到"咨询师
本人同意用于小红书宣传"的确认，未确认停等不出图；②**只本地合成、绝不喂 AI**——照片只走 `compose_photo.py`
做几何处理，绝不喂 Gemini/GPT 生图重绘（AI 改脸致肖像失真 + 伪造肖像合规风险）；③**不入库、用完即弃**——
照片不提交 git，交付后提醒运营自行保管。一张未授权或被改脸的咨询师照片流出，对靠信任吃饭的工作室是
可上门维权的事故，故宁可退回纯插画简历卡，也不碰这三条。

---

## [1.28.1] — 2026-07-24

### 修复 pillar-spec 表格排版

- v1.27.0/v1.27.1 把「固定分类清单」「标签选型三规则」误插进 API 字段映射表格中间，
  表格被拦腰截断；现移到表格之后，内容不变。

---

## [1.28.0] — 2026-07-24

### lint 新增 stat-block 规则：把 R3「带出处统计块」变成机器闸

- SEO/GEO 巡检发现近期文章（恋爱脑一文）引 8 篇实证研究却零统计数据点——硬性要求 R3
  （≥3 处统计+紧跟来源）一直存在但无机器校验，靠人工遵守失守。
- lint_markdown.py 新增 `--stats-min N`（默认 0 向后兼容）：统计样式（数字+%/‰/倍）须与
  `[[n]](url)` 引用标注**同行**才计数，不足 N 报 stat-block 违规；SKILL 流程命令改为
  `--citations <N> --stats-min 3`。测试 +3（含真实事故形态用例），288 全绿。

---

## [1.27.1] — 2026-07-24

### pillar-spec 补标签选型三规则

- v1.27.0 只给 tags 加了数量说明，本版补全体系：①**优先复用已有标签**（写前先拉
  /api/public/blog/tags 现有库，同义必须用原词——自由词自动入库，同义分裂会废掉标签聚合与
  相关推荐）；②命名规范（2–6 字中文名词短语、不带 #、不与分类名重复）；③至少 1 个标签对齐
  本篇 target_keywords 核心长尾词（标签页=长尾词聚合着陆面）。

---

## [1.27.0] — 2026-07-24

### seo-artical-creator：博客分类体系六分类 + 选型指南

- **动机**：官网 45 篇长文全挂「心理科普」单一分类，筛选条形同虚设——根因是 pillar-spec 的
  frontmatter 示例写死 `category_slug: psych-101` 且无选型指南，所有文章照抄示例。
- 生产库已建 5 个新分类并按主题回填 45 篇（创伤与疗愈 11 / 情绪与自我 18 / 亲密与家庭 7 /
  职场心理 2 / 留学生心理 1 / 心理科普兜底 6）；发布链路（category_slug/tags 映射）本就齐全，零代码改动。
- pillar-spec 新增「固定分类清单」六选一与判据（两类都沾选更具体的；绝不自造 slug——服务端 400；
  扩分类须先生产库建好再用）；SKILL.md frontmatter 字段清单补 category_slug/tags 并强调选型。

---

## [1.26.0] — 2026-07-24

### 黄金范例升级 v1.9 知识海报密度体系（xiaohongshu-creator）

- **动机**：assets/example-xhs-note.md 是 SKILL 指定的「对照学习」锚点，但内容页提示词
  还是 v1.8 之前的老简版（每页 285–335 字，实测出图仅 3 条要点），落后于 v1.9 规格会把
  新拆笔记的密度往低里带。
- **升级**：P2–P5 按 layout-gallery 金标准颗粒度逐页重写（335→1800–2200 字/页），四页四种
  版式（⑭误区纠错卡/②对比表/⑦拆解结构图/⑥数据图），每页 ≥6 信息点、图文双通道、抽象落地
  具体场景；P1 封面/P6 末页保持柔和治愈精简定位；补齐缺失的「视频参考图提示词」节
  （**PN** 标记，不破坏页数计数契约）。事实基底零新增（数字/出处全部溯源 pillar 原文）。
- **对抗审查 2 medium + 5 low 全修**：比例锚点「竖版 3:4 构图（1080×1440）」统一归位行尾
  （防 1:1 切换正则截断锚点后的合规要求）、⑭ 结语条补模板必备的求助判据、P5 数据补
  Cloitre 2019 出处并厘清分母口径、P3 溯源修正与格内说明压回 ≤10 字、P6 副标题两处同源。
- **真图密度验证通过**：新版 P2 实测出图为完整误区纠错海报（10+ 信息点、6 个各不相同的
  具体场景、锚点人物一致），对比旧版 3 条要点简卡密度质变。285 测试全绿。

---

## [1.25.0] — 2026-07-23

### 路线 0 复活：后端一致性生图回归通过 + 删除四态对齐 + 插件 2.1.3 话术

- **一致性生图已在 nbdpsy-server 按原契约 1:1 复刻上线**，skill 侧端到端回归通过
  （P1 封面 + 锚点批量 2/2，urls 下标对齐/锚点一致性/中文零错字/502 瞬时容忍均实测）；
  撤掉 SKILL.md 路线 0 与 gen_images.py 的「暂不可用」标注，后端自动出图恢复为默认首选。
  对齐行为差异：台账 404=gone→「可安全重新发起」（生图与删除相反，重发只多扣额度）；
  单次 prompts>99 客户端硬拦；已知实际出图 1024×1536（2:3），风格闸门与提示词注明勿贴上下边缘。
- **删除任务四态对齐**（server 台账已落库）：新增接口 unknown（重启打断删除执行→人工创作中心
  核对）；404 语义改「deletion_id 不存在」；超时 hint 改 --delete-status 重查（台账落库随时可查）。
- **guide 插件话术**：extension_version（当前 2.1.3）↔ chrome://extensions 版本比对（别拿服务端
  version 字段比）；换新包步骤；「使用帮助」内置指南入口 FAQ。
- 两份交接文件反馈区均已回执（含 2:3 比例与引号渲染两条信息级反馈）。

---

## [1.24.1] — 2026-07-23

### guide 补视频 remake/revise 话术

- guide 3.5 节此前只讲基础搬运——补「再制作（remake）」与「修订成片（revise，可反复迭代）」
  两条运营话术与命令（含仅 remake 可修订、真人出镜勿用 remake、attribution 等边界），速查表加
  「这条视频 XX 处改一下」一行。youtube-transport skill 本体 v1.22.0 已支持，此为客服台入口补齐。

---

## [1.24.0] — 2026-07-23

### 删除已发布笔记（全新能力）+ 导出 no_data 语义 + 拉数据 --refresh

- **来源**：nbdpsy-server 交接《2026-07-23 server 更新——删除笔记与数据导出》。server 已上线两块
  运营能力（均真账号 e2e 验证、生产生效）：**按标题删除已发布笔记**（异步，`note-deletions` 两条端点）
  与**笔记数据导出的 no_data 明确语义**。契约以 `notes_rest.py` 的 `MANIFEST_ENTRIES` 为准逐参核对。
- **`publish_note.py` 新增 `--delete-note`**（按标题删已发布笔记，**不可逆**）：
  `--delete-note --account <号> --title "<标题>" [--count N]`。stderr 起手警示「删除不可逆，应已与运营
  确认」；POST `/api/accounts/{id}/note-deletions {title,count}`（客户端预检 count 1–10）→ 每 4s 轮询
  到终态（默认 300s）。`done` → `{outcome:done, deleted, remaining}`（remaining>0 带剩余篇数 hint）；
  `error` → 按 reason 给 hint（`note_not_found`=标题须精确匹配可先 --notes 核对；`need_manual_login`=
  登录态失效重扫码），exit 1。**poll 404（进程内存台账失效，server 重启即丢）或轮询超时 → `unknown`**：
  删除不可逆、可能已执行也可能没有，hint 引导「先 --notes --refresh 核对剩余篇数、确认仍需删除再重发，
  绝不盲目重发」，exit 0。
- **`--notes` 新增 `--refresh` 旗标**：先 POST `/api/accounts/{id}/note-exports` → 每 4s 轮询导出到终态
  （默认 300s）→ 成功后走现有 `account_notes` 读快照。导出 `error` 且 reason 含 `no_data`（当天刚发的
  笔记次日才入看板）→ `{available:false, no_data:true}` + 话术 hint，**exit 0（不是故障）**；其它 error
  原样落 failed。`--wait-timeout` 默认改为按用途取（发布 900 / 删除·导出 300）。
- **`account_notes` 404 兜底文案更新**：由「联系管理员核对」改为「先跑 --notes <账号> --refresh 触发
  一次导出再读」。
- **`nbdpsy-guide/SKILL.md`**：手册 ⑦ 之后插入「⑧ 删除已发布的笔记（不可逆）」——触发前必须复述
  「账号+完整标题+删几篇」得运营确认才执行；原「⑧ 图床」顺延为 ⑨，「八件事」→「九件事」，速查表/FAQ
  同步（删错不能恢复 / 发重了用 ⑧ 清理 count=多余篇数 / 今天刚发次日才有数据）；⑥ 拉数据节补 `--refresh`
  用法与 no_data 话术。
- **测试**：`tests/test_publish_note.py` 追加 13 例（delete POST 路径与 {title,count} payload、count 0/11
  预检、done 带 deleted/remaining、error 两 reason 的 hint 分支、poll 404→gone→unknown 安全 hint、超时
  running→unknown；refresh POST note-exports→轮询→no_data available:false exit 0、done 末尾调
  account_notes、其它 error 抛；404 新文案；`--delete-note` 缺 --title argparse 校验），全绿。

---

## [1.23.0] — 2026-07-23

### 发布线增强（改期 / 撤稿 / 列任务 / 图床 / whoami 自检）

- **背景**：nbdpsy-server 已上线一批发布线 REST 端点（`publish_rest.py` 的 PATCH/cancel/list、
  `uploads_rest.py` 图床、`system.py` whoami），`publish_note.py` 补齐对应子命令，让运营发出去之前
  还能改、发错了能撤、图片可先传图床。契约以服务端 manifest（`publish_rest.py`/`uploads_rest.py`/
  `system.py`）为唯一事实源逐条核对。
- **publish_note.py 新增子命令**（风格与既有 `--list-accounts`/`--job`/`--check-cookie` 一致，stdout 纯 JSON）：
  - `--list-jobs [--account 号] [--status 状态] [--limit N]`：列发布任务，输出精简字段
    `{job_id, account_id, title, status, schedule_time, note_url, error, created_at}`（与服务端
    `_job_view` 对齐取子集）；`status` 原样透传，非法值由服务端 400 回合法清单。
  - `--reschedule <id> --schedule <时刻|now>`：改待发定时，**PATCH 只带 `schedule_time`，绝不多带字段**
    （部分更新语义是服务端契约核心）；`now` → `{"schedule_time": null}` 清空转立即发；非 pending
    返回 `{ok:false,status}` → exit 1 + hint（已在发/已终态需另建新任务）。
  - `--cancel <id>`：撤稿；`{ok:true}` exit 0，`{ok:false,status}` exit 1 + 按 status 区分文案，404 透传。
  - `--upload-images <目录|文件...>`：图床上传（multipart 字段名统一 `files`），客户端预检 1–18 张，
    目录按文件名排序；输出 `{batch_id, urls, expires_at, warnings}`，urls 可直接作发布 images，7 天过期。
  - `--list-uploads`：列自己未过期的上传批次，透传 `{batches:[...]}`。
- **`--self-check` 说明对齐**：第一步先打 `GET /api/whoami`（最便宜的连通 + key 校验），身份
  `{name, role}` 并入输出——此前版本已如此实现，本次补测试固化该顺序契约。
- **测试**：`tests/test_publish_note.py` 追加 14 例（reschedule PATCH 方法/路径/payload 只含
  schedule_time/`now`→null/非 pending 语义、cancel 两分支、list-jobs query 组装与精简字段、
  upload-images multipart 字段名与顺序及 1–18 预检、目录收集排序、whoami 先行），全绿。

---

## [1.22.0] — 2026-07-23

### 薯营家停机迁移（视频线切 /api/video + remake/revise 新能力 + 生图缺口协同记录 + 死链清理 + 基址统一）

- **背景**：薯营家（`xhs.nbdpsy.com`）2026-07-23 整套永久停机（调用=连接失败非 410），一切能力统一到
  nbdpsy-server（`mcp.nbdpsy.com`），唯一凭据仍是同一把 `NBDPSY_XHS_API_KEY`（nbdpsy-server apikey）。
- **基址统一（shared/nbdpsy_common.py，同步 6 副本）**：`DEFAULT_VIDEO_API_BASE` 由 `xhs.nbdpsy.com`
  改为 `https://mcp.nbdpsy.com`（与 `xhs_api_base` 同服务同凭据）；`SANDBOX_ALLOW_DOMAINS` 移除
  `xhs.nbdpsy.com`。
- **视频线迁移+增强（nbdpsy-youtube-transport/scripts/transport_video.py）**：
  - 端点 `/api/video-transport/jobs*` → `/api/video/jobs*`（建/查/列/retry/delete 全部）；列表读 `items`。
  - 建任务新增 **`--mode transport|remake`**（默认 transport）；逐参核对 nbdpsy-server `video_rest.py`
    请求模型，`voice/burn_subtitles/max_resolution` 服务端仍收，故保留。
  - 产物键扩展 `storyboard_url`/`meta_url`（仅 remake，缺失容忍），相对 `/uploads/…` 拼 mcp 成免鉴权直链。
  - **新增成片修订 `--revise <job_id> --instructions "…"`** → `POST /api/video/jobs/{id}/revise` →
    派生子任务增量重制并默认轮询到终态（`--no-wait` 同语义）；400=解析失败带 LLM 说明、409(detail)=父片
    未完成/非 remake。
  - 轮询间隔对齐红线（30s）；`--mode remake` 与 `--revise` 默认 wait-timeout 提到 4500s，transport 维持 1800s。
  - 错误契约注释写明 409 用 `detail` 键；unknown 态绝不重发语义原样保留。
  - SKILL.md 补 remake/revise（含「仅平面图形类、真人勿用」「发布须附 meta attribution、重要成片人工终审」）、
    基址/凭据表述改 nbdpsy-server、附两条 mcp 标杆样片直链；tests 同步（路径、mode、revise、409 detail、items）。
- **生图缺口处置（不绕路）**：nbdpsy-server 36 端点无一致性生图（原薯营家 `POST /api/op/consistent-images`
  随停机消失）。`nbdpsy-xiaohongshu-creator/SKILL.md` 路线 0 开头 + `gen_images.py` docstring 顶部加现状
  说明（本路线暂不可用、走宿主/人工兜底、服务端补齐即恢复）；**代码逻辑与契约不动**，base 随 `video_api_base`
  指向 mcp。缺口与旧契约完整记录在 NBDpsy 仓 `文档/2026-07-23-一致性生图未迁移-协同记录.md`，请 server 侧排期。
- **死链清理**：README/setup.py/nbdpsy-guide/publish_note.py/gen_images.py 及 tests 中的 `xhs.nbdpsy.com`
  /`video-transport`/「运营接入 JWT」措辞逐处清理为 nbdpsy-server apikey；publish_note `--notes` 注释由
  「server 端上线中」改为已上线（笔记主键 (账号,标题,发布时间) 三元组、无 note_id）。
- 版本 1.21.0 → 1.22.0（plugin.json + marketplace.json 共 3 处）。

---

## [1.21.0] — 2026-07-21

### xiaohongshu-creator：篇数以用户为准（1–2 篇小批量模式）

- 此前验证闸门写死 5–8 篇，用户说「只拆 1 篇」时 agent 需临场取舍、行为不一致。
  现明确：**用户指定篇数时以用户为准**，小批量选型优先级——单篇选 P2 处境命名（主力路径），
  两篇选 P2 + P9 首访祛魅（击中场景＋降求助门槛，认知层+转化层最小闭环）；固定配比不适用，
  **其余护栏一律不降**（五问/慢性度/G1–G10/危机声明/合规扫描/P4·F1 零产出照常）。
  overview 须注明本次未覆盖的原文核心点，便于同一长文下次续拆不撞车。

---

## [1.20.1] — 2026-07-21

### 安全修复：基址解析不再信任 workspace/.env（confused deputy）

- **缺陷**：`xhs_api_base()` / `video_api_base()` 原走 `get_secret` 三层解析（环境变量 >
  workspace/.env > 用户级 secrets）。攻击者往内容工作区塞一个**只写 `NBDPSY_XHS_API_BASE=
  <恶意主机>`、不写 key** 的 `.env`：基址被 workspace 层改写、真密钥继续从用户级穿透解析，
  发布/搬运/生图请求会把真 Bearer 密钥发去恶意主机。
- **修复**：新增 `get_base()`——基址只认 环境变量 > 用户级 secrets > 默认值，**跳过
  workspace/.env**（与 publish_post.py / fetch_post.py 的既有正确写法对齐）；密钥解析三层
  行为不变。三个调用方（publish_note / transport_video / gen_images）经共享助手一处修复全覆盖。
  临时改基址请用环境变量或各脚本 `--api-base`。安全回归测试 +2。

### 即梦登录对齐 CLI 设备流现实（dreamina_login.py）

- 即梦 CLI 已弃用旧「本地回调自动弹浏览器」，现行默认即 OAuth 设备流。浏览器模式改为：
  从管道拿到完整登录链接后**脚本自己开浏览器**（主路径而非兜底），并顺手生成一张备用二维码
  PNG（默认浏览器不可用时手机直接扫）；进度文案同步改写，不再声称"CLI 已自动弹出浏览器"。

---

## [1.20.0] — 2026-07-21

### 小红书配图接后端一致性出图（gpt-image 锚点法）

- **动机**：轮播配图此前只有「宿主自己画 / 人工喂 Gemini-GPT」两条路，一套 5–8 篇 × 6–9 页 = 30–70 张，
  品牌基底一漂移（配色跑偏 / 人物换脸 / 出成方图）就整批全废重出——最贵的事故。后端上线 gpt-image
  **锚点法一致性出图**后，本级接上它，让「先出封面过闸门、确认后整号锚定同一张 P1 批量出」变成命令。
- **新脚本 nbdpsy-xiaohongshu-creator/scripts/gen_images.py**：经运营工具 op API 出图（复用
  `NBDPSY_XHS_API_KEY` 同一把运营接入 JWT，base 用 `NBDPSY_VIDEO_API_BASE`，默认 `https://xhs.nbdpsy.com`）。
  - **本地提取**每页提示词，判据与后端 `extract_slide_prompts` 完全一致（行首 `### P<数字>` 定位页 +
    页区间内第一个完整 ``` 围栏块）；**完整性校验**拦缺围栏页（后端会静默跳过导致页序错位）；
    `## 视频参考图提示词` 节的 `**P1**` 加粗标记天然不被计入。
  - **P1 锚点闸门**：`--cover-only` 只出封面 → 运营确认配色/人物/比例/图中中文 → 输出里的 `anchor_url`
    喂给**整套所有篇所有页**（`--anchor-url`），各页独立锚定生成，整个号调性统一。
  - 异步 job（202 拿 job_id + session_id）+ 轮询到终态（间隔 10s，默认超时 max(180, 页数×90)）+
    逐页下载到 `{note目录}/images/{note名}/P01.png…`；`--pages 2-9 / 3,5` 只重出失败页（带同一锚点）；
    `--job/--session` 复查补下（状态文件恢复页映射）；`--dry-run` 离线看 payload。
  - stdout 纯 JSON（done/partial/failed/pending/unknown）：额度/限流表现为 done+errors，透传到该页 `error`；
    `pending/unknown` 绝不重发（防重复生成烧额度）——与 publish_note / transport_video 同款不重发范式。
- **SKILL.md 第 6 步**改名「出图（后端一致性出图优先，宿主自适应兜底）」，新增**路线 0 · 后端一致性出图**
  （凭据在位默认首选，把风格闸门映射成三条命令）；原「有/没有图像生成能力」两分支降为凭据缺失时的兜底；
  风格确认闸门 blockquote 原样保留；关键文件表与铁律 3 同步。
- 单测 `tests/test_gen_images.py`（24 例，纯函数不打网）：提取器 / 完整性校验 / 视频参考图节不被提取 /
  页选择解析与越界 / 两位数命名 / 相对 URL 拼绝对 / 终态映射与 errors 透传 / dry-run CLI 契约。

---

## [1.19.1] — 2026-07-20

### nbdpsy-guide 补「更新工具包」指引

- 此前 7 个 skill 里无任何一处写更新命令，运营说「更新 nbdpsy-skills」时 agent 只能靠猜。
  nbdpsy-guide 新增「更新工具包」节：**命令由 agent 替运营跑**（Windows 借
  `powershell.exe -NoProfile -ExecutionPolicy Bypass` 跑 irm 一条命令；Linux/macOS 用 curl|bash），
  说明凭据不受覆盖影响（用户级 secrets.env / ~/.dreamina_cli/ 均在仓库外）、完成后提醒重启 Claude Code。
- description 触发词补「更新工具包 / 更新 nbdpsy-skills / 升级 skill / 装最新版」；常见问题速查表同步加行。

---

## [1.19.0] — 2026-07-20

### 即梦登录一键化（dreamina_login.py）

- **事故动机**：Windows 小白运营被旧文案引导跑 `dreamina login --headless`，终端字符二维码显示不出
  （headless 需 google-chrome + 终端字体），PowerShell 折行又把 verification_uri 里的 user_code 参数
  截断（浏览器报"没有 user_code"），每次重跑还生成新码作废旧网址——反复登录失败。而有屏机器根本
  不该用 `--headless`：`dreamina login` 默认模式本就会自动弹默认浏览器完成登录。
- **新脚本 scripts/dreamina_login.py**：登录全程 agent 包办，用户唯一动作是用**抖音 App 扫码/点确认**。
  - `--mode auto`（默认）自动判断：Windows/macOS 或有 DISPLAY/WAYLAND 的 Linux → 弹默认浏览器
    （`dreamina login`）；无屏 Linux 服务器 → `dreamina login --headless` 并把抖音二维码生成 PNG 图片
    交给 agent 展示给用户扫（缺 `qrcode` 库先自动 pip 装，装不上降级为只给完整网址）。
  - 浏览器模式下 CLI 若弹不开浏览器（设备流回退），脚本从管道拿到**完整逻辑行**的 verification_uri
    自己 `webbrowser.open()`——天然免疫终端折行截断（根治 Windows 事故）。
  - 成功判据 = 每 4s 轮询 `dreamina user_credit` 拿到 `total_credit`，不依赖子进程退出码；已登录则幂等直接返回。
  - 二维码几分钟过期 → `--timeout`（默认 240s）超时自动杀进程换新码，`--retries`（默认 3）次。
  - 所有子进程 `encoding=utf-8, errors=replace`（防 Windows GBK 崩），异常/退出路径 finally 杀子进程。
  - `--check-only` 只查登录态不发起登录；stdout=JSON / stderr=中文进度。
- **全仓话术统一**：check_env.py / SKILL.md / setup.py / README.md / jimeng_gen.py / seedance_jimeng.py /
  nbdpsy_common.py（含 6 份副本）里教用户手敲 `dreamina login --headless` 的引导，一律改为
  「让 AI 帮你登录（自动弹浏览器/出二维码，抖音 App 扫码即可）」；`--headless` 仅保留在脚本内部实现
  与「无屏服务器」说明语境。
- 测试 +8（test_dreamina_login.py：设备流行解析提完整 URL/user_code + 干扰行/缺项、auto 模式选择
  Windows/macOS/Linux±DISPLAY/Wayland 五场景），不跑网络/真 CLI。

---

## [1.18.0] — 2026-07-18

### 新增 skill：nbdpsy-youtube-transport（YouTube 视频搬运）

- **新技能**：给一条 YouTube 链接，产出带中文字幕/配音、可直接发布的成片 + 中英字幕 + 中英双语逐字稿。
  重活全在服务端（小红书运营工具后台 `https://xhs.nbdpsy.com`）：下载 → 转写 → qwen-mt 翻译 →
  豆包配音 → 音画同步 → 烧中文字幕 → 出成片，并自动打 NBDpsy 品牌 logo + 片头版权声明。
- **scripts/transport_video.py**：经 video-transport REST 建任务（`POST /api/video-transport/jobs`，
  异步 202）→ 轮询（`GET .../jobs/{id}`，pending→running→completed/failed，每 ~15s，瞬时故障容忍）→
  取产物（相对 `/uploads/…` 拼成免鉴权公网绝对 URL）。含 `--url/--job/--list/--retry/--delete/
  --download/--no-wait`。沿用发布脚本的**防重发**范式：状态未确认落 `unknown` 带 job_id，绝不重建任务。
  客户端预检只放行 youtube.com / youtu.be（防子串绕过）。
- **凭据零新增**：复用小红书运营接入的 `NBDPSY_XHS_API_KEY`（同一套 `get_current_user` 鉴权），
  配过自动发布即可直接搬运；基址可选 `NBDPSY_VIDEO_API_BASE`（默认 `https://xhs.nbdpsy.com`）。
- **沙盒放行**新增 `xhs.nbdpsy.com`（nbdpsy_common.SANDBOX_ALLOW_DOMAINS）。
- **登记**：install.sh / install.ps1 / plugin.json / marketplace.json / sync_shared.py 加入新技能；
  nbdpsy-guide 增「第 3.5 步 · 搬运 YouTube 视频」操作引导与能力表/菜单/FAQ 条目。
- 测试 +12（test_transport_video.py：URL 预检、错误体两形、产物 URL 拼接、建任务 payload、轮询终态/
  瞬时容忍/永久错误、CLI 拒非 YouTube/缺 key），全量 210 过。

---

## [1.17.0] — 2026-07-16

### 视频配音支持火山克隆音色（seed-icl-2.0）——用运营自己的声音

- **tts_gen.py 新增克隆音色路由**：默认音色（VOLC_TTS_VOICE）以 `S_` 开头（火山声音复刻 speaker）时，
  旁白走 `X-Api-Resource-Id: seed-icl-2.0` + `X-Api-App-Id` 头（VOLC_TTS_APPID）+ body 带 user.uid，
  speaker=S_xxx；否则回归 seed-tts-2.0 默认音色；再不行 edge。同一个 unidirectional 端点、复用现有
  流式解析器。纯人声（声音复刻是标准 TTS，无自带 BGM/音效，与 BGM 层不冲突）、全片音色一致。
  缺 VOLC_TTS_APPID 时报清晰错误（不静默失败）。凭据零新增槽位（复用 API Key/AppID/默认音色）。
- check_env.py / .env.example / SKILL.md / setup.py 同步克隆音色说明。
- 实测：用真实克隆音色 S_moiqVFN72 出合法 mp3（24kHz、ID3）。测试 +3，全量 199 过。

> 管理端：后台豆包卡片填 API Key + AppID + 默认音色（S_xxx），凭据包/运营接入包自动带上
> （需 NBDpsy 后端 assemble_bundle 更新，见该仓库同日提交）。

---

## [1.16.0] — 2026-07-15

### 新增 nbdpsy-guide 上手向导 + 小红书运营 API 操作手册 + 凭据持久化澄清

- **新 skill `nbdpsy-guide`**（第 6 个）：新运营说「教我用 / 能干啥 / 帮我上手 / 怎么发小红书 /
  怎么装插件 / 有哪些账号 / 看笔记数据」时的第一站。先自检环境（doctor + --self-check），再介绍
  五个内容技能能干啥、怎么串产线，带做第一个任务；并逐条给出 server 工具操作命令（装插件 /
  登录扫码 / 看账号 / 验活 / 发布 / 拉数据分析）。已登记 install.sh / install.ps1 / plugin.json。
- **publish_note.py 新增 `--notes <账号>`**：拉账号已发布笔记的清单与互动数据供分析；server 端
  该端点（`GET /api/accounts/{id}/notes`）正在上线中，404 优雅降级为「还在上线中」而非报错。
- **凭据持久化说明**：接入包与 guide 讲明「凭据存 `~/.config/nbdpsy/secrets.env` 永久保存，
  新对话自动读、只需发一次；重发新包自动覆盖旧凭据」。配置包 Part A 改为「先 doctor 查是否已装、
  已装则跳过安装只换凭据」。装插件默认步骤（v1.15.1）补的 serverUrl 同步进 guide。
- 测试：+7 例（--notes 三态 + guide 结构四项），全量 196 过。

---

## [1.15.1] — 2026-07-15

### 修：装插件默认步骤漏 serverUrl，运营会卡在「插件连不上」

- Chrome 插件（小红书登录用）弹窗要填 **serverUrl + apikey 两样**，SKILL「装插件」章节的
  手写兜底步骤只写了 apikey、漏了 serverUrl（`https://mcp.nbdpsy.com`）。虽然 skill 已写
  「以 `--extension-info` 返回的 install_steps 为准」，但兜底版补全 serverUrl + 无痕模式勾选，
  防 agent 走简版时运营卡住。server 端 `GET /api/extension`（v0.4.0）返回的官方步骤本就完整。

---

## [1.15.0] — 2026-07-15

### 一键接入自检 --self-check（配合配置包在 Claude Desktop 里傻瓜式接入）

- **publish_note.py 新增 `--self-check`**：一条命令验证「连通性 + 身份 + 被授权账号 + 就绪」，
  输出结构化 JSON（`ok`/`ready`/`identity`/`account_count`/`accounts`/`need_relogin`/`verdict`），
  可反复跑（运营说「帮我做接入自检 / 我配好了吗」即触发）。whoami/accounts 失败都保持 self-check
  信封（不落 publish 失败信封）；`cookie_status=error` 不误导重扫；`unknown` 视为可用（新号初始态）。
- **管理后台配置包模板优化**（NBDpsy 后端）：新增 O 段环境闸门（先验本机可执行，粘错到
  Chat/网页/手机版会被友好挡回并指去 Claude Desktop 的 Code 标签页；Windows 探针用
  `python --version` 而非在 PowerShell/Git Bash 里不存在的 `ver`）；B 段从裸 curl 自检收敛为一条
  `--self-check`；apikey 从正文散落 4 处收敛到凭据块 1 处（更安全）。
- 测试：+4 例（self_check 就绪/401/无账号/accounts 失败信封），全量 189 过。

---

## [1.14.0] — 2026-07-13

### 小红书账号接入自检 + chrome 插件安装/登录/验活全套指导

- **publish_note.py 新增三个接入辅助命令**：
  - `--extension-info`：插件包 download_url + 官方 install_steps + `server_time`（登录轮询起点，须在扫码前取）
  - `--wait-login --since <server_time> [--account-id N]`：轮询 `GET /api/login/poll` 等运营扫码完成（done=0/未等到=1）
  - `--check-cookie <账号名或id>`：触发 cookie 验活并轮询五态到结果（valid=0；error=基础设施失败≠失效）
- **SKILL.md 新增「小红书账号接入与管理」章节**：三步接入自检（凭据 xhs_ready / 授权账号 /
  插件判据倒推）、装插件逐步人话指导（chrome://extensions 开发者模式加载已解压 + 填 apikey）、
  登录新号与重扫流程（先取 server_time → 无痕窗扫码 → wait-login 确认 → check-cookie 兜底）、
  用账号打开小红书（插件卡片 cookie 注入）。content-pipeline 7.5 步与 README 排障表同步指路。
- 测试：+3 例（extension_info 透传 / wait_login 轮询与 URL 编码与 account_id / cookie 验活 202→轮询），全量 185 过。

---

## [1.13.0] — 2026-07-13

### 小红书自动发布（经 nbdpsy-api，纯 REST）+ Claude 沙盒网络放行

> 服务端 nbdpsy-mcp 已删除 MCP、收口为纯 REST 的 **nbdpsy-api**（仓库改名 Buxiulei/nbdpsy-server，
> 线上 `https://mcp.nbdpsy.com`，`GET /api/manifest` 自描述）。本版让工具包直接消费该 API，
> 小红书图文笔记从「只能人工发布」升级为「自动发布可选、人工兜底」。

- **新增 `nbdpsy-xiaohongshu-creator/scripts/publish_note.py`**：解析笔记「发布文案」块 +
  `images/post-NN/` 配图（base64 内联，服务端无上传端点）→ `POST /api/publish-jobs`（异步 202）→
  轮询到 published/failed；支持 `--list-accounts`（选号）/ `--job`（复查）/ `--schedule`（定时，带时区
  偏移）/ `--dry-run`；标题≤20/正文≤900/话题≤10/图 1–18 超限提前 warning（服务端会静默截断）；
  frontmatter `hashtags: [#a, #b]` 非法 YAML 有退化解析；错误体两套形状（401/422=detail，其余=error）
  已适配；cookie 失效提前预警。
- **新增凭据 `NBDPSY_XHS_API_KEY`（可选）+ `NBDPSY_XHS_API_BASE`**：doctor 报 `xhs_ready`、
  env_check xhs/pipeline profile 列为可选项（缺失只 warn 不阻塞）、setup 凭据向导第 5 问；
  由管理后台「小红书运营接入」生成的运营接入包一键导入。
- **新增 `nbdpsy_common.py sandbox allow`**：把 nbdpsy 域名合并进 `~/.claude/settings.json` 的
  `sandbox.network.allowedDomains` + `permissions.allow`（只追加不覆盖、不碰 sandbox.enabled、
  坏 JSON 拒写）——解决 Claude Code Bash 沙盒（macOS/Linux/WSL2）拦外网致发布失败；setup 向导
  自动执行一次，运行期被拦时 skill 会引导重跑并提示 `dangerouslyDisableSandbox` 兜底。
- **SKILL.md/README 更新**：xiaohongshu-creator 第 7 步改「发布（自动可选）或交付（人工兜底）」，
  发布前必须经运营确认账号与篇目；content-pipeline 插入第 7.5 步可选自动发布；README 流程图/
  凭据手册/排障表同步（新增沙盒拦网条目）。
- 测试：新增 test_publish_note.py（16 例）+ test_sandbox_allow.py（5 例），全量 179 过。

---

## [1.12.0] — 2026-07-12

### 小红书：场景深挖路径升级为 MECE 体系（12 条 · 经三路红队攻击重构）

> 上一版只有 2 条深挖路径（处境具象化 / 认知反转），不满足 MECE。本版经**四路调研 + 三路对抗验证**重构：R1 求助行为模型（Andersen/HBM/Rickwood 等 8 个模型）、R2 痛点方法论（JTBD/Schwartz 认知五阶段）、R3 36 条真实爆款归纳、**R4 用我们自己 51 个长期客的真实付费触发时刻做校验**。

- **分类基准（唯一划分维度）**：**这篇笔记消解的那一道求助闸门**——读者从「有困扰」到「决定付费求助」必须跨过的坎。互斥靠唯一落点判定，穷尽靠链路封闭，合规靠结构性隔离（危机内容在链上无处安放，自动出局）。
- **12 条路径**（三层）：认知层 P1 痛感认领 / P2 处境命名（★主力）/ P3 归因矫正 / P4 代价显影（⛔ **配额=0**）；阻力层 P5 去羞耻化 / P6 失效归因 / P7 价值论证；转化层 P8 求助路径显影 / P9 首访祛魅（★打头阵）/ P10 可得性破解 / P11 临门推动；外加 **PX 关系人轴**（读者≠受苦者时走这条，落点必须是读者自己的动作）。
- **红队攻破并修正的三处致命问题**：
  1. **旧路径 A 一条踩三道闸门**（处境+代价+无解），天然违反互斥 → 拆开；且"当事人无解"是高威胁+低效能的绝望闭环（读者会去解决恐惧本身：否认、划走），改为必须给出口。
  2. **旧路径 B 的方向被生产数据证伪**：它生产的是"自诊完成态"而非购买态——预沟通不转化 42 人中 49% 主诉 CPTSD、8 人明写 CPTSD 却零转化；站内 CPTSD 集群 11 篇日均浏览全站最低、零预约关联。→ 降权为 P3 且落点从"确认标签"改为"机制+下一步"。
  3. **框架装不下自己最好的客户**：原链条全在心理认知上，装不下海外客（长期组 22% vs 脱落组 0%、LTV 1.9 倍、投放头名）→ 新增 P10 结构约束路径。
- **⛔ P4 代价显影配额 = 0**（恐惧不是求助的独立预测因子——HBM 中国样本里"感知严重性"不显著，显著的只有自我效能 β=0.279 与行动线索 β=0.323）。分类保留仅作**废稿检测器**。
- **选型规则**：**只看落点**——"读完这篇，读者要完成的那一个内在动作是什么？"（看最后三行）数不出唯一一个 = 选题没想清楚，返工。
- **配比（客户质量优先，不按痛感强度）**：7 篇 = 固定 5 篇（P2×2 · P5 · P9 · P8）+ 弹性 2 篇；硬约束：转化层 ≥1 且必含 P9、任一路径 ≤2、**护栏与配额按"篇内出现的任一路径元素"计**（堵住"标 P2 实写 P4"的规避洞）。
- **场景深挖五问**改版：删掉「不管它会怎样」（它直接生产 P4），换成 **「这一幕反复到第几次了」（慢性度计数器）**——钩到长期客的概率与议题**慢性度**正相关、与**痛感强度无关**。
- **十条全局硬闸 G1–G10**：最低出口律 / 躯体分流律 / 不给第三人贴标签 / 不代读者作结论 / 案例三律 / 危机与 CTA 分离 / 不卖依赖 等。
- reviewer checklist-note 第 0 条同步升级（主路径唯一性、落点审查、配额规避检测）；范例 frontmatter 新增 `scene_path` / `audience` / `chronicity`。

### 小红书：竞品调研落地的三项加固（23 个同类 skill 源码拆解后择优）

- **标题字数守卫**（`count_xhs.py`）：spec 写了「标题硬限 20 字」但脚本从来没查过——现补上 `title_chars`（剔除 emoji 计数），超限 exit 2。
- **负面提示词**（`illustration-spec.md`）：扩散模型经常无视"默认 3:4"自作主张出方图/宽幅——比例行现在带负面词。⚠️ 负面词**跟着比例一起切换**（3:4 禁"正方形"、1:1 禁"竖版"），避免切到 Instagram 出现「正方形构图……不要正方形」的自相矛盾。
- **风格确认闸门**（`SKILL.md` 第 6 步）：一套笔记 = 30–70 张图，品牌基底一漂就整批全废——现强制**先只出 P1 封面 1 张**，确认配色/人物/比例/无错字后，把它当参考图再批量出剩余。

---

## [1.11.0] — 2026-07-12

### 小红书：选题必须从「现象」深挖到「痛点场景」（本 skill 最高优先级规则）

> **为什么**：停留在现象层的笔记，读者反应是"学到了"（收藏 → 划走 → 忘记）；深挖到场景层的笔记，读者反应是**"这说的就是我"**（对号入座 → 情绪被击中 → 才可能付费）。**付费不是被科普说服的，是被场景击中的。**

- **拆分逻辑重写**（`SKILL.md` 第 1 步）：从「按 H2 主题智能聚合」改为**按痛点场景分箱**——长文是知识组织，笔记必须是场景组织。一篇笔记 = 一个具体场景 ＋ 长文里能解答这个场景的那部分知识（不必和 H2 一一对应）；5–8 篇 = 5–8 个互不重叠的**具体场景**，不是 5–8 个知识角度。
- **两条深挖路径**（`references/xiaohongshu-spec.md` §1.5 新增）：
  - **路径 A · 处境具象化** = 现象 ＋ 具体处境 ＋ 恶化后果 ＋ 当事人无解
    （孩子不爱说话 → 「孩子在学校被欺负了，回家一个字不说，你问什么他都摇头」）
  - **路径 B · 认知反转** = 你以为是 X（无害解释）＋ 但其实可能是 Y（被忽略的真相）＋ 信号
    （孩子不爱说话 → 「你以为他只是性格慢热，可很多孩子在真正出事之前，给父母的信号也不过就是不太爱说话」）
- **场景深挖五问**（动笔前逐题回答，答不上来禁止开写）：谁 / 什么时刻 / 正在发生什么冲突或代价 / 不管它会怎样 / **她自己为什么解决不了**（第 ⑤ 问是"你可能需要专业帮助"这句话唯一诚实的理由）。
- **一票否决（换行业测试）**：选题换成别的行业/人群还说得通 = 还在现象层，返工。「孩子内向不爱说话」教育机构、口才班、儿童摄影都能写；「被欺负了回家一个字不说」只有心理这条路能接住。
- **标题必须承载场景**而非知识点命名（❌「CPTSD 和 PTSD 的区别」／✅「一句'方案再改改'，我在工位上僵住了」）；三段式的「痛点场景开头」直接由第 1 步挖出的场景落地。
- ⚠️ **合规护栏（YMYL 红线）**：深挖场景 ≠ 制造恐慌。可写"这些信号值得当回事"，**不可写**"不管就会出大事"；风险提示须在源长文有出处、不得为钩子夸大因果；每篇必须给建设性出路；高危议题（自伤/自杀/重度精神障碍）只做识别与转介（12356 + 建议就医），**绝不暗示我们能处理危机**。判据：读者应感到「被理解了，且知道下一步能做什么」，不是「被吓到了，必须马上花钱」。
- **审查闸门**：`nbdpsy-content-reviewer` 的 checklist-note 新增**第 0 条（生死线，先审这条）**——换行业测试 + 场景要素在位 + 三段式在位 + 合规护栏；多篇并排若读起来像一份目录（第一章定义、第二章区别…）= 整组 FAIL。
- 黄金范例升级为场景型示范（frontmatter 新增 `scene` / `scene_5q` 字段，封面与标题同步场景化）；evals 新增 4 条断言。

---

## [1.10.0] — 2026-07-12

### 小红书：正文三段式（解决「纯科普难转化 / 硬广难曝光」）
- **强制三段式骨架**：① 痛点场景开头（15–20%，必须是具体生活场景，禁问卷腔）→ ② 科普干货主体（65–75%，**完全不谈自家服务**，读者不点主页也有收获）→ ③ 结尾轻引导（1–2 句，陈述事实、给出选项，不催不促不承诺）。
  依据：对齐小红书真实决策链路（痛点搜索 → 案例对比 → 私信咨询 → 社群成交）与投流过审规律（全文绝大部分是科普、只有结尾轻引导的笔记最易过审）。
- **轻引导写法**：新增安全句式库与反面例子（`references/xiaohongshu-spec.md` §1）。
- **合规脚本新增「硬广特征」闸门**（`check_compliance.py`）：促销/催促/诱导三类词进词表，投流拒审风险卡在发布前；已做防误伤窄化——「免费的自助练习」「立即求助」等正当科普表达放行。

### 小红书：封面三层组件 + 跨平台比例切换
- **封面/末页拆为三层组件**：`■ 背景层`（品牌资产，跨笔记原样复用）+ `■ 文字层`（每篇换）+ `■ 元素层`（每篇换）——批量产出、风格自动统一。
- **预览页「小红书 3:4 / Instagram 1:1」一键切换**：切换后所有提示词的比例参数行实时替换，复制按钮复制的即该比例版本（localStorage 记忆选择）；1:1 适配规则（副标题 ≤14 字、内容页信息点收到 4–7 个）随切换提示。
- 黄金范例与 evals 断言同步更新。

---

## [1.9.0] — 2026-07-08
- **小红书提示词模板体系重审（多 agent）**：版式扩至 **17 种**（分区图标清单/对比表/流程步骤/象限/隐喻/数据占比/拆解结构/因果链/时间轴周期/自查清单/恶性循环圈/情景对话/身体地图/误区纠错/认知重构/程度光谱/概念定义卡），每种配一条实测级完整范例（`references/layout-gallery.md`）+ 选型指引（"这页信息之间是什么关系"映射表）。

## [1.8.2] — 2026-07-08
- 版式扩至 13 种；新增「详写房规」（把提示词当施工图写，锁死模型随机性保证套图风格统一）；补第二个金标准范例。

## [1.8.1] — 2026-07-08
- **修正密度口径**：密度 = 图文共同表达的信息量，**不是字数**（反例：一个大隐喻 + 几个抽象标签仍是低密度）；粗黑标题从硬性要求降为可选设计项。

## [1.8.0] — 2026-07-08
- 小红书内容页升级为**高密度知识海报体系**：图文双通道（每条信息配一个能解码的具体场景小图）、一页 6–10 个信息点、分 2–3 区块组织。

## [1.7.1] — 2026-07-07
- Windows 缺 Git 时用 winget 自动装 Git 再走即梦官方主路（真正零前提安装）。

## [1.7.0] — 2026-07-07
- Windows 也自动安装即梦 CLI（官方脚本原生支持 Windows，无需 WSL）。

## [1.6.0] — 2026-07-07
- 小红书内容页版式从单一「要点卡」扩为**信息图菜单**（要点卡 + 对比/流程/象限/隐喻/数据/拆解图），干货感更强。

## [1.5.1] — 2026-07-07
- **回滚**：配图比例从 9:16 改回 **3:4（1080×1440）**（小红书显示面积最大、点击率最高），保留信息密度提升。

## [1.5.0] — 2026-07-07
- 配图比例改 9:16 + 信息密度提升（内容页 4–6 条/说明 ≤28 字/90–140 字/留白 1/3→1/5）+ 首图安全区提示。

## [1.4.1] — 2026-07-06
- **长文渲染事故防线**：新增 `lint_markdown.py`（CommonMark 加粗侧翼冲突 + 文内 `[[n]]` 数字引用标注校验），规范强制化，审查清单增加渲染页抽查。

## [1.4.0] — 2026-07-06
- **五 skill 统一加 `nbdpsy-` 前缀**便于检索（目录/frontmatter/互引/安装器/测试全量重命名）；安装器自动清理旧名副本。

## [1.3.2] — 2026-07-06
- 插件简介改小白一句话口径，最简启用方式前置。

## [1.3.1] — 2026-07-03
- **修复**：豆包 TTS V3 流结束哨兵 `code=20000000` 不再误判为错误（生产实测发现，官方文档未载）+ 回归测试。

## [1.3.0] — 2026-07-03
- 豆包 TTS 升级 **V3 单一 API Key 引擎**（`X-Api-Key`/unidirectional，V1 凭据向后兼容）；doctor/setup/文档口径同步。
- 修复：V3 流解析改增量 UTF-8 解码（跨 chunk 中文不再丢字）。

## [1.2.0] — 2026-07-03
- **五 skill 开跑前环境自检**：共享 `env_check.py`（profile 化依赖表 + `--install` 自动补 pip 包 + 凭据/系统件指引），插件市场安装路线自愈。
- 凭据体系：`doctor` 运行时自检 + `secret import` 消化凭据包（白名单过滤、不回显值）。

## [1.1.0] — 2026-07-03
- **六项使用反馈修复**：出图/参考图真停等闸门、视频分镜确认页 storyboard、HTML 按内容命名、缺密钥指向管理员、即梦与依赖全自动安装。

## [1.0.0] — 2026-07-02
- **首个插件版本：五 skill 内容产线成型**
  - `nbdpsy-seo-artical-creator`（官网 pillar 长文，走 external API 发布，后端自动推百度/IndexNow）
  - `nbdpsy-xiaohongshu-creator`（长文拆小红书图文 + 配图提示词）
  - `nbdpsy-text-to-video`（长文/笔记 → 竖屏短视频，即梦 Seedance + 豆包 TTS + ffmpeg 合成）
  - `nbdpsy-content-reviewer`（四清单对抗审查 + 图片/视频确定性检查脚本）
  - `nbdpsy-content-pipeline`（总导演：话题 → 成品全程编排 + 审查闸门）
  - 跨平台安装器（`install.sh` / `install.ps1` / `setup.py`，三系统 + 凭据向导）；共享层 `nbdpsy_common.py`（工作区 + 凭据三层解析）；校验脚本全面 Python 化（Windows 兼容）。

---

### 更早（插件化之前的独立 skill 阶段）
- **2026-06-30**：新增 text-to-video skill（长文/小红书笔记 → 竖屏短视频）。
- **2026-06-29**：首次发布 NBDpsy 内容创作 skills（seo-artical-creator + xiaohongshu-creator）。
