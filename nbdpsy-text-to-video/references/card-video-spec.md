# 字卡短片产线规格（第三内容形态 · 2026-08-11 老板验收入库）

> **定位**：口播驱动的 GSAP 动效字卡竖版短片。质感档位在「图拼视频」与「AI 动画短片」之间，
> **边际成本 ≈ ¥0.2/条（MiniMax 口播）+ 本地渲染 ¥0**，改一个字约 1 分钟重出全片。
> 首片《一个嗯字让你想了一晚上》36.5s，四版式一天内出齐并经老板逐版验收（含两轮返工：字符遮挡、音画不同步）。

## 产线五步

```
① 文案（8-10 句、含一个全片情绪焦点句）→
② tts_gen --engine minimax --timed 口播+cues（★必须 2026-08-11 后版本：wav 域拼接）→
③ （仅 kinetic 模板）extract_word_timings.py 拿 ASR 词级时间戳 →
④ 选版式模板（assets/card-templates/）改卡片文案 →
⑤ render_card.py <tpl.html> <out.mp4> 逐帧渲染+混音
```

## 四个版式模板（`assets/card-templates/`）

| 模板 | 概念 | 适用 | 已知代价 |
|---|---|---|---|
| **tpl-basic** | 品牌暖色+具象小动效（聊天气泡剧场/雷达扫描/下划线描画） | 默认；叙事场景类 | 最朴素 |
| **tpl-camera** | 一镜到底：八卡钉在大画布上摄像机运镜+景深换焦+电影遮幅 | 高级感/品牌片 | 渲染最慢（blur 负载，~4 min）；卡内断行手写、换字体会撑破 |
| **tpl-collage** | 心理手帐拼贴：纸片甩入/胶带/拍立得/印章「哐」盖章/信纸展开 | 温暖调性、贴手帐人群 | 码率最高（纸纹细节 ~18MB）；纸底色改动须同步印泥斑点色 |
| **tpl-kinetic** | 动力学文字：逐词砸屏/背景色情绪翻转/巨字滚屏/焦点句全片唯一红底 | 冲击力最强、观点型内容 | **必须走 ASR 词级卡点**（步骤③）；黑底强调块必须 inline-block 独立盒 |

模板=「可复制改造的参考实现」：**版式/动效层直接复用，内容层（各卡文案+强调词）按新笔记替换**。
换内容时守住各模板头部注释的硬契约（层级/字号收敛/安全区）。

## 渲染契约（每个模板必须满足，render_card.py 依赖）

- 画布 1080×1920，`html,body` 定死 overflow:hidden；
- 读 `const CUES = __CUES__;`（渲染器注入逐句 {text,start,end}）；kinetic 另读 `const WORDS = __WORDS__;`（无该占位的模板不受影响）；
- 主时间轴 `gsap.timeline({paused:true})`；暴露 `window.TOTAL` 与 `window.SEEK = t => tl.seek(t,false)`；
- **确定性**：⛔ Math.random/Date.now——一切"随机"用写死数组（重渲染必须逐帧一致）；
- 混音源优先 `narration.mp3.wav` sidecar（render_card.py 自动选）。

## 🩸 音画同步双层根因（2026-08-11 实战，全产线最重要的知识）

1. **mp3 逐段拼接漂移（全形态共性）**：每段拼接漂 ~46ms 随句数**累积**（8 句实测 0.41s，字卡越后越提前）。
   与播客线 2026-08-07 定性死路同因，tts_gen `--timed` 路径 2026-08-11 已根治：**wav/PCM 域按样本数拼接**，
   cues 按样本数构造，一次性编码输出（encoder delay 仅 ~43ms 且不累积），另出无损 `.wav` sidecar。
   **⛔ 检验法**：`ffprobe` 音频时长 vs cues 尾差 >0.1s ＝拼接路径有漂移，别用。
2. **词级卡点不能估算（kinetic 特有）**：句内按语速均匀分配＝必漂。正解＝faster-whisper 词级时间戳
   （`extract_word_timings.py`，三条坑见其文件头注释：wav 源/简体 prompt 不含正文/首字游标容错回退）。
   验证法：取一个关键词的 ASR 时刻抽帧，字应正在砸入瞬间。

## 工程坑清单（GSAP 逐帧渲染，全部实战踩过）

