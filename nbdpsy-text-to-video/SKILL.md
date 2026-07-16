---
name: nbdpsy-text-to-video
description: >-
  把一段文本 / 一篇官网博客长文 / 一个心理科普主题，丝滑地转成一条带中文字幕的竖屏短视频，
  用字节官方「即梦(Dreamina)CLI + Seedance 2.0」生成画面（走会员积分）、纯 ffmpeg 合成（零 Remotion 依赖）。
  agent 全程自检依赖、缺啥自动装、再跑生成与合成任务。只要用户提到「文本转视频 / 文章转视频 /
  博客转视频 / 把这篇长文做成视频 / 做个科普短视频 / 出条视频号(抖音/B站)视频 / 用即梦/Seedance 生成视频 /
  把文章做成视频」，或给一篇小红书笔记+参考图要求直接出片，即使没说「skill」字样也应使用本 skill。
  主要服务 NBDpsy 心理科普（绑定其合规红线与品牌美学），但文本输入通用。它产出 MP4 文件；
  可选把成片回写到 blog_posts.video_url。
---

# 文本转视频（即梦 Seedance 2.0 + ffmpeg）

把文本/长文/小红书笔记 → 一条**带中文字幕的竖屏短视频**。画面用字节官方 **即梦 Dreamina CLI** 调 **Seedance 2.0**（消耗你已购的会员积分，现金边际≈0），合成用**纯 ffmpeg**（中文字幕烧录 + AI 生成合规角标），全程零 Remotion/Node 依赖。

**一句话心智**：这是「**你当导演、脚本跑腿、每条人工终审**」的半自动产线，不是一键批量出片机。质量取决于分镜脚本的用心 + 中文打磨，不是堆钱。

**路径约定**：以下命令中 `{SKILL_DIR}` 指本文件（SKILL.md）所在目录；`{workspace}` 指内容工作区根目录，用 `python3 {SKILL_DIR}/scripts/nbdpsy_common.py workspace` 查询实际路径。

多步任务先维护一份中文任务清单，每步做完勾掉。

## 关键事实（已实测验证）

- 即梦 CLI 是**字节官方**工具（`dreamina`），走会员积分（`dreamina user_credit` 可查）。
- **Seedance 2.0 在 CLI 里只有 720p**；单段 `duration` 4–15s（整数）；`image2video` 画幅由输入图推断（不接受 `--ratio`），`text2video`/`multimodal2video` 可设 `--ratio`（1:1 / 3:4 / 4:3 / 9:16 / 16:9 / 21:9）。
- 生成**异步、排队可能数小时**（会员单账号串行）。→ 大批量用「`--submit-only` 先灌队列、并行 `fetch` 取回」，submit_id 不丢、不重复扣分。
- `{SKILL_DIR}/scripts/` 下所有脚本输出统一 **stdout=JSON / stderr=进度**，便于解析。

---

## 第 0 步 · 环境自检（自检自装，`ready=true` 才开跑）

```bash
python3 {SKILL_DIR}/scripts/check_env.py            # 只检测
python3 {SKILL_DIR}/scripts/check_env.py --install  # 缺啥自动装(dreamina 用 curl；系统包给 sudo 命令)
```

读 stdout 的 `{"ready": true/false, "checks":[...]}`：
- `dreamina CLI` 缺 → 自动 `curl -fsSL https://jimeng.jianying.com/cli | bash`。
- `dreamina 登录 & 积分` 失败 → **必须人介入**：让用户在终端跑 `dreamina login --headless`，用**抖音 App 扫码**（这步无法自动）。积分偏低会给警告。
- `ffmpeg`/`ffprobe`/`Noto Sans CJK SC 字体` 缺 → 给 `sudo apt-get install -y ffmpeg fonts-noto-cjk`（macOS 用 brew；Windows 无 Noto 时字幕回退微软雅黑，或用 `FONT_PATH` 环境变量显式指定字体文件）。
- `edge-tts 旁白(可选)` 缺 → `pip install edge-tts`（要 TTS 配音才需要；纯字幕+BGM 可不装）。
- `requests(豆包TTS依赖)` 缺 → `pip install requests`（用豆包高音质旁白才需要；edge 引擎不需要）。
- `豆包 TTS 凭据(可选)` 未配 → 优先在 skill 的 `.env` 填 `VOLC_TTS_API_KEY`（新版控制台单一凭据，火山控制台 `speech/new/setting/apikeys` 自建）；也可用旧版 `VOLC_TTS_APPID/VOLC_TTS_ACCESS_TOKEN/VOLC_TTS_CLUSTER`（向后兼容）。用 edge 免费旁白可跳过，`.env` 已 gitignore 不入库。
- 首次用某模型若报 `AigcComplianceConfirmationRequired`，让用户去 Dreamina 网页端对该模型做一次性授权。

