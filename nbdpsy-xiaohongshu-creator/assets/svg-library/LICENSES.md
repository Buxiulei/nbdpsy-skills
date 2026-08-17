# SVG 素材库 · 许可证台账

> 这份表是**免责依据**：库内每一个 SVG 的来源、许可证、是否需要署名、下载日期都逐个记在这里。
> 新增任何素材，必须先查清许可证再下载，并在本表补一行；查不到许可证的一律不入库。

**采信规则（NBDpsy 商用红线）**

| 许可证 | 处理 |
|---|---|
| MIT / Apache-2.0 / CC0 / ISC | ✅ 可用，商用免署名 |
| CC-BY（需署名） | ⚠️ 原则上跳过——小红书图上署名难看，且漏署名即违约 |
| CC-BY-NC（禁商用） | ⛔ 一律不要，我们是商业机构 |
| 来源不明 / 查不到条款 | ⛔ 不下载 |

**本库结论**：全部 63 个文件均为 ✅ 级——ISC / MIT / NBDpsy 自有版权，
**没有任何一个需要在图上署名**，可直接用于小红书、公众号、官网等商业发布物。

**署名与再分发义务的准确边界**

- ISC 与 MIT 都要求「在软件的副本或实质性部分中保留版权与许可声明」。我们的做法是：
  ① 每个 SVG 文件头注释里写明来源与许可证；② `licenses/` 目录保留上游 LICENSE 全文
  （`licenses/lucide-ISC-LICENSE.txt`、`licenses/tabler-MIT-LICENSE.txt`）。这已满足条款。
- 用这些图标渲染出来的**成品图片**（封面 JPG／长图 PNG）不构成「软件副本」，
  **不需要在图上标注来源，也不需要在笔记正文署名**。
- 但若把 **SVG 源文件本身**再分发给第三方（例如打包给外部设计师、开源出去），
  必须连同 `licenses/` 目录一起给。

**上游快照日期**：2026-08-17（Lucide `main` 分支、Tabler Icons `main` 分支）。
上游后续更新不会自动同步到本库；需要更新时按下方「更新方法」重新拉取并更新本表。

---

> ⚠️ **核对口径**：`plant-stake.svg` 与 `domino-fall.svg` 在本文件出现两次——一次在主表、一次在下方「自绘件」说明区（记录为什么自绘）。**核一致性时按主表计**：主表行数 = 目录 `*.svg` 文件数。

> 🔴 **核对口径 · 2026-08-17 补充（本库从「一层」变成「两层」，上面那句的适用范围要跟着缩）**
>
> 本库现在是**两段结构**，两段的记法与数法都不一样，⛔ 别拿一段的口径去核另一段：
>
> | | 上半段：**手工件** | 下半段：**集合包** |
> |---|---|---|
> | 存在哪 | `svg-library/*.svg`（平铺） | `svg-library/collections/<前缀>/icons.json` |
> | 台账怎么记 | **逐文件一行**（§一、§二，原样保留） | **逐集合一行**（§五）——34,995 枚逐个记没人维护得动 |
> | 逐条许可证在哪看 | 每个 SVG 的文件头注释 | **`svg_find.py` 检索输出里那一列**——集合级台账不逐条记，就把「逐条」挪到用的时候现打 |
> | 怎么数 | `ls *.svg \| wc -l` 减掉落地件 | `python3 scripts/svg_find.py --list-collections`（读 icons.json 现算） |
>
> **手工件那 66 个怎么核**（上面那句「主表行数 = 目录 `*.svg` 文件数」现在只对这一段有效，且要修正）：
> 主表（§一）实际 **63 行**，`headphones` / `coffee` / `cup-soda` 三个记在 §二 的表里，
> 两表去重后共 **66 行 = 66 个手工件**。所以准确的口径是
> **§一 + §二 去重后的行数 = 平铺目录里手工件的个数**，⛔ 不是「主表行数」。
>
> **落地件另算**：平铺目录里还会多出 `<集合前缀>-<图标名>.svg`——由
> `svg_find.py --emit … --install` 从集合包落地（为什么要落地见 §五末尾）。
> 它们的许可证**由所属集合那一行覆盖**，⛔ 不必逐个补行。于是：
>
> ```
> ls *.svg | wc -l  =  66 手工件  +  落地件个数
> 落地件 = 文件名以「已知集合前缀 + 连字符」开头的那些（当前 1 个：tabler-mood-sad.svg）
> ```

