# 服务号运营 · 端点清单与微信侧硬约束（运行时速查）

> **这不是需求真源**。需求与设计的唯一真源是 NBDpsy 主仓库的
> `docs/superpowers/specs/2026-08-02-fuwuhao-operator-design.md`（服务端行为、数据表、scheduler 任务、
> 部署次序都在那儿）。本文只放**skill 运行时要查的事实**：调什么端点、微信侧有哪些绕不开的限制、
> 错误码怎么读。两边打架时以主仓库 spec 为准。

## 一、我们自己的端点（`{base}` 默认 `https://database.nbdpsy.com`）

鉴权：请求头 `Authorization: Bearer <NBDPSY_WECHAT_API_KEY>`，服务端按 scope `wechat:operate` fail-closed 校验
（key 有效但没这个 scope → 403，找管理员补勾权限，不用换 key）。

### 受控透传

| 端点 | 说明 |
|---|---|
| `POST /api/external/wechat/proxy` | `{path, body}`——把请求转给微信开放接口，服务端注入 token。**path 必须在白名单内**，否则 403 |

透传白名单（第一版）：

- **菜单**：`/cgi-bin/menu/create`、`/get`、`/delete`、`/addconditional`、`/delconditional`、`/trymatch`、`/cgi-bin/get_current_selfmenu_info`
- **草稿**：`/cgi-bin/draft/add`、`/get`、`/update`、`/delete`、`/count`、`/batchget`
- **素材**（只读 + 删）：`/cgi-bin/material/get_material`、`/batchget_material`、`/get_materialcount`、`/del_material`
- **发布**（只读）：`/cgi-bin/freepublish/get`、`/getarticle`、`/batchget`
- **统计**：前缀 `/datacube/` 全放（全部只读）

**不在白名单**（走专门端点或彻底禁止）：`freepublish/submit`（走 `/publish`，要落台账）、
`freepublish/delete`（走 `/article-delete` 高危端点）、`message/mass/*`（走 `/mass-send` 高危端点）、
`clear_quota`（每月仅 10 次，禁止 skill 触达）。

菜单写操作、草稿 add/update/delete、素材 del 会被服务端记结构化日志（谁、什么路径、摘要）。

### 专门端点

| 端点 | 行为 |
|---|---|
| `POST /api/external/wechat/publish` | `{media_id, title?}` → 提交发布，台账插 `publishing` 行，返回台账 id |
| `POST /api/external/wechat/upload-image` | multipart，转发 `media/uploadimg`，返回 **mmbiz URL**（正文配图用；jpg/png ≤1MB） |
| `POST /api/external/wechat/upload-material` | multipart，`type=image\|thumb`，返回**永久 media_id**（封面用） |
| `POST /api/external/wechat/mass-send` | **高危**：`{article_ledger_id 或 media_id, filter, confirm, note}`。`confirm≠true` 时**不发**，只回本月配额现状；台账记 `msg_id` / `mass_sent_at` |
| `POST /api/external/wechat/article-delete` | **高危**：`{article_id, index?, confirm}`。`confirm≠true` 只回警示；执行后台账标 `deleted` |
| `GET /api/external/wechat/ledger` | `?status&limit&offset` 台账分页——**"线上有什么"的唯一权威** |
| `POST /api/external/wechat/schedule` | `{job_type: publish\|mass_send, run_at, payload}` 入定时队列；`mass_send` 型同样要 `confirm`+`note`，入队即校验配额、执行时二次校验 |
| `GET /api/external/wechat/schedule` | `?status` 队列查询 |
| `POST /api/external/wechat/schedule/cancel` | `{id}`，**仅 pending 可取消** |
| `GET /api/external/wechat/stats` | `?type&from&to&msgid` 查每日快照（本地聚合，**支持跨任意区间**） |

服务端异步节奏：发布状态每 **5 分钟**轮询一次微信；定时队列每 **1 分钟**扫一次；统计快照每日 **08:30** 抓前一天。

## 二、微信侧硬约束（绕不开，设计已兜住，但话术要说对）

| 约束 | 对运营意味着什么 |
|---|---|
| 换 token 有 **IP 白名单**，只认生产服务器固定出口 IP | 本机永远不直连微信；`40164` 只能找管理员核对白名单 |
| AppSecret 不下发 | 运营电脑上没有、也不需要微信凭据，只有个人 API key |
| 微信 API **没有原生定时参数** | 定时靠服务端队列到点执行；队列没跑=没发，`SCHED --list` 是准的 |
| **发布(freepublish) ≠ 群发(mass)** | 发布不推送粉丝、不占次数；群发**每自然月仅 4 次且不可逆** |
| 台账月计数只统计**经本系统**的群发 | 公众平台后台手动群发不计入，实际剩余可能更少——复述配额时必须带上这句 |
| **已发布文章无修改 API** | 改 = 删 + 重发 → 换链接、阅读清零 |
| `freepublish/batchget` **查不到已群发文章** | 别拿微信侧列表当权威，一律看台账 |
| 正文是 **HTML 白名单沙盒** | 无 `class` / `<style>` 标签 / JS / `iframe` / `position`；图片必须先 uploadimg 换 mmbiz URL。故排版只走 `md2wechat.py` |
| 自定义菜单**客户端缓存约 24h** | apply 成功不等于粉丝立刻看到；让运营取消关注再关注可即时验证 |
| 菜单结构上限（微信官方文档） | 一级最多 3 个、每个一级下二级最多 5 个；一级名 ≤4 汉字、二级 ≤7 汉字，超出以 `...` 显示 |
| `datacube` 跨度上限 1~30 天不一、**次日 8 点后才稳**、新口径数据**仅 2025-11-01 起**、无单篇过滤参数 | 当天数据查不到属正常；跨区间查询由服务端快照兜住 |

第一版**明确不做**：留言评论管理、个性化菜单、模板消息/客服消息/订阅通知、带参二维码、素材库清理工具。

## 三、错误契约

微信侧错误**原样透出**：`{success: false, wechat_errcode, wechat_errmsg, hint}`。

| 码 | 含义 | 处置 |
|---|---|---|
| `40164` | 调用 IP 不在白名单 | 找管理员核对生产服务器出口 IP |
| `45009` | 接口调用频控 | 等一等再试，别连续重跑 |
| `48001` | 接口未授权 | 核对服务号认证与权限状态 |
| `53501` | 发布过于频繁 | 隔开时间再发 |
| `45028` | 群发保护，需管理员手机 30 分钟内确认 | **不是失败**，通知管理员确认 |

非幂等动作（发布 / 群发 / 删除）的败相按**请求有没有发出去**分两种（脚本实现契约）：

| 败相 | 什么情况 | 信封 / 退出码 | 处置 |
|---|---|---|---|
| 结果未确认 | **请求已发出**后出岔：读响应超时、连接断、服务端 5xx、响应解析失败 | `outcome: unknown`，exit 0 | **先查台账核实，绝不自动重试** |
| 确定没发出去 | **请求未发出**：鉴权 401/403、参数校验不过、连接未建立、缺凭据 | `outcome: failed`，exit 1 | 改配置/参数再来；配置错误**绝不静默通过** |
