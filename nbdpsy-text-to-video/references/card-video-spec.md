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
7. 双格式落盘防重（出图目录 png+jpg 同名会被发布脚本收两遍——publish_note 已去重，但落盘仍建议单格式）。

## 交付与发布

- 上传直链：`POST /api/admin/blog/posts/upload-video`（multipart `file` 字段**必须显式 `;type=video/mp4`**，
  服务端按 MIME 判格式，curl 默认 octet-stream 会被拒）→ `https://database.nbdpsy.com/static/blog/videos/…`；
- 发小红书走 publish-jobs `video` 字段（服务器侧路径，同机 cp 落盘，见 xiaohongshu-creator SKILL 视频发布节）；
- 封面按 3:4 单独做（沿用小红书封面规范），版式知识见 xiaohongshu-creator `illustration-spec.md` §2-b。
