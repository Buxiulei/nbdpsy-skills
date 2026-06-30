# nbdpsy-skills

NBDpsy 心理科普内容创作的三个 Agent Skill，支持 **Claude Code** 与 **Codex** 一键安装。

| Skill | 作用 |
|-------|------|
| **seo-artical-creator** | 把心理科普主题写成面向 SEO + GEO 的 pillar 长文（查证优先 → GEO 化结构 → 合规校验 → 生成即发布），产物入官网博客。 |
| **xiaohongshu-creator** | 承接上面的长文，拆成多篇可直接发小红书的图文笔记：每篇 ~300 字发布文案 + 一套 6–9 页「PPT 式」轮播插图（每页含页面文字 + 可喂给 Gemini/GPT 的中文绘图提示词），并生成带一键复制按钮的 `preview.html`。 |
| **text-to-video** | 把长文 / 小红书笔记转成带中文字幕的竖屏短视频：即梦 Seedance 2.0 生成画面（走会员积分）+ 豆包 TTS 旁白 + 纯 ffmpeg 合成。可衔接 xiaohongshu-creator，给每篇笔记按「文生」或「图生」生成视频。**需另配** dreamina CLI 登录 + 豆包 TTS key + ffmpeg（首次跑 `text-to-video/scripts/check_env.py --install` 自检自装）。 |

> 这些 skill 为 NBDpsy（咨询师全员北大硕博的纯线上华人心理咨询工作室）定制，绑定其品牌话术、心理科普合规红线（YMYL）与数据库结构。**他人使用需按自己项目改造** SKILL.md 里的品牌 / 数据库 / 发布相关部分。

---

## 一键安装

### Claude Code（插件市场，推荐）

```text
/plugin marketplace add Buxiulei/nbdpsy-skills
/plugin install nbdpsy-content@nbdpsy-skills
```

装完重启 Claude Code，说「写一篇 XX 主题的 pillar 长文」或「把这篇长文拆成小红书」即会触发对应 skill。

### Codex / 通用（脚本安装）

```bash
git clone https://github.com/Buxiulei/nbdpsy-skills.git
cd nbdpsy-skills
./install.sh codex      # 装到 Codex（~/.codex/skills/）
# ./install.sh claude   # 装到 Claude Code（~/.claude/skills/）
# ./install.sh both     # 两个都装
```

远程一行安装（不想先 clone）：

```bash
curl -fsSL https://raw.githubusercontent.com/Buxiulei/nbdpsy-skills/master/install.sh | bash -s -- both
```

---

## 安装位置对照

| 工具 | Skill 目录 |
|------|-----------|
| Claude Code（全局） | `~/.claude/skills/<skill>/` |
| Claude Code（单项目） | `<repo>/.claude/skills/<skill>/` |
| Codex | `${CODEX_HOME:-~/.codex}/skills/<skill>/` |

每个 skill 是一个含 `SKILL.md`（带 `name` / `description` frontmatter）的目录，两个工具都按此约定原生加载。

---

## 工作流（两个 skill 串起来）

```
心理科普主题
   │  seo-artical-creator
   ▼
官网博客 pillar 长文（4000+ 字，已发布）
   │  xiaohongshu-creator
   ▼
5–8 篇小红书图文笔记（发布文案 + 每页配图中文提示词 + preview.html）
   │  ① 人工：文案粘进小红书，提示词喂 Gemini/GPT 出图（3:4，首图当封面）
   │  ② text-to-video（可选衔接）：每篇笔记 → 一条竖屏短视频
   │     文生 = 页面提示词→Seedance 文生；图生 = 用已出的图→image2video
   ▼
发布（小红书图文 / 视频号·抖音短视频）
```

## 合规红线（三个 skill 共用）

- 不编造数字 / 出处 / 专家原话（YMYL 健康领域）。
- 不用「治疗 / 诊断 / 治愈 / 医院 / 医生」自我描述；不用极限词；不夸大。
- 小红书侧额外：任何位置不放站外导流（微信 / 二维码 / 外链）。
- 危机声明（全国统一心理援助热线 12356）每篇在位。
