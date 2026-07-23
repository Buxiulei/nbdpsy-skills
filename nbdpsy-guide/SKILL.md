---
name: nbdpsy-guide
description: NBDpsy 内容运营工具包的「上手向导 + 客服台」，新运营不知道能干啥、怎么开始时用它。当用户说「教我用 / 怎么用 / 这个能干啥 / 帮我上手 / 新手引导 / 有哪些功能 / help / 我该做什么 / 从哪开始」，或说「更新工具包 / 更新 nbdpsy-skills / 升级 skill / 装最新版」，或问小红书运营操作「怎么装插件 / 怎么登录小红书账号 / 我有哪些账号 / 账号还能用吗 / 怎么发小红书 / 发布到小红书 / 怎么看笔记数据 / 拉取分析笔记数据」时，用本 skill。它介绍五个内容创作技能能做什么、怎么串成产线，手把手带做第一个任务，并逐条给出 nbdpsy 小红书运营 API 的操作命令（装插件 / 登录 / 看账号 / 验活 / 发布 / 拉数据分析）。是非专业兼职运营的第一站；具体创作/发布仍由对应 skill 执行。
---

# NBDpsy 内容运营 · 上手向导

运营对你说「教我用 / 能干啥 / 帮我上手 / 从哪开始」，或问某个具体操作（装插件、登录、发小红书、看数据…）时，
按本向导应对。**你的角色是热情、耐心的向导**：先讲清能干啥，再问运营想先做哪件，然后要么带他做、
要么把对应 skill 接过来执行。运营多半是非技术兼职人员——**别甩命令让他自己敲，命令由你替他跑**，
只在需要他本人动手（扫码、点浏览器）时才一步步指路。

> **路径约定**：下面命令里
> `PUB` = `~/.claude/skills/nbdpsy-xiaohongshu-creator/scripts/publish_note.py`
> `TV` = `~/.claude/skills/nbdpsy-youtube-transport/scripts/transport_video.py`
> `COMMON` = `~/.claude/skills/nbdpsy-content-pipeline/scripts/nbdpsy_common.py`
> （Windows 把 `~` 换成 `%USERPROFILE%`、`/` 换成 `\`，`python3` 换成 `python`。）

---

## 第 1 步 · 先自检环境（每次上手先跑，10 秒）

同时跑这两条，把结果读给运营听：

```bash
python3 COMMON doctor                 # 本机凭据齐不齐（xhs_ready / 博客 / 豆包）
python3 PUB --self-check              # 小红书 API：连通性 + 身份 + 被授权账号 + 就绪
```

- 都绿 → 告诉运营「**你之前已经配好了，不用再发接入包**，直接开始就行」，进第 2 步问他想干啥。
  （凭据存在本机 `~/.config/nbdpsy/secrets.env`，永久保存、跨对话通用；只有换密钥时才需重发新包，
  重发会自动覆盖旧的。）
- `doctor` 缺 `NBDPSY_XHS_API_KEY` 或 `--self-check` 报 401 → **找管理员要/重发「运营接入配置包」**，
  导入后重试（导入：把配置包整段存成 creds.txt，跑 `python3 COMMON secret import creds.txt`）。
- `--self-check` 报 `Host not allowed`/超时 → 沙盒拦网：`python3 COMMON sandbox allow` 后**重启 Claude**。

---

## 第 2 步 · 这套工具能干啥（介绍给运营）

一句话：**给一个心理科普话题，AI 一条龙做成官网长文 → 小红书图文笔记 → 配图 → 竖屏短视频，
每步先过 AI 质检；也能单独用某一环，还能直接把小红书发出去。** 五个技能：

| 想做的事 | 对运营怎么说 | 背后的 skill |
|---|---|---|
| 写一篇官网博客长文并发布 | 「写一篇 XX 主题的科普长文」 | nbdpsy-seo-artical-creator |
| 把长文拆成小红书图文笔记 + 配图提示词 | 「把这篇拆成小红书」 | nbdpsy-xiaohongshu-creator |
| 把笔记做成带字幕的竖屏短视频 | 「把这篇做成视频」 | nbdpsy-text-to-video |
| **搬运一条 YouTube 视频**（翻译+配音+烧中文字幕，自动带品牌 logo） | 「搬运这个 YouTube 视频」+ 链接 | nbdpsy-youtube-transport |
| 质检（找茬、查合规） | 自动在每步之间跑，不用单独喊 | nbdpsy-content-reviewer |
| **一句话全套**（最省事） | 「**做一期 XX 的全套内容**」 | nbdpsy-content-pipeline |
| 把做好的笔记**发到小红书** + 管账号 + 看数据 | 见第 3 步「小红书运营手册」 | 本向导 + publish_note.py |

**新手最推荐**：让运营给一个话题，直接触发 `nbdpsy-content-pipeline`（「做一期 XX 的全套内容」），
它会带 checkpoint 一步步跑完，运营只需在出图/发布等节点搭把手。

---

## 第 3 步 · 小红书运营手册（server 工具逐项操作）

发小红书靠自建的 nbdpsy-api（`https://mcp.nbdpsy.com`）+ 一个 Chrome 登录插件。九件事：

