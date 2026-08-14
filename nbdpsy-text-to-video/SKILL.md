---
name: nbdpsy-text-to-video
description: >-
  把一段文本 / 一篇官网博客长文 / 一个心理科普主题，丝滑地转成一条带中文字幕的竖屏短视频，
  用字节官方即梦(Dreamina) Seedance 系列（默认 seedance2.5）生成画面——主路走 nbdpsy-server 的即梦
  REST 面（运营零安装零登录），server 不可用时回落本机 dreamina CLI；纯 ffmpeg 合成（零 Remotion 依赖）。
  agent 全程自检依赖、缺啥自动装、再跑生成与合成任务。只要用户提到「文本转视频 / 文章转视频 /
  博客转视频 / 把这篇长文做成视频 / 做个科普短视频 / 出条视频号(抖音/B站)视频 / 用即梦/Seedance 生成视频 /
  把文章做成视频」，或给一篇小红书笔记+参考图要求直接出片，即使没说「skill」字样也应使用本 skill。
  主要服务 NBDpsy 心理科普（绑定其合规红线与品牌美学），但文本输入通用。它产出 MP4 文件；
  可选把成片回写到 blog_posts.video_url。
---

# 文本转视频（即梦 Seedance + ffmpeg，默认 seedance2.5）

把文本/长文/小红书笔记 → 一条**带中文字幕的竖屏短视频**。画面用字节官方**即梦 Seedance 系列**（默认 `seedance2.5`，消耗你已购的会员积分，现金边际≈0）——**主路走 nbdpsy-server 的即梦 REST 面**（零安装零登录、排队不用挂会话），server 不可用自动回落本机 dreamina CLI；合成用**纯 ffmpeg**（中文字幕烧录 + AI 生成合规角标），全程零 Remotion/Node 依赖。

**一句话心智**：这是「**你当导演、脚本跑腿、每条人工终审**」的半自动产线，不是一键批量出片机。质量取决于分镜脚本的用心 + 中文打磨，不是堆钱。

**三种内容形态**（2026-08-07 命名定案两种＋2026-08-11 新增一种）：
- **「笔记微电影」**——小红书笔记短内容 → 电影化动画短片（1–3 分钟，几秒一个分镜，
  Seedance 画面 + 口播旁白 + 分页字幕 + 品牌收尾）。本文十步产线就是它；创作方法论见
  `references/cinematic-direction.md`，旁白逐字稿规范见 `references/narration-spec.md`。
- **「长文播客」**——长文 → 一男一女对谈播客视频（声音+字幕为主，HTML 播放器画面录屏，
  黑底大字幕+波形+栏目名）。规格见 `references/podcast-video-spec.md`。
- **「字卡短片」**（2026-08-11 老板验收入库）——笔记文案 → 口播驱动的 GSAP 动效字卡竖版短片
  （30–40 秒，逐帧渲染帧级音画同步，四个版式模板：basic 品牌动效/camera 电影运镜/collage 手作拼贴/
  kinetic 动力学文字）。**边际成本 ≈¥0.2/条、改字 1 分钟重出**，三形态里量产成本最低。
  规格与工程坑清单见 `references/card-video-spec.md`，模板在 `assets/card-templates/`，
  渲染 `scripts/render_card.py`（默认 CPU 光栅与存量批次像素一致；⚠️ GPU 会改像素，显式
  `--angle vulkan` 且开了就整批开），赶时间用 `scripts/render_sharded.sh <tpl> <out> 4`
  分片并行（**分片零像素变化，是提速主路**，camera 类默认 CPU 路径实测 131s→33s），kinetic 词级卡点
  须先跑 `scripts/extract_word_timings.py`。
  ⚠️ 依赖本 skill 2026-08-11 后的 `tts_gen --timed`（wav 域拼接修复版）——旧版 cues 有累积漂移必不同步。

**路径约定**：以下命令中 `{SKILL_DIR}` 指本文件（SKILL.md）所在目录；`{workspace}` 指内容工作区根目录，用 `python3 {SKILL_DIR}/scripts/nbdpsy_common.py workspace` 查询实际路径。

多步任务先维护一份中文任务清单，每步做完勾掉。

## 关键事实（已实测验证）