## 一、逐文件台账

### 手

| 文件名 | 意象 | 来源 URL | 许可证 | 是否需署名 | 下载日期 |
|---|---|---|---|---|---|
| `hand-heart.svg` | 手捧一颗心：自我关怀、递出善意 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/hand-heart.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `hand-helping.svg` | 援手托举：被接住、被支持 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/hand-helping.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `hand.svg` | 张开的手掌：交托、坦白、停一停 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/hand.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `handshake.svg` | 双手相握：建立关系、达成共识 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/handshake.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |

### 拥抱／陪伴

| 文件名 | 意象 | 来源 URL | 许可证 | 是否需署名 | 下载日期 |
|---|---|---|---|---|---|
| `friends.svg` | 并肩站立的两个人：同行、陪伴（拥抱的近似替代） | https://raw.githubusercontent.com/tabler/tabler-icons/main/icons/outline/friends.svg | MIT（Paweł Kuna / Tabler Icons） | 否（商用免署名） | 2026-08-17 |
| `heart-handshake.svg` | 交握的手中托着心：联结与被抱住（拥抱的近似替代） | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/heart-handshake.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `users-round.svg` | 两个人：陪伴、不是一个人（拥抱的近似替代） | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/users-round.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |

### 植物与支架

| 文件名 | 意象 | 来源 URL | 许可证 | 是否需署名 | 下载日期 |
|---|---|---|---|---|---|
| `flower.svg` | 花：绽放、被看见 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/flower.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `leaf.svg` | 一片叶：生命力、自然节奏 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/leaf.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `plant-2.svg` | 盆栽植物：被照料才长得好（容器＝支持系统） | https://raw.githubusercontent.com/tabler/tabler-icons/main/icons/outline/plant-2.svg | MIT（Paweł Kuna / Tabler Icons） | 否（商用免署名） | 2026-08-17 |
| `plant-stake.svg` | 植物与支架：有支撑才长得直（支持系统／外部帮助） | —（原创，无上游） | NBDpsy 自有版权 | 否 | 2026-08-17 |
| `sprout.svg` | 破土幼苗：新的开始、缓慢生长 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/sprout.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `tree-deciduous.svg` | 阔叶树：扎根、长期成长 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/tree-deciduous.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |

### 门

| 文件名 | 意象 | 来源 URL | 许可证 | 是否需署名 | 下载日期 |
|---|---|---|---|---|---|
| `door-closed.svg` | 关着的门：边界、暂时不谈 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/door-closed.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `door-open.svg` | 开着的门：可能性、离开与进入 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/door-open.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |

### 路

| 文件名 | 意象 | 来源 URL | 许可证 | 是否需署名 | 下载日期 |
|---|---|---|---|---|---|
| `footprints.svg` | 脚印：一步一步、已经走过的路 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/footprints.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `milestone.svg` | 里程碑：阶段性进展 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/milestone.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `route.svg` | 折线路径：过程、非直线的康复 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/route.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `signpost.svg` | 路标：方向选择、需要指引 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/signpost.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |

### 灯

| 文件名 | 意象 | 来源 URL | 许可证 | 是否需署名 | 下载日期 |
|---|---|---|---|---|---|
| `flashlight.svg` | 手电：主动照见暗处、探索 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/flashlight.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `lamp.svg` | 台灯：夜里的安全感、有人为你留灯 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/lamp.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `lightbulb.svg` | 灯泡：领悟、想通了 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/lightbulb.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |

### 云雨

| 文件名 | 意象 | 来源 URL | 许可证 | 是否需署名 | 下载日期 |
|---|---|---|---|---|---|
| `cloud-rain.svg` | 下雨的云：难过、坏日子 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/cloud-rain.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `cloud-sun.svg` | 云开见日：好转、间歇性的好 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/cloud-sun.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `cloud.svg` | 云：情绪的天气、说不清的低落 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/cloud.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `umbrella.svg` | 伞：庇护、自我保护 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/umbrella.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |

### 心

| 文件名 | 意象 | 来源 URL | 许可证 | 是否需署名 | 下载日期 |
|---|---|---|---|---|---|
| `heart-broken-solid.svg` | 实心碎心：可作色块点缀（fill 版） | https://raw.githubusercontent.com/tabler/tabler-icons/main/icons/filled/heart-broken.svg | MIT（Paweł Kuna / Tabler Icons） | 否（商用免署名） | 2026-08-17 |
| `heart-crack.svg` | 有裂缝的心：受伤、丧失 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/heart-crack.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `heart-pulse.svg` | 心电波：还活着、身体反应 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/heart-pulse.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `heart-solid.svg` | 实心心形：可作色块点缀（fill 版） | https://raw.githubusercontent.com/tabler/tabler-icons/main/icons/filled/heart.svg | MIT（Paweł Kuna / Tabler Icons） | 否（商用免署名） | 2026-08-17 |
| `heart.svg` | 心：情感、在乎 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/heart.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |

### 书

| 文件名 | 意象 | 来源 URL | 许可证 | 是否需署名 | 下载日期 |
|---|---|---|---|---|---|
| `book-open.svg` | 摊开的书：知识、被讲清楚的事 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/book-open.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `book.svg` | 合上的书：一段经历、一个章节 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/book.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `notebook-pen.svg` | 本子和笔：书写、记录练习 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/notebook-pen.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |

### 对话气泡

| 文件名 | 意象 | 来源 URL | 许可证 | 是否需署名 | 下载日期 |
|---|---|---|---|---|---|
| `message-circle-heart.svg` | 带心的气泡：温和表达、被善待的对话 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/message-circle-heart.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `message-circle.svg` | 圆形气泡：说出来 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/message-circle.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `messages-square.svg` | 两个气泡：来回沟通、咨询对话 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/messages-square.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |

### 时钟

| 文件名 | 意象 | 来源 URL | 许可证 | 是否需署名 | 下载日期 |
|---|---|---|---|---|---|
| `alarm-clock.svg` | 闹钟：作息、被惊醒的早晨 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/alarm-clock.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `clock.svg` | 钟面：时间、什么时候会好 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/clock.svg | MIT（Cole Bemis / Feather，经 Lucide 再分发） | 否（商用免署名） | 2026-08-17 |
| `hourglass.svg` | 沙漏：等待、疗愈需要时间 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/hourglass.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |

### 镜子

| 文件名 | 意象 | 来源 URL | 许可证 | 是否需署名 | 下载日期 |
|---|---|---|---|---|---|
| `mirror-rectangular.svg` | 方镜：自我形象、身体意象 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/mirror-rectangular.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `mirror-round.svg` | 圆镜：自我觉察、看自己 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/mirror-round.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |

### 骨牌

| 文件名 | 意象 | 来源 URL | 许可证 | 是否需署名 | 下载日期 |
|---|---|---|---|---|---|
| `domino-fall.svg` | 骨牌连锁：一件事推倒下一件（连锁反应／恶性循环） | —（原创，无上游） | NBDpsy 自有版权 | 否 | 2026-08-17 |

### 台阶

| 文件名 | 意象 | 来源 URL | 许可证 | 是否需署名 | 下载日期 |
|---|---|---|---|---|---|
| `ladder.svg` | 梯子：借助工具往上、外部支持 | https://raw.githubusercontent.com/tabler/tabler-icons/main/icons/outline/ladder.svg | MIT（Paweł Kuna / Tabler Icons） | 否（商用免署名） | 2026-08-17 |
| `stairs-up.svg` | 向上的台阶：进展、爬坡 | https://raw.githubusercontent.com/tabler/tabler-icons/main/icons/outline/stairs-up.svg | MIT（Paweł Kuna / Tabler Icons） | 否（商用免署名） | 2026-08-17 |
| `stairs.svg` | 台阶：分步骤、循序渐进 | https://raw.githubusercontent.com/tabler/tabler-icons/main/icons/outline/stairs.svg | MIT（Paweł Kuna / Tabler Icons） | 否（商用免署名） | 2026-08-17 |