---

## 凭据引导（主动问用户，绝不硬编码）

**铁律**：所有加密信息一律**运行时向用户索取**、写进 skill 的 `.env`（已 gitignore）——绝不硬编码进 SKILL.md/脚本、绝不提交、绝不从任何项目配置文件里读硬编码密码。变量清单见同目录 `.env.example`（`cp .env.example .env` 后填）。

check_env 报某项凭据缺失时，按下表**主动引导用户提供**，拿到后写入 `.env` 再复检；**任何时候都不要把用户给的凭据回显到对话、日志或 git 提交里**：

| 凭据 | 存哪 | 怎么做 |
|---|---|---|
| 豆包 TTS · 新版（`VOLC_TTS_API_KEY`，**优先**）| skill `.env` | 主动问用户要（火山控制台 `speech/new/setting/apikeys` 自建单一 API Key），写入 `.env`。不配也行 → 用 edge-tts 免费旁白（`--engine edge`） |
| 豆包 TTS · 旧版（`VOLC_TTS_APPID` / `VOLC_TTS_ACCESS_TOKEN` / `VOLC_TTS_CLUSTER`，向后兼容）| skill `.env` | 已有 `VOLC_TTS_API_KEY` 可不填；否则主动问用户要（火山控制台→语音合成大模型），写入 `.env` |
| 即梦登录 | `~/.dreamina_cli/`（本地）| **引导用户**在终端跑 `dreamina login --headless` 抖音 App 扫码；agent 碰不到该凭据、只能引导，不代填 |
| 首模型合规授权 | Dreamina 网页端 | 报 `AigcComplianceConfirmationRequired` 时引导用户去网页端一次性授权 |
| sudo（装 ffmpeg/字体，如需）| 不留存 | 需要时即时问用户密码，用完不写进任何文件/日志 |

> 豆包凭据也可由管理后台「博客 → API Keys → 生成凭据配置包」统一下发（工作室已集中配置时，包里会自动带上 `VOLC_TTS_*`，含新版 `VOLC_TTS_API_KEY`）；即梦登录仍需本机扫码，无法进包。

配好后 `python3 {SKILL_DIR}/scripts/check_env.py` 复检到全绿再开跑。用户想撤销时，删 `.env` 对应行 / `~/.dreamina_cli/` 即可。

---

## 产线流程（笔记→成片，十步 + 2.5 分镜确认页）

### 工作目录契约

每篇笔记一个目录：`{workspace}/videos/{slug}-{NN}/`（下称 `<workdir>`）。目录内文件命名是**跨脚本硬契约**（sync_durations / build_manifest 按名扫描），别自创名字：

```
shots.json                 分镜脚本（parse_note 产出 + 你精修）
{workdir名}-storyboard.html  分镜确认页（第 2.5 步产出，按内容命名；给运营看脚本/复制提示词/核对参考图）
images/                    参考图目录（第 2.5 步收图：P{页号}.png）
narr-NN.mp3                每镜旁白（两位序号，01 起，对应 shots.json 的 index）
narr-NN.mp3.cues.json      每镜逐句时间轴（tts_gen --timed 的 sidecar，命名语义 {out}.cues.json）
shot-NN.mp4                每镜成片（fetch 下载后重命名）
bgm.mp3                    （可选）背景音乐
manifest.json              build_manifest 产出的合成清单
final.mp4                  成片
```

### 十步

**1. 解析笔记 → shots.json**

```bash
python3 {SKILL_DIR}/scripts/parse_note.py <note_dir>/post-NN.md \
  --images-dir <去文字版参考图目录> --out <workdir>/shots.json
```

- 图生模式且参考图**已经就绪**（如笔记出图环节已产出去文字版图）：`--images-dir` 指向该目录（命名 `P1.png` 或 `P01.png` 均可，大小写不敏感，按页序号自动映射到每镜 `image` 字段）。
- 参考图还没有：省略 `--images-dir`，第 2.5 步的分镜确认页会负责收图并写回。
- 纯文生（无图）：省略 `--images-dir`。
- shots.json 输出目录会自动创建，无需手动 mkdir。
- stdout JSON `{"out": ..., "shots": N}`，核对页数；stderr 会警告缺提示词/页面文字的页。