- 即梦 CLI 是**字节官方**工具（`dreamina`），走会员积分（`dreamina user_credit` 可查）。
- **本产线统一出 720p**（`--video_resolution` 必填且逐档校验，各档支持的分辨率并不一致，720p 是唯一对全家族都合法的一档）；单段 `duration` 取整数秒，**`seedance2.5` 4–30s、其余模型 4–15s**；`image2video` 画幅由输入图推断（不接受 `--ratio`），`text2video`/`multimodal2video` 可设 `--ratio`（1:1 / 3:4 / 4:3 / 9:16 / 16:9 / 21:9）。
- 生成**异步、排队可能数小时**（会员单账号串行）。→ 大批量用「`--submit-only` 先灌队列、并行 `fetch` 取回」，submit_id 不丢、不重复扣分。
- `{SKILL_DIR}/scripts/` 下所有脚本输出统一 **stdout=JSON / stderr=进度**，便于解析。
- **多图参考已可用**（2026-08-06 起）：`multimodal2video` 传 `images[]`，2.5 最多 30 张、
  2.0 家族 9 张，**顺序即语义**（数组第 N 张 = 提示词里的 `@图片N`，脚本与服务端都保序不去重）。
- **要做「有电影感」的片子，先读 `references/cinematic-direction.md`**——那是本 skill 的
  创作方法论（分镜四件套、反套话词表、1–3 分钟分段策略、对抗审查清单）。脚本只管执行，
  片子好不好看取决于那份文档里的判断。

---

## 第 0 步 · 环境自检（自检自装，`ready=true` 才开跑）

```bash
python3 {SKILL_DIR}/scripts/check_env.py            # 只检测
python3 {SKILL_DIR}/scripts/check_env.py --install  # 缺啥自动装(dreamina 用 curl；系统包给 sudo 命令)
```

读 stdout 的 `{"ready": true/false, "checks":[...]}`：
- **即梦后端自动探测**：本机有 `NBDPSY_XHS_API_KEY`（与小红书自动发布同一把）且 server 已上线即梦能力（`GET /api/dreamina-status` 回 `logged_in=true`）→ 画面生成走 **nbdpsy-server**，运营**免装 dreamina CLI、免扫码**（登录态与积分在 server 一份，管理员维护）。此时自检里 `dreamina CLI` / `dreamina 登录 & 积分` 两条换成一条 `即梦服务(server)`，下面两条不适用。探测不通（没凭据 / server 未上线该能力 / 网络不通）自动回落本机 CLI，下面两条照旧。
- `dreamina CLI` 缺 → 自动 `curl -fsSL https://jimeng.jianying.com/cli | bash`。
- `dreamina 登录 & 积分` 失败 → **CLI a857341 起登录改为 OAuth Device Flow**：agent 直接跑 `python3 {SKILL_DIR}/scripts/dreamina_login.py`（后台跑，把 stderr 里的 `verification_uri` 网址开给/发给用户）。**任何设备打开授权都行**（不再有旧版 127.0.0.1 回调「必须本机打开」的限制），用户抖音 App 扫码/确认即可；授权码约 10 分钟过期，过期就重跑一次脚本拿新码。脚本等 CLI 退出后会用 `user_credit` 复核，stdout 出 `{"success":true,"total_credit":…,"vip_level":…}`。新凭据在 `~/.local/share/dreamina/`。积分偏低会给警告。
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
| 即梦登录 | `~/.local/share/dreamina/`（本地，CLI a857341 起；旧版在 `~/.dreamina_cli/`）| **server 模式下本机不需要登录**——管理员在 server 侧配好公司号登录态后，运营只要有 `NBDPSY_XHS_API_KEY` 就零登录零安装（见第 0 步「即梦后端自动探测」）。回落本机 CLI 时才需要：agent 后台跑 `python3 {SKILL_DIR}/scripts/dreamina_login.py`，把 stderr 里的 `verification_uri` 开给用户，**任何设备**抖音 App 扫码授权即可（Device Flow，码约 10 分钟过期）；agent 不经手凭据本体，即梦登录无法进凭据配置包 |
| 首模型合规授权 | Dreamina 网页端 | 报 `AigcComplianceConfirmationRequired` 时引导用户去网页端一次性授权 |
| sudo（装 ffmpeg/字体，如需）| 不留存 | 需要时即时问用户密码，用完不写进任何文件/日志 |

