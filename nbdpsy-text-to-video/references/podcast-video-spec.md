# 「长文播客」形态规格（长文 → 对谈播客视频）

> 2026-08-07 老板立项。参考形态：抖音「老徐的会客厅」（8.4 万赞样本）——**声音+字幕为主**，
> 画面是极简 HTML 播放器（黑底 + 期号标题 + 当前句大字幕 + 波形播放器图形 + 栏目名），
> 录屏成片。适合官网查证长文的深度内容二次分发；与「笔记微电影」互补（那个重画面，这个重内容密度）。

## 产线五步

```
长文 → ①对话逐字稿 → ②DeepSeek 三轮审校 → ③MiniMax 双声合成 → ④HTML 播放器页 → ⑤录屏+混音
```

### ① 对话逐字稿（一男一女对谈）

- **格式**：`podcast.json`
  ```json
  {
    "series": "栏目名",              // 如「NBDpsy 会客厅」，老板定
    "vol": 1,
    "title": "本期主题（两行内）",
    "source": "源长文 slug/路径",
    "lines": [
      {"speaker": "F", "text": "……", "emotion": null, "speed": 1.05, "pause_after": 0.3},
      {"speaker": "M", "text": "……"}
    ]
  }
  ```
- **角色分工**（对谈的骨架，不是两个人轮流念稿）：一个「引导者」（提问、追问、替观众说
  出困惑、偶尔抬杠），一个「阐述者」（专业输出、举例、纠正）。谁是 M 谁是 F 按内容定，
  别固定「男问女答」的套路。
- **语气语速规划写进每行**：`speed`（0.5–2.0，问句可稍快、共情句稍慢）、`pause_after`
  （行间停顿秒数，转折前 0.5–0.8）、句内用 `<#x#>` 与 `(sighs)(emm)` 等标签
  （纪律见 `narration-spec.md` 第五节；对谈里 `(emm)` `(chuckle)` 比微电影口播更常用——
  真人对话本来就有磕绊）。
- **写稿守则**：沿用 `narration-spec.md` 写稿六律，另加对谈三条——
  ⑴ 每轮发言 ≤3 句，超了拆成对方一句短接话（「嗯」「对」「等一下，你是说……」）；
  ⑵ 阐述者引用研究/数据须来自源长文（查证过的），对谈不新增事实主张；
  ⑶ 引语坑同样适用：转述不加引号。

### ② DeepSeek 三轮审校

流程同 `narration-spec.md` 第二节（3 轮 temperature 0.3 取 ≥2 轮交集、agent 裁决留痕）。
对谈稿额外审两项：**像不像真人对话**（有没有播音腔/互相念稿感）、**角色一致性**
（引导者不突然变专家、阐述者不突然装小白）。

### ③ MiniMax 双声合成

- 逐行合成（`tts_gen.py --engine minimax --timed`），行间静音按 `pause_after` 用 ffmpeg
  anullsrc 垫；产出 `podcast.mp3` + 合并时间轴 `podcast.cues.json`
  （每行一条 cue：`{speaker, text, start, end}`——字幕与说话人高亮都靠它）。
- 音色：女声=温暖闺蜜（现役）；**男声待选**（候选：温润男声 `Chinese (Mandarin)_Gentleman`、
  电台男主播 `Chinese (Mandarin)_Radio_Host`、真诚青年 `Chinese (Mandarin)_Sincere_Adult`，
  试音后老板定）。
- 成本：对谈 10 分钟 ≈ 2600 字 ≈ ¥1.8（speech-2.8-hd），忽略不计。

### ④ HTML 播放器页（`assets/podcast_player.html` 模板）

参考截图的构图，竖屏 720×1280 黑底，从上到下：
1. **期号+标题**（两行内，白字，Vol.N：主题）；
2. **当前句大字幕**（画面视觉中心，随 cues 逐句切换；当前说话人可用颜色/前缀区分）；
3. **波形播放器图形**（居中：波形条 + 播放键造型 + 进度点——纯装饰，CSS/JS 动画随
   播放进度走，不必真实反映频谱；真实感优先级低于稳定性）；
4. **栏目名**（书法感字体或 logo 字，底部）。
- 全部资源内联（字体用系统 Noto，不依赖外网）。数据注入：模板顶部
  `<script id="podcast-data" type="application/json">` 占位，录屏脚本把 `{title,vol,series,cues}`
  写入后落临时 html 再打开（`file://` 下 fetch 本地 json 会被 CORS 拦，query 驱动走不通，
  2026-08-07 实现时定案）；音频固定同目录相对路径 `podcast.mp3`。页面暴露
  `window.__start()` / `window.__done` / `window.__t()` 供录屏脚本控制与检测结束。

### ⑤ 录屏 + 混音

- Playwright chromium 打开页面 → 720×1280 视口 → `page.video` 录制 → 播放到 `__done` →
  ffmpeg 把录屏视频与 `podcast.mp3` 混轨（录屏声道丢弃，用原始音频保音质）+ faststart。
- 封面沿用「封面首帧」能力（compose 的 `cover`）；片尾 `fade_out`。
- AI 标识：本形态**画面非 AI 生成**（HTML 排版），但**声音是 AI 合成**——发布时平台
  AIGC 声明照勾，角标按发布场景决定。

## 与「笔记微电影」的公用件

TTS（tts_gen 三引擎）、DeepSeek 审校流程、封面规范（小红书封面三级层级）、`fade_out`、
发布链路全部复用；新增件只有：对谈稿格式与驱动脚本（`podcast_gen.py`）、播放器模板、录屏脚本。

## 已定案（2026-08-07 老板逐项验收）

- **栏目名：「NBDpsy心理会客厅」**（podcast.json 的 series 字段统一用它）；
- **双声响度归一**：每行按 mean_volume 拉到 -22dB（±12dB 限幅），wav 阶段做（实测
  温暖闺蜜 -31dB vs 温润男声 -23.6dB 差 7.5dB，归一后逐行 -22.0dB 对齐）；
- **字幕规则与短视频一致**：逗号换行、句号翻页、每页最多两行超出翻页——record_podcast
  注入前把行级 cues 用 compose_video 的分页管线变换成页级 cues，页时长按文字宽度比例分配；
- **波形=心电图式真实声纹**（三形态试到第三版定案）：离线预计算每 80ms 窗的有符号
  峰值对（真实波形上下包络），canvas 连续描线成过零摆动的心电轨迹，中心=当下（辉光
  播放头）、已播金色辉光/未播暗灰、亚像素平滑滚动、两侧渐隐窗口；
  ⛔ file:// 下 Web Audio AnalyserNode 全零、设 crossOrigin 音源直接被拒，都是死路；
- **音画同步=帧级标记**：预滚 0.8s 挂黑幕+品红块，audio playing 撤幕，录屏后逐帧扫描
  切齐（误差≤1帧）；load 后立刻开播标记一帧都录不到，预滚必不可少；
- **男声定案：温润男声 `Chinese (Mandarin)_Gentleman`**；
- **首期定案**：黄安麟《你越用力要爱，他越冷漠：投射性认同的怪圈》
  （slug yue-yao-ai-yue-lengmo，其署名文章阅读量第一）。