**2. 精修分镜（智力步骤，你来做，决定成片质量）**

逐镜编辑 `<workdir>/shots.json`：
- `narration_text` 改写成**口语化旁白**（书面语→说给人听的话；共情、不堆术语、忠于原文不编造）。
- 文生镜：`prompt` 按「分镜与旁白写作要点」节改写成 Seedance 视频 prompt，**必须含「画面中无任何文字」**。
- **走图生的镜：补 `"image_prompt"` 字段**——从笔记的「## 视频参考图提示词」节取该页去文字版提示词填入（没有笔记就按 illustration-spec 的去文字版规则自己写）。这是第 2.5 步生图的依据。
- 图生镜（`image` 非空）：**补 `"operation": "image2video"`**（batch 默认 text2video，不补不会吃图）；`prompt` 只写运镜+微动作（如「镜头缓慢推近，光斑轻微流动，无对白，画面无文字」）。参考图在 2.5 步才回传的，就在 2.5 收图后回来补这两项。
- 急件在镜级设 `"model": "seedance2.0fast_vip"`（排队差异见「生成细节」节）。

**2.5 分镜确认页（storyboard：给运营看脚本 + 收参考图）**

```bash
python3 {SKILL_DIR}/scripts/render_storyboard.py --workdir <workdir>
# 产出 <workdir>/{workdir目录名}-storyboard.html（按内容命名，绝不重名）
# 每镜一卡：旁白脚本、字幕、生图提示词（一键复制，优先 image_prompt 去文字版）、参考图回传状态
```

无论哪种模式都生成这一页并把**绝对路径**给运营——这是运营查看每一镜脚本的入口。然后按模式分流：

- **走图生 + 宿主没有图像生成能力（如 Claude Code）：⛔ 停等闸门（硬性协议，违反=事故）**——把 storyboard 绝对路径发给运营，并把**每一镜的生图提示词逐镜直接贴在会话里**，告诉运营（`<workdir>` 等占位符必须替换成真实绝对路径，别让运营看到尖括号/花括号）：「打开确认页逐镜核对脚本；复制每镜提示词生成 3:4 竖版图，命名成 P01.png 两位数（写成 P1.png 也认），放进 `<workdir>/images/`，全部放好回复我『图片好了』」。**说完立即结束你的当前回合**——不要继续第 3 步、不要假设图片已就绪。这是预期内的正常停等，不是任务失败。运营回复后先收图写回再核验：

  ```bash
  python3 {SKILL_DIR}/scripts/render_storyboard.py --workdir <workdir> --attach-images <workdir>/images
  ```

  核对 stdout 的 `attached` 数与走图生的镜数一致、每个图生镜 `image` 非空；缺图就列出缺哪几镜（P 几），再次停下等待。齐了回到第 2 步补 `operation:"image2video"` 与运镜化 prompt，再进第 3 步。
- **走图生 + 宿主有图像生成能力（如 Codex）**：按每镜 `image_prompt` 逐镜生成 3:4 竖版图到 `<workdir>/images/P{页号}.png`，跑上面的 `--attach-images` 写回，同样把刷新后的 storyboard 路径给运营备查，然后继续。
- **纯文生**：storyboard 仅作脚本确认页给运营备查，不停等，直接进第 3 步。

**3. 旁白合成（逐镜单条，命名铁律）**

```bash
# 逐镜执行；NN = 该镜 index 的两位序号（01、02…）
python3 {SKILL_DIR}/scripts/tts_gen.py --engine doubao --timed \
  --text "<该镜精修后的旁白>" --out <workdir>/narr-01.mp3
```

- `--timed` **必开**：逐句合成+ffprobe 实测时长，sidecar 自动落 `narr-NN.mp3.cues.json`——字幕真同步的根。
- 豆包凭据缺失会直接报错 → 改 `--engine edge` 免费兜底（音色/语速选项见「旁白与 BGM 细节」节）。
- **克隆音色**：配了克隆音色（默认音色 `VOLC_TTS_VOICE=S_xxx` + `VOLC_TTS_APPID`）则旁白自动用你克隆的专属声音，走 `seed-icl-2.0`，纯人声、全片一致（缺 appid 会直接报错）。
- ⚠️ 别用 `--plan` 批量模式出旁白：它落名 `000.mp3`（三位、0 起），**不符合工作目录契约**，后续脚本找不到文件。