> 豆包凭据也可由管理后台「博客 → API Keys → 生成凭据配置包」统一下发（工作室已集中配置时，包里会自动带上 `VOLC_TTS_*`，含新版 `VOLC_TTS_API_KEY`）；即梦登录仍需本机扫码，无法进包。

配好后 `python3 {SKILL_DIR}/scripts/check_env.py` 复检到全绿再开跑。用户想撤销时，删 `.env` 对应行 / `~/.local/share/dreamina/`（旧版 CLI 是 `~/.dreamina_cli/`）即可。

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

> 🎬 **动笔前先读 `references/cinematic-direction.md`**（电影感方法论，1–3 分钟片的完整框架）。
> 三条最要紧的：**①「电影感」这个词本身不能写进提示词**，要写造成它的物理原因（景别+运镜+
> 光源+色调）；**② 分镜按四件套写**——景别 / 构图 / 运镜手法 / 画面内容，每行只回答一个问题，
> 别混成一句话；**③ 每个 beat 至少一次景别跳跃**，且要有一个「可见的抑制动作」
> （攥紧、话到嘴边咽回去）——那是全片最值钱的一格。

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

**4.5 动态分镜 animatic（电影化必做，零积分的彩排）**

在花任何积分之前，用已有素材免费验证全片节奏——这是真实片场的 previz 环节：

```bash
# 分镜参考图 + 已出的旁白 mp3，ffmpeg 拼一条「静态动画版」（每图配该 beat 旁白时长）
python3 {SKILL_DIR}/scripts/build_manifest.py --workdir <workdir> --stills images/
python3 {SKILL_DIR}/scripts/compose_video.py --manifest <workdir>/manifest.json --output animatic.mp4
# （--stills 未实现时手工：ffmpeg loop 每张图 narr 时长 → concat → 加旁白轨）
```

**看什么**：旁白配上画面后节奏累不累、哪个 beat 拖、钩子前 3 秒立不立得住、收尾留白够不够。
**改分镜/旁白在这一步改**——animatic 上改是免费的，生成后改是烧钱的。运营/老板终审节奏也看它。

**5. 提交生成**

**电影化（v3，默认）**：segments 整段提交，模型在段内自己切镜：

```bash
python3 {SKILL_DIR}/scripts/jimeng_gen.py batch --plan <workdir>/shots.json \
  --out-dir <workdir> --submit-only > <workdir>/submit_ids.json
# v3 的 batch 自动按段展开；结果 results[].target_name 是 segment-NN.mp4
# ⚠️ 提交前第 4 步的 sync_durations 必须 ok=true（它校验每段 gen ≥ 旁白总长——
#    gen 不够意味着生成出来不够切，钱白花）
```

**快版（v1 单层 shots）**：

```bash
python3 {SKILL_DIR}/scripts/jimeng_gen.py batch --plan <workdir>/shots.json \
  --out-dir <workdir> --submit-only > <workdir>/submit_ids.json
```

- **保存 stdout JSON 到 `<workdir>/submit_ids.json`**：`results[].submit_id` 是取片凭证与防重复扣分的关键（注意 `results[].index` 是 0 起，shots.json 的 `index` 是 1 起，映射时 +1）。submit_id 保留不重复提交，即使超时也可后续再 fetch 补取。
- 新题材首次跑建议先 `gen` 试水 1 镜确认观感+实测排队，再放量（见「生成细节」节）。

**6. 取片 + 切段**

**电影化（v3）**：取回段片后按旁白边界切成 shot-NN.mp4（build_manifest 消费的老契约）：

```bash
python3 {SKILL_DIR}/scripts/jimeng_gen.py fetch --submit-id <id> --out-dir <workdir>
mv <取回的文件> <workdir>/segment-01.mp4        # 按 results[].target_name 改名
python3 {SKILL_DIR}/scripts/cut_assemble.py --workdir <workdir>   # 切出 shot-NN.mp4
# 关键镜（钩子段/收尾段）建议多条选优：同段再提交 1–2 次（换 client_ref），谁好用谁
```

**快版（v1）**：

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

### 故事化演绎输入（一句话选题种子 → 虚构故事微电影）

用户只给一个**科普点/话题/新闻/观点/标题**，要「编个故事演出来」「做成有悬念的微电影」时，
走 **`references/screenwriting-spec.md`**（微电影编剧规格）：种子受理 → 论据查证定稿 →
What-If/How-to-Tell 双路概念 → 结构选型 → 剧本 → 内部自检硬闸，产出 `script.md` +
`shots.json` 骨架接产线第 2 步。**双层结构铁律：论据是真的（可查证出处），故事是编的
（必须有"演绎创作"标注），两层观众必须分得清**——细则以该规格 §1 为最高优先级。

