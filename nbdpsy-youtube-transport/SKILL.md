---
name: nbdpsy-youtube-transport
description: 把一条 YouTube 视频「搬运」成带中文字幕/配音、可直接发布的成片——服务端全自动完成下载→转写→qwen-mt 翻译→豆包配音→音画同步→烧中文字幕→出成片，并自动打上 NBDpsy 品牌 logo（右下角）与片头版权声明。除搬运外还支持 remake（分镜级再制作：画面像素全自产，仅「平面图形类」原片如 EMDR 黑底几何动画保证质量、真人出镜勿用）与 revise（对 remake 成片提自然语言修订意见、可链式再修订）。当用户说「搬运这个 YouTube 视频 / 把这条油管视频翻译配音 / 搬运油管 / YouTube 视频转中文 / 把这个视频做成中文版 / 搬个视频 / 再制作一版 / 修订这条视频」并给出 youtube.com 或 youtu.be 链接时，用本 skill。它经 nbdpsy-server 视频管线 REST API 建任务、轮询进度、取回成片与中英字幕/双语逐字稿/分镜脚本的公网下载链接。仅处理 YouTube 链接；从零创作竖屏视频请用 nbdpsy-text-to-video。
---

# YouTube 视频搬运（下载→翻译→配音→烧字幕→成片）

给一条 YouTube 链接，产出一条**带中文字幕/配音的成片** + 中英字幕 + 中英双语逐字稿。
**所有重活都在服务端**（小红书运营工具后台）：下载、语音转写、qwen-mt 翻译、豆包配音、
音画同步、烧录中文字幕、加 NBDpsy 品牌 logo（右下角）与片头版权声明——**调用方不传任何额外参数**。
本 skill 只做三件事：**建任务 → 轮询到完成 → 取回产物公网链接**（可选下载到本地）。

> **和 nbdpsy-text-to-video 的分工**：本 skill 是「把别人的 YouTube 视频搬成中文版」；
> nbdpsy-text-to-video 是「把我们自己的博客/小红书笔记从零做成竖屏短视频」。别混。

> **路径约定**：下面 `{SKILL_DIR}` 指本 SKILL.md 所在目录；
> `TV` = `{SKILL_DIR}/scripts/transport_video.py`；
> `COMMON` = `{SKILL_DIR}/scripts/nbdpsy_common.py`。
> （Windows 把 `python3` 换成 `python`、`/` 换成 `\`。）

---

## 凭据（与小红书自动发布同一把，无需另发）

视频接口和小红书发布接口在 **nbdpsy-server（`https://mcp.nbdpsy.com`）同一台主机、同一把 apikey**，
复用本机凭据 **`NBDPSY_XHS_API_KEY`**（nbdpsy-server apikey，接入包同一把）。配过小红书自动发布
就能直接用，不用再要新凭据。自检：

```bash
python3 COMMON doctor          # 看 xhs_ready=true 即凭据就绪（同一把 key 也给视频用）
```

- 缺 `NBDPSY_XHS_API_KEY`（`doctor` 报缺 / 命令回 `MISSING:`）→ 找管理员要「运营接入配置包」，
  存成 creds.txt 后 `python3 COMMON secret import creds.txt` 一键导入。
- 命令报 `Host not allowed` / 恒超时 → Claude 沙盒拦网：`python3 COMMON sandbox allow` 写入放行名单
  （已含 `mcp.nbdpsy.com`），**重启 Claude Code** 后重试；单次命令也可用 Bash 工具参数
  `dangerouslyDisableSandbox` 兜底。
- `401` → apikey 失效/已轮换，找管理员重发接入包。

基址默认 `https://mcp.nbdpsy.com`（可用凭据 `NBDPSY_VIDEO_API_BASE` 覆盖，一般无需动）。
> 2026-07-23 起旧的薯营家（`xhs.nbdpsy.com`）已整套停机，视频与发布全部收口到 nbdpsy-server；
> 如仍见到指向 `xhs.nbdpsy.com` 的旧链接/配置，一律作废。

---

## 完整流程（每步有验证闸门）

