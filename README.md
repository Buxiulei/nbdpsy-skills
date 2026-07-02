# nbdpsy-skills

NBDpsy 心理科普内容创作的五个 Agent Skill，覆盖「话题 → 官网 SEO 长文 → 小红书图文笔记 → 配图 → 竖屏短视频」全产线，每级产物都有对抗审查闸门。支持 **Claude Code** 与 **Codex** 一键安装。

| Skill | 作用 |
|-------|------|
| **seo-artical-creator** | 把心理科普主题写成面向 SEO + GEO 的 pillar 长文（查证优先 → GEO 化结构 → 合规校验 → 生成即发布），产物入官网博客。 |
| **xiaohongshu-creator** | 承接上面的长文，拆成多篇可直接发小红书的图文笔记：每篇 ~300 字正文 + 一套 6–9 页「PPT 式」轮播插图（每页含页面文字 + 可喂给 Gemini/GPT 的中文绘图提示词），并生成带一键复制按钮的 `preview.html`。 |
| **text-to-video** | 把长文 / 小红书笔记转成带中文字幕的竖屏短视频：即梦 Seedance 2.0 生成画面（走会员积分）+ 豆包 TTS 旁白 + 纯 ffmpeg 合成。可衔接 xiaohongshu-creator，给每篇笔记按「文生」或「图生」生成视频。**需另配** dreamina CLI 登录 + 豆包 TTS key（可选，见下）+ ffmpeg（首次跑 `text-to-video/scripts/check_env.py --install` 自检自装）。 |
| **content-reviewer** | 内容产线的对抗审查员：对长文 / 笔记 / 配图 / 视频四类产物先跑确定性检查脚本、再逐条「找茬」核对合规清单，产出 PASS/FAIL 审查报告。必须由独立子代理执行（生产者不自审），是发布前最后一道闸门。 |
| **content-pipeline** | 内容产线总导演：运营只给一个话题，说一句「做一期 XX 的全套内容」，就自动把长文创作→审查→拆笔记→审查→出图→审查→出视频→审查整条流水线串完，每级产物过审才进下一级。适合非专业兼职运营的傻瓜式入口；各生产 skill 也可单独使用。 |

> 这些 skill 为 NBDpsy（咨询师全员北大硕博的纯线上华人心理咨询工作室）定制，绑定其品牌话术、心理科普合规红线（YMYL）与数据库结构。**他人使用需按自己项目改造** SKILL.md 里的品牌 / 数据库 / 发布相关部分。

---

## 一键安装

### Claude Code（插件市场，推荐）

```text
/plugin marketplace add Buxiulei/nbdpsy-skills
/plugin install nbdpsy-content@nbdpsy-skills
```

装完重启 Claude Code，说「写一篇 XX 主题的 pillar 长文」「把这篇长文拆成小红书」或「做一期 XX 的全套内容」即会触发对应 skill。

### Linux / macOS（脚本安装）

```bash
git clone https://github.com/Buxiulei/nbdpsy-skills.git
cd nbdpsy-skills
./install.sh all      # 默认值，等价于不带参数直接跑 ./install.sh
# ./install.sh claude  # 只装 Claude Code（~/.claude/skills/）
# ./install.sh codex   # 只装 Codex（~/.agents/skills/ + ~/.codex/skills/ 符号链接）
# ./install.sh agents  # 只装 Agent 标准目录（~/.agents/skills/）
```

远程一行安装（不想先 clone）：

```bash
curl -fsSL https://raw.githubusercontent.com/Buxiulei/nbdpsy-skills/master/install.sh | bash
```

### Windows（脚本安装）

```powershell
git clone https://github.com/Buxiulei/nbdpsy-skills.git
cd nbdpsy-skills
.\install.ps1          # 默认 all；也可传 claude / codex / agents
```

远程一行安装：

```powershell
irm https://raw.githubusercontent.com/Buxiulei/nbdpsy-skills/master/install.ps1 | iex
```

---

## 安装位置对照

| 工具 | Skill 目录 | 安装方式 |
|------|-----------|---------|
| Claude Code（全局） | `~/.claude/skills/<skill>/` | `install.sh claude` / `install.ps1 claude`，或插件市场 |
| Claude Code（单项目） | `<repo>/.claude/skills/<skill>/` | 手动放置，脚本不装此层 |
| Agent 标准目录 | `~/.agents/skills/<skill>/` | `install.sh agents` |
| Codex | `${CODEX_HOME:-~/.codex}/skills/<skill>/` | `install.sh codex`（Linux/macOS 为指向 `~/.agents/skills` 的符号链接，Windows 为实拷贝） |

`all`（默认）三处都装。每个 skill 是一个含 `SKILL.md`（带 `name` / `description` frontmatter）的目录，各工具都按此约定原生加载。

---

## 安装后首次必跑：环境向导

```bash
python3 setup.py                # Linux/macOS
py setup.py                     # Windows
```

跑一遍：探测系统 → 装 ffmpeg / 中文字幕字体 → 装 Python 依赖 → 检测/引导装 dreamina CLI（视频生成用，可选）→ **凭据向导** → 每个 skill 冒烟测试（`--help` 级别）→ 打印终检报告。幂等，可反复跑。参数：`--yes`（非交互，能装的都装，凭据/dreamina 只报缺不问）、`--skip-credentials`（跳过凭据向导）。