### 延伸意象

| 文件名 | 意象 | 来源 URL | 许可证 | 是否需署名 | 下载日期 |
|---|---|---|---|---|---|
| `anchor.svg` | 锚：稳定化、抓地感（grounding） | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/anchor.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `bandage.svg` | 创可贴：处理伤口、临时办法 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/bandage.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `battery-low.svg` | 低电量：耗竭、倦怠 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/battery-low.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `brain.svg` | 大脑：神经机制、认知 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/brain.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `compass.svg` | 指南针：价值方向 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/compass.svg | MIT（Cole Bemis / Feather，经 Lucide 再分发） | 否（商用免署名） | 2026-08-17 |
| `droplets.svg` | 水滴：眼泪、一点一点积累 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/droplets.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `feather.svg` | 羽毛：轻盈、放下 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/feather.svg | MIT（Cole Bemis / Feather，经 Lucide 再分发） | 否（商用免署名） | 2026-08-17 |
| `key.svg` | 钥匙：解法、关键一步 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/key.svg | MIT（Cole Bemis / Feather，经 Lucide 再分发） | 否（商用免署名） | 2026-08-17 |
| `life-buoy.svg` | 救生圈：求助、危机支持 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/life-buoy.svg | MIT（Cole Bemis / Feather，经 Lucide 再分发） | 否（商用免署名） | 2026-08-17 |
| `link-2.svg` | 链环：联结、因果相连 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/link-2.svg | MIT（Cole Bemis / Feather，经 Lucide 再分发） | 否（商用免署名） | 2026-08-17 |
| `moon.svg` | 月亮：夜晚、失眠 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/moon.svg | MIT（Cole Bemis / Feather，经 Lucide 再分发） | 否（商用免署名） | 2026-08-17 |
| `mountain.svg` | 山：难题、要翻过去的东西 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/mountain.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `puzzle.svg` | 拼图：整合、缺失的一块 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/puzzle.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `scale.svg` | 天平：权衡、取舍 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/scale.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `shield-check.svg` | 盾牌打勾：边界、安全感 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/shield-check.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `sun.svg` | 太阳：希望、白天的力气 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/sun.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |
| `waves-horizontal.svg` | 波浪：情绪起伏、有起有落 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/waves-horizontal.svg | ISC（Lucide Icons and Contributors） | 否（商用免署名） | 2026-08-17 |

**小计**：63 个文件，合计 51.4 KB（单文件上限 20KB、目录上限 2MB，均达标）。

---

## 二、缺口与自绘补齐（如实记录，不拿不相干的图形凑数）

任务要求备齐的心理科普常用意象共 15 类。逐类核对结果：

| 意象 | 状态 | 说明 |
|---|---|---|
| 手 | ✅ 齐 | hand / hand-helping / hand-heart / handshake |
| 拥抱 | ⚠️ 无严格对应，用近似 | Lucide / Tabler / Heroicons 都**没有「两人相拥」**的图形。收了 heart-handshake（双手交握托心）、users-round（两个人）、friends（并肩两人）三个**近似替代**，文件头与本表均已标注「拥抱的近似替代」。需要真·拥抱时只能另找（CC-BY 图库居多，按红线跳过）或自绘。 |
| 植物与支架 | ✅ 齐（支架部分自绘） | 植物本体上游有 sprout / leaf / flower / tree-deciduous / plant-2；**「植物＋支架」上游全无**，已自绘 plant-stake.svg 补齐。 |
| 门 | ✅ 齐 | door-open / door-closed |
| 路 | ✅ 齐 | route / footprints / signpost / milestone |
| 灯 | ✅ 齐 | lamp / lightbulb / flashlight |
| 云雨 | ✅ 齐 | cloud / cloud-rain / cloud-sun / umbrella |
| 心 | ✅ 齐 | heart / heart-crack / heart-pulse ＋ 两个实心版 |
| 书 | ✅ 齐 | book-open / book / notebook-pen |
| 对话气泡 | ✅ 齐 | message-circle / messages-square / message-circle-heart |
| 时钟 | ✅ 齐 | clock / hourglass / alarm-clock |
| 镜子 | ✅ 齐 | mirror-round / mirror-rectangular（Lucide 近年新增，早期版本没有） |
| 骨牌 | ✅ 齐（自绘） | **上游全无 domino**（Lucide 只有 dice 骰子，语义完全不同，不拿来凑数），已自绘 domino-fall.svg。 |
| 台阶 | ✅ 齐 | Lucide 没有 stairs，取自 Tabler：stairs / stairs-up / ladder |
| 灯／路／门等其余 | ✅ | 见上 |

