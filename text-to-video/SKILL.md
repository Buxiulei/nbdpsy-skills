---
name: text-to-video
description: >-
  把一段文本 / 一篇官网博客长文 / 一个心理科普主题，丝滑地转成一条带中文字幕的竖屏短视频，
  用字节官方「即梦(Dreamina)CLI + Seedance 2.0」生成画面（走会员积分）、纯 ffmpeg 合成（零 Remotion 依赖）。
  agent 全程自检依赖、缺啥自动装、再跑生成与合成任务。只要用户提到「文本转视频 / 文章转视频 /
  博客转视频 / 把这篇长文做成视频 / 做个科普短视频 / 出条视频号(抖音/B站)视频 / 用即梦/Seedance 生成视频 /
  把文章做成视频」，即使没说「skill」字样也应使用本 skill。主要服务 NBDpsy 心理科普（绑定其合规红线与品牌美学），
  但文本输入通用。它产出 MP4 文件；可选把成片回写到 blog_posts.video_url。
---

# 文本转视频（即梦 Seedance 2.0 + ffmpeg）

把文本/长文/主题 → 一条**带中文字幕的竖屏短视频**。画面用字节官方 **即梦 Dreamina CLI** 调 **Seedance 2.0**（消耗你已购的会员积分，现金边际≈0），合成用**纯 ffmpeg**（中文字幕烧录 + AI 生成合规角标），全程零 Remotion/Node 依赖。

**一句话心智**：这是「**你当导演、agent 跑腿、每条人工终审**」的半自动产线，不是一键批量出片机。质量取决于分镜脚本的用心 + 中文打磨，不是堆钱。

## 关键事实（已在本机实测验证）

- 即梦 CLI 是**字节官方**工具（`dreamina`），本机已装、已登录、走会员积分（`dreamina user_credit` 可查）。
- **Seedance 2.0 在 CLI 里只有 720p**；单段 `duration` 4–15s；`image2video` 画幅由输入图推断（不接受 `--ratio`），`text2video`/`multimodal2video` 可设 `--ratio`。
- 生成**异步、排队可能数小时**（会员单账号串行）。→ 大批量用「夜间 `submit` 提交、次日 `fetch` 取回」，submit_id 不丢、不重复扣分。
- 三个脚本都在 `scripts/`，输出统一 **stdout=JSON / stderr=进度**，便于 agent 解析。

## 产线总览

```
文本/长文/主题
  │  ① 自检环境(check_env.py) ── 缺啥装啥/提示扫码登录
  ▼
② 写分镜脚本(LLM) ── 心理科普骨架: 钩子→概念图解→步骤→收尾CTA
  │   产出 shots.json(喂 jimeng_gen) + 字幕文案
  ▼
③ 预估积分 & 试水 1-2 镜(jimeng_gen) ── 先验证观感+排队再放量
  ▼
④ 批量生成片段(jimeng_gen batch) ── 每镜 720p MP4 落本地
  │   (可选) 旁白: edge-tts / 豆包TTS / 或用 Seedance 原生音/纯字幕
  ▼
⑤ 合成(compose_video.py) ── 归一化+烧中文字幕(Noto Sans CJK SC)+TTS旁白+BGM混音
  ▼
⑥ 人工终审(合规清单) → 成片 MP4
  ▼
⑦ (可选) 回写 blog_posts.video_url / 投放视频号·抖音·B站
```

多步任务先建中文 Todo 看板，每步勾掉。

---

## 第 ① 步 · 环境自检（自检自装）

```bash
cd .claude/skills/text-to-video
python3 scripts/check_env.py            # 只检测
python3 scripts/check_env.py --install  # 缺啥自动装(dreamina 用 curl；系统包给 sudo 命令)
```