**凭据向导会问 3 个 key：**

| 变量 | 是否必需 | 用途 | 缺失怎么办 |
|------|---------|------|-----------|
| `NBDPSY_BLOG_API_KEY` | 必需 | seo-artical-creator 调用官网博客发布 API | 管理后台 `manage.nbdpsy.com` → 博客 → API Keys 新建 |
| `VOLC_TTS_APPID` / `VOLC_TTS_ACCESS_TOKEN` | 可选 | text-to-video 豆包高音质旁白 | 留空跳过即可，旁白改用免费引擎 `tts_gen.py --engine edge` |

答案存进**用户级凭据文件**（`~/.config/nbdpsy/secrets.env`，Windows 为 `%APPDATA%\nbdpsy\secrets.env`，可用 `NBDPSY_SECRETS` 环境变量覆盖路径）——**在任何仓库之外，绝不会被 git 跟踪或提交**；向导只报「已配置」，不会读取或回显已存在凭据的真实值。`NBDPSY_BLOG_API_KEY` 由三个生产 skill 通过 `shared/nbdpsy_common.py` 的 `get_secret()` 统一读取（优先级：环境变量 > 内容工作区 `.env` > 用户级凭据文件）。

> `VOLC_TTS_*` 的凭据探测按三级链执行（优先级从高到低）：
> 1. **环境变量** — 当前 shell 已设置的值
> 2. **skill 目录 `.env`** — `cp text-to-video/.env.example text-to-video/.env` 后手填 `VOLC_TTS_APPID` / `VOLC_TTS_ACCESS_TOKEN` / `VOLC_TTS_CLUSTER`
> 3. **用户级凭据文件** — `~/.config/nbdpsy/secrets.env`（setup.py 向导写入的值）
> 
> 未在前两级配置时，text-to-video 会自动回退到用户级凭据；若三级都未配置，旁白改用免费引擎 `tts_gen.py --engine edge`。

**即梦（dreamina）视频生成需要另外扫码登录**，向导无法代劳：终端跑 `dreamina login --headless`，用**抖音 App 扫码**，凭据存本地 `~/.dreamina_cli/`；不装/不登录也不影响其余四个 skill。

---

## 工作区说明

各 skill 的产物（草稿、笔记、视频工作目录）都落在**内容工作区**，路径按以下顺序解析（`python3 <任一 skill>/scripts/nbdpsy_common.py workspace` 可查询实际路径）：

1. `NBDPSY_WORKSPACE` 环境变量——设了就优先用它。
2. 未设时，若当前目录下存在 `seo-geo/content`（如在 NBDpsy 仓库根运行）——用它，向后兼容旧约定。
3. 都没有——落回 `~/nbdpsy-content`。

---

## 工作流（五个 skill 串起来）

```
心理科普话题
   │  content-pipeline（一句话触发：「做一期 XX 的全套内容 / 一条龙 / 全流程」）
   │
   ├─① seo-artical-creator
   │     → 官网博客 pillar 长文（4000+ 字，查证优先，生成即发布，走 publish API）
   │     └─ content-reviewer 审查（checklist-article）
   │        FAIL → 报告交回定向返工 → 复审（最多 2 轮，仍 FAIL 停手找人）
   │
   ├─② xiaohongshu-creator（自动拉取 ① 刚发布的 slug）
   │     → 5–8 篇小红书图文笔记（发布文案 + 配图提示词 + preview.html）
   │     └─ content-reviewer 审查（checklist-note）→ 同返工协议
   │
   ├─③ 出图（宿主自适应，无独立 skill，属 xiaohongshu-creator 第 6 步）
   │     宿主有生图能力（如 Codex）  → 直接按提示词生成 images/post-NN/P01…PNN.png
   │     宿主无生图能力（如 Claude Code）→ 停下把 preview.html 给运营，
   │                                      人工用 Gemini/GPT 出图后回传同一路径 images/post-NN/
   │     └─ content-reviewer 审查（checklist-images）→ FAIL 只重出问题页
   │
   ├─④ text-to-video（driver 十步：解析笔记→精修分镜→逐镜旁白→写回时长→
   │     提交生成→并行取片→BGM→拼合成清单→合成→…）
   │     → 带中文字幕的竖屏短视频 final.mp4
   │     └─ content-reviewer 审查（checklist-video）→ FAIL 只重跑问题镜
   │
   └─⑤ 人工上传（小红书图文 / 视频号·抖音·B站短视频，均无发布 API，最后一步必人工）
```

各 skill 也可单独使用，不必经过 content-pipeline；content-reviewer 必须由独立子代理执行，生产 agent 绝不自审。

## 合规红线（五个 skill 共用）

- 不编造数字 / 出处 / 专家原话（YMYL 健康领域）。
- 不用「治疗 / 诊断 / 治愈 / 医院 / 医生」自我描述；不用极限词；不夸大。
- 小红书侧额外：任何位置不放站外导流（微信 / 二维码 / 外链）。
- 视频侧额外：图内不出现文字（CJK 渲染必乱码）；driver 产线默认打「AI 生成」角标。
- 危机声明（全国统一心理援助热线 12356）每篇 / 每条在位。
- 生成产线只在开发机/专用机跑，**绝不部署到生产服务器**。