**自绘素材**（NBDpsy 原创，无第三方版权牵连）

| 文件名 | 意象 | 来源 | 许可证 | 需署名 | 创建日期 |
|---|---|---|---|---|---|
| `domino-fall.svg` | 骨牌连锁：一件事推倒下一件 | NBDpsy 自绘（对齐 Lucide 24×24 网格与 2px 线宽规范，未复制任何上游路径数据） | NBDpsy 自有版权 | 否 | 2026-08-17 |
| `plant-stake.svg` | 植物与支架：有支撑才长得直 | NBDpsy 自绘（同上） | NBDpsy 自有版权 | 否 | 2026-08-17 |
| `headphones.svg` | 耳机：听、陪伴、引导音频 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/headphones.svg | ISC（Lucide） | 否 | 2026-08-17 |
| `coffee.svg` | 咖啡杯：停下来、喘口气、日常时刻 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/coffee.svg | ISC（Lucide） | 否 | 2026-08-17 |
| `cup-soda.svg` | 冷饮杯：轻松、放松时刻 | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/cup-soda.svg | ISC（Lucide） | 否 | 2026-08-17 |

---

## 三、评估过但**未收**的图库（留档，省得下次重新查一遍）

| 图库 | 许可证核查结果 | 结论与理由 |
|---|---|---|
| **Heroicons** | MIT（tailwindlabs） | ✅ 许可合规，但图形语汇是 UI 功能图标（箭头、勾叉、界面元件），心理意象覆盖不如 Lucide／Tabler，且与已收两家混用会破坏线条一致性。**本轮未收**；将来若缺特定图形可随时补，合规无障碍。 |
| **unDraw** | 自有开放许可：可商用、免署名，但明文禁止「redistribute in packs」（打包再分发）与「compile assets to replicate a similar service」（核查日 2026-08-17，来源 https://undraw.co/license ） | ⛔ **不收**。本目录正是「打包成素材库随 skill 仓库分发」的形态，落在其禁止条款的灰区；且 unDraw 是多色扁平插画，无法用 currentColor 跟品牌色，风格也与赭红／暖米白冲突。 |
| **Humaaans** | CC0 公共领域（官网 humaaans.com 明示 "CC0 Free for commercial or personal use by Pablo Stanley"，核查日 2026-08-17） | ⚠️ 许可**合规**（CC0 连署名都不需要），但形态不合：多色人物插画、不可 currentColor 着色、单文件体积远超 20KB、需要在设计工具里拼装。**本轮不收**；将来若要做「人物插画风」封面可再引入，但必须人工重上色成品牌色。 |
| **Font Awesome Free** | 图标部分 CC-BY 4.0（需署名） | ⛔ 不收，按红线跳过署名类。 |
| **Noun Project** | 免费档为 CC-BY（需署名），去署名要订阅付费 | ⛔ 不收。 |

---

## 四、更新方法（不需要脚本，逐个 curl 即可）

```bash
LIB=/home/roots/nbdpsy-skills/nbdpsy-xiaohongshu-creator/assets/svg-library
# Lucide（ISC）
curl -sSL https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/<name>.svg -o $LIB/<name>.svg
# Tabler outline（MIT）
curl -sSL https://raw.githubusercontent.com/tabler/tabler-icons/main/icons/outline/<name>.svg -o $LIB/<name>.svg
```

拉下来之后**三件事必须做全**：

1. 删掉 Tabler 自带的元数据注释头，在文件顶部补上 NBDpsy 文件头注释（照抄库内任一文件的格式：意象／来源／许可证／需署名／下载日期）；
2. 给 `<svg>` 根加 `class="nbd-svg-icon"`（模板 CSS 靠它统一着色与线宽），保留上游的 `stroke="currentColor"`／`fill="currentColor"` 不动；
3. 回本表补一行，并确认单文件 ≤20KB、目录总体积 ≤2MB。

