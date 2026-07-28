---
name: nbdpsy-content-pipeline
description: NBDpsy 内容产线总导演：运营只给一个心理科普话题/想法，就把「官网 SEO 长文创作与发布 → 拆小红书图文笔记 → 轮播配图 → 竖屏短视频」整条流水线自动串完，每级产物先过 nbdpsy-content-reviewer 对抗审查（不过自动返工，最多2轮）再进下一级。只要用户说「做一期 XX 的全套内容 / 一条龙 / 全流程 / 从话题到视频 / 全套产出 / 帮我把这个话题做成内容矩阵」，即使用本 skill。适合非专业兼职运营的傻瓜式入口；各生产 skill 也可单独使用不经过本 skill。
---

## 你是流水线导演

依次驱动四个 skill，自己不生产内容。全程维护一份任务清单让用户看到进度。

## 第 0 步 · 环境与凭据自检（开跑前必做）

先跑一次自检，缺啥一次性告诉运营，别做到一半才卡（`{SKILL_DIR}` 沿用各 SKILL.md 既有占位约定）：

```bash
python3 {SKILL_DIR}/scripts/env_check.py --profile pipeline --install
```

依赖（yaml/requests/PIL）会自动补装；视频链依赖由 nbdpsy-text-to-video 自己的第 0 步 `check_env.py` 负责，本步不管。再跑凭据自检：

```bash
python3 {SKILL_DIR}/scripts/nbdpsy_common.py doctor
```

- 退出码 0 且 `ok=true` → 发文凭据齐，继续。
- `ok=false`（缺 `NBDPSY_BLOG_API_KEY`）→ **停下**，对运营说：
  「打开管理后台 manage.nbdpsy.com → 博客 → API Keys → 点『生成凭据配置包』，把整段复制发给我。」
- `doubao_ready=false` 只是提醒：视频将用免费 edge 配音，不阻塞。
- `xhs_ready=false` 只是提醒：第 7.5 步小红书自动发布不可用、改人工交付，不阻塞
  （要开通就找管理员在后台「小红书运营接入」生成接入包导入）。

### 消化「凭据配置包」（运营粘贴过来时）

当运营发来以 `# ===== NBDPSY 内容工具包 · 凭据配置包 =====` 开头的整段：

1. 把整段原样写入一个临时文件（如 `/tmp/nbd_bundle.txt`，权限 600）。
2. 运行 `python3 {SKILL_DIR}/scripts/nbdpsy_common.py secret import /tmp/nbd_bundle.txt`。
3. 删除临时文件。
4. 复跑 `python3 {SKILL_DIR}/scripts/nbdpsy_common.py doctor` 确认转绿。

**全程不要把密钥值回显到对话/日志**——值只经临时文件落本机凭据，不进命令行参数。

### 流程

0. 确认输入：话题/想法（唯一必需）。可选：指定篇数、只到某一级停。
1. 【长文】触发 nbdpsy-seo-artical-creator 完成选题→查证→撰写。写作态正文里的引用只写
   `【引: 作者/机构 年份, 文献简称】` 简称标记，编号、URL、参考文献区、frontmatter `citations`
   都不在这一步做（2026-07-26 老板定案：写作只管组织语言）。