读 stdout 的 `{"ready": true/false, "checks":[...]}`：
- `dreamina CLI` 缺 → 自动 `curl -fsSL https://jimeng.jianying.com/cli | bash`。
- `dreamina 登录 & 积分` 失败 → **必须人介入**：让用户在终端跑 `dreamina login --headless`，用**抖音 App 扫码**（这步无法自动）。积分偏低会给警告。
- `ffmpeg`/`ffprobe`/`Noto Sans CJK SC 字体` 缺 → 给 `sudo apt-get install -y ffmpeg fonts-noto-cjk`（macOS 用 brew）。
- `edge-tts 旁白(可选)` 缺 → `pip install edge-tts`（要 TTS 配音才需要；纯字幕+BGM 可不装）。
- `requests(豆包TTS依赖)` 缺 → `pip install requests`（用豆包高音质旁白才需要；edge 引擎不需要）。
- `豆包 TTS 凭据(可选)` 未配 → 在 skill 的 `.env` 填 `VOLC_TTS_APPID/VOLC_TTS_ACCESS_TOKEN/VOLC_TTS_CLUSTER`（火山控制台申请；用 edge 免费旁白可跳过，`.env` 已 gitignore 不入库）。
- 首次用某模型若报 `AigcComplianceConfirmationRequired`，让用户去 Dreamina 网页端对该模型做一次性授权。

`ready=true` 才进下一步。

---

## 凭据引导（skill 主动问用户，绝不硬编码）

**铁律**：所有加密信息一律**运行时向用户索取**、写进 skill 的 `.env`（已 gitignore）——绝不硬编码进 SKILL.md/脚本、绝不提交、绝不从项目 CLAUDE.md 里读硬编码密码。变量清单见同目录 `.env.example`（`cp .env.example .env` 后填）。

check_env 报某项凭据缺失时，agent 按下表**主动引导用户提供**，拿到后写入 `.env` 再复检；**任何时候都不要把用户给的凭据回显到对话、日志或 git 提交里**：

| 凭据 | 存哪 | agent 怎么做 |
|---|---|---|
| 豆包 TTS（`VOLC_TTS_APPID` / `VOLC_TTS_ACCESS_TOKEN` / `VOLC_TTS_CLUSTER`）| skill `.env` | 主动问用户要（火山控制台→语音合成大模型），写入 `.env`。不配也行 → 回退 edge-tts 免费旁白 |
| 即梦登录 | `~/.dreamina_cli/`（本地）| **引导用户**在终端跑 `dreamina login --headless` 抖音 App 扫码；agent 碰不到该凭据、只能引导，不代填 |
| 首模型合规授权 | Dreamina 网页端 | 报 `AigcComplianceConfirmationRequired` 时引导用户去网页端一次性授权 |
| sudo（装 ffmpeg/字体，如需）| 不留存 | 需要时即时问用户密码，用完不写进任何文件/日志 |

配好后 `python3 scripts/check_env.py` 复检到全绿再开跑。用户想撤销时，删 `.env` 对应行 / `~/.dreamina_cli/` 即可。

---

## 第 ② 步 · 写分镜脚本（这一步决定成片质量）

把文本浓缩成 **6–12 个分镜**（一条 60–120s 竖屏短视频）。心理科普推荐骨架：

1. **开场钩子（1 镜，5s）**：一句戳中痛点的提问/场景，配情绪空镜。
2. **核心概念（2–4 镜）**：把抽象概念可视化（空镜/隐喻画面 + 字幕讲清）。
3. **方法/步骤（2–4 镜）**：可操作的 1-2-3，每镜一个要点。
4. **收尾 CTA（1 镜）**：温柔收束 + 引导（关注/预约咨询，**不得承诺疗效**）。

每个分镜产出两样东西：**画面 prompt**（喂 Seedance）+ **字幕文案**（烧在画面上）。

### Seedance 中文 prompt 写作要点

公式：`主体 + 动作 + 镜头运动 + 光线/色调 + 氛围`。例：
`温暖的心理咨询室，一杯冒着热气的茶放在木桌上，晨光透过百叶窗缓缓移动，镜头极慢推近，宁静治愈氛围`

