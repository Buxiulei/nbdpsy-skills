# nbdpsy-skills 工具包优化 验收记录（2026-07-02）

对应计划：NBDpsy `docs/superpowers/plans/2026-07-02-nbdpsy-skills-optimization.md`（22 任务全部完成）
对应 spec：`docs/superpowers/specs/2026-07-02-nbdpsy-skills-optimization-design.md` v2 §11 验收标准

## 验收结果总览

| 项 | 结果 | 说明 |
|----|------|------|
| §11.1 干净环境安装 | ✅ | 临时 HOME：install.sh all → 5+5 目录 + 5 symlink；setup.py --yes --skip-credentials 凭据报缺 exit 1（预期）；远程 curl\|bash 一行安装恰 5 skill |
| §11.2 API 发布 | ✅ | --draft 发布 → 409 幂等跳过 → 生产 DELETE 清理闭环；本轮多次真跑（含 pipeline 演练 id=38） |
| §11.3 拉文+拆分校验 | ✅ | fetch --list 3 恰 3 条；--slug 拉真实文章 → count_hanzi ok:true；count_xhs/check_compliance fixture 全绿 |
| §11.4 视频链 | ✅ | parse_note(6镜)→tts edge --timed→sync_durations(missing 语义+写回)→build_manifest(cues 显式)→compose 成片→check_video 交叉校验（Σ镜=final 检测有效） |
| §11.5 审查对抗自检 | ✅ | 4 个坏样本全部 FAIL 且植入毛病 17/17 全中；良品判 FAIL 系抓到范文真实瑕疵（见下），属过度尽职非误报 |
| §11.6 pipeline 演练 | ✅ | 编排全流程（替身裁剪）：审查首行判读、--draft 发布、出图 Claude 分支停等话术完整、中断恢复判据明确 |
| §11.7 Codex | ⚠️ 部分 | codex-cli 0.142.5 安装成功、~/.codex/skills 5 symlink 就位；交互触发因无 OpenAI 登录态未实测（留真机） |
| Windows | ⚠️ 留验 | install.ps1 语法/BOM/guard 已静态核验（本机无 pwsh），真机行为留 Windows 侧验证 |
| 最终全量 review | ✅ Ready to ship | fable 终审：跨模块契约 5 项一致、全历史凭据扫描干净、README 三承诺在位 |

## 对抗自检明细（盲测，审查者不见毛病清单）

| 样本 | 植入毛病 | 结果 |
|------|---------|------|
| 坏长文 | 编造引用/无源数字/字数/治愈措辞/缺危机声明（5） | FAIL，5/5 命中，连 .invalid 保留域名都识别 |
| 坏笔记 | 超字数/治愈/微信号导流/缺12356/页数不符（5） | FAIL，5/5 命中 |
| 坏图组 | 缺P03/500×500/刺眼撞色（3） | FAIL，3/3 命中 + 额外抓渲染空壳、人物缺失 |
| 坏视频 | duration超限/实际≠声称/cues逆序/缺manifest（4） | FAIL，4/4 命中 |
| 良品长文 | 无 | FAIL——抓到范文三处真实瑕疵：CDC 引用 301 漂移至导航页、一条孤儿参考文献、ICD-11 生效年份误差（2019→实为 2022） |

**盲测额外战果（已全部加固落地 4eacff2）**：check_video 不对照 shots.json 声明镜数、check_compliance 导流词表缺「微信」裸词变体、合规扫描不含配图页面文字。

## 遗留事项

1. **内容层跟进（NBDpsy 侧，非工具包）**：线上 CPTSD 文章（blog id=3）可能与范文同源存在 CDC 引用漂移与 ICD-11 年份误差，建议编辑核修。
2. **Windows 真机**：install.ps1 / setup.py winget 分支 / py setup.py 全链留 Windows 机器实测。
3. **Codex 交互触发**：CLI 已装（0.142.5）+ skills 目录就位；`$nbdpsy-seo-artical-creator` 显式与描述隐式触发留登录后实测。
4. **dreamina Windows**：官方 CLI 未验证 Windows，Windows 出片建议 WSL（setup.py 已引导）。
5. **Backlog（终审 triage 判定可延后）**：publish_post slug/title 显式空值兜底（一行）；parse_note 回退分支标记行混入；check_images 两防御分支补测试；金范例补视频参考图节（注意双副本齐改）；nbdpsy-content-pipeline 补「以报告首行为准」一句；checklist-video 非心理主题 12356 豁免口径；NBDpsy external GET 回读五字段。
6. **不修（终审判定）**：sync_durations 死变量/stderr 文案、OSError 元组冗余、setup 终检表 CJK 对齐、测试 reload 仪式。

## 关键运维事实

- 发布 API Key：生产 blog_api_keys id=2（prefix nbdblog_KcHVzxIo，永不过期），本机存 `~/.config/nbdpsy/secrets.env`
- 豆包 TTS 凭据已从旧 skill .env 迁入用户级 secrets（tts_gen 三级链可读）
- NBDpsy 仓库已删除三 skill 副本（22e39862+7741bca1），唯一真源=本仓库；本机为全局安装