---

## 分镜与旁白写作要点（第 2 步的知识库）

三档形态，按用户要求选（默认电影化）：

- **电影化**（现行默认，1–3 分钟）：按 `references/cinematic-direction.md` 走——beat（旁白单元）
  × 每 beat 2–3 镜，60s 约 20 镜上下；分段生成（30s/段，一段 4–5 镜官方密度）。
- **故事化演绎**（用户要「编故事/有悬念/微电影感」或只给一句话种子时）：先走
  `references/screenwriting-spec.md` 出剧本与 shots.json 骨架（含双层合规硬闸），再按电影化档执行。
- **快版**（用户明说「简单出一条/别太讲究」时）：把文本浓缩成 **6–12 个分镜**单层结构。

心理科普推荐叙事骨架（两档通用）：

1. **开场钩子（1 镜，5s）**：一句戳中痛点的提问/场景，配情绪空镜。
2. **核心概念（2–4 镜）**：把抽象概念可视化（空镜/隐喻画面 + 字幕讲清）。
3. **方法/步骤（2–4 镜）**：可操作的 1-2-3，每镜一个要点。
4. **收尾 CTA（1 镜）**：温柔收束 + 引导（关注/预约咨询，**不得承诺疗效**）。

### Seedance prompt 写作（完整方法论见 `references/cinematic-direction.md`，**以它为准**）

⛔ 旧的一句话混写公式（主体+动作+镜头+光线+氛围）**已废弃**——那是单镜短片时代的写法。
现行写法两层：**外层官方四段式**（【素材描述】+【一句话概述】+【具体情节描述】+【全局补充】），
**内层分镜五行**（景别 / 构图 / 运镜手法 / 画面内容 / 潜台词）。时间戳、转场咒语、
人物八维、禁止项的写法全在方法论文档里，写 prompt 前先读它。

**四条本 skill 特有的铁律**（方法论之外的本地约束，仍然有效）：
- **图内绝不要中文/任何文字**（Seedance 渲染 CJK 必乱码）。所有文字一律走 ffmpeg 字幕叠加，
  prompt 的【全局补充】必带「画面中无任何文字」（唯一例外：片尾金句可试模型直出，见方法论）。
- 出现人物时指定**东亚面孔、自然真实**；心理内容优先用**空镜/隐喻/背影/手部特写**，
  规避真人肖像与审核风险。
- 美学统一：温暖、柔光、低饱和、治愈感，贴合 NBDpsy 品牌。
  ⚠️ **色板怎么来，如实说**：`kind=video` 的风格档案体系**还没落地**（P3 排期：server 侧 `style_profile`
  的 KINDS 只有图文/文字版两个取值，视频产线也没有任何一行脚本去读它）。所以现阶段
  **色板由创作者按该运营的「图文那套」档案手工继承**——`--get` 读出 `visual.palette` / `visual.texture`
  的实际取值，逐字抄进提示词。⛔ 别写成"色板走运营风格档案"这种自动继承的口气：
  那是假绿，没有任何代码路径会去读它，写了也没人执行。
- 品牌 logo：片头/收尾/水印一律用 `assets/brand/` 内置矢量 SVG（六变体与用法见 `assets/brand/brand-logo.md`），深底用 reversed 或渐变金徽记，禁止再用位图 logo 抠图。
- 多镜人物一致性：**2–3 张独立单视图**分别作 `@图片1/2/3` 传（⛔ 不做单图三视图拼版，
  官方裁决：多图多视图 > 单图多视图）+ 提示词强身份锁。

### 旁白与字幕文案

**逐字稿规范（写稿六律 / DeepSeek 三轮本土化审校 / TTS 引语坑 / 表演标记纪律）见
`references/narration-spec.md`——口播稿定稿前必须走完该文档的审校流程。**
**屏显文字排版铁律（2026-08-13 老板令，全形态）见同文档 §七**：逗号=换行、句号/问号/
省略号=翻页、每句独立成页禁多句连排；任何文字渲染路径必须过同一排版规则。
口语化、共情、**忠于原文不编造**；不下诊断、不承诺疗效。`subtitle` 是无旁白镜的兜底固定字幕（每镜 1–2 行、每行 ≤ ~16 字）；有旁白+cues 时字幕逐句真同步、无需手写。shots.json 里的 `narration_text`/`subtitle` 由 TTS 与合成清单消费，`jimeng_gen` 生成画面时会忽略它们（只吃 operation/prompt/duration/ratio/model/image）。

