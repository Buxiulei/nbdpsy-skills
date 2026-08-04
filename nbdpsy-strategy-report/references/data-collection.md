# 六路并行采集：任务模板与口径手册

六路采集代理并行跑（子代理或 Workflow）。每路的提示词都必须包含「访问方式」「三条铁律」和
「交付格式」；正文给出各路的采集清单与**已知口径坑**——这些坑每一个都在 2026-07 报告制作中实际踩过
或核实过，直接抄进提示词能省一轮返工。

## 通用：访问方式与铁律（写进每路提示词）

```
生产库是唯一真实数据来源。查询方式：把 SQL 写进本地临时文件，然后
  ssh nbdpsy "PGPASSWORD='<生产库密码>' psql -h localhost -U root -d psychology_counseling" < query.sql
探索表结构用 \d 表名。
【铁律】只允许 SELECT / \d / \dt；不许 sleep 死等；查不到就如实说明，绝不编数。
【时区】库时区 Asia/Shanghai。appointments / payment_orders / users 的时间列是
naive timestamp 存 +08 本地时间，窗口直接用裸字面量 '2026-07-01' ~ '2026-08-01' 比较；
带 tz 的列（events.created_at 等）用 '2026-07-01 00:00:00+08' 显式写偏移。
```

交付格式（每路统一）：关键指标表（本月+环比）→ 结构拆分表 → 发现与异常（每条附数字）→
口径说明（每个数字用了哪张表哪个字段什么过滤）。

## 第 1 路 · 预约与会话

采集：已发生会话总量（正式/预沟通分列）、会话小时数、活跃来访者、新来访首会数、按咨询师拆分、
新建预约（剔占位）、取消/爽约/改约、循环占位规模、待确认待付款积压、booking_queue 排队。

口径坑（必须写进提示词）：
- **「已发生会话」= `status IN ('completed','pending_feedback')`**。pending_feedback 是自动完成待反馈态，
  占比约九成——只数 completed 会低估一个数量级。
- **占位行判据 = `is_placeholder = true`**。`series_key` 全表非空，**不可**用作占位判据。
  循环判据两口径不等价：会话口径用 `recurrence_interval_days > 0`，新建口径用 `origin='recurring'`
  （序列首场 origin='normal' 但 interval>0）。
- 取消统计必须剔占位，否则取消量虚报近一倍；取消有两个归月口径（cancelled_at=动作口径 /
  appointment_date=场次口径），报告用动作口径、注明即可。
- 积压（pending_confirm/pending_payment）是**查询时刻快照**不是月末快照；其中约七成多是占位序列的
  未来分期，「真实待付款」要剔占位后再算，否则欠款高估数倍。
- 预沟通 `session_count` 恒为 0，计费会话数只对正式咨询求和。
- 测试账号 `EMP20260204001`（测试胡）从所有口径剔除。
- 交付溯源很有价值：按「预约创建月」拆当月会话，能算出「本月交付有多少靠往月序列兑现」。

## 第 2 路 · 财务

采集：毛额/净收/订单数/客单价/付费用户/首付新客/退款结构/支付渠道/订单类型/按咨询师净额/
优惠券核销/平台分成/LLM 成本。

口径坑：
- 支付成功 = `payment_status IN ('paid','partial_refunded','refunded')` 且按 `paid_at` 归月；
  金额字段单位是**元**（先抽样验证再汇总）；用 `actual_amount`（`total_amount` 含未抵扣优惠差额）。
- 净收入两口径都算：主口径 = 毛额 −「该批订单」退款；现金流口径 = 毛额 − 当月发生退款
  （`refunded_at` 归月，含跨月旧单退款）。两者差额单独列出。
- 咨询师关联**必须走 `apt_no`**（`payment_orders.appointment_id` 大量为 NULL，走它得 0 行）。
- 优惠券让利额取订单侧 `discount_amount`（`user_coupons.discount_value` 对 percentage 券存的是折扣数
  不是金额）；承担方拆分看 `coupon_templates.cost_bearing`。
- 平台分成：`counselor_income` 台账可能为空，此时只能按 `counselors.commission_ratio` 当前值反推，
  报告里必须注明是派生值。