**4. 时长写回（脚本化，禁止跳过）**

```bash
python3 {SKILL_DIR}/scripts/sync_durations.py --shots <workdir>/shots.json --audio-dir <workdir>
# 默认 --min 4 --max 15
```

- 每镜 `duration` = clamp(旁白实测 + 0.3s, 4, 15)，原地写回 shots.json。
- **overflow（旁白+0.3s > 15s）或缺音频 → exit 1** → 回第 2 步拆镜/精简旁白、重出该镜旁白，再跑本步。**禁止跳过**——手工漏做这步 = 画面被异常放慢的最大事故源。

**5. 提交生成（全部镜头先灌队列）**

```bash
python3 {SKILL_DIR}/scripts/jimeng_gen.py batch --plan <workdir>/shots.json \
  --out-dir <workdir> --submit-only > <workdir>/submit_ids.json
```

- **保存 stdout JSON 到 `<workdir>/submit_ids.json`**：`results[].submit_id` 是取片凭证与防重复扣分的关键（注意 `results[].index` 是 0 起，shots.json 的 `index` 是 1 起，映射时 +1）。submit_id 保留不重复提交，即使超时也可后续再 fetch 补取。
- 新题材首次跑建议先 `gen` 试水 1 镜确认观感+实测排队，再放量（见「生成细节」节）。

**6. 并行取片 + 重命名**

```bash
# 每个 submit_id 各开一个 fetch（可多进程并行，墙钟≈最慢单镜）
python3 {SKILL_DIR}/scripts/jimeng_gen.py fetch --submit-id <id> --out-dir <workdir>
# fetch 输出 JSON，使用其中 videos[] 字段里的真实路径逐镜重命名成契约名
# 示例（fetch 返回 {"success":true, "videos":["/path/to/video_0.mp4", "/path/to/video_1.mp4"]}）：
mv /path/to/video_0.mp4 <workdir>/shot-01.mp4
mv /path/to/video_1.mp4 <workdir>/shot-02.mp4
```

- 以 fetch 输出 JSON 的 `videos[]` 字段里的真实路径为准，不要假设文件名格式——按实际输出路径逐镜改名为 `shot-NN.mp4`（两位序号，01 起）。
- 个别任务卡 `querying` 数小时（同批其他 30–60min 出）→ 提交积分已是沉没成本，**重提新 submit_id（走 VIP）并行抢，谁先渲染好用谁**。
- fetch 超时不丢任务：submit_id 保留，稍后再 fetch，不重复扣分。

**7. BGM（可选）**

```bash
python3 {SKILL_DIR}/scripts/gen_bgm.py --duration <≈成片总秒数> --out <workdir>/bgm.mp3 --mood calm
# mood: calm / warm；时长略大于成片即可，合成时会截断+结尾淡出
```

**8. 拼合成清单（脚本扫描，零手工拼 JSON）**

```bash
python3 {SKILL_DIR}/scripts/build_manifest.py --workdir <workdir>
```

- 按 shots.json 逐镜配齐 `shot-NN.mp4 / narr-NN.mp3 / cues`，缺件 **exit 1 报明细且不写 manifest** → 补齐再跑。
- 自动带上 `bgm.mp3`（若存在）、按 ratio 定分辨率，并**默认写入 `"ai_label": "AI 生成"`**（合规默认安全；确需关闭，手动把 manifest.json 的 ai_label 置空）。

**9. 合成成片**

```bash
python3 {SKILL_DIR}/scripts/compose_video.py --manifest <workdir>/manifest.json
```

输出 `{"success":true,...}`，成片在 `<workdir>/final.mp4`。合成细节与 manifest 字段见「合成细节」节。

**10. 对抗审查**

触发 **nbdpsy-content-reviewer** skill（独立子代理，绝不自审）按其 `references/checklist-video.md` 审片（确定性检查脚本 + 抽帧观看）。
- FAIL → 按报告定位问题镜，**只重跑该镜相关步骤**，再 8–9 重新合成：
  - 改旁白/换音色 → 该镜重跑 3–4（改旁白**必须**连带 4，否则 duration 失真）
  - 改画面 prompt / 重生成 → 该镜重跑 5–6
  - 只调 BGM → 重跑 7
- PASS → 进入投放前人工终审（下节）。

### 通用输入（非笔记：任意文本/长文/主题）