1. `gsap.fromTo` 一律 `immediateRender:false`——否则后段动画的 from 值提前渲染到开场（冲击环提前显形实例）；
2. 显隐 ⛔「CSS opacity:0 + tl.from({opacity:0})」——from 终值=当前 CSS 值=0 全程隐形；用 fromTo 显式终值或 tl.set；
3. **行内高亮块巨字必溢出**：`b { background:… }` 的 inline 背景盒跟不住大字号字形（笔画溢出块缘、两行咬合）——
   **必须 `display:inline-block` 独立盒**（padding 包字形+line-height 1.05+块间 margin）；
4. 绝对定位装饰层与文字分区布局，禁止重叠遮字；
5. 词组切换用 `duration:0` 的 fromTo 硬切（出场 to 与入场撞同帧时，普通补间在自身 start 渲染 progress 0 会出空帧）；
6. 渲染性能：多层 text-shadow/大面积 blur 拖慢逐帧截图（tpl-camera 251s vs tpl-kinetic 58s），量产优先轻负载模板；
   重负载模板走分片并行可把墙钟时间压回来（见下节「GPU 加速与分片渲染」）；
7. 双格式落盘防重（出图目录 png+jpg 同名会被发布脚本收两遍——publish_note 已去重，但落盘仍建议单格式）。

## GPU 加速与分片渲染

**提速主路是分片，不是 GPU。** 逐帧截图**默认 CPU 光栅**（SwiftShader）——与 2026-08-11 验收入库的
存量字卡片逐字节同一套参数（已实测校验：默认路径与改造前原始启动参数的 222 帧哈希同为
`0a5485a6…`）。GPU 要显式开，且**开了就整批开**（理由见纪律②）。

```bash
# 整片（默认 CPU，与存量批次像素一致）
python3 render_card.py tpl-basic.html out.mp4
# 分片并行：预清帧目录 → N 片并行 → 帧连续性校验 → 合帧混音，一条命令收口
bash render_sharded.sh tpl-camera.html out.mp4 4
# 逐字节可复现模式（跑验收闸门时用，见纪律①）
bash render_sharded.sh tpl-camera.html out.mp4 4 --deterministic
# 显式开 GPU（⚠️ 会改像素，整批统一才用）／vulkan 起不来的退路
python3 render_card.py tpl.html out.mp4 --angle vulkan
python3 render_card.py tpl.html out.mp4 --angle egl
```

`render_card.py` 启动后把实际后端打进 stderr：默认路径打一行中性说明
（`ℹ️ 当前 CPU 光栅（与存量批次一致）`）；**显式要了 GPU 却落回 SwiftShader 才打醒目警告**，
看到就别往下渲。⚠️ `--use-angle=egl` 不是 ANGLE 的合法取值、会**静默**回落 SwiftShader，
所以 `--angle egl` 内部映射成 `gl-egl`（2026-08-12 实测）。

**实测（本机 RTX 4090 + Playwright 1.58 headless，1080×1920，2026-08-12）**：

| 模板 | 帧数 | CPU 整片（默认） | CPU 4 片 | GPU 整片 | GPU 2 片 | GPU 4 片 |
|---|---|---|---|---|---|---|
| tpl-basic | 222 | 20s | 14s（2 片） | 11s（1.8×） | — | — |
| tpl-camera | 415 | 131s | **32-33s（4.0×）** | 83s（1.6×） | 43s | 28s |

**分片是提速主力，而且它零像素变化**：默认 CPU 路径上 camera **131s→33s（4.0×）**，全部来自分片。
在此之上再开 GPU 只多买到 33s→28s（约 1.15×）——用「与全部存量片字形不一致」换 15%，不划算，
所以默认关。GPU 单跑那 1.6-1.8× 在分片之后基本被吃掉了。
另注：GPU 提速比与模板负载**无正相关**——重负载的 camera 受益反而略小（1.6× vs basic 的 1.8×），
瓶颈在截图编码与 IPC，不在光栅。

⚠️ 上表分片数字**逐条复测过**：首测 GPU 4 片 38s 是单跑噪声，复跑两次稳定 28s。
分片耗时受同机其他负载影响明显，**要拿它做决策就跑两遍**（本节的教训之一）。

N 按内存定不按核数定：一路 Chromium 逐帧渲染峰值可吃到数 GB（EMDR 线 R15 有 7.1GB 被 OOM 杀的实例），
**2-4 是安全区**；4 片相对 2 片已进入争抢递减区。`--deterministic` 约慢 1.7×。

### 三条纪律