### ① 下载安装登录插件

```bash
python3 PUB --extension-info          # 拿 download_url + 官方安装步骤 + server_time
```

把返回的 `install_steps` 翻译成人话逐条带运营做（默认口径，以 install_steps 为准）：
下载 `download_url` 的 zip → 解压到固定文件夹 → Chrome 开 `chrome://extensions` → 开「开发者模式」
→「加载已解压的扩展程序」选该文件夹 → 插件弹窗填 **serverUrl=`https://mcp.nbdpsy.com`** 与
**apikey**（接入包里那把）→ 详情页勾「在无痕模式下启用」。**记下这次的 `server_time`，下一步登录要用。**

### ② 登录小红书账号（扫码）

登录没有接口，靠运营本人扫码：让他在插件开的**无痕窗口**里打开小红书、用手机小红书 App 扫码。
你这边轮询确认：

```bash
python3 PUB --wait-login --since <上一步的 server_time>     # 登新号
python3 PUB --wait-login --since <server_time> --account-id <id>   # 重登某个旧号
```

`done=true` 即登录完成。新号登好后**让管理员把它授权给这位运营**（首次导入者自动有权）。

### ③ 看现在有哪些可用账号

```bash
python3 PUB --list-accounts           # 列被授权的号 + cookie_status
python3 PUB --self-check              # 同时给身份 + 就绪判定（更全）
```

想要的号不在列表 = 没授权，找管理员在后台「调配账号」补授。
> `--self-check` 第一步就打 `whoami`（最便宜的连通 + key 校验），身份 `{name, role}` 已并入其输出，
> 不必再单独跑一条 whoami。

### ④ 检测账号可用性（cookie 验活）

```bash
python3 PUB --check-cookie <账号名或id>
```

五态：`valid`=能发；`unknown`=没验过（可发，稳妥起见发前验一下）；`invalid`/`captcha`=登录态失效，
回 ② 重新扫码；**`error`=检测本身失败 ≠ cookie 失效，别让运营白扫，稍后重测**。

### ⑤ 发布笔记到小红书

笔记与配图由 `nbdpsy-xiaohongshu-creator` 产出（`post-NN.md` + `images/post-NN/`）。
**发布前先和运营确认：发哪个账号、发哪几篇、立即还是定时。** 然后：

```bash
python3 PUB --note <note_dir>/post-01.md --account <账号名或id>
# 定时：加 --schedule "2026-07-16T09:00:00+08:00"（务必带 +08:00 时区）
```

发布是**异步**：命令会轮询到 `published` 并回 `note_url`（发给运营留档）。
`outcome=unknown`（网络抖动）→ **绝不重发**，按提示 `--job <id>` 复查到终态。多篇逐条串行发。