---

## 生成细节与实测经验（第 5–6 步引用）

```bash
# 查余额
python3 {SKILL_DIR}/scripts/jimeng_gen.py credits

# 新题材先试水 1 镜，确认观感 + 实测排队时长（关键决策变量！）
python3 {SKILL_DIR}/scripts/jimeng_gen.py gen --operation text2video \
  --prompt "温暖咨询室空镜，晨光移过沙发，镜头极慢推近，画面中无任何文字" \
  --duration 5 --ratio 9:16 --model seedance2.5 --out-dir <workdir>
```

- **后端参数（所有子命令通用）**：`--backend server|local|auto`（默认 `auto`，规则见第 0 步；环境变量 `NBDPSY_JIMENG_BACKEND` 可改默认，显式 `--backend` 优先）、`--api-base URL`（server 基址，默认 `NBDPSY_VIDEO_API_BASE` 或 `https://mcp.nbdpsy.com`）。输出 JSON 多一个 `backend` 键表明这次实际走了哪条；**服务化之前的字段两个后端一个不少**（`success`/`submit_id`/`status`/`videos`/`credit_count`/`meta`/`raw`/`error`），server 侧另附 `client_ref`/`video_url`/`expires_at`/`batch_id`/`low_threshold_hit` 等新键，老解析忽略即可。server 模式下 `--image` 收**图床直链、`/uploads` 路径或本机路径**——本机路径会自动先传 server 图床（`POST /api/uploads/images`）换成直链再提交，stderr 打一行 `[upload] P01.png → …`；只有上传失败（文件不存在 / 非 png·jpg·webp / 两次网络异常）才整镜回落本地 CLI 并说明原因。多图或带 `--video`/`--audio` 的镜 server 单镜契约表达不了，照旧整镜回落。
- 模型可选：`seedance2.5`（**默认**）/ `seedance2.0` / `seedance2.0fast` / `seedance2.0_vip` / `seedance2.0fast_vip` / `seedance2.0mini`。**`seedance2.5` 是新一代，没有 fast / vip 变体，是 VIP-only**，时长 4–30s（其余模型 4–15s，超了当场被拦、不会白跑一趟提交）。⚠️ **2.5 首次使用可能需要先到即梦网页端手动生成一次**做账号级合规授权（否则回 `AigcComplianceConfirmationRequired`）——那是要人去点的一次性动作，脚本重试无意义。
- **积分 & 排队（实测，重要）**：**`seedance2.5` = 26 积分/秒，按秒线性计价、不是按 5 秒档取整**
  （server 三次独立实测：4s=104 是决定性证据——块状公式会算 130；5s=130、10s=260），秒级出片无排队。
  普通 `fast` 25/5s 但排队极长（队列可 15 小时+）；`fast_vip` 55/5s ~3 分钟出片（两档仅 5s 单点实测，
  非 5 倍数时长属外推）。扣费 success 才结算；`estimated_credits` 是预估、**实扣一律以 `credit_count`
  为准**；`frames2video` 价格从未实测——**首条真任务跑完必对一次 credit_count**。
  → 默认 2.5 = 质量+速度换约 5 倍于 fast 的积分；预算敏感批量用 `fast_vip` 或夜间 `fast` 错峰。
- **失败/超时保留 submit_id，绝不重复提交扣分**；排队中任务无法取消（dreamina 无 cancel）。
- **并行生产（关键提速）**：`batch` 不带 `--submit-only` 时是**串行** submit+fetch（等一镜下完才提交下一镜）很慢。正解 = 十步流程的 5–6 步：**先全部 `--submit-only` 灌队列、再并行 fetch**，即梦后端同时排队渲染，墙钟≈最慢单镜而非 N 镜相加。
- **卡 querying 重提**：个别任务卡 `querying` 数小时 → 重新提交拿新 submit_id（走 VIP）、新旧并行谁先渲染好用谁（旧积分已沉没，不因等待翻倍损失时间）。
- 生成端 `duration` 取整数秒；与旁白的零点几秒差值由合成层匀速兜底，无感。
- `gen`/`fetch` 返回 `{"success":true, "videos":[...], "credit_count":N}`，`videos` 是已下载的真实路径。