- 退款原因值得文本归类：「小红书已付/站外支付」类是对账性退款，剔除后另报一个「真实退款率」。

## 第 3 路 · 增长转化

采集：新注册（按来源拆：小程序/网页手机号/邮箱/Google/后台补录）、leads 线索台账（渠道/加微/
预沟通/成交漏斗）、预沟通→正式当月转化、埋点渠道（PV/UV/新访客首触/转化事件）、脱落与回流。

口径坑：
- 官网月度 UV 用 events 明细 `COUNT(DISTINCT visitor_id)` 且**排除 `properties->>'origin'='server_synthetic'`**
  （服务端合成兜底事件）；daily_aggregates 的 uv 是逐日去重、跨月相加会重复计人。
- booking_complete 分两档：营销站真实事件 vs 服务端合成兜底（多来自小程序、无首触归因），必须分开报。
- 埋点上线日之后才有的事件（如 booking_step_view）不能与上月的 0 做环比，注明覆盖天数。
- leads 成交 = `is_closed = true`（NULL 与 false 均算未成交）；注意台账上线日，上线前的月份是回溯补录。
- 脱落检测的**首跑日会一次性清出历史积压**，「月度新增脱落」要看首跑日之后的记录。
- 内部流量已被 `nbdpsy_internal` cookie 在 SDK 层拦截不落库；表内 `channel='internal'` 指站内跳转，
  是另一回事。

## 第 4 路 · 小红书双账号

工具：`note_ops.py`（找 `~/.claude/skills/` 下 nbdpsy 前缀 skill 内，或 `find ~/.claude/skills -name note_ops.py`）。

- **篇数只认 `--ledger` 台账口径**；表现指标来自创作中心导出，两者数量对不上是常态（老帖/私密/
  标题截断导致的差异，逐项注明）。
- 导出指标是**累计值**且时间窗混合（曝光/涨粉是 T-1、阅读/点赞是实时）——跨日对比必须用
  「两天都在导出表内的笔记」配对做差，账号级 total 直接相减会因笔记集合漂移得出假下降。
- 有上期诊断/报告的，逐条对照其结论：仍成立/有变化，用成熟样本（发布 ≥7 天）复算相关系数。
- 只读！不发布、不修改、不删除任何笔记。

## 第 5 路 · SEO / 博客 / 公众号

数据源：NBDpsy 仓库 `seo-geo/ops/logs/` 下 gsc-weekly.csv、bing-weekly.csv、ai-crawler-stats.csv、
index-sentinel.csv + 生产库 blog_posts / blog_comments / wechat_* 表。

口径坑：
- GSC 周报可能缺周（环比失真时按周均比较并注明）；平均排名按展现加权。
- Bing 的 `*_7d` 列是快照日往前 7 天滚动值，非自然月；查询词数取期末快照值不求和。
- AI 爬虫 CSV：`log_first_line_hint` 变更 = 日志轮转，其后首个快照是残窗、数据塌陷是假象——
  横向比较用单快照峰值；CSV 的 AI referrer 列与 events 实测可能矛盾，以 events 为准。
- blog_posts.view_count 是发布至今累计计数器，与 events 的 blog_post_view 是两套独立计数，不可混比。
- 博客评论要查用户分布——功能自测账号的批量评论不能当有机互动。
- 公众号未接入期间「无数据」是客观事实不是采集失败，报告写「未启动」而非 0。

## 第 6 路 · 战略基线提炼（文本理解，适合较轻量模型）

通读三份材料：上一期战略报告底稿（`docs/战略报告-*-底稿.md`）、H1 深度分析
（`docs/运营深度分析报告-2026H1.md`）、双主线战略规划（`docs/战略规划-双主线-2026H2-2027.md`）。

产出：①战略主线与北极星定义；②所有可量化基线数字（标注出处章节）；③本报告周期内战略排期表
承诺的行动项清单（供第 3 步取证对照）；④「本期报告应该回答的 10-15 个问题」清单。
只提炼文档里真实存在的内容并标注出处，不自行补数。