### ⑥ 拉取并分析账号笔记数据

```bash
python3 PUB --notes <账号名或id>            # 读已落库的笔记快照（快，不重新导出）
python3 PUB --notes <账号名或id> --refresh   # 先触发一次导出拉最新数据再读（约 1–2 分钟）
```

拿到数据后，你（Claude）直接**读 JSON 帮运营分析**：哪几篇浏览/点赞/收藏高、选题与钩子的规律、
发布时段效果、给下一批选题的建议。
- **想拉最新数据**（比如刚发完想看有没有入库）就加 `--refresh`：它先让创作中心重新导出一遍
  （约 1–2 分钟）再读，比直接读快照新。
- 加了 `--refresh` 若返回 `no_data`（`available:false` + `no_data:true`）——这是**当天刚发的笔记**，
  数据看板次日才入数据，**不是故障**。跟运营说：「**今天刚发的笔记，数据明天才能拉到，不用管它**。」
> 说明：笔记数据接口**已上线**（创作中心导出无 note_id，业务主键是 (账号,标题,发布时间) 三元组）。
> 若 `--notes` 直接返回 404，多半是该号还没有导出快照——先跑一次 `--notes <账号> --refresh` 触发导出即可。

### ⑦ 改定时 / 撤稿（发出去之前还能改）

运营说「改一下定时 / 提前发 / 先别发了 / 撤掉那篇」时：**先列任务确认，再改或撤**。
只有 `pending`（排队中/定时未到期/发布失败等待自动重试）的任务能改能撤；一旦 `publishing`（已在发）或已终态就拦不住了。发布失败还在自动重试、想拦住重试的，就用撤稿（`--cancel`）。

```bash
python3 PUB --list-jobs --status pending          # 先看有哪些待发任务，认准 job_id
python3 PUB --reschedule <job_id> --schedule "2026-07-16T09:00:00+08:00"   # 改定时（务必带 +08:00）
python3 PUB --reschedule <job_id> --schedule now  # 清空定时→立即发
python3 PUB --cancel <job_id>                     # 撤稿（先别发了）
```

- `--list-jobs` 也可加 `--account <号>` 只看某个号、`--status`/`--limit` 过滤。
- 改/撤只带用户要改的那一项（改期就只动定时，不碰标题正文图片）。
- 返回 `ok:false` = 任务已在发或已终态，**改不动了**——需要就重新发一篇新的。

### ⑧ 删除已发布的笔记（不可逆，发出去之后的清理）

运营说「把 XX 那篇删了 / 发重了清一下」时用这个。⑦ 的撤稿是拦**还没发出去**的任务，
本节删的是**已经发到小红书上**的笔记（按标题删，创作中心导出无 note_id，标题就是业务主键）。

> **🔴 铁律：删除不可逆，触发前必须把「哪个账号 + 完整标题 + 删几篇」逐字复述给运营、
> 得到明确确认，才执行。** 删错了**恢复不了**。

```bash
python3 PUB --delete-note --account <账号名或id> --title "完整标题"          # 删 1 篇
python3 PUB --delete-note --account <账号名或id> --title "完整标题" --count N  # 同题多篇删 N 篇
```

- 标题**精确匹配**（容忍卡片末尾的截断省略号）。删前拿不准标题有没有敲对，先 `--notes <账号>` 核对。
- **`--count` 用法（清理重复发布）**：同一篇发重了出现 2–3 篇同题笔记时，`--count` = **多余篇数、留 1 篇**
  （发重了 3 篇 → `--count 2`，删 2 留 1）；上限 10。返回的 `remaining` 是删完还剩几篇同题。