**铁律**：
- **图内绝不要中文/任何文字**（Seedance 等模型渲染 CJK 必乱码）。所有文字一律走 ffmpeg 字幕叠加。prompt 里可加「画面中无文字」。
- 出现人物时指定**东亚面孔、自然真实**，避免西化/恐怖谷；心理内容优先用**空镜/隐喻/背影/手部特写**，规避真人肖像与审核风险。
- 美学统一：温暖、柔光、低饱和、治愈感，贴合 NBDpsy 品牌。
- 多镜人物一致性：用同一张参考图走 `image2video` 或 `multimodal2video` 锚定。

### 字幕文案

口语化、共情、**忠于原文不编造**；每镜 1–2 行、每行 ≤ ~16 字；不下诊断、不承诺疗效。

### 产出 shots.json（喂 jimeng_gen 批量）

```json
[
  {"operation": "text2video", "prompt": "温暖咨询室空镜，晨光移过沙发，镜头极慢推近，治愈氛围，画面中无文字", "duration": 5, "ratio": "9:16", "model": "seedance2.0fast", "subtitle": "总觉得累，却说不出哪里不对？"},
  {"operation": "text2video", "prompt": "窗边绿植特写，光斑流动，柔焦，宁静", "duration": 5, "ratio": "9:16", "subtitle": "这可能不是懒，\n是情绪在求救"}
]
```
> `subtitle` 字段是给第 ⑤ 步合成用的（jimeng_gen 生成时会忽略它）；先把它一并写进每个分镜，方便后面拼 manifest。

---

## 第 ③–④ 步 · 预估积分 + 生成片段

```bash
# 查余额
python3 scripts/jimeng_gen.py credits

# 先试水 1 镜，确认观感 + 实测排队时长（关键决策变量！）
python3 scripts/jimeng_gen.py gen --operation text2video \
  --prompt "温暖咨询室空镜，晨光移过沙发，镜头极慢推近，画面中无文字" \
  --duration 5 --ratio 9:16 --model seedance2.0fast --out-dir ./clips

# 满意后批量（同步等待，每镜阻塞到完成）
python3 scripts/jimeng_gen.py batch --plan shots.json --out-dir ./clips

# 大批量 / 排队长：夜间只提交，记下 submit_id，次日取回（不重复扣分）
python3 scripts/jimeng_gen.py batch --plan shots.json --out-dir ./clips --submit-only
python3 scripts/jimeng_gen.py fetch --submit-id <id> --out-dir ./clips
```

**积分 & 排队（2026-06 实测，重要）**：5s/720p——普通 `fast` 25 积分、`fast_vip` 55 积分（+30 换插队）；扣费 success 才结算。**排队是真瓶颈**：实测高峰普通 `fast` 一条 5s 片排队 **近 2 小时仍未出片**，而 `fast_vip` 加速通道 **~3 分钟出片**。→ **投放/急用务必走 `--model seedance2.0fast_vip`**（真实可用单条成本按 VIP 55 积分算）；不急的量才用普通档 + `--submit-only` 夜间错峰。失败/超时保留 submit_id，绝不重复扣分；排队中任务无法取消（dreamina 无 cancel）。

**并行生产 & 卡死重提（关键提速，实测）**：`batch` 默认**串行** submit+fetch（等一镜下完才提交下一镜）很慢。正解=**先全部 `--submit-only` 灌队列、再并行 fetch**（多进程/线程各 `fetch --submit-id`），即梦后端同时排队渲染，墙钟≈最慢单镜而非 N 镜相加。偶有个别任务卡 `querying` 数小时（同批其他 30–60min 出）→ 提交积分已是沉没成本，**重新提交拿新 submit_id（走 VIP）、新旧并行谁先渲染好用谁**。

`gen`/`batch` 返回每镜 `{"success":true, "videos":["clips/xxx.mp4"], "credit_count":N}`。用返回的真实路径填第 ⑤ 步 manifest。

### 旁白配音（TTS）+ 背景音乐

