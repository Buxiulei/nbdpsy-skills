# 更新日志

NBDpsy 内容创作 skills（`nbdpsy-content` 插件）的版本变更记录。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)：
**Feature = Minor（1.x.0）｜Bugfix = Patch（1.0.x）｜Breaking = Major（x.0.0）**。

> 每次发版：改 `.claude-plugin/plugin.json` + `.claude-plugin/marketplace.json` 的版本号（共 3 处），在本文件顶部追加一节，然后 `git push`。

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