1.5【引用落地】派**独立子代理**（不是写作那个实例）按 nbdpsy-seo-artical-creator 的「引用落地」步
   执行：扫标记 → 对回「查证优先」步产出的素材清单 → 去重编号 → 替换成 `[[n]](url)` → 生成文末
   「## 参考文献」与 frontmatter `citations` → 实跑 lint_markdown.py / preflight.py 自检。
   细则以那一步为准，此处不重抄。
   **派单时必须把两个绝对路径一并交给子代理**——它是新实例，没有写作那段对话，清单不落盘等于没有：
   带标记的草稿 `$WS/drafts/{slug}.md` + 素材清单 `$WS/drafts/{slug}.sources.md`
   （`WS=$(python3 {SKILL_DIR}/scripts/nbdpsy_common.py workspace)`）。
   **派单前先确认 `$WS/drafts/{slug}.sources.md` 存在且非空**：
   ⛔ 缺文件 / 空文件 = **打回第 1 步补查证轮并把清单落盘**，落盘后再派 1.5；
   **绝不许让子代理改走「自己联网查」分支**——那个口子只留给「清单里漏了的单条」，
   不是给「根本没有清单」用的，全靠联网自查正是编造风险最高的那条路。
   **产出是发布态**：正文 `【引:` 残留数为 0，
   `[[n]](url)` 与 `citations[n-1].url` 逐字一致，preflight 的**引用职责内三项**（`CITE-MATCH` / `RENDER-cite` / 残留=0）全绿。
   ⚠️ **不要在这一级要求「preflight 全绿」**——preflight 还判 R1 字数、R10 结构、加粗、title 长度等一堆与引用无关的项，
   而引用 agent **不许改正文措辞**（细则见 `nbdpsy-seo-artical-creator` 的「引用落地」步「preflight 门槛分级」）。
   写成全绿会让它要么违规改正文、要么反复打回烧掉返工预算。职责外的 fail **原样记进报告、随打回清单交给写作端**。
   引用 agent 打回（简称对不上素材清单、联网也查不到出处）→ 视同本级不过，把打回清单交回
   nbdpsy-seo-artical-creator 定向返工（换一条有出处的说法或删掉该断言）→ 重跑本步；
   沿用【审查】那套返工协议，长文这一级的返工轮次与第 2 步**合并计数**（≤2轮，仍不过→停，
   汇报人工），不因多这一步而放宽。
   ⛔ 本步没跑完不得进第 2 步：带简称标记的长文审查必判 FAIL，更糟的是第 4 步拆小红书时
   会把标记一起拆进笔记正文。
2. 【审查】派独立子代理加载 nbdpsy-content-reviewer 审长文（checklist-article）。
   FAIL → 把报告交回 nbdpsy-seo-artical-creator 定向返工 → 复审（≤2轮，仍FAIL→停，汇报人工）。
   引用 agent 报告里标注「引用阶段新增、未经查证轮」的条目要提示审查端重点复核。
3. 【发布】PASS 后按 nbdpsy-seo-artical-creator 的「生成即发布」步（API 直发）发布，记录 slug。
4. 【拆笔记】触发 nbdpsy-xiaohongshu-creator，传入 slug（自动拉文）。
   ⚠️ **该 skill 有两条形态路线，本步默认走路线①（信息图轮播，5–8 条笔记）**——
   流水线是"一句话全套"场景，不该在中途自作主张换产出形态。
   走**路线②（文字版，整篇 1 条）**只在两种情况：
   ① **运营在第 0 步就说了**（「做成文字版」「整篇发别拆」）→ 记进流水线输入，本步照做；
   ② 拆分时发现这篇的价值在**完整论证链**上、或有**必须整体呈现的表格/分级清单**
   （判据见该 skill 第 0.6 步）→ **停下来问运营一句**，别默默改形态：
   产出从 5–8 条变成 1 条，差别太大，不是可以静默替他决定的事。
   走了路线② 时，本步之后的【审查】【出图】按 `references/longform-typeset-spec.md` 的口径
   （§6 那张适用性对照表：密度五字段/页数/正文字数三项不适用，合规与红线一条不减），
   第 6 步的"停等闸门"**不适用**（路线② 不过 AI 生图，脚本直接出图）。
5. 【审查】nbdpsy-content-reviewer 逐篇审笔记（checklist-note），FAIL 同返工协议。
6. 【出图】按 nbdpsy-xiaohongshu-creator 的宿主自适应出图章节执行：
   宿主有图像生成能力 → 直接生成；没有 → **⛔ 停等闸门（硬性协议）**：把预览页
   （{note_dir}/{note_dir目录名}-preview.html）绝对路径给运营，并把 post-01 的全部页提示词
   逐页贴在会话里，说明回传方式（图片按 P01.png… 放进 images/post-NN/ 子目录），然后
   **立即结束当前回合等待**——不得继续第 7 步、不得假设图片已就绪。这是全流程预期内的
   正常长停等，不算失败。运营回复后逐篇核验图片数量=页数才继续；不齐则列缺再停。
