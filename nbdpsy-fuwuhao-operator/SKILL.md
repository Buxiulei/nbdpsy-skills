---
name: nbdpsy-fuwuhao-operator
description: 运营 NBDpsy 微信服务号（公众号）：把长文/分发稿排版成公众号样式并建草稿、发布或定时发布、给粉丝群发（高危，每自然月仅 4 次）、装修自定义菜单、查已发文章台账与删除、看涨粉与阅读数据。当用户说「发公众号 / 发到服务号 / 服务号发文 / 把这篇长文发到公众号 / 公众号排版 / 排版成公众号样式 / 定时发公众号 / 明早九点发公众号 / 公众号群发 / 推送给粉丝 / 装修菜单 / 服务号菜单 / 公众号底部按钮改一下 / 公众号数据 / 服务号涨了多少粉 / 公众号阅读量 / 服务号台账 / 公众号都发过哪些 / 公众号文章改错字 / 删掉公众号那篇」时，即使没说「skill」字样也应使用本 skill。五个子场景：①**排版发文**（Markdown → 微信白名单内联样式 HTML，图片自动上传换 mmbiz 链接，封面自动进素材库）②**定时发布与定时群发**（微信 API 没有定时参数，由服务端队列到点执行）③**自定义菜单装修**（本地 JSON 为编辑真源，apply 前 diff）④**已发布文章查/删**（微信没有「改」，只能删+重发，会换链接、阅读清零）⑤**数据统计**（涨粉/阅读/分享，查服务端每日快照，可跨任意区间）。微信凭据（AppSecret）只存生产服务器、出站走固定出口 IP，运营电脑只拿个人 key（`NBDPSY_WECHAT_API_KEY`）走 REST。本 skill 只服务 NBDpsy 自家服务号，内容优先承接 nbdpsy-seo-artical-creator 的长文与公众号分发稿；不适用于其它公众号的泛化代运营。
---

# 微信服务号运营（排版 / 发布 / 定时 / 群发 / 菜单 / 数据）

给一篇稿子或一句运营指令，完成服务号侧的全部动作：**排版 → 建草稿 → 发布（可定时）→ 查台账 → 看数据**，
另含**菜单装修**与**已发布文章删除**两条独立线。

**重活全在生产服务器**（`database.nbdpsy.com`）：换 token、调微信接口、定时队列、发布状态轮询、每日统计快照。
本机脚本只做三件事：**组装参数 → 调 REST → 把结果讲人话给运营**。

> **为什么不在本机直连微信**：微信换 access_token 有 **IP 白名单**，只认生产服务器那个固定出口 IP；
> 运营电脑出网走 VPN、IP 不固定，直连必被 `40164` 拦。而且 AppSecret 一旦下发到多台运营电脑就失控了，
> 所以它**只存生产服务器 .env，永不下发**。

---

## 五条红线（动手前先过一遍，每条都记住"为什么"）

### ① 「发布」默认不打扰粉丝；「群发」才推送，且每自然月只有 4 次

- **默认走发布（freepublish）**：文章正式上线、有永久链接、可被搜索到，但**不会推送给粉丝**，**不占群发次数**。
- **只有运营明说「群发 / 推送给粉丝 / 让粉丝收到」时才走群发（mass）**。群发前**必须复述本月配额**
  （「本月已用 X/4 次，这条发出去就是第 X+1 次」）并拿到运营明确确认，才带 `--confirm` 调用。
- **为什么这么严**：群发**不可逆**、直接推到每个粉丝的对话框，且**每自然月只有 4 次**——用错一次，
  这个月就少一次真正重要的推送机会。台账的月计数**只统计经本系统发的**，运营若在公众平台后台手动群发过，
  实际剩余次数可能更少，所以**复述配额时要把这句一并说出来**，别让运营以为 4 次是精确保证。

### ② 已发布文章**不能改**：改 = 删 + 重发

微信没有「修改已发布文章」的接口。哪怕只改一个错别字，也只能**删掉旧的、重新发一篇**。
执行前**必须先把代价说清楚并拿到确认**：

> 「这篇已经发布了，微信不支持改。要改只能删掉重发，代价是：**原链接立刻失效**（已分享出去的、
> 菜单里挂的、别处引用的全部变死链）、**阅读/在看/分享数据清零重新算**。确认要改吗？」

**为什么**：删除不可逆，链接是对外资产。运营常以为"改个错字"是小事，不讲清代价就是替他做了不可逆的决定。

### ③ 排版只走 `md2wechat.py`，不接受外部 HTML 直灌