用 `tts_gen.py` 生成旁白。**双引擎**：`edge`(免费无 key) / `doubao`(火山豆包大模型，高音质，需 `.env` 配 `VOLC_TTS_*`)。

```bash
# 逐句时间轴(--timed)：字幕真同步的根，强烈建议开
python3 scripts/tts_gen.py --engine doubao --plan shots.json --out-dir tts/ --timed
# 单条：python3 scripts/tts_gen.py --engine doubao --text "焦虑不是敌人…" --out tts/1.mp3 --timed
```

- **逐句时间轴 `--timed`（字幕真同步，必开）**：不开时字幕只能按字数比例**估算**时长，与真实语速错位（实测明显不同步）。`--timed` 把旁白按句切、每句单独合成、**ffprobe 实测时长**后拼接，并写 sidecar `{out}.cues.json`。compose 检测到 cues 就让字幕严格按每句实测时长走——旁白讲到哪、字幕走到哪。长句(只有结尾一个句号的整段)会在句内按逗号再细分成多条字幕滚动，不会一条久挂。
- **豆包音色**（本机实测已开通，cluster=`volcano_tts`；音色主观，新项目建议合成几个候选让用户试听选定）：
  - `zh_female_wenroushunv_mars_bigtts` 温柔淑女（**默认**·成熟温柔知性，心理科普首选）
  - `zh_female_qingxinnvsheng_mars_bigtts` 清新女声（清新偏年轻）
  - `zh_female_meilinvyou_moon_bigtts` 魅力女友（偏柔偏慢偏嗲）
  - `zh_female_shuangkuaisisi_moon_bigtts` 爽快思思（明快活泼）
  - 经典 BV 系列(BV001/BV700)未授权会报 `code=3001 resource not granted`。edge 引擎：`zh-CN-XiaoxiaoNeural`(温柔女)/`zh-CN-YunxiNeural`(沉稳男)。
- 生成的 mp3(+`.cues.json`) 按 index 填进第⑤步 manifest 每镜 `narration`（cues 同名自动探测，无需手填）。
- **连贯关键（旁白驱动 duration）**：先出旁白、按其时长定每镜画面 `duration`(向上取整 clamp 4–15s)，画面与旁白等长正常速度，最连贯。兜底：画面短于旁白时 compose 匀速放慢填满(不卡顿)，旁白绝不被截。⚠️ 换音色会变语速→旁白时长变→画面放慢幅度变（温柔淑女较慢，多镜会触发兜底放慢，可接受）。
- **背景音乐（轻音乐·自动生成）**：`gen_bgm.py` 算法合成舒缓钢琴/竖琴拨弦琶音轻音乐(和弦进行+ADSR包络+混响+低通+头尾淡入淡出)，零版权零等待，比手搓正弦 pad 有旋律有层次：
  ```bash
  python3 scripts/gen_bgm.py --duration 67 --out bgm.mp3 --mood calm   # mood: calm / warm
  ```
  时长设成≈成片长(略大即可，finalize 会截断、结尾自然淡出)。路径填 manifest 的 `bgm`；也可自备无版权音乐(Pixabay/Suno)。
- **BGM 响度自动相对化（别用固定系数）**：finalize 测旁白与 BGM 的 mean、把 BGM 压到比旁白低 `bgm_gap_db`(默认12dB)。实测教训：自合成 pad 用固定 `volume=0.16` 会被**完全淹没**(mean −54dB)，真实音乐又可能盖过旁白——相对响度才稳。`amix` 内部已加 `normalize=0`，否则旁白会被压低 ~6dB。

---

## 第 ⑤ 步 · 合成成片

把每镜的视频路径 + 字幕（+ 可选旁白）写进 manifest，跑 ffmpeg 合成：