没有笔记时跳过第 1 步：按「分镜与旁白写作要点」节把文本浓缩成 6–12 镜，手写 `<workdir>/shots.json`（结构同工作目录契约：`{"video":{"title","ratio":"9:16"},"shots":[{"index":1,"prompt":...,"subtitle":...,"narration_text":...,"image":null,"duration":null},...]}`，index 从 1 起），然后从第 3 步接入，后续完全一致。

---

## 分镜与旁白写作要点（第 2 步的知识库）

把文本浓缩成 **6–12 个分镜**（一条 60–120s 竖屏短视频）。心理科普推荐骨架：

1. **开场钩子（1 镜，5s）**：一句戳中痛点的提问/场景，配情绪空镜。
2. **核心概念（2–4 镜）**：把抽象概念可视化（空镜/隐喻画面 + 字幕讲清）。
3. **方法/步骤（2–4 镜）**：可操作的 1-2-3，每镜一个要点。
4. **收尾 CTA（1 镜）**：温柔收束 + 引导（关注/预约咨询，**不得承诺疗效**）。

### Seedance 中文 prompt 写作要点

公式：`主体 + 动作 + 镜头运动 + 光线/色调 + 氛围`。例：
`温暖的心理咨询室，一杯冒着热气的茶放在木桌上，晨光透过百叶窗缓缓移动，镜头极慢推近，宁静治愈氛围，画面中无任何文字`

**铁律**：
- **图内绝不要中文/任何文字**（Seedance 等模型渲染 CJK 必乱码）。所有文字一律走 ffmpeg 字幕叠加。prompt 里必须加「画面中无任何文字」。
- 出现人物时指定**东亚面孔、自然真实**，避免西化/恐怖谷；心理内容优先用**空镜/隐喻/背影/手部特写**，规避真人肖像与审核风险。
- 美学统一：温暖、柔光、低饱和、治愈感，贴合 NBDpsy 品牌。
- 多镜人物一致性：用同一张参考图走 `image2video` 或 `multimodal2video` 锚定。

### 旁白与字幕文案

口语化、共情、**忠于原文不编造**；不下诊断、不承诺疗效。`subtitle` 是无旁白镜的兜底固定字幕（每镜 1–2 行、每行 ≤ ~16 字）；有旁白+cues 时字幕逐句真同步、无需手写。shots.json 里的 `narration_text`/`subtitle` 由 TTS 与合成清单消费，`jimeng_gen` 生成画面时会忽略它们（只吃 operation/prompt/duration/ratio/model/image）。

---

## 生成细节与实测经验（第 5–6 步引用）

```bash
# 查余额
python3 {SKILL_DIR}/scripts/jimeng_gen.py credits

# 新题材先试水 1 镜，确认观感 + 实测排队时长（关键决策变量！）
python3 {SKILL_DIR}/scripts/jimeng_gen.py gen --operation text2video \
  --prompt "温暖咨询室空镜，晨光移过沙发，镜头极慢推近，画面中无任何文字" \
  --duration 5 --ratio 9:16 --model seedance2.0fast --out-dir <workdir>
```

- 模型可选：`seedance2.0` / `seedance2.0fast`（默认）/ `seedance2.0_vip` / `seedance2.0fast_vip`。
- **积分 & 排队（实测，重要）**：5s/720p——普通 `fast` 25 积分、`fast_vip` 55 积分（+30 换插队）；扣费 success 才结算。**排队是真瓶颈**：实测高峰普通 `fast` 一条 5s 片排队**近 2 小时仍未出片**，而 `fast_vip` 加速通道 **~3 分钟出片**。→ **投放/急用务必走 `seedance2.0fast_vip`**（真实可用单条成本按 VIP 55 积分算）；不急的量才用普通档 + `--submit-only` 夜间错峰。
- **失败/超时保留 submit_id，绝不重复提交扣分**；排队中任务无法取消（dreamina 无 cancel）。
- **并行生产（关键提速）**：`batch` 不带 `--submit-only` 时是**串行** submit+fetch（等一镜下完才提交下一镜）很慢。正解 = 十步流程的 5–6 步：**先全部 `--submit-only` 灌队列、再并行 fetch**，即梦后端同时排队渲染，墙钟≈最慢单镜而非 N 镜相加。
- **卡 querying 重提**：个别任务卡 `querying` 数小时 → 重新提交拿新 submit_id（走 VIP）、新旧并行谁先渲染好用谁（旧积分已沉没，不因等待翻倍损失时间）。
- 生成端 `duration` 取整数秒；与旁白的零点几秒差值由合成层匀速兜底，无感。
- `gen`/`fetch` 返回 `{"success":true, "videos":[...], "credit_count":N}`，`videos` 是已下载的真实路径。