微信正文是 **HTML 白名单沙盒**：`class` / `<style>` 标签 / JS / `iframe` / `position` 全被吞掉或直接报错，
图片必须是先上传换来的 `mmbiz` 域名 URL（外链图一律不显示）。秀米 / 135 编辑器导出的 HTML 带大量 class 与
外链资源，**灌进去必然变形或掉图**。所以排版**只由 `md2wechat.py` 编译**（只产内联样式、自动上传图片换链接）。
运营拿来一段外部 HTML → 请他给 **Markdown 或原文**，重新编译。

### ④ 台账（`--ledger`）是"线上到底有什么"的**唯一权威**

微信的 `freepublish/batchget` **查不到已群发的文章**，后台列表也和 API 口径对不齐。
所以服务端把每次发布/群发**自动落台账**，回答「发过哪些 / 那篇的链接 / 是否群发过 / 现在什么状态」
**一律以 `article_ops.py --ledger` 为准**，⛔ 不要凭对话记忆回答，也不要拿微信侧列表当权威。

### ⑤ 群发 / 删除**失败不自动重试**——先分清哪种败相

这两个动作**非幂等**：重试可能变成"发了两次"（白烧一次配额）或"删了不该删的"。
所以脚本按**这次到底成没成、能不能确定**分成两种败相，**处置完全不同**（这也是脚本侧的实现契约）：

| 败相 | 什么情况 | 信封 / 退出码 | 怎么处置 |
|---|---|---|---|
| **结果未确认** | 拿不准到底生效没有。线索：**请求已发出**之后出的岔子——读响应超时、连接被断、服务端 5xx、响应解析不了；外加唯一一个特例 `45028`（见下） | `outcome: unknown`，**exit 0** | **先查台账核实**，见下面三步 |
| **结果已确定失败** | 能确定这次没做成。线索：**请求根本没发出**（鉴权 401/403、参数校验没过、连接未建立、缺凭据），**或**微信明确回了拒绝码（见下） | `outcome: failed`，**exit 1** | 按错误提示**改配置/改参数**再来。配置错误**绝不静默通过** |

**微信返回确定性 errcode 拒绝的归哪桶**（`45009` 频控 / `53501` 发布频繁 / `40164` IP 不在白名单 /
`48001` 接口未授权 等**一切「明确说没做成」的码**）→ 归 **`failed` 桶**（exit 1，原样透出
`wechat_errcode` / `wechat_errmsg` / `hint`）。结果是**确定的**，**不查台账**——`unknown` 存在的意义
是防「可能已生效」的误重试，确定拒绝没有这个风险。

**唯一例外 `45028`**（群发保护，待管理员手机确认）→ 归 **`unknown` 桶**（exit 0），它是**真正的结果未确认**。
`hint` 固定为这句：

> 群发保护已触发：请管理员在 30 分钟内于手机微信确认本次群发；超时未确认则本次失败。之后以台账/后台核实为准

⛔ **不新增第五态**——`done|partial|failed|unknown` 四态信封是全 skill 家族的共同约定，语义由 `hint` 承载。

**为什么按「能不能确定」分**：只有"可能已生效"才有误重试的风险，这时必须先查台账；而结果**已经确定失败**的
（压根没发出去、或微信明确拒绝）一定没生效，含糊成 unknown 只会让运营去查一个必然为空的台账，
还把 401 这种明摆着的配置错误变成"可能成功了"。

`outcome: unknown` 时（**只有这一种**要查台账）：

1. **先** `article_ops.py --ledger` / `schedule_ops.py --list` 查真实状态；
2. 确认**确实没生效**，再问过运营、手动重发一次；
3. ⛔ **绝不**在没查台账的情况下重跑同一条命令。

---