---

## 旁白与 BGM 细节（第 3、7 步引用）

**三引擎**：`edge`（免费无 key，兜底）/ `doubao`（火山豆包）/ `minimax`（**口播默认**，
2026-08-07 起）。**minimax** 走 MiniMax 同步 T2A（`speech-2.8-hd`，凭据 `MINIMAX_API_KEY`，
现役音色「温暖闺蜜」`Chinese (Mandarin)_Warm_Bestie`）——独有秒级停顿 `<#x#>` 与 19 个语气词
标签（`(sighs)` 等，不会被念出来），是表演控制最强的一档；**引语坑与选型对照表见
`references/narration-spec.md` 第三节**。`doubao` 保留（有老板克隆音色 S_），按凭据自动路由两套接口，互不干扰：
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
- [ ] 内容**忠于原文、无编造**数据/引语。**故事化演绎片改核双层**：①论据出处可回溯
  （查 `video.source_text` 对定稿卡）；②「演绎创作」标注已生效（成片右上角角标目视确认，
  且收尾旁白带"故事是编的"消歧句——声明只写 subtitle 会静默不渲染，见 screenwriting-spec §1.4）。
- [ ] 画面无诡异/恐怖谷/西化失真；无图内乱码文字；人物得体。
- [ ] 危机相关选题带求助提示（如适用）。
- [ ] 字幕断行通顺、读音正确、无错别字。
- [ ] 音画同步、无黑帧/断音；时长适配平台。

> ⚠️ 商用授权：即梦会员「生成内容可商用」无清晰明示条款，正式商用投放前请让用户**法务核对最新会员协议**，尤其虚拟人肖像 + 心理健康内容。

---

## （可选）回写 blog_posts.video_url / 投放

NBDpsy 官网博客已有 `blog_posts` 表与站内图片上传基建。把成片当作博客视频时，最小集成：给 `blog_posts` 加 `video_url` 列 + 详情页 `<video>` 播放器 + 复用已有上传接口。这部分是独立的代码改动，按需另开任务，**不属于本 skill 的生成产线**。或直接把 MP4 投视频号/抖音/B站。

> **交付形态现状**：成片暂以**本地 MP4 文件**交付运营/老板审看——与小红书图文成图不同，视频目前**没有图床上传端点**（图床白名单只收图片扩展名）。"视频产物公网直链"能力已向 nbdpsy-server 侧提协同需求（见 NBDpsy 仓 `文档/2026-07-24-视频产物上传直链-协同请求.md`），落地后本步改为**上传得直链、把链接交付运营**，与图文成图上图床同一范式；在此之前流程逻辑不变（本地文件交付照旧）。

---

## 发视频号 / 小红书 / 公众号（成片投放，三家通用）

**三家都没有官方内容发布 API**——视频号是 2026-08-07 实调定案（服务号 token 调视频号接口回
`errcode 48001 api unauthorized`，连读粉丝数都不给）。**视频号 / 公众号只能人工发**，⛔ 不碰浏览器自动化
刷发布（账号是核心资产）。本 skill 对这两家能做到的上限是**出成品包 + 把该拦的在上传前拦住**：

> ⚠️ **小红书是例外**：我们自建的 nbdpsy-server 有一条 job 队列（在服务端跑，与运营本机、与 Chrome 插件无关），
> 视频笔记发布**必经** `nbdpsy-xiaohongshu-creator/scripts/publish_video.py`——见下面「小红书视频笔记发布」一节，
> 那一节是硬闸门，不是可选路径。

```bash
python3 {SKILL_DIR}/scripts/video_pack.py \
  --video <成片.mp4> --title "标题" --text 文案.txt --out {workspace}/videos/<slug>/投放包/ \
  --for-upload                  # 发布前推荐：短边升 1080 + 提码率
```

产出 `video.mp4` / `cover.jpg` / `标题.txt` / `文案.txt` / `上传清单.md`（含逐平台判定表）。
三平台**全部**可发才 exit 0；否则 exit 1，但清单里逐家给判定——**某家超限不代表另两家不能发**。

