# NBDpsy 封面 SVG 素材库

给 **HTML 封面模板**用的线条图形库，**两层结构**，全部 ISC / MIT / Apache-2.0 / 自有版权，**商用免署名**：

- **手工件 66 个**（平铺 `*.svg`）——逐个查过许可证、加过 NBDpsy 文件头与 `class="nbd-svg-icon"`，**挑图优先用这一层**；
- **集合包 34,995 枚**（`collections/`，6 个开源集合）——2026-08-17 扩库，管「手工件里没有」的长尾。

改文案＝改文本，版式与图形分毫不动、秒出、零 AI 出图额度——图形这一环就靠这个库兜住。

- 许可证台账（免责依据）：[`LICENSES.md`](./LICENSES.md)　⚠️ **手工件逐文件记、集合逐集合记**，两套数法见台账顶部「核对口径」
- 上游许可证全文：[`licenses/`](./licenses/)
- **一眼看全手工件**：浏览器打开 [`gallery.html`](./gallery.html)（品牌配色渲染，按意象分组）
- **在集合里找图**：`python3 ../../scripts/svg_find.py 咖啡杯` —— 见下面 §〇

```
svg-library/
├── README.md            ← 本文件：怎么用
├── LICENSES.md          ← 许可证台账（手工件逐文件；集合逐集合）
├── gallery.html         ← 手工件总览页（图标已内联，双击即可看）
├── licenses/            ← 上游 LICENSE 全文（再分发时须一并附带）
├── collections/         ← 集合包：<前缀>/{icons.json, info.json}
│   ├── lucide/      2,053 枚  ISC        描边 2/24  ★同族
│   ├── tabler/      6,426 枚  MIT        描边 2/24  ★同族
│   ├── iconoir/     2,020 枚  MIT        描边 1.5/24 ◇需归一
│   ├── heroicons/   1,297 枚  MIT        描边/填充混合
│   ├── ph/          9,198 枚  MIT        填充 · 256 网格
│   └── mdi/        14,001 枚  Apache-2.0 填充
└── *.svg                ← 66 个手工件（文件名即上游名，自绘除外）
                           ＋ 落地件 <集合前缀>-<图标名>.svg（从集合包取下来的）
```

> ⛔ **`collections/` 里的图标不能直接在封面里点名**。`render_cover.py` 只认平铺 `*.svg`，
> 子目录它看不见——这是**故意的**，扩库没有把「图标必须在库内」那道闸门弄松。
> 要用某一枚，先 `svg_find.py --emit … --install` 落地成平铺文件。见 §〇之三。

---

## 〇、`svg-find`：在 34,995 枚里挑图（⛔ 默认不联网）

脚本在 [`../../scripts/svg_find.py`](../../scripts/svg_find.py)。⛔ 别手翻 `icons.json`。

### 之一：检索

```bash
python3 scripts/svg_find.py 咖啡杯          # 中文
python3 scripts/svg_find.py coffee          # 英文
python3 scripts/svg_find.py 心 --family same --limit 20   # 只要同族
python3 scripts/svg_find.py coffee --json   # 给排版 agent 用
```

```
# 「咖啡杯」→ 英文词：coffee, cup（命中映射键：咖啡杯）
lucide:coffee    ISC         描边2/24        ★同族  已入库 assets/svg-library/coffee.svg
tabler:cup       MIT         描边2/24        ★同族
tabler:coffee    MIT         描边2/24        ★同族
lucide:cup-soda  ISC         描边2/24        ★同族  已入库 assets/svg-library/cup-soda.svg
ph:coffee        MIT         填充(线宽不可调)  ⚠️异族
mdi:cup          Apache-2.0  填充(线宽不可调)  ⚠️异族
```

四列各是什么：

- **许可证列**：集合级台账不逐条记，那就在**用的时候**逐条打出来——这一列就是免责依据的现场版；
- **族别**：`★同族`＝描边 2/24，跟 66 个手工件同一形状，直接用；
  `◇近亲`＝描边但线宽不是 2（Iconoir 是 1.5），取图时加 `--stroke-width 2`；
  `⚠️异族`＝填充族。⚠️ 「填充」**不等于**「实心色块」——Phosphor 常规档是用填充路径描出轮廓，
  目视跟线条图几乎一样；真正的差别是**线宽写死在路径几何里，调不动**；
- **已入库**：命中的图标如果已经是那 66 个手工件之一，会标出本地路径——**优先用手工件**
  （它带 NBDpsy 文件头与 class，是人工挑过、写过意象说明的）；
- 自绘件（`domino-fall` / `plant-stake`，集合里根本没有）以 `local:` 前缀参与检索，排最前。

