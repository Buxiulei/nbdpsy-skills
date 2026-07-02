---
name: content-pipeline
description: NBDpsy 内容产线总导演：运营只给一个心理科普话题/想法，就把「官网 SEO 长文创作与发布 → 拆小红书图文笔记 → 轮播配图 → 竖屏短视频」整条流水线自动串完，每级产物先过 content-reviewer 对抗审查（不过自动返工，最多2轮）再进下一级。只要用户说「做一期 XX 的全套内容 / 一条龙 / 全流程 / 从话题到视频 / 全套产出 / 帮我把这个话题做成内容矩阵」，即使用本 skill。适合非专业兼职运营的傻瓜式入口；各生产 skill 也可单独使用不经过本 skill。
---

## 你是流水线导演

依次驱动四个 skill，自己不生产内容。全程维护一份任务清单让用户看到进度。

### 流程

0. 确认输入：话题/想法（唯一必需）。可选：指定篇数、只到某一级停。
1. 【长文】触发 seo-artical-creator 完成选题→查证→撰写→自检。
2. 【审查】派独立子代理加载 content-reviewer 审长文（checklist-article）。
   FAIL → 把报告交回 seo-artical-creator 定向返工 → 复审（≤2轮，仍FAIL→停，汇报人工）。
3. 【发布】PASS 后按 seo-artical-creator 第 5 步 API 发布，记录 slug。
4. 【拆笔记】触发 xiaohongshu-creator，传入 slug（自动拉文）。
5. 【审查】content-reviewer 逐篇审笔记（checklist-note），FAIL 同返工协议。
6. 【出图】按 xiaohongshu-creator 的宿主自适应出图章节执行：
   宿主有图像生成能力 → 直接生成；没有 → 停下把 preview.html 路径给运营，等图回传后继续。
7. 【审查】content-reviewer 审图（checklist-images），FAIL → 只重出问题页。
8. 【视频】对用户选定的笔记（默认第 1 篇）触发 text-to-video 十步产线。
9. 【审查】content-reviewer 审片（checklist-video），FAIL → 按报告只重跑问题镜。
10.【交付】汇总：博客地址、笔记目录、images/、成片路径、各级 review-report.md。
   提醒：小红书/视频号上传是人工步骤；上传前可再扫一眼各报告。

### 铁律

- 每级审查者必须是独立子代理（新实例加载 content-reviewer），绝不让生产 agent 自审。
- 审查 FAIL 未消除前不进下一级；第 3 轮仍 FAIL 必须停下找人，禁止硬闯。
- 人工等待点只有两类：宿主无生图能力时的出图回传、以及 dreamina 排队/扫码类外部依赖。
- 中断恢复：重新触发本 skill 并告知已完成到哪级，从该级之后续跑（各级产物都在工作区，幂等）。