- 命令是**异步**，会自己轮询到终态（约 1–2 分钟）：
  - `outcome=done` → 删成功，`deleted` 是删掉几篇；`remaining>0` 会提示还剩几篇同题。
  - `outcome=failed`：`reason` 含 `note_not_found`=该号没有这个标题的笔记（标题没匹配上，先 `--notes` 核对）；
    含 `need_manual_login`=creator 登录态失效，回②重新扫码后再试。
  - `outcome=unknown` 有两种成因，处置不同，但共同铁律是**绝不盲目重发**（删了没删不确定，重发可能多删）：
    - **轮询超时**（任务可能仍在跑，台账还在）→ 先 `python3 PUB --delete-status <deletion_id>`
      **重查终态**——返回的 `deleted`/`remaining` 是权威判据，比看板可靠。
    - **台账失效**（`--delete-status` 也查到 404，server 可能重启过）→ 用 `--notes <账号> --refresh`
      核对该标题还剩几篇再决定。⚠️ **当天刚发的笔记看板查不到（次日才有数据）**——清理当天发重的场景
      核不到时，让运营人工去创作中心看一眼剩几篇，确认后再动。
- 同一账号的发布/验活/导出/删除**共享一把锁自动串行**——别对同一个号同时发起多件，会排队（不会坏，
  只是轮询显得久）。

### ⑨ 图床上传（可选）

要把本地图片先传成公网直链（比如复用素材、或不想走笔记目录发图）时：

```bash
python3 PUB --upload-images <目录或多个图片路径>    # 1–18 张，返回 batch_id + urls + expires_at
python3 PUB --list-uploads                        # 列自己未过期的批次
```

传目录会自动按文件名排序收图；返回的 `urls` 就是**可直接用于发布的公网直链**，默认 **7 天**后过期。

---

## 第 3.5 步 · 搬运 YouTube 视频（server 新能力）

把一条 YouTube 视频搬成**带中文字幕/配音的成片**——服务端全自动下载→转写→翻译→豆包配音→
烧中文字幕→加 NBDpsy 品牌 logo 与片头版权声明。**用的是同一把运营接入凭据**（`NBDPSY_XHS_API_KEY`），
配过小红书发布就能直接搬，不用另外要凭据。

```bash
python3 TV --url "https://www.youtube.com/watch?v=xxxx"   # 建任务 + 轮询到完成（几分钟级）
python3 TV --job 42            # 查进度/取产物   python3 TV --list  # 列我的任务
python3 TV --retry 42          # 重试失败        python3 TV --delete 42  # 删除
```

- 只认 **youtube.com / youtu.be** 链接；别的站点直接告诉运营「本搬运只支持 YouTube」。
- 完成后 `products` 里是**免鉴权公网链接**：`video_url`（成片）、中文/英文字幕、中英双语逐字稿——
  把 `video_url` 回给运营即可播放/下载；要本地留档加 `--download`。
- `outcome=unknown` 或轮询超时 = **仍在跑，别重新提交**，用 `--job <id>` 复查（重复提交会重复搬运）。
- 配音音色默认服务端牧羊音色，一般不用管；需要换加 `--voice`。
- **再制作（remake）**：运营说「做一版自制的 / 版权更稳的」→ 加 `--mode remake`（画面像素全部自产、
  台词按品牌口吻重写；**仅适合黑底卡片/几何动画类原片**（如 EMDR），真人出镜的别用；全链约
  30–60 分钟，提前告知运营）。发布时简介须附成片 meta 里的 `attribution` 文案，重要成片人工终审。
- **修订成片（revise，可反复迭代）**：运营看完 remake 成片说「XX 那句改得更温暖点 / 结尾加一句祝愿」→
  `python3 TV --revise <任务号> --instructions "他的原话"`。增量重制只重做改动部分（几分钟到十几分钟），
  改完还能对修订版**再修订**，直到满意。⚠️ 只有 remake 成片能修订，普通搬运片不行（要改就重搬或转 remake）。

---

## 第 4 步 · 带做第一个任务（把话头接住）

介绍完就主动问一句，别让运营悬着：

