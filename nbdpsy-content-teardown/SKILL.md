---
name: nbdpsy-content-teardown
description: 对标内容拆解：把别人的爆款内容（小红书笔记/视频号视频/新闻/音频/手机录屏/任意视频文件）稳定拆成一份「拆解素材单」——数据判型、文字稿还原、形式逐秒拆解、钩子公式、可以学/不要学/差异化机会、落到 NBDpsy 产线的复刻蓝图。当用户说「拆解这条视频/笔记/链接/新闻/录屏」「对标拆解 / 对标分析」「这个形式怎么模仿 / 可以怎么抄」「出一份拆解素材单」并给出链接或文件时，用本 skill。它只产分析（素材单+关键帧归档），不产成片：照蓝图做图文用 nbdpsy-xiaohongshu-creator、做短视频用 nbdpsy-text-to-video、搬运 YouTube 成片用 nbdpsy-youtube-transport、审自家稿件用 nbdpsy-content-reviewer。
---

# 对标内容拆解（链接/文件 → 拆解素材单）

产出物永远是一份**拆解素材单**（模板见 `references/teardown-playbook.md`），核心是回答四个问题：
**它凭什么爆（数据判型）／它说了什么（文字稿）／它怎么说的（形式）／我们怎么合规地抄（复刻蓝图）**。

> **路径约定**：`{SKILL_DIR}` 指本 SKILL.md 所在目录。三个脚本：
> `DISSECT` = `{SKILL_DIR}/scripts/dissect_video.py`
> `SPH` = `{SKILL_DIR}/scripts/sph_meta.py`
> `XHS` = `{SKILL_DIR}/scripts/fetch_xhs_note.py`

## 第 0 步 · 依赖自检

```bash
python3 {SKILL_DIR}/scripts/env_check.py --profile teardown --install
```

- 视频/录屏拆解需 `ffmpeg/ffprobe`（**必需，缺则不就绪**）+ `faster-whisper`（缺则脚本会给安装提示，ASR 可 `--no-asr` 跳过）；
- 视频号元数据需 `playwright`——pip 装完还要装浏览器内核：`python3 -m playwright install chromium`（env_check 不查内核，缺了 `sph_meta.py` 会 exit 2 给同样提示）；
- 小红书提取需凭据 `NBDPSY_XHS_API_KEY`（缺→找管理员发接入包，不阻塞其他输入形态）。

## 第 1 步 · 按输入形态路由

| 输入 | 命令 | 得到 |
|---|---|---|
| 小红书笔记 URL | `python3 {XHS} <分享链接>` | note.json + note.md（正文/数据/图片永久链）。⚠️ **必须用 App/网页「分享」生成的链接**（xhslink.cn 短链或带 `xsec_token` 的完整链）——浏览器地址栏裸 `/explore/<id>` 链会被 400 拒；正文同步秒回，评论加 `--comments N --account <号>`（**烧一次浏览器会话额度**，非必要别抓） |
| 视频号分享链（weixin.qq.com/sph/…） | `python3 {SPH} <链接>` → **人工录屏**（见下）→ `DISSECT` | 元数据+封面 → 正片 |
| 视频 / 录屏 / 音频文件 | `python3 {DISSECT} <文件...>` | probe + 转写稿 + 帧看板 + REPORT.md 骨架（纯音频无帧看板，REPORT 会标注） |
| 新闻 / 网页图文 | 直接抓页面正文（WebFetch/curl），引用原文 | 正文+发布时间+互动数 |
| 抖音 / B站等 | `yt-dlp` 能下则下（抖音常有登录墙，不保证）→ `DISSECT` | 同视频文件 |

### 视频号正片获取流程（正片流微信外必拿不到，只有这条路）

1. `SPH` 先拿元数据+封面（**封面 CDN 链过期极快——实测最短只剩 ~2h**，脚本已自动落盘并在 sph_meta.json 里给出到期时刻，产完立即归档）；
2. 请用户在微信里打开视频**手机录屏**（完整放一遍即可）；
3. 上传口：手机浏览器登录 manage.nbdpsy.com → 博客 → 新建文章 → 「配套视频」框选文件——**选中即上传，不必保存文章**（MP4/MOV 均收，上限 1GB）；
4. 从服务器取回最新上传文件（管理员机器已配 ssh 别名，上传落 `uploads/blog/videos/`）→ 跑 `DISSECT`；
5. **拆完请示用户后删除服务器上的录屏**——录屏常带群聊/通知等隐私画面。

## 第 2 步 · 七步拆解法（详版与素材单模板见 playbook）

1. **基础信息 + 数据判型**——四指标比值判内容型（转发型/收藏型/讨论型），间隔 ≥6h 二抓补增速（小红书二抓必须带 `--refresh`，extract 有 24h 缓存，不带会拿到第一次的旧数）；
2. **文字稿还原**——口播走 ASR；`DISSECT` 报「疑无口播」= 纯音乐片，文字稿=字幕层，对着帧看板逐帧抄录；图文直接引全文；
3. **形式拆解**——场景清单与切换节奏、字幕层结构、循环体判定、时长；
4. **钩子公式提炼**——注意封面句式与正片标题句式常是**两套钩子**各干各的活；
5. **趋势语境查证**——WebSearch 查这个题材的热度与**辟谣浪潮**（科学表述先查真伪再定学不学）；
6. **三段式建议**——可以学的 / 不要学的 / 差异化机会，**复刻蓝图必须落到具体产线**（图文→xiaohongshu-creator，短视频→text-to-video，长文→seo-artical-creator）并给内核替换建议；
7. **归档提交**——素材单入 NBDpsy 主仓 `文档/YYYY-MM-DD-拆解素材单-<平台>-<标题>.md`，关键帧入 `seo-geo/content/videos/benchmark-<slug>/`，commit+push。

## 红线（每条都是踩过的坑，实例见 playbook 坑典）

1. **不编造文字稿**——拿不到正片就把该节标「待补」，宁缺毋假；
2. **互动数只认 API 或全分辨率帧**——缩略看板会把账号名读成数据（「3.27蕊」被误读成 3.27 万赞的事故）；
3. **录屏先切条再拆**——一条录屏可能含多条内容+群聊隐私；群聊帧不入库、不外发；
4. **先识别商品笔记**——卖货漏斗的落点结构不能学，只学它的前 80%；
5. **钩子里的科学表述必须查证**——「排出皮质醇」类伪科学话术流量再高也不抄，专业机构一条伪科学能毁全矩阵人设；
6. **小号数据不外推**——几十赞的号只学形式不学数据，素材单里必须写明。