> ⛔ **`video_pack.py` 产出的 `cover.jpg` 不是投放封面。** 不传 `--cover` 时它是 `--cover-at`（默认 2.0s）
> 抽的一帧，只够内部预览/自查用。投放封面一律走下面「封面」一节的主流程③，
> 并把③的产物用 `--cover <③产出的封面.jpg>` 显式传进来。

### 小红书视频笔记发布（必经脚本层，⛔ 无 job 直调）

```bash
# 视频版的 publish_note.py 对等物；具体参数以 --help 为准（脚本由 nbdpsy-xiaohongshu-creator 维护）
python3 ~/.claude/skills/nbdpsy-xiaohongshu-creator/scripts/publish_video.py --help
```

它替你做四件手搓 payload 一定会漏的事：**落 job 行（台账先行）/ 拆 `topics` / 带 cover·合集·活动 /
按终态白名单（`published|failed|canceled`，⚠️ **一个 l**——与脚本里的 `TERMINAL_STATUSES` 逐字一致，写成两个 l 永远等不到终态）轮询**。

- ⛔ **手搓 payload 直调 `POST /api/publish-jobs` 是禁令。** job **337** 就是这么发的：`#标签` 只写在
  正文里是纯文本、不成话题实体，回执里 `"topics_requested": []`、`"topics_applied": []`——五个话题
  一个没挂上，而 job 状态是 `published`，**没有任何报错**（时间线与回执原文见
  `docs/2026-08-14-视频笔记发布事故实证-供skill重塑反例.md`）。图文走 `publish_note.py` 有
  `split_content_topics` 兜底，视频直调裸奔，没有这层保护。
- **台账先行**：job 行就是「我要发什么」的意图记录，先落库再执行。会话断了也能用
  `python3 ~/.claude/skills/nbdpsy-xiaohongshu-creator/scripts/publish_note.py --list-jobs`（或 `--job <id>`）
  续核——**回执核对以台账行为准，不靠记性**
  （事故第 3 条：补封面步骤随会话中断丢失，最后由老板人肉发现）。
- **提交后回读比对**：终态回执里读回 `topics_applied` / `applied.cover` / `note_url`，与意图清单逐项比。
  **差集非空 = 本批未完成**，把差集写成待办（如 `cam-2: cover=FAIL(需补) topics=OK`）落台账，
  ⛔ **差集非空不许报"发完了"**。
- **补封面与查欠账，就这两个命令**（都在 `publish_video.py` 上，⛔ 别再跳到 xhs SKILL 里翻）：

  ```bash
  # ① cover=FAIL 的唯一补救：发布后补封面（走弹窗结构，已真号验证可用），补到 applied.cover=true
  python3 ~/.claude/skills/nbdpsy-xiaohongshu-creator/scripts/publish_video.py --fix-cover --job <id> --cover <③产出的封面.jpg>
  # ② 接手/收尾第一件事：读台账欠账（exit 0=全闭环；3=还有未闭合项；4=台账压根不存在＝没有证据，不是绿）
  python3 ~/.claude/skills/nbdpsy-xiaohongshu-creator/scripts/publish_video.py --ledger-check [台账路径]
  ```

  ⚠️ `--fix-cover` 换封面**同样过闸门 A**（复用 `check_cover_receipt`），所以补的那张也得有产出凭证——
  ⛔ 别为了补而随手截一帧顶上。
- ⚠️ **视频正文与话题发布后改不了**（`content`/`title` 编辑被 server 以 422 拒："文本/图片编辑只对图文笔记验证过"）——
  **漏挂无补救通道：要么接受缺话题、要么删稿重发**（删稿重发的代价是换链接、数据清零）。
  ⛔ **别拿 `note_ops.py --set-components` 试**——试不出来，只会烧掉该号的会话额度（12 会话/号/时）。
  所以第一条发完必须先回读校验，再发第二条。
- `outcome=unknown` / 轮询超时 **绝不重发**（会重复发出去），用 `--job <id>` 复查到终态。
- 视频文件**不走图床**（图床白名单只收图片扩展名）：走服务器同机落盘路径，⛔ 别把大文件经隧道来回传。

### 封面（本 skill 不做，一律回主流程③）

**三形态（图文轮播 / 文字版 / 视频）共用同一道封面必经步**：`nbdpsy-xiaohongshu-creator` 主流程
第 **③ 步「封面」**，版式细则见其 `references/illustration-spec.md` §2-b。本 skill **没有自己的封面做法**，
`card-video-spec.md` / `cinematic-direction.md` / 本节都不许另起一套。