**中文缺词**：映射表当前 374 个词（→ 411 个英文词），缺词时会明说「**没有中文映射**——不是库里没有这个图标，
是这个词还没进映射表」，并给相近的词与英文重查建议，**退出码 1**。
⛔ 不会静默返回空表——那会让人误判成「库里没有」，转头去烧 AI 出图额度。
补词就往 `svg_find.py` 的 `ZH_KEYWORDS` 里加一行（有测试挡着死词：映射到的英文名必须真实存在）。

**零命中**：本脚本**只查本地 6 个集合，不联网**。真要现搜就自己去
<https://icon-sets.iconify.design>，找到后回来核许可证再入库。⛔ 没有 `--online` 这个开关。

### 之二：取图（打印可直接内联的完整 SVG）

```bash
python3 scripts/svg_find.py --emit lucide:coffee                      # 原样
python3 scripts/svg_find.py --emit iconoir:coffee-cup --stroke-width 2 # 跨族：线宽归一到 2
python3 scripts/svg_find.py --emit local:domino-fall                   # 手工件（自动剥版权注释头）
```

出来的 SVG 跟手工件同一形状：根上带 `class="nbd-svg-icon"`，
并把 body 里**取值唯一**的 `stroke` / `fill` / `stroke-width` / `linecap` / `linejoin` **提到根上**。
⚠️ 这一步不是洁癖：Iconify 把这些属性写在**子元素**上，而写在子元素上的呈现属性
**盖得过**从根继承的 CSS —— 不提上来的话，模板里那条 `.nbd-svg-icon{stroke-width:1.6}`
会**静默失效**（图照出，只是线宽没变，截完图才发现）。

线宽归一按网格折算（Phosphor 是 256 网格），保证**视觉粗细**一致而不是数字一致；
路径数据一个字节都不改（有测试钉着），所以⛔ 不会变形。
填充族给了 `--stroke-width` 会**明确警告无效**，不静默吞掉。

> **归一后的目视确认**（2026-08-17 实测，非只改数字）：Iconoir 的 `coffee-cup` / `brain` /
> `heart` / `flower` 四个从 1.5 归一到 2，与右侧 Lucide 同名图并排渲染 —— 粗细齐平、形状无变形。
> ⚠️ 一条注意：**细节密的图标**（如 `iconoir:brain` 的脑回沟）归一到 2 后笔画间距明显变紧，
> 104px 上仍清晰，但**≤40px 的角标位置会糊成一团**，那种位置请保留 1.5 或换图。

### 之三：落地（让 `render_cover.py` 认得它）

```bash
python3 scripts/svg_find.py --emit tabler:mood-sad --install --note "低落的脸：说不出哪里不对劲"
# → assets/svg-library/tabler-mood-sad.svg
# → 封面 JSON 里写 "icons": ["tabler-mood-sad"]
```

文件名一律 `<集合前缀>-<图标名>.svg`，⛔ 不用裸名——防止覆盖同名手工件。
许可证由 `LICENSES.md` 集合行覆盖，⛔ 不必回逐文件表补行。

### 之四：集合台账速查

```bash
python3 scripts/svg_find.py --list-collections
```

会连**故意没入库的集合**一起列出来（当前 `ri` / Remix Icon，理由见 `LICENSES.md` §五），
⛔ 不会让人以为「查不到就是没有」。

---

## 一、三种引用方式：**只有内联能着色**（已实测）

封面渲染走的是 Playwright 打开 `file://` 本地 HTML 再截图，这个环境下三种写法表现完全不同。
下表是在本机 Chromium + `file://` 下实测出来的结论，不是推测：

| 写法 | 能否显示 | 能否跟品牌色 | 结论 |
|---|---|---|---|
| **内联 `<svg>`**（把文件内容塞进 HTML） | ✅ | ✅ 跟 `color` 走 | **首选**，唯一能改描边色又能改线宽的方式 |
| **CSS `mask` + data-URI** | ✅ | ✅ 跟 `background-color` 走 | 备选：想用 CSS 批量着色、不想动 HTML 结构时用 |
| CSS `mask` + 文件路径（相对或绝对） | ❌ 整块空白 | — | **不能用**：`file://` 下 CSS 引外部 SVG 被同源策略拦掉，静默不显示 |
| `<img src="x.svg">` | ✅ | ❌ 永远是黑色 | 只在「图形本来就该是黑」时用；`currentColor` 在 img 里解析成黑色 |

> 踩过的坑：`mask:url("heart.svg")` 在浏览器里手动打开也许能看到，在 Playwright 无头 `file://` 里是**空白且不报错**——
> 属于「静默失败」，截完图才发现图标没了。要么内联，要么 data-URI，别赌路径。