> **路径约定**：下面 `{SKILL_DIR}` 指本 SKILL.md 所在目录；
> `MD2WX` = `{SKILL_DIR}/scripts/md2wechat.py`、`ART` = `{SKILL_DIR}/scripts/article_ops.py`、
> `SCHED` = `{SKILL_DIR}/scripts/schedule_ops.py`、`MENU` = `{SKILL_DIR}/scripts/menu_ops.py`、
> `STATS` = `{SKILL_DIR}/scripts/stats_ops.py`、`COMMON` = `{SKILL_DIR}/scripts/nbdpsy_common.py`；
> `{workspace}` 指内容工作区（`python3 COMMON workspace` 查询），本 skill 的产物落 `{workspace}/wechat/{slug}/`。
> （Windows 把 `python3` 换成 `python`、`/` 换成 `\`。）

**所有脚本 stdout 是纯 JSON**；写操作统一回 `outcome: done | partial | failed | unknown` 信封。
各脚本的完整参数以 `--help` 为准，下文只列日常最常用的几条。

---

## 凭据（`NBDPSY_WECHAT_API_KEY`，与博客发文那把是两把独立的 key）

```bash
python3 COMMON secret ensure NBDPSY_WECHAT_API_KEY   # 无输出 = 已配置；输出键名 = 缺
```

⛔ **绝不用 `secret get` 探测凭据**——它命中时会把**密钥原值打进 stdout 与对话转录**。
探测在不在，一律用 `secret ensure`（只回缺哪些键、永不回显值）。

- 输出了 `NBDPSY_WECHAT_API_KEY`（= 缺）→ 找管理员要「凭据配置包」，生成时**勾选微信服务号权限**
  （管理员入口：`manage.nbdpsy.com` → 博客 → API Keys → 生成凭据配置包）。拿到后
  `python3 COMMON secret import <配置包文件>` 一键导入。
- `403` / 提示缺 scope → key 有效但**没勾微信服务号权限**（`wechat:operate`），请管理员补勾，别换 key。
- `401` → key 失效或已轮换，请管理员重发配置包。
- 命令报 `Host not allowed` / 恒超时 → Claude 沙盒拦网：`python3 COMMON sandbox allow`
  （放行名单已含 `database.nbdpsy.com`），**重启 Claude Code** 后重试。

基址默认 `https://database.nbdpsy.com`，可用凭据 `NBDPSY_WECHAT_API_BASE` 覆盖（一般无需动）。

---

## 完整流程（发一篇文章的主线，每步都有验证闸门）

```
0. 环境与凭据自检          → 验证：secret ensure NBDPSY_WECHAT_API_KEY 无输出（有输出=缺，先去配）；网络不通先 sandbox allow
1. 判子场景                → 验证：五个子场景已对号入座；涉及群发/删除的，红线①/②已当面复述并拿到确认
2. 取内容                  → 验证：拿到本地 md 路径（优先 nbdpsy-seo-artical-creator 的长文/公众号分发稿）
3. 排版编译（MD2WX）       → 验证：产物 HTML 无 class/<style>/<script>/iframe/position；图片全是 mmbiz 域名；封面拿到 thumb media_id
4. 建草稿（ART --draft-add）→ 验证：拿到 media_id；标题/作者/摘要已与运营核对
5. 发布：立即 或 定时      → 验证：立即=拿到台账 id 且 status=publishing；定时=拿到 job id，run_at 已按「几月几号几点」复述给运营
6. 查终态（ART --ledger）  → 验证：status=published 且拿到 url；失败读 fail_reason（原创校验/审核不通过等）
7. 群发（仅运营明说时）    → 验证：本月配额已复述 + 运营明确确认 + confirm/note 已带 + 台账落 msg_id
8. 看数据（T+1 起）        → 验证：STATS 拿到区间数据；当天数据查不到属正常，不是故障
```

### 第 1 步 · 判子场景（对号入座，别混线）

| 运营怎么说 | 走哪条线 | 关键脚本 |
|---|---|---|
| 「把这篇发公众号」「排版一下发出去」 | 排版发文 | MD2WX → ART |
| 「明早 9 点发」「周一定时推」 | 定时发布/定时群发 | 上面一整套 + SCHED |
| 「让粉丝收到」「群发一下」「推给粉丝」 | **群发（高危）** | ART `--mass-send`，先过红线① |
| 「菜单加个入口」「改下底部按钮」 | 菜单装修 | MENU |
| 「发过哪些」「那篇链接给我」「删掉那篇」 | 台账 / 删除（删是高危） | ART `--ledger` / `--delete-published` |
| 「涨了多少粉」「那篇多少阅读」 | 数据统计 | STATS |

### 第 2 步 · 取内容（**优先承接自家长文，不做无源之稿**）

内容来源优先级：**nbdpsy-seo-artical-creator 产出的 pillar 长文 / 公众号分发稿** > 运营给的 Markdown 原稿。
运营只给了一个题目、手上没有稿子 → **先用 nbdpsy-seo-artical-creator 把稿子写出来**（它带查证与合规校验），
再回本 skill 排版发布。⛔ 不要在本 skill 里现编正文——本 skill 没有查证与合规闸门，编出来的数据没人兜底。

心理科普的合规红线（极限词 / 医疗词 / 站外导流）与长文侧同源，稿子来自长文 skill 时已过校验；
运营自带稿子时，把明显违规处指出来再发。

### 第 3 步 · 排版编译

```bash
python3 MD2WX {workspace}/blog/{slug}/post.md --cover {封面图路径} \
  --html-out {workspace}/wechat/{slug}/content.html --out {workspace}/wechat/{slug}/compiled.json
```