- **产出凭证是过闸判据**：③步出图后落 `cover-*.meta.json`（gen_images 回执的 job/session id + 提示词摘要），
  发布步逐张校验「有回执 **且** 回执提示词含本批风格档案的调色板/版式声明」，**无凭证一律拒发**。
- ⛔ **命名合规 ≠ 过闸**：自造的 HTML 也能渲出叫 `cover-01.jpg` 的文件，但它拿不出回执。
- ⛔ **抽帧/截帧不得作投放封面**——平台自动截的第 0 帧是「文字还没显出来的空白卡」，
  这正是 2026-08-14 老板发现「你居然都没有做封面！！！」的现场。
- 两次绕规范都留了痕，当反例读：`docs/2026-08-14-视频笔记发布事故实证-供skill重塑反例.md`（三条根因）
  + `seo-geo/content/video/koubo-ziwoguanhuai/cover/cover-notes.md`（hero 三问、副题要答"然后呢"、
  特殊人群的特殊安排不得放大成通用承诺——三轮打回逐条留痕）。
- 封面比例 **3:4 竖版**（1080×1440），与成片 9:16 不同是正常的（信息流按 3:4 展示）。

### 三平台限制（最紧的那条决定"一份文件通传"的天花板）

| | 视频号 | 小红书 | 公众号 |
|---|---|---|---|
| 时长 | 3 秒~8 小时 ⁽官⁾ | ≤15 分钟 | 2 秒~60 分钟 |
| 体积 | ≤2GB ⁽官⁾ | ≤10GB | **≤200MB** ← 最紧 |
| 其他 | **不支持 HDR**、h265 在 Chrome 传不上、宽高比 0.33~3.0 ⁽官⁾ | 建议 1080×1920 | 最高 1080p |

⁽官⁾＝已核到官方原文；其余官方页在登录墙后，取第三方一致口径中**最严**的一档。

**通吃编码**：MP4 + **H.264 High** + AAC + yuv420p + bt709(SDR) + faststart。
H.264 是唯一三家都稳的——h265 在视频号 Chrome 上传直接失败，别用。

### `--for-upload` 在解决什么（别讲错）

即梦素材原始 ~10Mbps，合成 CRF 20 后只剩 ~600kbps。肉眼直接看没问题（CRF 20 视觉近无损），
但**平台会二次压缩，低码率源在转码器手里更吃亏**。`--for-upload` 把短边升到 1080 并给足码率
（实测 720×1280 615kbps → 1080×1920 3063kbps，74 秒片子 27MB，离公众号 200MB 很远）。

⛔ **放大不会凭空长出细节**——即梦 Seedance 2.5 只出 480p/720p，源就是 720p，这是"假 1080p"。
值得做的理由是另两条：平台按 1080p 档转码、二次压缩更温和；手机端不必客户端拉伸。
**别把它当"变高清"卖给运营。**（想要原生高清需换 seedance2.0_vip，2026-08-08 运营定调：只用 2.5。）

### 合规扫词（命中即 exit 1，必须回源头改）

「包治/根治/彻底治愈/100%/保证有效」等绝对化用语 + 「加微信/私信我」等引导脱离平台。
心理科普踩第一条最容易，且是**账号级风险**。

### 上传前必须念给运营的两句

① **视频号文案发布后终生只能改一次、每次 ≤20 字**——粘贴前通读，一次到位；
② 逐条打**原创声明**（影响推荐权重与被引用能力）；③ 视频号行业类目**不要**选医疗健康相关。

> 账号现状：视频号「NBDpsy-严选咨询师」已认证并绑定同名服务号。公域推荐可观——
> 21 粉丝时单条播放 541~1039，远超服务号图文，这是这条线值得做的核心理由。

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
- **封面无旁路**：三形态共用 `nbdpsy-xiaohongshu-creator` 主流程第③步，凭证（`cover-*.meta.json`）在才准发；
  ⛔ 抽帧/截帧/自造 HTML 封面一律不算（2026-08-14 两次打回实证）。
- **发小红书必经 `publish_video.py`**（有 job 行 = 台账先行），⛔ 手搓 payload 直调 `POST /api/publish-jobs`；
  发完回读 `topics_applied`/`applied.cover` 比对意图，**差集非空不许报完成**。