---

## 旁白与 BGM 细节（第 3、7 步引用）

**双引擎**：`edge`（免费无 key）/ `doubao`（火山豆包大模型，高音质，需 `.env` 配凭据；凭据缺失即报错，兜底改 `--engine edge`）。`doubao` 引擎内部按凭据自动路由两套接口，互不干扰：
- 配了 `VOLC_TTS_API_KEY`（新版单一凭据，**优先**）→ 走 V3 单向流式接口，默认音色「温柔淑女 2.0」`zh_female_wenroushunv_uranus_bigtts`。
- **克隆音色（火山「声音复刻」）**：默认音色（`VOLC_TTS_VOICE` / `--voice`）填成 `S_` 开头的克隆音色 id（如 `S_moiqVFN72`）→ 旁白自动用你克隆的专属声音，走 `seed-icl-2.0`（同端点换 resource-id + 带 `X-Api-App-Id` 头），**纯人声、全片一致**。此时**必须**同时配 `VOLC_TTS_APPID`（作 `X-Api-App-Id`），缺失直接报错不静默。没填 S_ 音色则用上面的默认音色，行为不变。
- 未配 API Key 但配了 `VOLC_TTS_APPID` + `VOLC_TTS_ACCESS_TOKEN`（旧版双凭据）→ 走 V1 接口（官方已标"不推荐"，仅向后兼容），默认音色「温柔淑女」`zh_female_wenroushunv_mars_bigtts`。
- ⚠️ V3 只认 2.0 系音色（`*_uranus_bigtts`），V1 的音色名（`*_mars_bigtts`/`*_moon_bigtts`）在 V3 下不可用——两套接口的 `--voice` 不能混用，按当前生效的凭据选对应版本的音色名。

- **逐句时间轴 `--timed`（字幕真同步，必开）**：不开时字幕只能按字数比例**估算**时长，与真实语速错位（实测明显不同步）。`--timed` 把旁白按句切、每句单独合成、**ffprobe 实测时长**后拼接，并写 sidecar `{out}.cues.json`。compose 检测到 cues 就让字幕严格按每句实测时长走——旁白讲到哪、字幕走到哪。长句（只有结尾一个句号的整段）会在句内按逗号再细分成多条字幕滚动，不会一条久挂。
- **豆包音色（以下是 V1/旧版凭据下生效的音色，实测已开通，cluster=`volcano_tts`）**：音色主观，新项目建议合成几个候选让用户试听选定；`--voice` 指定、`--speed` 调语速 0.8–2.0。走 V3（配了 `VOLC_TTS_API_KEY`）时默认音色是 2.0 系的 `zh_female_wenroushunv_uranus_bigtts`（见上「双引擎」节），下列音色名仅对 V1 有效：
  - `zh_female_wenroushunv_mars_bigtts` 温柔淑女（**V1 默认**·成熟温柔知性，心理科普首选）
  - `zh_female_qingxinnvsheng_mars_bigtts` 清新女声（清新偏年轻）
  - `zh_female_meilinvyou_moon_bigtts` 魅力女友（偏柔偏慢偏嗲）
  - `zh_female_shuangkuaisisi_moon_bigtts` 爽快思思（明快活泼）
  - 经典 BV 系列(BV001/BV700)未授权会报 `code=3001 resource not granted`。edge 引擎：`zh-CN-XiaoxiaoNeural`(温柔女)/`zh-CN-YunxiNeural`(沉稳男)，语速 `--rate "-10%"`。
- **连贯关键（旁白驱动 duration）**：先出旁白、由第 4 步把每镜 `duration` 定为旁白时长+0.3s（clamp 4–15s），画面与旁白等长正常速度，最连贯。兜底：画面短于旁白时 compose 匀速放慢填满（不卡顿），旁白绝不被截。⚠️ 换音色会变语速→旁白时长变→**必须重跑第 3–4 步**（温柔淑女较慢，多镜会触发兜底放慢，可接受）。
- **背景音乐（轻音乐·自动生成）**：`gen_bgm.py` 算法合成舒缓钢琴/竖琴拨弦琶音轻音乐（和弦进行+ADSR包络+混响+低通+头尾淡入淡出），零版权零等待，比手搓正弦 pad 有旋律有层次。也可自备无版权音乐（Pixabay/Suno），放 `<workdir>/bgm.mp3` 即被 build_manifest 拾取。
- **BGM 响度自动相对化（别用固定系数）**：合成时实测旁白与 BGM 的响度、把 BGM 压到比旁白低 `bgm_gap_db`（默认 12dB）。实测教训：自合成 pad 用固定 `volume=0.16` 会被**完全淹没**（mean −54dB），真实音乐又可能盖过旁白——相对响度才稳。`amix` 内部已加 `normalize=0`，否则旁白会被压低 ~6dB。