7. 【审查】nbdpsy-content-reviewer 审图（checklist-images），FAIL → 只重出问题页。
7.5【发小红书·可选】图审 PASS 且本机有 `NBDPSY_XHS_API_KEY`（看第 0 步 doctor 的 `xhs_ready`，
   别用 `secret get` 探测——会回显密钥值）时，按 nbdpsy-xiaohongshu-creator
   第 7 步路线 A 执行：**先问清运营**（发哪个账号、发哪几篇、立即/定时），确认后逐篇
   `publish_note.py` 发布（异步轮询到 published，汇总 note_url）。运营不发/无凭据 → 跳过，
   交付时走人工发布提醒。账号没接入/登录态失效时，按 nbdpsy-xiaohongshu-creator
   「小红书账号接入与管理」一节引导运营装插件/扫码后再发。
8. 【视频】对用户选定的笔记（默认第 1 篇）触发 nbdpsy-text-to-video 十步产线。视频走图生时同样有
   storyboard 停等闸门（nbdpsy-text-to-video 第 2.5 步：分镜确认页 {workdir名}-storyboard.html
   给运营复制每镜提示词、回传 P{页号}.png 到 <workdir>/images/），停等协议同上。
9. 【审查】nbdpsy-content-reviewer 审片（checklist-video），FAIL → 按报告只重跑问题镜。
10.【交付】汇总：博客地址、笔记目录、images/、已自动发布的小红书 note_url、成片路径、
   各级 review-report.md。提醒：未自动发布的小红书笔记与视频号上传仍是人工步骤；
   上传前可再扫一眼各报告。

### 铁律

- 每级审查者必须是独立子代理（新实例加载 nbdpsy-content-reviewer），绝不让生产 agent 自审。
- 长文这一级有两道闸，顺序不可颠倒：先【引用落地】（第 1.5 步，`【引:` 残留必须为 0），
  后【审查】（第 2 步）。引用 agent **绝不自己编 URL**，对不上素材清单就打回写作端（2026-07-26 老板定案）。
- 审查 FAIL 未消除前不进下一级；第 3 轮仍 FAIL 必须停下找人，禁止硬闯。
- 人工等待点只有三类：笔记配图回传（第 6 步）、视频参考图回传（nbdpsy-text-to-video 第 2.5 步）、
  以及 dreamina 排队/扫码类外部依赖。停等时必须结束回合，恢复时从停等点续跑。
- 中断恢复：重新触发本 skill 并告知已完成到哪级，从该级之后续跑（各级产物都在工作区，幂等）。
  **长文这一级要问到 1.5 级粒度**：「写完了」（第 1 步，正文还是 `【引: ...】` 简称标记）与
  「引用已落地」（第 1.5 步，已替换成 `[[n]](url)` 的发布态）是两级；运营口头说的"长文写完了"
  通常只到第 1 级，**别顺势跳到第 2 步审查**——带标记进审查必判 FAIL，还会把标记一路拆进小红书笔记。
  不确定就机检判定，不靠追问：

  ```bash
  WS=$(python3 {SKILL_DIR}/scripts/nbdpsy_common.py workspace)
  # cite_scan.py 在 nbdpsy-seo-artical-creator 的 skill 根目录下（记作 {SEO_SKILL_DIR}）
  python3 {SEO_SKILL_DIR}/scripts/cite_scan.py "$WS/drafts/{slug}.md" --expect-empty
  ```

  exit 0（残留 0）→ 第 1.5 步已完成，可进第 2 步；**非 0 → 一律不进第 2 步，停在第 1.5 步先把引用落地**
  （exit 2 = 连草稿文件都找不到，说明第 1 步就没完成，回第 1 步）。