```json
{
  "output": "out/final.mp4",
  "resolution": "720x1280",
  "fps": 30,
  "bgm": "assets/bgm.mp3",
  "bgm_gap_db": 12,
  "segments": [
    {"video": "clips/shot1.mp4", "narration": "tts/000.mp3", "narration_text": "总觉得累，却说不出哪里不对？这可能不是懒。"},
    {"video": "clips/shot2.mp4", "subtitle": "无旁白时的固定字幕"}
  ]
}
（字幕优先级：narration 同名 .cues.json(真同步) > narration_text(按句估算) > subtitle(固定整段)。
 默认不叠任何水印/角标；如需 AI 标识，加 "ai_label": "AI 生成"。bgm_gap_db 越大 BGM 越轻）
```

```bash
python3 scripts/compose_video.py --manifest manifest.json
```

输出 `{"success":true,...}`。合成层自动：统一分辨率/帧率 → 烧中文字幕（Noto Sans CJK SC，白字黑描边底部居中；**有 `.cues.json` 则按 TTS 实测时间轴逐句真同步**，否则按句估算）→ TTS 旁白 + BGM 混音（**画面与旁白等长**：画面短则匀速放慢填满、不卡顿，旁白绝不被截；**BGM 自动相对响度**压到比旁白低 `bgm_gap_db`dB，`amix normalize=0` 防旁白被压低）→ h264/aac/+faststart。**默认不叠任何水印/角标**；如需 AI 标识，manifest 加 `"ai_label": "AI 生成"`。

---

## 第 ⑥ 步 · 人工终审（合规清单，逐条过）

YMYL（健康）内容，**只做白帽，绝不编造**。投放前逐条核：
- [ ] **AI 生成标识**：本产线默认**不叠**角标（按需求）。⚠️《AI 生成合成内容标识办法》要求显式标识——投放前自行决定是否给 manifest 加 `"ai_label"`，或依赖平台自动打标 / 隐式元数据。
- [ ] 旁白/字幕**不下诊断、不承诺疗效**（「缓解/陪伴/支持」可，「治愈/根治」不可）。
- [ ] 内容**忠于原文、无编造**数据/引语。
- [ ] 画面无诡异/恐怖谷/西化失真；无图内乱码文字；人物得体。
- [ ] 危机相关选题带求助提示（如适用）。
- [ ] 字幕断行通顺、读音正确、无错别字。
- [ ] 音画同步、无黑帧/断音；时长适配平台。

> ⚠️ 商用授权：即梦会员「生成内容可商用」无清晰明示条款，正式商用投放前请让用户**法务核对最新会员协议**，尤其虚拟人肖像 + 心理健康内容。

---

## 第 ⑦ 步 · （可选）回写 blog_posts.video_url / 投放

本仓库博客已有 `blog_posts` 表与图片上传基建（见 [[project_blog_cover_upload]] 范式）。把成片当作博客视频时，最小集成：给 `blog_posts` 加 `video_url` 列 + 详情页 `<video>` 播放器 + 复用上传 handler。这部分是独立的代码改动，按需另开任务，**不属于本 skill 的生成产线**。或直接把 MP4 投视频号/抖音/B站。

---

## 衔接 xiaohongshu-creator（每篇笔记 → 短视频）

承接 `xiaohongshu-creator` 的产出（每篇笔记 = ~300 字正文 + 6–9 页轮播，每页有「页面文字」+「中文绘图提示词」），给选定笔记生成竖屏短视频。**先让用户选哪几篇做**（每条烧积分，别盲目全做）。

**每页 → 一个分镜**：
- **旁白(narration_text)** = 该页正文/页面文字，改写成口语化解说（共情、不堆术语、忠于原文不编造）。
- **字幕(subtitle)** = 该页大标题/核心句（≤2 行）。
- **画面** 两种模式让用户选：
  - **模式 A · 文生（默认/全自动）**：把该页「中文绘图提示词」**改写成 Seedance 文生 prompt**——去掉"图中显示的中文文字"（图内 no-text，文字全走字幕）、保留场景/主体/风格、补运镜与电影质感（"镜头缓慢推近、柔光、真实质感、画面安静无对白"）、东亚人物治愈氛围。→ `operation=text2video`、`ratio=9:16`。
  - **模式 B · 图生（更可控/与图文一致）**：用户已用 xiaohongshu 提示词在 Gemini/GPT 出的每页图 → 当首帧 `image2video`，prompt 只写运镜（"镜头缓慢推近/平移"）。画面与小红书图文完全一致、连贯度最高；画幅由图推断（小红书图常 3:4）。