脚本自动做三件事：Markdown → 微信白名单内联样式 HTML（NBDpsy 品牌模板：正文 / 标题竖线 / 引用卡片 /
表格 / 分隔）、正文里的 `<img>` 逐张经 `/upload-image` 换成 mmbiz URL、封面经 `/upload-material`
换成永久 `thumb_media_id`。`--html-out` 落的就是下一步建草稿要的正文文件；`--out` 是整份 JSON 存档。
只想看排版效果不碰网络时加 `--dry-run`（不需要凭据，但产物会掉图，**不能拿去发布**）。

- 图片限制：**jpg/png、单张 ≤1MB**。超限的先压缩，别硬传。
- **`warnings` 逐条念给运营**，尤其这三类：残留 `**` 星号（发出去改不了，只能删+重发）、
  正文超 2万字符（微信拒收，要拆上下篇）、外链可能不可点。
- 标题：frontmatter 的 `title`（没有就取正文首个 H1）会被抽进 JSON 的 `title` 字段并从正文删掉——
  微信标题在建草稿时单独设，正文再放一遍读者会看到两遍。下一步 `--title` 直接用它。
- 编译完**扫一眼产物**，确认没有 `class=` / `<style>` / `<script>` / `iframe` / `position:`（脚本自检
  会拦下并直接编译失败，但运营塞了原始 HTML 片段进 Markdown 时值得再看一眼——那些片段会被转义成纯文本）。

### 第 4 步 · 建草稿

```bash
python3 ART --draft-add --content {workspace}/wechat/{slug}/content.html \
  --title "标题" --author "胡佰亿" --digest "摘要" --thumb-media-id <上一步的 id>
```

拿到 `media_id`。**标题/作者/摘要发出去就定死了**（发布后只能删+重发），落草稿前**先跟运营念一遍**。

### 第 5 步 · 发布（立即 / 定时）

```bash
# 立即发布（不推送粉丝、不占群发次数）
python3 ART --publish --media-id <media_id>

# 定时发布：run_at 用本地时间（Asia/Shanghai）
python3 SCHED --add --job-type publish --run-at "2026-08-03 09:00" --media-id <media_id>
```

- 发布是**异步**的：立即发布返回 `status=publishing`，服务端每 5 分钟轮询一次微信，几分钟内转 `published`。
  **拿不到 url 不等于失败**，去第 6 步查台账。
- 定时任务提交后**把时间按「8 月 3 日上午 9 点」复述给运营**——`run_at` 写错一天是最常见的事故。
- 定时任务可查可撤：`python3 SCHED --list` / `python3 SCHED --cancel <id>`（**只有 pending 能撤**，
  已到点执行的撤不了，这时候按红线②处理）。

### 第 6 步 · 查终态（台账是唯一权威）

```bash
python3 ART --ledger --limit 20          # 台账分页：状态 / 链接 / 是否群发过
python3 ART --status --id <台账 id>       # 单篇终态
```

`status` 语义：`publishing` 发布中（等轮询）/ `published` 已发布（有 url）/ `publish_failed` 失败（读
`fail_reason`，常见是原创校验或内容审核不通过）/ `deleted` 已删除。

### 第 7 步 · 群发（**高危，先回头看红线①**）

```bash
# 第一步：不带 --confirm 跑一次，拿本月配额现状（此时不会真发）
python3 ART --mass-send --ledger-id <台账 id>

# 第二步：把配额复述给运营、拿到明确确认后，才带 confirm 与 note 真发
python3 ART --mass-send --ledger-id <台账 id> --confirm --note "运营 XX 确认，8月推送第2条"
```

- `--note` 是**问责留痕**（谁拍板），必填，写清是谁在什么场景下拍的板。
- 定时群发同理走 `SCHED --add --job-type mass_send ... --confirm --note "..."`，入队时校验一次配额、
  执行时再校验一次。
- 失败按红线⑤分两种处置：`outcome: unknown`（结果未确认）→ **先查台账，绝不直接重试**；
  `outcome: failed`（结果已确定失败，如 401/403、参数不合法、微信明确回了拒绝码）→ 改完配置或参数再来，
  **不用查台账**。
- 若服务号开了「API 群发保护」，微信会回 `45028` → 脚本回 `outcome: unknown`（**不是失败**）：
  告诉运营「请管理员 30 分钟内在手机微信上确认，超时未确认才算失败」，之后按红线⑤查台账核实结果，
  ⛔ **别因为看到报错就重发一次**——那正是白烧一次配额的典型场景。