### 用法 A：内联（首选）

```python
import re, pathlib

LIB = pathlib.Path("/home/roots/nbdpsy-skills/nbdpsy-xiaohongshu-creator/assets/svg-library")

def icon(name: str, size: int = 96, stroke: float = 1.6) -> str:
    """读一个 SVG，剥掉文件头注释，交出可直接插进模板的内联片段。"""
    s = (LIB / f"{name}.svg").read_text(encoding="utf-8")
    s = re.sub(r"^<!--.*?-->\s*", "", s, flags=re.S)          # 去掉版权注释头（省体积，信息已在 LICENSES.md）
    s = re.sub(r'\swidth="24"', "", s, count=1)                # 尺寸交给 CSS / 行内样式
    s = re.sub(r'\sheight="24"', "", s, count=1)
    return s.replace("<svg", f'<svg style="width:{size}px;height:{size}px;stroke-width:{stroke}"', 1)

html = TEMPLATE.replace("{{ICON}}", icon("hand-helping"))
```

模板侧只要给它一个有 `color` 的容器，图标就跟着品牌色走：

```html
<style>
  :root{
    --ink:#A34B3A;        /* 赭红 · 主视觉 */
    --paper:#E8D8C4;      /* 暖米白 · 纸底 */
    --sage:#C9D6CE;       /* 鼠尾草绿 */
    --mist:#A8B5C4;       /* 雾霾蓝灰 */
    --text:#5A6B7B;       /* 正文色 */
  }
  .nbd-svg-icon{ width:96px; height:96px; stroke-width:1.6; }  /* 库内每个 svg 根都带这个 class */
  .icon-ink   .nbd-svg-icon{ color:var(--ink); }               /* 描边＝赭红 */
  .icon-sage  .nbd-svg-icon{ color:var(--sage); }              /* 描边＝鼠尾草绿 */
  .icon-quiet .nbd-svg-icon{ color:var(--mist); opacity:.55; } /* 背景装饰用 */
</style>

<div class="icon-ink">{{ICON}}</div>
```

要点：

- 库里每个 `<svg>` 根都已加 `class="nbd-svg-icon"`，CSS 一条规则就能统一全库；
- 描边色用 `color`（因为上游是 `stroke="currentColor"`），**不是** `fill`；
  `heart-solid.svg` / `heart-broken-solid.svg` 是实心版（`fill="currentColor"`），同样跟 `color` 走；
- `stroke-width` 写在 CSS 里能盖掉 SVG 自带的 `2`（属性优先级低于 CSS 规则），子元素会继承。

### 用法 B：CSS mask + data-URI（想用 CSS 批量着色时）

```python
import re, urllib.parse, pathlib

def icon_data_uri(name: str) -> str:
    s = (LIB / f"{name}.svg").read_text(encoding="utf-8")
    s = re.sub(r"^<!--.*?-->\s*", "", s, flags=re.S)
    return "data:image/svg+xml;utf8," + urllib.parse.quote(re.sub(r"\s+", " ", s))
```

```css
.deco-heart{
  width:120px; height:120px;
  background: var(--ink);                       /* 颜色由 background 决定 */
  -webkit-mask: url("data:image/svg+xml;utf8,…") center/contain no-repeat;
          mask: url("data:image/svg+xml;utf8,…") center/contain no-repeat;
}
```

注意：mask 只保留图形的形状，**线宽用的是 SVG 里写死的 `stroke-width="2"`**，CSS 改不动。
想要更细的线（封面大图上 2px 会显粗），用内联法。

---

## 二、尺寸与线宽（封面上好看的取值）

24×24 网格的图标放大到封面尺寸时，线宽要按比例回调，否则显得又粗又土：

| 场景 | 显示尺寸 | 建议 `stroke-width` |
|---|---|---|
| 封面主视觉图形（1080×1440 画布） | 120–220px | **1.2 – 1.5** |
| 段落／要点前的小图标 | 48–96px | **1.6 – 1.8** |
| 正文行内、角标 | 24–40px | **2**（保持上游默认） |
| 背景装饰（大面积、低对比） | 300px+ | 1.0–1.2 ＋ `opacity:.12~.25`，颜色用 `--mist` 或 `--sage` |

其它经验：

- **一张封面只用一个图形**。多个图标堆在一起立刻变成「PPT 素材页」，老板否掉的就是这种；
- 图形颜色优先 `--ink` 赭红，次选 `--mist` 雾霾蓝灰做弱化；`--sage` 鼠尾草绿适合做背景大图形；
- 自绘的 `domino-fall.svg` / `plant-stake.svg` 在 28px 以下会糊，别用在角标位置。