**连贯（旁白驱动 duration）**：先 `tts_gen.py --engine doubao` 批量出旁白 → 读每条 mp3 时长 → **每镜 `duration` 取该页旁白时长（向上取整 clamp 4–15s）** → 再生成视频。画面与旁白等长、正常速度，不卡顿（compose 变速仅兜底）。

**端到端**：选笔记 → 每页正文整理成 `narration_text` → 豆包 `--timed` 批量出旁白(+cues)、读时长定 duration → 画面(A 改写提示词跑 `jimeng_gen batch` / B 收集每页图跑 image2video) → `compose_video.py` 合成(逐句字幕+豆包旁白+自动轻音乐) → 人工终审(合规同小红书：不诊断/不导流/危机声明/AI 自评)。每篇一条，可投视频号·抖音，与小红书图文双投放。

**图生实战经验（2026-06-30 CPTSD 第1篇跑通）**：
- **去文字图**：小红书发布图带大标题/信息卡文字，视频文字全走逐句字幕——图生要另出一套**去文字版**同人物图(在 xiaohongshu 提示词基础上删掉"图中文字"、信息卡页换成画面)，避免图内文字与字幕打架。
- **信息卡页补画面 + 相关性取舍**：纯文字信息卡页(P2/P3)没画面主体，image2video 补 contextual 画面(雨窗/抱膝/城市灯火等情绪隐喻)。抽象科普概念("占4%""三组困难")靠**逐句字幕**承载相关性，画面只做情绪烘托——写意治愈风的固有取舍；要画面强相关得改"信息图解"形态(另一种视频)。
- **逐句字幕真同步**：旁白 `--timed` 出 cues，字幕严格按实测时长滚动；长句句内按逗号细分多条滚动。
- **提速 & 卡死**：先全 `--submit-only` 灌队列再并行 fetch；个别镜卡 querying 数小时则重提新 submit_id 并行抢（详见第③④步）。
- **image2video 画幅**：3:4 图 → 输出 834×1112(720p)，画幅由图推断，prompt 只写运镜+微动作(无对白、画面无文字)。

## 进阶 · 接入 OpenMontage（可选，重）

如果将来上完整 agentic 产线（OpenMontage 的分镜导演/质量闸门/Remotion 精细动效），`assets/seedance_jimeng.py` 是一个**让 OpenMontage 的 Seedance 槽位改吃即梦会员积分**的 provider（`provider="seedance_jimeng"`、`cost_usd=0`、`quality_score=0.95`、`fallback_tools` 降级到 fal/replicate 版）。部署：把它放进 OpenMontage 的 `tools/video/` 即被自动注册。**但 OpenMontage 依赖重（Python+Node+Remotion headless Chromium）、约 3 周龄、AGPLv3 建议锁 commit**——与"丝滑"相悖，仅在确有需求时启用。本 skill 主线（dreamina + ffmpeg）不依赖它。

## 红线汇总

- 图内 no-text（CJK 必乱码，文字全走 ffmpeg 字幕）。
- 每条必经人工终审；不下诊断、不承诺疗效、不编造。
- AI 生成标识：默认不加；⚠️ 合规上《标识办法》要求显式标识，投放前自行评估加 `ai_label` 或靠平台打标。
- 排队长 → 夜间 `--submit-only` 错峰；submit_id 保留不重复扣分。
- 生成只在开发机/专用机跑，**绝不部署到生产服务器**（抢资源 + 凭据安全）。
- Seedance CLI 仅 720p；要更高分辨率需另寻（非本产线）。
```