```
0. 拿到 YouTube 链接        → 验证：是 youtube.com / youtu.be 链接（脚本会预检，非 YouTube 直接拒绝）
1. 建任务（异步）           → 验证：拿到 job_id（HTTP 202）
2. 轮询到终态              → 验证：outcome=completed（失败为 failed；中间态 pending/running 继续等）
3. 取回产物 / 交付          → 验证：拿到 video_url 等公网链接；如需存档加 --download
```

### 第 0 步 · 确认链接

只接受 **youtube.com / youtu.be** 链接（脚本客户端预检 + 服务端二次校验）。用户给了别的站点的链接，
直接说明「本搬运只支持 YouTube」，不要硬提交。

### 第 1–2 步 · 建任务并轮询（一条命令搞定）

默认命令会**建任务 + 轮询到终态**（transport 搬运耗时按视频时长几分钟级，脚本每 ~30s 轮询一次）：

```bash
python3 TV --url "https://www.youtube.com/watch?v=xxxx"
```

可选参数：

| 参数 | 作用 | 默认 |
|---|---|---|
| `--mode transport\|remake` | `transport` 搬运（原片画面）/ `remake` 分镜级再制作（画面全自产） | transport |
| `--voice 音色` | 指定服务端配音音色 | 不传 = 服务端默认牧羊音色 |
| `--no-burn-subtitles` | 不把字幕烧进画面 | 默认烧录中文字幕 |
| `--max-resolution N` | 成片最高分辨率 | 1080 |
| `--no-wait` | 提交后立即返回、不等结果（稍后 `--job` 查） | 默认等到终态 |
| `--wait-timeout 秒` | 轮询等待上限 | transport 1800 / remake·revise 4500 |
| `--download` | 终态 completed 后把产物下载到本地工作区 | 默认只回公网链接（视频较大不自动下载） |
| `--out-dir 目录` | `--download` 落盘目录 | `<工作区>/video/job-N/` |

**长视频/怕断**：加 `--no-wait` 先拿 `job_id`，之后用 `python3 TV --job <id>` 复查，避免长时间占用会话。

### remake · 分镜级再制作（版权收窄的自制版）

`--mode remake` 让服务端**画面像素全部自产**（品牌卡片 + 程序化渲染），台词翻译后按 NBDpsy
口吻重写。**全链约 30–60 分钟**（脚本 remake 默认把等待上限拉到 4500s，轮询 30s 一次）：

```bash
python3 TV --url "https://www.youtube.com/watch?v=xxxx" --mode remake
```

- **只对「平面图形类」原片保证质量**（黑底卡片/几何动画，如 EMDR 双侧刺激自助视频）；
  **真人出镜类勿用 remake**（后续版本才做动画人物替代）。
- remake 成片多一件产物 `storyboard_url`（分镜脚本 JSON，可人工核对）；`meta_url` 两模式成片都有，
  但只有 remake 的 meta 含发布简介建议文案 `attribution`（修订片的另含修订血统 `revision`）。
- **版权定位是参考借鉴而非零风险**：发布简介须附 meta 里的 `attribution` 文案（如「练习设计参考
  国际公开的 EMDR 双侧刺激自助方法」），**重要成片建议人工终审**后再发。

### revise · 成片修订（自然语言意见，可链式）

对**已完成的 remake 成片**提一句自然语言意见，服务端解析成编辑清单、派生子任务**增量重制**
（继承下载/分析/转写/重分段/翻译五个最贵阶段，未改动台词的配音走缓存，命中率 ≥99%）：

```bash
python3 TV --revise 42 --instructions "收束那句改得更温暖一些，加上祝愿今晚睡个好觉的意思"
```

- 返回子任务 `job_id` + `parent_job_id` + `edit_plan`（解析出的编辑清单），默认继续轮询子任务到终态
  （`--no-wait` 同语义：只回 pending + edit_plan，稍后 `--job <子id>` 复查）。
