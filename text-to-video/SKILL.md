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
- 首次用某模型若报 `AigcComplianceConfirmationRequired`，让用户去 Dreamina 网页端对该模型做一次性授权。

`ready=true` 才进下一步。

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

`gen`/`batch` 返回每镜 `{"success":true, "videos":["clips/xxx.mp4"], "credit_count":N}`。用返回的真实路径填第 ⑤ 步 manifest。

### 旁白配音（TTS）+ 背景音乐

用 `tts_gen.py`（edge-tts，免费无 key，中文音色自然）生成旁白：
```bash
# 分镜计划每镜写 narration_text(旁白文案)，批量生成 tts/000.mp3, 001.mp3 …
python3 scripts/tts_gen.py --plan shots.json --out-dir tts/
# 单条：python3 scripts/tts_gen.py --text "焦虑不是敌人…" --out tts/1.mp3
```
- 默认温柔女声 `zh-CN-XiaoxiaoNeural` + 语速 `-10%`(科普稍慢)；男声 `--voice zh-CN-YunxiNeural`。
- 生成的 mp3 按 index 填进第⑤步 manifest 每镜 `narration`。
- **连贯关键（旁白驱动 duration）**：**最佳做法是先出旁白、按其时长定每镜画面 `duration`**（向上取整、clamp 4–15s），画面与旁白等长、正常速度播放，最连贯。
- 兜底：若画面仍短于旁白，compose 会把该段画面**匀速放慢填满**旁白时长（画面持续运动、不卡顿）；短则片尾静音；旁白绝不被截断。**别依赖兜底变速**（变速幅度大画面会偏慢），优先旁白驱动 duration。
- **BGM**：自备一段无版权音乐(Pixabay/Suno 等)，路径填 manifest 的 `bgm`，`bgm_volume` 控制音量(默认 0.12，压在旁白下)。
- 想要更高音质可换豆包 TTS(需 key)，同样产出 mp3 填 `narration`。

---

## 第 ⑤ 步 · 合成成片

把每镜的视频路径 + 字幕（+ 可选旁白）写进 manifest，跑 ffmpeg 合成：

```json
{
  "output": "out/final.mp4",
  "resolution": "720x1280",
  "fps": 30,
  "bgm": "assets/bgm.mp3",
  "bgm_volume": 0.12,
  "segments": [
    {"video": "clips/shot1.mp4", "subtitle": "总觉得累，\n却说不出哪里不对？", "narration": "tts/000.mp3"},
    {"video": "clips/shot2.mp4", "subtitle": "这可能不是懒，\n是情绪在求救", "narration": "tts/001.mp3"}
  ]
}
（默认不叠任何水印/角标；如需 AI 标识，加 `"ai_label": "AI 生成"`）
```

```bash
python3 scripts/compose_video.py --manifest manifest.json
```

输出 `{"success":true,...}`。合成层自动：统一分辨率/帧率 → 烧中文字幕（Noto Sans CJK SC，白字黑描边底部居中）→ TTS 旁白 + BGM 混音（**画面与旁白等长：画面短则匀速放慢填满、不卡顿，旁白绝不被截**）→ h264/aac/+faststart。**默认不叠任何水印/角标**；如需 AI 标识，manifest 加 `"ai_label": "AI 生成"`。

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

**端到端**：选笔记 → 每页正文整理成 `narration_text` → 豆包批量出旁白+读时长定 duration → 画面(A 改写提示词跑 `jimeng_gen batch` / B 收集每页图跑 image2video) → `compose_video.py` 合成(中文字幕+豆包旁白+可选 BGM) → 人工终审(合规同小红书：不诊断/不导流/危机声明/AI 自评)。每篇一条，可投视频号·抖音，与小红书图文双投放。

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