---

## 合成细节（manifest 契约，第 8–9 步背后）

`build_manifest.py` 自动产出的 manifest 形如：

```json
{
  "output": "<workdir>/final.mp4",
  "resolution": "720x1280",
  "ai_label": "AI 生成",
  "bgm": "<workdir>/bgm.mp3",
  "segments": [
    {"video": "<workdir>/shot-01.mp4", "narration": "<workdir>/narr-01.mp3",
     "cues": "<workdir>/narr-01.mp3.cues.json", "narration_text": "…", "subtitle": "…", "duration": 9.7}
  ]
}
```

- **字幕优先级**：`cues`（真同步）> `narration_text`（按句估算）> `subtitle`（固定整段）。
- 可选全局字段：`fps`（默认 30）、`bgm_gap_db`（默认 12，越大 BGM 越轻）、`bgm_volume`（仅响度探测失败时的回退系数）。
- 合成层自动：统一分辨率/帧率 → 烧中文字幕（Noto Sans CJK SC，白字黑描边底部居中；有 cues 则按 TTS 实测时间轴逐句真同步）→ TTS 旁白 + BGM 混音（**画面与旁白等长**：画面短则匀速放慢填满、不卡顿，旁白绝不被截；**BGM 自动相对响度**）→ h264/aac/+faststart。
- **AI 角标**：`compose_video.py` 自身默认 `ai_label=""`（不叠）；但 **driver 产线经 build_manifest 默认写入「AI 生成」角标**。要关闭须手动改 manifest.json——投放合规见终审清单。
- 手动微调（如覆盖输出路径）：`python3 {SKILL_DIR}/scripts/compose_video.py --manifest <m> --output <o>`。

---

## 投放前人工终审（合规清单，逐条过）

YMYL（健康）内容，**只做白帽，绝不编造**。对抗审查 PASS 后、投放前仍逐条人工核：
- [ ] **AI 生成标识**：driver 产线成片默认带「AI 生成」角标（build_manifest 默认值）。⚠️《AI 生成合成内容标识办法》要求显式标识——若手拼 manifest 关闭了角标，投放前自行评估补 `ai_label` 或依赖平台自动打标 / 隐式元数据。
- [ ] 旁白/字幕**不下诊断、不承诺疗效**（「缓解/陪伴/支持」可，「治愈/根治」不可）。
- [ ] 内容**忠于原文、无编造**数据/引语。
- [ ] 画面无诡异/恐怖谷/西化失真；无图内乱码文字；人物得体。
- [ ] 危机相关选题带求助提示（如适用）。
- [ ] 字幕断行通顺、读音正确、无错别字。
- [ ] 音画同步、无黑帧/断音；时长适配平台。

> ⚠️ 商用授权：即梦会员「生成内容可商用」无清晰明示条款，正式商用投放前请让用户**法务核对最新会员协议**，尤其虚拟人肖像 + 心理健康内容。

---

## （可选）回写 blog_posts.video_url / 投放

NBDpsy 官网博客已有 `blog_posts` 表与站内图片上传基建。把成片当作博客视频时，最小集成：给 `blog_posts` 加 `video_url` 列 + 详情页 `<video>` 播放器 + 复用已有上传接口。这部分是独立的代码改动，按需另开任务，**不属于本 skill 的生成产线**。或直接把 MP4 投视频号/抖音/B站。

---

## 衔接 nbdpsy-xiaohongshu-creator（每篇笔记 → 短视频）

承接 `nbdpsy-xiaohongshu-creator` 的产出（每篇笔记 = ~300 字正文 + 6–9 页轮播，每页有「页面文字」+「中文绘图提示词」+ 笔记内的 `## 视频参考图提示词` 节），给选定笔记生成竖屏短视频。**先让用户选哪几篇做**（每条烧积分，别盲目全做）。