- 可**对修订片再修订**（多层链），每次都是增量重制。
- 失败面相：`outcome=failed` + `error` 含 `HTTP 400` → 父任务不是 remake（仅 remake 成片可修订），
  或意见解析失败/编辑清单为空（`hint` 会按 error 文本区分；解析失败时换个更具体的说法重试）；
  含 `HTTP 409` → 父片尚未完成或父产物缺失，等父任务 `completed` 后再试。

### 第 3 步 · 取回产物

stdout 是**纯 JSON**。终态 `outcome=completed` 时 `products` 里是**已拼成公网绝对 URL** 的产物直链
（**免鉴权**可直接下载/播放；transport 五件、remake 六件）：

| 键 | 内容 |
|---|---|
| `video_url` | 成片（带中文字幕/配音 + NBDpsy logo + 片头版权声明） |
| `transcript_zh_srt_url` | 中文字幕 SRT |
| `transcript_en_srt_url` | 英文字幕 SRT |
| `transcript_bilingual_url` | 中英双语逐字稿 |
| `storyboard_url` | 分镜脚本 JSON（**仅 remake**，可人工核对；缺失容忍） |
| `meta_url` | 视频元信息（**两模式都有**，缺失容忍）；仅 remake 的 meta 含发布简介建议 `attribution`、仅修订片含修订血统 `revision` |

把 `video_url` 回给运营即可播放/下载。要本地留档就加 `--download`（脚本用 `SendUserFile` 之类交付时
需要本地文件，这时下载更方便）。**remake 成片对外发布时，简介须附 `meta_url` 里的 `attribution`
文案，且重要成片建议人工终审后再发。**

**其它状态怎么读**：
- `outcome=failed` + `error` → 搬运失败（源视频不可下载/超时等），可 `python3 TV --retry <id>` 重试。
- `outcome=running`/`pending`（`--no-wait` 或轮询超时）→ **仍在跑，不是失败**，稍后 `--job <id>` 复查。
- `outcome=unknown` + `job_id` → 任务已入队但状态没确认（网络抖动）——**绝不重新建任务**，按 `hint`
  用 `--job <id>` 复查到终态为止（重复建任务会让服务端重复搬运同一条视频）。

---

## 任务管理

```bash
python3 TV --list              # 列出我建的所有视频任务（只属于本账号）
python3 TV --job 42            # 查某任务的状态/产物
python3 TV --retry 42          # 重试失败/已完成任务（重跑并轮询到终态）
python3 TV --delete 42         # 删除任务（运行中不可删）
python3 TV --revise 42 --instructions "……"   # 对已完成的 remake 成片提修订意见
```

任务只属于创建它的账号，用同一凭据查询即可。

## 标杆样片（nbdpsy-server e2e 验收版，可直接引用）

- EMDR 自助干预视频 remake 重制版（约 30 分钟全片）：
  `https://mcp.nbdpsy.com/uploads/video/1-c7d004c8d2f2c1b6/out/final.mp4`
- 其单句 revise 修订版（缓存命中 123/124）：
  `https://mcp.nbdpsy.com/uploads/video/2-247a3e02603c589f/out/final.mp4`

---

## 关键文件

| 用途 | 路径 |
|------|------|
| 建任务 / 轮询 / 取产物 / 任务管理（--url / --mode / --job / --list / --retry / --delete / --revise / --download） | `scripts/transport_video.py` |
| 凭据工具 / 沙盒放行（sandbox allow，已含 mcp.nbdpsy.com） | `scripts/nbdpsy_common.py` |

## 红线速记

1. **只搬 YouTube**：非 youtube.com/youtu.be 链接一律拒绝，不硬提交。
2. **状态未确认绝不重建任务**：`outcome=unknown` / 轮询超时 → 一律 `--job <id>` 复查，**绝不**重新 `--url` 提交同一条（会重复处理、白烧算力）。
3. **remake 只对平面图形类原片**：真人出镜勿用 remake；发布须附 `meta_url` 的 `attribution` 文案，重要成片人工终审。
4. **发布是对外动作**：本 skill 只出成片与链接；要把成片发到小红书等平台，仍需运营确认账号与内容后，走对应发布流程。
5. **产物链接免鉴权公开**：`products` 里的 URL 谁拿到都能访问，回给运营时按需注意分享范围。
