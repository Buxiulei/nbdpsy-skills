# NBDpsy 封面 SVG 素材库

给 **HTML 封面模板**用的线条图形库：63 个可着色 SVG，全部 ISC / MIT / 自有版权，**商用免署名**。
改文案＝改文本，版式与图形分毫不动、秒出、零 AI 出图额度——图形这一环就靠这个库兜住。

- 许可证台账（免责依据，逐文件）：[`LICENSES.md`](./LICENSES.md)
- 上游许可证全文：[`licenses/`](./licenses/)
- **一眼看全库**：浏览器打开 [`gallery.html`](./gallery.html)（品牌配色渲染，按意象分组，标了文件名与用法）

```
svg-library/
├── README.md            ← 本文件：怎么用
├── LICENSES.md          ← 逐文件许可证台账（新增素材必须补一行）
├── gallery.html         ← 全库总览页（图标已内联，双击即可看）
├── licenses/            ← 上游 LICENSE 全文（再分发 SVG 源文件时须一并附带）
└── *.svg                ← 63 个图形，平铺，文件名即上游名（自绘除外）
```

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
5. **体积**：单文件 ≤20KB，目录总量 ≤2MB（现状 63 个共 51.4 KB，SVG 超 20KB 通常说明拿错了东西）。
6. **找不到就如实记「缺」**，别拿不相干的图形凑数——真需要就自绘（自绘请对齐 24×24 网格 / 2px 线宽 / 圆角端点，
   并在文件头写明「NBDpsy 自绘原创」）。

`gallery.html` 里的图标是**内联进去的快照**，改动或新增 SVG 后需要重新生成才会同步；
生成逻辑就是把每个 SVG 剥掉注释头后按分组内联进一张静态页，二十行 Python 即可，不必长期维护脚本。