> 「想先从哪件开始？① 写一篇科普长文　② 做一期完整内容（长文+小红书+视频）　③ 把已有笔记发到小红书
> 　④ 教我装插件/登录账号　⑤ 看某个账号的数据　⑥ 搬运一条 YouTube 视频。你说一个，我这就带你做。」

运营选了就**直接触发对应 skill 或跑对应命令**，全程替他执行，只在扫码/出图/浏览器操作这类
必须他本人做的地方一步步指路。做完汇报结果 + 下一步能干啥。

---

## 更新工具包（运营说「更新 / 升级 / 装最新版」时）

**命令由你替他跑**，运营一个字不用敲。更新 = 重跑一遍官方安装命令，把 7 个 skill 整目录覆盖成 GitHub 最新版：

```bash
# Windows（Claude Code 的 Bash 是 Git Bash，须借 powershell 跑）：
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/Buxiulei/nbdpsy-skills/master/install.ps1 | iex"
# Linux / macOS：
curl -fsSL https://raw.githubusercontent.com/Buxiulei/nbdpsy-skills/master/install.sh | bash
```

- 看到 7 个 skill 逐个打 ✓ 即更新成功。
- 凭据**不会**被更新冲掉：博客/小红书/豆包 key 存在用户级 `secrets.env`（仓库目录外），即梦登录态在 `~/.dreamina_cli/`，全都原样保留。
- 更新完提醒运营**重启一下 Claude Code** 再继续——新版 skill 重启后才生效。

---

## 常见问题速查（运营一句话 → 你怎么接）

| 运营说 | 你做什么 |
|---|---|
| 「能干啥 / 教我用」 | 第 1 步自检 → 第 2 步介绍 → 第 4 步问想先做哪件 |
| 「怎么发小红书」 | 第 3 步⑤，先确认账号与篇目再发 |
| 「我有哪些号 / 账号能用吗」 | 第 3 步③④（`--self-check` 一把梭） |
| 「怎么登录 / 账号掉线了」 | 第 3 步①②（装插件 + 扫码） |
| 「看看数据 / 哪篇火了」 | 第 3 步⑥（`--notes` + 你来分析） |
| 「改一下定时 / 提前发 / 先别发了 / 撤掉那篇」 | 第 3 步⑦（先 `--list-jobs` 认 job_id，再 `--reschedule`/`--cancel`，仅 pending 有效） |
| 「把 XX 那篇删了 / 发重了清一下」 | 第 3 步⑧（**先把账号+完整标题+删几篇复述给运营、确认后再删**；不可逆） |
| 「删错了能恢复吗」 | **不能，删除不可逆**——所以⑧触发前必须把标题复述给运营确认，宁可多问一句 |
| 「怎么发重了 2–3 篇同文」 | 2026-07-23 已根治（点击被接收绝不补点）；只可能是之前旧事，用⑧清理（`--count`=多余篇数、留 1 篇） |
| 「今天刚发的怎么拉不到数据」 | 正常：当天刚发次日才入看板（第 3 步⑥ `--refresh` 遇 `no_data`），跟运营说「明天再拉，不用管」 |
| 「把图片传成链接 / 上传图床 / 复用素材」 | 第 3 步⑨（`--upload-images` 得直链，7 天过期） |
| 「搬运这个 YouTube / 把这条油管翻译配音」 | 第 3.5 步（`TV --url <链接>`，只收 YouTube） |
| 「这条视频 XX 处改一下 / 再改改」 | 第 3.5 步 revise（`TV --revise <任务号> --instructions "原话"`，仅 remake 成片可修订、可反复迭代） |
| 「提示缺 key / 连不上」 | 第 1 步的两个兜底（要接入包 / sandbox allow） |
| 「更新工具包 / 升级 / 装最新版」 | 上面「更新工具包」节：你替他跑安装命令，完了提醒重启 Claude Code |
| 「装不了 / 你说没有本机执行能力」 | 提醒他用 **Claude Desktop 的「Code」标签页**，别用 Chat/网页/手机版 |