### 第 8 步 · 数据统计

```bash
python3 STATS --overview --from 2026-07-01 --to 2026-07-31    # 涨粉/阅读概况
python3 STATS --article <msgid>                                # 单篇曲线 + 读完率
python3 STATS --export --from ... --to ...                     # 导出
```

- 数据查的是**服务端每日快照**（每天 08:30 抓前一天），所以**可以跨任意区间**（微信原生接口跨度上限
  1~30 天不等）。
- **当天数据查不到是正常的**：微信 T+1 次日 8 点后才稳定。运营问"今天发的怎么样"→ 如实说"明天才有数据"，
  ⛔ 别拿别的指标凑数糊弄过去。
- 新口径数据**只有 2025-11-01 起**的，更早的区间查不到。

---

## 菜单装修（独立线）

**本地 JSON 文件是编辑真源**，改文件 → apply，别在公众平台后台和这里两头改。

```bash
python3 MENU --get > {workspace}/wechat/menu.json    # 先拉线上现状当基线
# 编辑 menu.json
python3 MENU --apply {workspace}/wechat/menu.json    # apply 前脚本会打 diff，念给运营确认再执行
python3 MENU --delete                                 # 删除整个自定义菜单（慎用，粉丝立刻看不到入口）
```

- **菜单有约 24 小时缓存**：apply 成功后粉丝不一定马上看到，让运营**取消关注再关注**可立即看到新菜单——
  提前说明，免得运营以为没生效反复 apply。
- 菜单结构限制（微信侧硬约束）：一级最多 3 个、每个一级下二级最多 5 个；一级菜单名 ≤4 个汉字、
  二级 ≤7 个汉字（超了会被截断显示）。
- 挂进菜单的链接**必须是已发布文章的正式 url**（从台账取）。⛔ 别挂草稿预览链接——那种链接会过期。

---

## 已发布文章删除（**高危，先回头看红线②**）

```bash
# 第一步：不带 --confirm，拿到警示与该文现状
python3 ART --delete-published --article-id <article_id>
# 第二步：把「链接失效 + 数据清零」讲清楚、拿到确认后
python3 ART --delete-published --article-id <article_id> --confirm
```

删除后台账标 `deleted`。**删除不可逆**，失败按红线⑤分两种处置：`outcome: unknown`（结果未确认）→
**先查台账核实那篇到底还在不在，绝不直接重删**；`outcome: failed`（结果已确定失败，如 401/403、
`article_id` 不合法、微信明确回了拒绝码）→ 改完配置或参数再来，**不用查台账**。

---

## 微信错误码速查（脚本会原样透出 `wechat_errcode` / `wechat_errmsg` + `hint`）

| 码 | 含义 | 信封 | 怎么办 |
|---|---|---|---|
| `40164` | 调用 IP 不在白名单 | `failed` | **不是运营能修的**：找管理员核对生产服务器出口 IP 是否还在公众平台白名单里 |
| `45009` | 接口调用频控 | `failed` | 等一会儿再试，别连着重跑 |
| `48001` | 接口未授权 | `failed` | 服务号权限/认证状态问题，找管理员核实 |
| `53501` | 发布过于频繁 | `failed` | 隔开时间再发，别改成定时任务硬怼 |
| `45028` | 群发保护，需管理员手机确认 | **`unknown`** | **不是失败**：让管理员 30 分钟内在手机上确认；超时未确认才算失败，之后以台账/后台核实为准 |

⛔ 看到错误码**不要自己猜着改参数连着重试**——先按上表处置。
这些码都是微信**明确说没做成**，结果是确定的 → 一律 `failed`（exit 1），**不用查台账**；
**只有 `45028` 是例外**（真·结果未确认）→ `unknown`（exit 0），按红线⑤查台账核实。

---

## 关键文件

| 用途 | 路径 |
|------|------|
| Markdown → 微信白名单内联样式 HTML（含图片上传换链接、封面进素材库） | `scripts/md2wechat.py` |
| 草稿 CRUD / 发布 / 台账 / 状态 / 群发（高危）/ 删除已发布（高危） | `scripts/article_ops.py` |
| 定时任务提交 / 列表 / 取消 | `scripts/schedule_ops.py` |
| 自定义菜单 查/应用/删除 | `scripts/menu_ops.py` |
| 数据统计（概况 / 单篇 / 导出） | `scripts/stats_ops.py` |
| 凭据工具 / 沙盒放行（`sandbox allow`，已含 `database.nbdpsy.com`） | `scripts/nbdpsy_common.py` |
| 端点清单与微信侧硬约束速查 | `references/wechat-oa-spec.md` |