---

## 三、和截图管线的关系（别另造轮子）

出图仍然走既有的 Playwright 截图范式 —— 参见
`scripts/typeset_longimage.py`：**设定 viewport → `page.screenshot(clip=…)` 精确出尺寸**，
无 playwright 时降级 `--html-only` 只出 HTML。本库不引入任何新依赖、不新增渲染路径，
只是给那套模板提供「图形」这一层素材。

自查用的最小回路（跟 `typeset_longimage.py` 同一套写法）：

```python
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1080, "height": 1440}, device_scale_factor=2)
    pg.goto("file:///abs/path/cover.html")
    pg.wait_for_timeout(300)
    pg.screenshot(path="cover.png", clip={"x": 0, "y": 0, "width": 1080, "height": 1440})
    b.close()
```

---

## 四、意象索引（挑图不用翻目录）

| 意象 | 文件 |
|---|---|
| 手 · 交托与援手 | `hand` `hand-helping` `hand-heart` `handshake` |
| 拥抱 · 陪伴与联结 | `heart-handshake` `users-round` `friends` ⚠️ 均为「拥抱」的近似替代，上游无真·相拥图形 |
| 植物与支架 · 生长 | `sprout` `leaf` `flower` `tree-deciduous` `plant-2` `plant-stake`（自绘：有支撑才长得直） |
| 门 · 进出与边界 | `door-open` `door-closed` |
| 路 · 过程与方向 | `route` `footprints` `signpost` `milestone` |
| 灯 · 照见与领悟 | `lamp` `lightbulb` `flashlight` |
| 云雨 · 情绪天气 | `cloud` `cloud-rain` `cloud-sun` `umbrella` |
| 心 · 情感与创伤 | `heart` `heart-crack` `heart-pulse` `heart-solid` `heart-broken-solid` |
| 书 · 知识与记录 | `book-open` `book` `notebook-pen` |
| 对话气泡 · 说出来 | `message-circle` `messages-square` `message-circle-heart` |
| 时钟 · 时间与等待 | `clock` `hourglass` `alarm-clock` |
| 镜子 · 自我觉察 | `mirror-round` `mirror-rectangular` |
| 骨牌 · 连锁反应 | `domino-fall`（自绘：一件事推倒下一件） |
| 台阶 · 分步推进 | `stairs` `stairs-up` `ladder` |
| 延伸 · 心理科普高频 | `brain`（神经机制）`anchor`（稳定化）`shield-check`（边界）`key`（解法）`puzzle`（整合）`life-buoy`（求助）`mountain`（难题）`feather`（放下）`droplets`（眼泪）`bandage`（疗愈）`scale`（权衡）`link-2`（联结）`compass`（方向）`battery-low`（耗竭）`moon`（失眠）`sun`（希望）`waves-horizontal`（起伏） |

每个 SVG 的文件头注释里写着它的意象、来源、许可证和下载日期，翻文件也能直接看到。

---

## 五、往库里加素材的硬规矩

1. **先查许可证再下载**：✅ MIT / Apache-2.0 / CC0 / ISC；⚠️ CC-BY 需署名——原则上跳过；
   ⛔ CC-BY-NC 一律不要；⛔ 来源不明或查不到条款的一律不下载。
2. **必须能着色**：`stroke="currentColor"` 或 `fill="currentColor"`，多色插画不收。
3. **补文件头注释 + 加 `class="nbd-svg-icon"`**（照抄库内任一文件的格式）。
4. **回 `LICENSES.md` 补一行**：文件名 / 意象 / 来源 URL / 许可证 / 是否需署名 / 下载日期。这张表是免责依据，不许留空。
5. **体积**：单文件 ≤20KB；**平铺目录**总量 ≤2MB（现状 67 个共 268 KB，SVG 超 20KB 通常说明拿错了东西）。
   ⚠️ 这条 2MB 只管平铺那一层；`collections/` 另算一档，上限 20MB（现 12MB），口径见 `LICENSES.md` §五末尾。
6. **找不到就如实记「缺」**，别拿不相干的图形凑数——真需要就自绘（自绘请对齐 24×24 网格 / 2px 线宽 / 圆角端点，
   并在文件头写明「NBDpsy 自绘原创」）。

`gallery.html` 里的图标是**内联进去的快照**，改动或新增 SVG 后需要重新生成才会同步；
生成逻辑就是把每个 SVG 剥掉注释头后按分组内联进一张静态页，二十行 Python 即可，不必长期维护脚本。