**Lucide 的一个坑**：Lucide 整体是 ISC，但其 LICENSE 里点名列出一批**派生自 Feather 的图标**，那些是 MIT（版权人 Cole Bemis）。
本表已逐个区分（本库涉及的 Feather 派生项：clock、compass、feather、key、life-buoy、link-2、moon）。两者都免署名，
差别只在版权声明写谁——照抄本表即可，别一律写成 ISC。

---

## 五、集合包台账（2026-08-17 扩库，**逐集合一行**）

> 手工件那 66 个是**逐文件**记的（§一、§二，原样不动）。这一节记的是另一层东西：
> 整包引进的图标集合，存放在 `collections/<前缀>/icons.json`。
> **逐条许可证不在这张表里，在 `svg_find.py` 的检索输出里现打**——理由见文件顶部「核对口径」。

**来源与形态**：`npm i @iconify-json/<前缀>` 取得，只把 `icons.json`（图标数据）与 `info.json`（元信息）
两个文件拷进本库，⛔ **node_modules 不进仓**。`icons.json` 里存的是 SVG 片段（`body`），
不是 38,239 个独立文件——要用时由 `svg_find.py --emit` 现拼成完整 SVG。

| 集合 | 前缀 | 许可证 SPDX | 作者 | 上游 LICENSE URL | 图标数 | 体积 | 入库日期 |
|---|---|---|---|---|---|---|---|
| Lucide | `lucide` | ISC | Lucide Contributors | https://github.com/lucide-icons/lucide/blob/main/LICENSE | 2053（1836 + 217 别名） | 0.6 MB | 2026-08-17 |
| Tabler Icons v3.45.0 | `tabler` | MIT | Paweł Kuna | https://github.com/tabler/tabler-icons/blob/master/LICENSE | 6426（6232 + 194 别名） | 2.0 MB | 2026-08-17 |
| Iconoir v7.11.0 | `iconoir` | MIT | Luca Burgio | https://github.com/iconoir-icons/iconoir/blob/main/LICENSE | 2020（1682 + 338 别名） | 0.6 MB | 2026-08-17 |
| HeroIcons v2.2.0 | `heroicons` | MIT | Refactoring UI Inc | https://github.com/tailwindlabs/heroicons/blob/master/LICENSE | 1297（1288 + 9 别名） | 0.6 MB | 2026-08-17 |
| Phosphor v2.1.1 | `ph` | MIT | Phosphor Icons | https://github.com/phosphor-icons/core/blob/main/LICENSE | 9198（9161 + 37 别名） | 4.4 MB | 2026-08-17 |
| Material Design Icons | `mdi` | Apache-2.0 | Pictogrammers | https://github.com/Templarian/MaterialDesign/blob/master/LICENSE | 14001（7638 + 6363 别名） | 3.0 MB | 2026-08-17 |

**合计 34,995 枚 / 11.2 MB**（`collections/` 目录实际占用 12 MB，含 `info.json` 与块对齐）。
全部 ✅ 级：**商用免署名**，与手工件同一条红线。
上游 LICENSE 全文已存进 `licenses/`（MIT / ISC / Apache-2.0 都要求再分发时保留声明，这就是履行方式）。

### ⚠️ 两处「Iconify 元数据与上游实际不符」（核查日 2026-08-17，⛔ 别照抄 info.json）

`icons.json` 同目录的 `info.json` 里有个 `license.spdx` 字段，**它是 Iconify 的二手记录，会过期**。
实测两处不符，本表以**上游 LICENSE 原文**为准：

| 集合 | info.json 写的 | 上游实际 | 影响 |
|---|---|---|---|
| `mdi` | `Apache-2.0` | 文件名叫 LICENSE，内容是 **Pictogrammers Free License**——正文写明「Icons: Apache 2.0」 | 结论不变（Apache-2.0、商用免署名）。上游**没有 NOTICE 文件**（实测 404），故 Apache-2.0 §4(d) 的 NOTICE 转录义务不触发 |
| `ri` | `Apache-2.0` | **已于 2026-01 换成自订 Remix Icon License v1.0**（旧的 Apache `LICENSE` 文件实测 404，现为 `License`） | ⛔ **因此没有入库**，见下 |