**每页 → 一个分镜**（parse_note 自动完成骨架，精修见十步流程第 2 步）：
- **旁白(narration_text)** = 该页页面文字，改写成口语化解说（共情、不堆术语、忠于原文不编造）。
- **字幕** = 有旁白+cues 时逐句真同步；`subtitle`（该页大标题/核心句）只是兜底。
- **画面** 两种模式让用户选：
  - **模式 A · 文生（默认/全自动）**：把该页「中文绘图提示词」**改写成 Seedance 文生 prompt**——去掉"图中显示的中文文字"（图内 no-text，文字全走字幕）、保留场景/主体/风格、补运镜与电影质感（"镜头缓慢推近、柔光、真实质感、画面安静无对白"）、东亚人物治愈氛围。→ `operation=text2video`、`ratio=9:16`。
  - **模式 B · 图生（更可控/与图文一致）**：参考图来自笔记的 **`## 视频参考图提示词`** 节产出的**去文字版图**——若笔记出图环节已产出，第 1 步 `--images-dir` 直接指向该目录；若还没有，留到第 2.5 步的分镜确认页收图：有图像生成能力的宿主（如 Codex）按 `image_prompt` 自动逐页生成，没有的宿主（如 Claude Code）由运营在确认页复制提示词、人工出图后回传，与出图环节同一套宿主自适应逻辑，两种情况都放进 `<workdir>/images/`（命名 `P01.png…PNN.png`）并跑 `--attach-images` 写回。每页图当首帧 `image2video`，prompt 只写运镜。画面与小红书图文人物/风格一致、连贯度最高；画幅由图推断（小红书图常 3:4）。

**图生实战经验（CPTSD 第 1 篇端到端跑通）**：
- **必须用去文字版图**：小红书发布图带大标题/信息卡文字，视频文字全走逐句字幕——直接拿发布图做首帧，图内文字会与烧录字幕打架。去文字版 = 同人物同基底、剔除全部图内文字指令（这正是 `## 视频参考图提示词` 节存在的原因）。
- **信息卡页补画面 + 相关性取舍**：纯文字信息卡页（如 P2/P3）没画面主体，image2video 补 contextual 画面（雨窗/抱膝/城市灯火等情绪隐喻）。抽象科普概念（"占4%""三组困难"）靠**逐句字幕**承载相关性，画面只做情绪烘托——写意治愈风的固有取舍；要画面强相关得改"信息图解"形态（另一种视频）。
- **image2video 画幅**：3:4 图 → 输出 834×1112（720p 档），画幅由图推断，prompt 只写运镜+微动作（无对白、画面无文字）。
- 提速与卡死处理、逐句字幕同步机制见十步流程与「生成细节」节。

**端到端** = 十步流程本身：选笔记 → parse_note → 精修 → 豆包 `--timed` 出旁白 → sync_durations 定 duration → submit/fetch 出画面 → build_manifest → compose → 对抗审查 → 人工终审。每篇一条，可投视频号·抖音，与小红书图文双投放。

---

## 进阶 · 接入 OpenMontage（可选，重）

如果将来上完整 agentic 产线（OpenMontage 的分镜导演/质量闸门/Remotion 精细动效），`{SKILL_DIR}/assets/seedance_jimeng.py` 是一个**让 OpenMontage 的 Seedance 槽位改吃即梦会员积分**的 provider（`provider="seedance_jimeng"`、`cost_usd=0`、`quality_score=0.95`、`fallback_tools` 降级到 fal/replicate 版）。部署：把它放进 OpenMontage 的 `tools/video/` 即被自动注册。**但 OpenMontage 依赖重（Python+Node+Remotion headless Chromium）、AGPLv3 建议锁 commit**——与"丝滑"相悖，仅在确有需求时启用。本 skill 主线（dreamina + ffmpeg）不依赖它。

## 红线汇总

- 图内 no-text（CJK 必乱码，文字全走 ffmpeg 字幕）。
- 每条必经对抗审查 + 人工终审；不下诊断、不承诺疗效、不编造。
- AI 生成标识：driver 产线默认带「AI 生成」角标（build_manifest 默认值）；⚠️ 合规上《标识办法》要求显式标识，关闭角标前自行评估或靠平台打标。
- 第 4 步 sync_durations 不可跳过；改旁白/换音色必须重跑 3–4。
- 排队长 → `--submit-only` 错峰灌队列；submit_id 保留不重复扣分；卡 querying 重提新 id 并行抢。
- 生成只在开发机/专用机跑，**绝不部署到生产服务器**（抢资源 + 凭据安全）。
- Seedance CLI 仅 720p；要更高分辨率需另寻（非本产线）。