**① 换渲染后端必须双跑 md5 验确定性**——同模板同 cues 双跑，mp4 md5 一致才可用。
GSAP 渲染契约禁 `Math.random`/`Date.now` 正是为此服务。
🩸 **但双跑必须带 `--deterministic`**：不带它时逐帧截图**本来就不是**逐字节可复现的（seek 后不等合成器
提交就取图），实测同配置三跑出两三个不同 md5，CPU 与 GPU 都一样、和分片无关——
**这是 2026-08-12 之前就有的老毛病，不是 GPU 引进的**。差异 ≤6/255、落在 <0.4% 像素上，肉眼与成片无感，
但拿裸默认路径跑 md5 闸门＝闸门永远红，会把人引去查根本不存在的 bug。

口径按场景写死（2026-08-12 定）：

| 场景 | `--deterministic` |
|---|---|
| 验收、复现、换后端/换 N 前后对比 | **必须带**，否则闸门无意义 |
| 批量产线出片 | **建议带**——1.7× 代价用分片买回来（camera 4 片仍比 CPU 整片快 2 倍多） |
| 迭代调模板、预览看效果 | 不必带，默认路径快且与旧版逐字节兼容 |

**② 整批视频统一后端不得混用**——GPU/CPU 是两套字形抗锯齿实现，**差异远不止"亚像素"**：
实测 tpl-basic（`--deterministic`，同模板同 cues）CPU 与 GPU **222/222 帧全部不同**，
最严重一帧差 300804 个像素（占 14.5%），最大通道差 3-4/255，有差异帧的非零像素中位数 17186。
EMDR 线在带阴影合成的球体模板上量到更大：**44-49 万像素、最大通道差 35/255**。
混用＝同批的字看起来不是一套东西。

**分片数 N 同样算渲染配置的一部分**：实测（`--deterministic`，tpl-basic）整片 vs 2 片 vs 3 片三份 mp4
md5 各不相同，差在 1 帧、383 个像素、最大通道差 1——这个量级才叫看不出来，但同批混用仍是无谓的不一致。

**同一批：后端一致 + N 一致。**

⚠️ **正因为此，默认后端是 CPU**：2026-08-11 验收入库的首片与四版式样片都是 CPU 渲的，
默认开 GPU 等于让新片跟存量不是一套字。要用 GPU 就**整批都用**（含同批的补渲、返工重出），
别只给某几条开。EMDR 线基于同一条理由也把 GPU 关掉了，两线口径一致。

另：EMDR 线报告 vulkan 下 `page.screenshot` 会间歇性抛 `Unable to capture screenshot`
（本线 tpl-basic/tpl-camera 十余次整片与分片实跑未复现，但显式开 GPU 时要留意，遇到就退回默认 CPU）。

**③ 两个全量渲染撞同一帧目录＝后来者拒绝启动，绝不清对方的帧**。
帧目录里放 `.render.pid`（整片）/ `.render.pid.s{i}of{N}`（分片），首行是 pid。开渲前扫一遍：
凡是**会写到同一批帧**的活锁存在就 exit 1 并报出持锁 pid；只有「同一 N 的不同分片」算互不冲突，
其余组合（任一为整片 / 同一片重入 / N 不同）一律挡。锁主已死则打印接管说明后接管。
`render_sharded.sh` 在**预清帧目录之前**也做同一道检查——否则"先清后拒"照样把别人的活清光了。

> 事故由来（EMDR 线 R15/R16，2026-08-12）：两个渲染进程开在同一个工作目录，各自开渲前
> `unlink` 了对方的帧，成片音画混轨，而当时的 QA 量具查不出来——**帧目录被静默清空是最伤的失败模式，
> 因为它不报错**。归因还有一层：那两起"双渲"都是**自撞**（chain 已接管渲染，人又按派工单手跑了一遍），
> 所以自锁必须挡的是"任何会写同一批帧的第二个进程"，不分敌我。

## 交付与发布

- 上传直链：`POST /api/admin/blog/posts/upload-video`（multipart `file` 字段**必须显式 `;type=video/mp4`**，
  服务端按 MIME 判格式，curl 默认 octet-stream 会被拒）→ `https://database.nbdpsy.com/static/blog/videos/…`；
- 发小红书走 publish-jobs `video` 字段（服务器侧路径，同机 cp 落盘，见 xiaohongshu-creator SKILL 视频发布节）；
- 封面按 3:4 单独做（沿用小红书封面规范），版式知识见 xiaohongshu-creator `illustration-spec.md` §2-b。