### ⛔ Remix Icon：评估后**不入库**（与 §三 unDraw 同一条红线）

- **许可证**：Remix Icon License v1.0（2026-01），全文留档 `licenses/ri-RemixIconLicense-v1.0-NOT-BUNDLED.txt`。
- **商用与署名**：§2.1 允许商用、§2.4 明写「Attribution … appreciated but not required」——**这两条本身没问题**。
- **卡住的是再分发**：§3.2「Prohibited: Competing Icon Libraries — You may NOT use the Icons to create,
  **distribute**, or sell a competing icon library or icon set」，**没有「仅限出售」的限定语**；
  §5 另要求「distributing the complete Icon library or substantial portions thereof」时随附许可证。
  而本目录正是「把整包 3,244 枚打包成素材库、随**公开仓库**分发」的形态——
  跟 §三 里 unDraw 被否掉的理由（「禁止 redistribute in packs」）是同一个形状。
- **结论**：按本库既有红线**不入库**。⚠️ 这是**合规灰区判断，不是黑白结论**——
  要推翻（认为 §2.3「作为更大产品的组成部分」足以覆盖），由老板拍板，加库只要一条命令：

  ```bash
  npm i @iconify-json/ri && cp node_modules/@iconify-json/ri/{icons,info}.json \
      nbdpsy-xiaohongshu-creator/assets/svg-library/collections/ri/
  # 再把 svg_find.py 里 COLLECTIONS 那条的 bundled 改成 True，并回本表补一行
  ```
- 在此之前，`svg_find.py` 对 `ri` 的一切请求都会**明确报出「故意没有入库 + 原因 + 加库命令」**，
  ⛔ 不会静默当成「没有这个图标」。

### 落地件：集合包里的图标怎么才能被 `render_cover.py` 用上

`render_cover.py` 有一道校验——**图标必须来自本素材库**，不在库就 exit 2 报红。它的判据是
平铺目录的 `SVG_LIB.glob('*.svg')`（**不递归**），且**拒收带 `lucide:` 前缀的名字**。

`collections/` 是子目录，那道 glob 看不见它 ⇒ **扩库没有把闸门弄松**：3 万多枚图标一枚都没被自动放行
（已实测：扩库后拿集合里的 `a-arrow-down` 喂进去，照样报红）。要用某一枚，必须显式**落地**：

```bash
python3 scripts/svg_find.py --emit tabler:mood-sad --install --note "低落的脸：说不出哪里不对劲"
# → 写出 assets/svg-library/tabler-mood-sad.svg（带 NBDpsy 文件头 + class="nbd-svg-icon"）
# → 此后 render_cover.py 的 icons 里写 "tabler-mood-sad" 即可
```

落地件的规矩：

1. **文件名一律 `<集合前缀>-<图标名>.svg`**，⛔ 不许用裸名——防止覆盖同名手工件（库里已有 `heart.svg`，
   落地 Tabler 的心就得叫 `tabler-heart.svg`）；
2. 许可证**由上表对应集合那一行覆盖**，⛔ 不必回 §一 补行（但文件头注释里会自动写清来源与许可证）；
3. 跨族取图记得归一线宽：`--stroke-width 2`（Iconoir 是 1.5，直接混进来会比周围细一档）。

**当前落地件清单**（1 个）：

| 文件名 | 来自 | 意象 | 许可证 | 落地日期 |
|---|---|---|---|---|
| `tabler-mood-sad.svg` | `tabler:mood-sad` | 低落的脸：说不出哪里不对劲 | MIT（见上表 Tabler 行） | 2026-08-17 |

### 体积口径的调整

§五 之前 README 里那条「目录总量 ≤2MB」是给**平铺手工件**定的，现在只对那一段有效
（当前 67 个文件共 268 KB，仍达标）。集合包另算一档：`collections/` 现 12 MB，
**上限定在 20 MB**——再多就该考虑只留同族两家（Lucide + Tabler 合计 2.6 MB）。
