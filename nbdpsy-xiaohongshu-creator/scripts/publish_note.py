#!/usr/bin/env python3
"""把 nbdpsy-xiaohongshu-creator 产出的图文笔记发布到小红书（经 nbdpsy-api，纯 REST）。

流程：解析 post-NN.md 的 frontmatter + 「## 发布文案」块 → 收集配图（base64 内联）→
POST {base}/api/publish-jobs（异步 202 拿 job_id）→ 轮询 GET /api/publish-jobs/{job_id} 到终态。

用法：
    python3 publish_note.py --note post-01.md --account 账号名或ID
        [--images-dir DIR] [--schedule "2026-07-14T09:00:00+08:00"]
        [--api-base URL] [--no-wait] [--wait-timeout 900] [--dry-run]
        [--collection-id N] [--quoted-note-id ID] [--activity-id N]
        [--related-counselor 姓名] [--note-purpose 推介咨询师]
    python3 publish_note.py --job 42            # 只查已提交任务的状态
    python3 publish_note.py --list-jobs [--account 号] [--status pending] [--limit N]  # 列发布任务
    python3 publish_note.py --reschedule 42 --schedule "2026-07-16T09:00:00+08:00"    # 改定时
    python3 publish_note.py --reschedule 42 --schedule now   # 清空定时→立即发（仅 pending）
    python3 publish_note.py --cancel 42         # 撤稿（仅 pending 任务可取消）
    python3 publish_note.py --upload-images DIR|文件...   # 上传图片得图床直链（1–18 张，7 天过期）
    python3 publish_note.py --list-uploads      # 列自己未过期的图床批次
    python3 publish_note.py --list-accounts     # 列出我可操作的小红书账号
    python3 publish_note.py --self-check        # 一键接入自检：whoami+身份+账号+就绪（可反复跑）
    python3 publish_note.py --notes 账号名或ID   # 拉该账号已发布笔记数据（供分析；已上线，(账号,标题,发布时间) 三元组主键）
    python3 publish_note.py --notes 账号名或ID --refresh   # 先触发一次导出拉最新数据再读（约 1–2 分钟）
    python3 publish_note.py --delete-note --account 号 --title "标题" [--count N]
                                                # 按标题删除已发布笔记（不可逆！触发前须与运营确认账号+标题+删几篇）
    python3 publish_note.py --delete-status <deletion_id>   # 重查删除终态（超时后的首选复查通道）
    python3 publish_note.py --extension-info    # chrome 插件下载地址+安装步骤+server_time
    python3 publish_note.py --wait-login --since <server_time> [--account-id N]
                                                # 等运营扫码登录完成（新号不传 account-id）
    python3 publish_note.py --check-cookie 账号名或ID   # 触发 cookie 验活并轮询到结果
    python3 publish_note.py --artifacts <job_id> [--out 目录] [--artifact-name 文件名]
                                                # 取该次发布的现场截图（排障；空清单不是异常）
    python3 publish_note.py --check-cover <首图>   # 只验封面产出凭证（出图后、发布前自查）
    python3 publish_note.py --confirm-cover <首图> --confirmed-by <姓名>  # 批量顺带出的封面：补单出确认戳
    python3 publish_note.py --ledger-check [路径]  # 读欠账（fresh agent 接手第一件事）

三道结构闸门（2026-08-14 起写成代码，此前图文线上只是文档里的一句话——「文字挡不住手快的执行者」）：
  闸门 A · 封面产出凭证：**图文的封面＝第一张图（P01）**，发布前逐篇校验同名 `P01.meta.json`
      （实现见 `check_cover_receipt`，图文/视频/播客三形态共用这一个函数，⛔ 别再抄第二份）。
      无凭证拒发；凭证比封面图旧也拒发（图比凭证新＝重出图后没更新凭证，凭证与文件脱钩）；
      凭证记的是**批量顺带出的封面**（`cover_only != true`）且无人工确认戳也拒发——
      那张 P1 没人看过缩略图就把已确认的封面覆盖了，补救＝重新 `--cover-only` 单出，或 `--confirm-cover`。
  闸门 B · 无 job 不发：本脚本每个动作都建一条 server 侧 job，⛔ 手搓 payload 直调 API 是违规路径。
  闸门 C · 台账先行 + 回读差集：提交前先往 `publish-ledger.md` 落一行「意图」，拿到终态回执后
      回填「实际」并算差集。**差集非空 ＝ 本批不许报完成**（exit 3）。
      台账**只落在稿件/媒体同目录**（或显式 `--ledger`；复查时也认 cwd 里**已存在**那份）——
      ⛔ 绝不在 cwd 推导的位置**新建**（2026-08-16 事故：单独跑复查时台账被新建到了 NBDpsy
      仓库根，真台账永远闭不掉）。
      差集会**合并事后补救任务的终态**（台账行的 `补救: cover=<任务号>` 是索引，
      生效与否回服务端读 applied 才作数）——否则补完封面台账也翻不成 `- [x]`。

凭据：NBDPSY_XHS_API_KEY（必需）、NBDPSY_XHS_API_BASE（可选，默认 https://mcp.nbdpsy.com），
由 nbdpsy_common 三层解析（环境变量 > workspace/.env > 用户级 secrets.env），
来自管理员发的「运营接入配置包」，secret import 导入后即用。

约束（服务端超限会静默截断，这里提前给 warning）：图片 1–18 张；标题≤20 字；
正文≤900 字；话题≤10 个；定时发布 schedule_time 务必带时区偏移（如 +08:00）。

输出契约：stdout 纯 JSON。发布 = {"outcome": "published|publishing|pending|failed|canceled|unknown",
"job_id", "note_url", "error", "warnings", "ledger", "intent", "actual", "gap", "gap_count"}。
发布 exit 码：0 = published 且差集为空（真闭环，才可以报完成）；1 = failed/canceled，或提交前
就被闸门拦下（封面无凭证等）；**3 = published 但有欠账**（差集非空：话题没挂上/合集没进/引用没挂）
——台账里那行仍是 `- [ ]`，补救完跑对应动作闭环，**这不是成功**；
pending/unknown 仍 **exit 0**（历史语义不动：任务已入队，非零会诱导重发，判据看 outcome 与 hint）。
`--ledger-check` 另有 exit 4 = 台账文件不存在（＝这批还没发过、或台账压根没落，**不是闭环**）。
unknown = 任务已入队但状态未确认（网络抖动等）——带真实 job_id 与复查提示，**绝不据此重发**；
--no-wait 或轮询超时后仍在跑同理，稍后用 --job 复查。正文发布前会剥离 Markdown 强调符（**/*/`）。
接入辅助命令 exit 码：--wait-login done=0/未等到=1；--check-cookie valid=0/其余=1
（error 是基础设施失败≠cookie 失效，别据此让人重新扫码）。

删除 = {"outcome":"done|failed|unknown|running", "deletion_id", deleted?, remaining?, reason?, hint?}
（running 仅 --delete-status 复查时出现）：done/unknown/running exit 0，failed exit 1。**删除不可逆**——
unknown 分两成因：轮询超时（台账仍在）→ 首选 `--delete-status <deletion_id>` 重查终态
（deleted/remaining 是权威判据）；台账 404 失效（server 重启）→ `--notes <账号> --refresh` 核对剩余
篇数（当天刚发的笔记看板次日才有数据，核不到时人工去创作中心确认）。两种情况都**绝不盲目重发**。
failed 仅表示服务端明确报 error：note_not_found（标题须精确匹配）/need_manual_login（重扫码后再试）。
--notes --refresh：先 POST 导出并轮询到终态再读快照；导出 no_data（当天刚发的笔记次日才入看板）→
{"available":false,"no_data":true} exit 0（不是故障，明天再拉）。

发布线增强命令（均先 --list-jobs 找到 pending 任务确认后再操作，仅 pending 可改可撤）：
--list-jobs 输出 {"jobs":[{job_id,account_id,title,status,schedule_time,note_url,error,created_at}]}；
--reschedule <id> --schedule <时刻|now>：改定时（PATCH 只带 schedule_time；now=清空转立即发），
  成功打服务端 {ok:true,job}；{ok:false,status} → exit 1 + hint（已在发/已终态改不了，需另建新任务）；
--cancel <id>：撤稿，{ok:true} exit 0；{ok:false,status} → exit 1 + hint（按 status 区分文案）；404 透传；
--upload-images 输出 {batch_id,urls,expires_at,warnings}（urls 可直接作发布 images，7 天过期）；
--list-uploads 透传 {batches:[...]}。PATCH 严格只发用户要改的字段（部分更新语义是服务端契约核心）。

发布可选字段（全部可缺省，只在显式给值时才下发——不传与传 null 服务端语义不同）：
--collection-id / --quoted-note-id / --activity-id / --related-counselor / --note-purpose；
后两个也可写进笔记 frontmatter（`note_purpose:` / `related_counselor:`），命令行优先。
related_counselor 驱动服务端**在本账号内**推导引用笔记，查不到就留空、绝不跨账号兜底
（跨账号引用＝把客户导到别的运营名下）。activity_id 会让服务端往正文末尾追加活动话题、
且话题名由活动侧配置不等于活动名。已发布笔记要改这些组件走 note_ops.py --set-components。
"""
import argparse
import base64
import json
import shutil
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlencode

# 同目录 vendored 副本
import nbdpsy_common

TERMINAL_STATUSES = {"published", "failed", "canceled"}
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
# 图床上传张数硬上限（与服务端 _MAX_IMAGES 一致；下限 1，无图不成图文）。
MAX_UPLOAD_IMAGES = 18
# 上传 multipart 的扩展名 → MIME（服务端只认这几类图片）。
_IMAGE_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}

def _fallback_meta(raw: str) -> dict:
    """笔记 frontmatter 惯用 `hashtags: [#a, #b]`——`#` 在 YAML 流序列里开注释，
    严格解析必炸；这里按行退化解析发布所需的键（title/hashtags 等简单标量）。"""
    meta = {}
    for line in raw.splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if key == "hashtags":
            meta[key] = [t for t in re.split(r"[\s,\[\]]+", val) if t.startswith("#")]
        elif key and val:
            meta[key] = val
    return meta


def parse_frontmatter(text: str):
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise ValueError("缺 frontmatter")
    raw = m.group(1)
    try:
        import yaml  # type: ignore
        meta = yaml.safe_load(raw)
        if isinstance(meta, dict):
            return meta, m.group(2)
    except ModuleNotFoundError:
        sys.exit("需要 python3-yaml（pyyaml）")
    except Exception:
        pass  # 含 #标签 流序列等非法 YAML → 走退化解析
    return _fallback_meta(raw), m.group(2)


def extract_publish_text(body: str) -> str:
    """取「## 发布文案」块正文（到下一个 ## 或文末）。"""
    m = re.search(r"^##\s*发布文案[^\n]*\n(.*?)(?=^##\s|\Z)", body, re.S | re.M)
    if not m:
        raise ValueError("笔记缺「## 发布文案」块")
    return m.group(1).strip()


_HASHTAG_LINE = re.compile(r"^\s*(#\S+\s*)+$")

# 小红书正文不渲染 Markdown：发布前剥掉强调符，否则笔记里出现字面 **/*/` 号
_EMPHASIS_PATTERNS = [
    (re.compile(r"\*\*(.+?)\*\*", re.S), r"\1"),
    (re.compile(r"\*(.+?)\*", re.S), r"\1"),
    (re.compile(r"`([^`\n]+)`"), r"\1"),
]

def strip_markdown_emphasis(text: str) -> str:
    for pat, rep in _EMPHASIS_PATTERNS:
        text = pat.sub(rep, text)
    return text

def split_content_topics(publish_text: str, meta: dict):
    """正文末尾的纯 #标签 行拆出来当话题（API 单独收 topics，避免正文重复一遍）。
    话题优先取 frontmatter hashtags，标签行仅作兜底来源。"""
    lines = publish_text.rstrip().splitlines()
    tag_line_topics = []
    while lines and _HASHTAG_LINE.match(lines[-1]):
        tag_line_topics = [t.lstrip("#") for t in lines[-1].split() if t.lstrip("#")] + tag_line_topics
        lines.pop()
    content = strip_markdown_emphasis("\n".join(lines).rstrip())
    hashtags = meta.get("hashtags")
    if isinstance(hashtags, list) and hashtags:
        topics = [str(t).lstrip("#").strip() for t in hashtags if str(t).lstrip("#").strip()]
    else:
        topics = tag_line_topics
    # 去重保序
    seen, uniq = set(), []
    for t in topics:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return content, uniq


# server 数据目录：mcp.nbdpsy.com 由本机 nbdpsy-server 提供时，媒体文件直接 cp 进去即可，
# 零网络传输。走隧道分片上传实测极不稳（50MB SSL 断连 / 8MB 502 / 2MB 传到第 5 片仍 502）。
SERVER_MEDIA_DIR = Path("/home/roots/nbdpsy-server/data/uploads/media/skill-uploads")
VIDEO_EXTS = {".mp4", ".mov", ".flv", ".f4v", ".mkv", ".rm", ".rmvb", ".m4v", ".mpg", ".mpeg", ".ts"}
AUDIO_EXTS = {".m4a", ".mp3", ".wav", ".flac", ".aac"}
COVER_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def stage_media(path: Path, kind: str) -> str:
    """把本机媒体文件放到 server 能读到的位置，返回服务器侧绝对路径。
    同机（SERVER_MEDIA_DIR 的父目录存在）→ 直接 cp；否则报错并提示走分片上传
    （远端 server 的分片通道 POST /api/uploads/media-sessions，本函数不代劳：
    那条路要按 server 返回的 chunk_size 切片、逐片 PUT、complete 校验 sha256）。"""
    exts = {"video": VIDEO_EXTS, "audio": AUDIO_EXTS, "cover": COVER_EXTS}[kind]
    if not path.is_file():
        raise ValueError(f"{kind} 文件不存在：{path}")
    if path.suffix.lower() not in exts:
        raise ValueError(f"{kind} 扩展名不支持：{path.suffix}（允许 {'/'.join(sorted(exts))}）")
    if not SERVER_MEDIA_DIR.parent.parent.exists():
        raise ValueError(
            f"本机没有 server 数据目录（{SERVER_MEDIA_DIR.parent.parent}）——"
            "说明 server 在远端，请改走分片上传 POST /api/uploads/media-sessions，"
            "拿 complete 返回的 path 再发布")
    SERVER_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    dst = SERVER_MEDIA_DIR / path.name
    if not (dst.exists() and dst.stat().st_size == path.stat().st_size):
        shutil.copy2(path, dst)
    return str(dst.resolve())


# 出图脚本落在**成图同目录**的缩略图（`render_cover.py` 的 `<成图名>.thumb<宽度>.<扩展名>`，
# 宽度跟 `--thumb` 走：P01.thumb220.png / P01.thumb132.jpg）。它是验收用的副产品，不是笔记的一页。
# 🔴 2026-08-17 dry-run 实测：不挡的话 `images=['P01.png', 'P01.thumb220.png']`——**两页、零告警**，
# 真发就是把 220px 缩略图当第二张图发出去。⛔ 挡了也必须出声：静默跳过和静默收进来是同一个病的两面。
THUMB_STEM_RE = re.compile(r"\.thumb\d+$", re.I)


def collect_images(note_path: Path, images_dir):
    """默认取笔记同目录 images/<note名>/ 下的图片，按文件名排序（P01→PNN 即页序）。

    同名不同扩展名视为同一页的两种格式（出图脚本常同时落 png 原图+jpg 压缩图），
    只取一份——否则一篇 7 页会被发成 14 张且零告警（2026-08-10 实战险情）。
    同页多格式时优先 jpg/jpeg（体积小、上传快），其次 png/webp。
    缩略图（`*.thumbNNN.*`）跳过并**点名报出来**（见 THUMB_STEM_RE）。
    """
    d = Path(images_dir) if images_dir else note_path.parent / "images" / note_path.stem
    if not d.is_dir():
        raise ValueError(f"配图目录不存在: {d}（先出图，或用 --images-dir 指定）")
    prefer = {".jpg": 0, ".jpeg": 1, ".png": 2, ".webp": 3}
    pages, thumbs = [], []
    for p in sorted(p for p in d.iterdir() if p.suffix.lower() in IMAGE_EXTS):
        (thumbs if THUMB_STEM_RE.search(p.stem) else pages).append(p)
    if thumbs:
        print(f"⚠️ 跳过 {len(thumbs)} 张缩略图：{'、'.join(p.name for p in thumbs)}"
              "——`*.thumbNNN.*` 是出图脚本落在同目录的验收副产品，不是笔记的一页。"
              "真要发这个名字的图，把文件名里的 `.thumbNNN` 去掉再来", file=sys.stderr)
    by_stem = {}
    for p in pages:
        old = by_stem.get(p.stem)
        if old is None or prefer[p.suffix.lower()] < prefer[old.suffix.lower()]:
            by_stem[p.stem] = p
    paths = sorted(by_stem.values())
    if not paths:
        raise ValueError(f"配图目录里没有图片: {d}"
                         + (f"（只有 {len(thumbs)} 张缩略图 {'、'.join(p.name for p in thumbs)}，"
                            "那是副产品不是笔记页——去出成图）" if thumbs else ""))
    dropped = len(pages) - len(paths)
    if dropped:
        print(f"⚠️ 配图目录存在同页多格式，已按 jpg>png>webp 去重：取 {len(paths)} 张、忽略 {dropped} 张重复格式", file=sys.stderr)
    return paths


# ---------------------------------------------------------------- 闸门 A · 封面产出凭证
# 图文 / 视频 / 播客三形态共用这一段（`publish_video.py` 直接绑定这里的函数，⛔ 别再抄第二份）。
# 图文的封面就是**第一张图 P01**（没有独立 cover 通道，传 --cover 服务端 422），
# 所以图文校验的对象是 `images/<post名>/P01.png` 的同名 `P01.meta.json`。

# 封面凭证认的五个具名版式（illustration-spec §2-b「封面版式工程」版式表，2026-08-14 补第五式）
COVER_LAYOUTS = ("通栏大字压顶", "左字右图分栏", "留白场", "色块压条", "上图下字·真人照")
# 凭证的合法来源三个，各自对应一条**真的走过**的封面产线：
#   gen_images       —— AI 出图（工序③），凭据是 server 回执的 job/session + 提示词摘要；
#   render_cover     —— HTML 确定性渲染（封面主路径，老板拍板「HTML 的更好」），
#                       它没有提示词，凭据换成模板/调色板/版式三个确定性字段（见 render_cover_evidence）；
#   manual_confirmed —— 人工/宿主出图，凭据是具名确认人 + 时间。
# ⛔ 视频截帧 / 随手找的图 / 手搓的 HTML 仍然都不是合法来源；把它们写成上面任何一档都是**伪造凭证**。
# ⚠️ 2026-08-17 补 render_cover 这一档的理由（干跑实测）：此前判据只认「AI 生图」这一个世界，
# 照文档钦定的主路径出的封面**如实填就发不出去**，唯一能过闸的做法是编一段这张图根本没用过的
# 提示词——**闸门只放行谎话**。那不是措辞问题，是判据缺了一整条合法产线。
import compliance_core  # noqa: E402  停用热线闸的唯一真源

COVER_SOURCES = ("gen_images", "render_cover", "typeset_longimage", "manual_confirmed")
# 🔴 **加新 source 必须与产线端同时改**（2026-08-21 typeset 那次）：
# 产线端落了凭证而这里不认 ⇒ **照样拒**，而产线那边看起来"已经做了"。
# ⚠️ 反过来也一样：这里加了名字而产线不落凭证 ⇒ 白名单形同虚设。
# ⛔ 两端任一单独改，都是"看起来做了"。
# 凭证比封面图旧多少秒算脱钩。留 2s 余量：同一次出图里「先落图、后写凭证」两步之间
# 有正常的秒级时差，文件系统时间戳精度也不一致；真正要挡的是"图重出了、凭证还是旧那份"。
COVER_RECEIPT_MTIME_SLACK = 2.0
# 「单出确认」不过时的拒发措辞真源：与 SKILL.md 逐字一致（2026-08-14 契约）。
# 单独拎成常量是为了**一行可 grep**——散在多行字符串里，文档与代码对不对得上就没人验得了。
# ⛔ 改这句必须同步改文档。
COVER_BATCH_REJECT_MSG = "封面凭证是批量顺带产出的（cover_only=false 且无人工确认戳）：先跑 --confirm-cover <路径> --confirmed-by 你的名字 补确认，或用 --cover-only 重新单出该篇封面"


def cover_meta_path(cover: Path) -> Path:
    return cover.with_suffix(".meta.json")


def render_cover_evidence(cover: Path, mp: Path, meta: dict) -> dict:
    """`source=render_cover` 的校验项①与④——**确定性渲染没有提示词，凭据换成确定性字段**。

    ④ 原本要 `prompt_excerpt` 里有色值 + 具名版式，本意是「证明这张封面按本批风格档案的
    调色板、按某个具名版式出的」。对 AI 路，提示词是唯一能拿到的凭据；对 HTML 渲染路，
    提示词根本不存在，而 **模板名 / 调色板 / 版式** 三样都是渲染器自己就知道的确定性事实——
    比一段人写的提示词更硬。所以这条路 ⛔ 不要 `prompt_excerpt`，改判这三样。

    ⚠️ 缺字段一律拒（fail-closed）：新来源如果允许"字段没有就跳过"，等于给闸门开了一整条旁路。
    """
    # ① 张冠李戴：render_cover 的凭证里没有 `cover_file`（它把图路径记在 outputs.image），
    # 两个键都不认就等于这条新来源整个跳过校验 ①——那正是"字段缺失＝放行"的老病。
    img = str(meta.get("cover_file") or (meta.get("outputs") or {}).get("image") or "").strip()
    if not img:
        raise ValueError(f"封面凭证 {mp.name} 没记这份凭证是给哪张图的"
                         "（`cover_file` 与 `outputs.image` 都没有）——校验不了张冠李戴，拒发")
    if Path(img).stem != cover.stem:
        raise ValueError(f"封面凭证张冠李戴：凭证记的是 {Path(img).name} ≠ 实际文件 {cover.name}"
                         "（主名不同；若只是 png→jpg 转档不会报这条）")
    # 模板：render_cover 的凭证里 `template` 本来就是 {path, kind, alias}（receipt@1 已占了这个键），
    # 所以两种写法都收——字符串，或那个 dict 里的 kind/alias/文件名。
    tpl = meta.get("template")
    if isinstance(tpl, dict):
        tpl = tpl.get("kind") or tpl.get("alias") or Path(str(tpl.get("path") or "")).stem
    tpl = str(tpl or "").strip()
    if not tpl:
        raise ValueError(f"封面凭证 {mp.name} 缺字段 `template`——HTML 渲染这条路靠模板背书"
                         "（写模板名字符串，或 render_cover 的 {path, kind, alias} 都收）")
    # 调色板：记的是**实际渲出来的**色值，⛔ 不是提示词里许诺的色值。
    pal = meta.get("palette")
    pal_txt = " ".join(str(x) for x in pal) if isinstance(pal, (list, tuple)) else str(pal or "")
    hexes = re.findall(r"#[0-9A-Fa-f]{6}\b", pal_txt)
    if not hexes:
        raise ValueError(f"封面凭证 {mp.name} 的 `palette` 里没有色值（#RRGGBB）——"
                         "说明这张封面没按本批风格档案的调色板出"
                         "（这条路记的是实际渲出来的调色板，⛔ 别拿提示词顶）")
    layout = str(meta.get("layout") or "").strip()
    if layout not in COVER_LAYOUTS:
        raise ValueError(f"封面凭证 {mp.name} 的 layout={layout or '(缺)'} 不是具名版式"
                         f"（{'/'.join(COVER_LAYOUTS)}）——封面版式工程没走，见 illustration-spec §2-b")
    # gates_ok 是 render_cover 自己对这次渲染的判决（红灯＝排版不达标）。**只报不拦**——
    # 小红书线现行口径是「照常出图、红字交人判断」（render_cover jinjin 路退出码故意恒 0），
    # 硬拦会打断正在跑活的用法（2026-08-17 老板拍板）。
    # 🔴 但「不拦」≠「不响」：放行必须留下声音，否则它就是一个看不见的默认放行
    #    （同型事故：横版豁免了 avatar 却不说，图上没头像闸门还是绿的）。
    #    ⚠️ 判据是 `is not True`——缺字段 / null 一样出声，⛔ 不给"字段没有＝当它绿"留口子。
    gates_ok = meta.get("gates_ok")
    reds = [str(w) for w in (meta.get("warnings") or []) if str(w).startswith("🔴")]
    if gates_ok is not True:
        print(f"⚠️🔴 这张封面自己报了红（{mp.name} gates_ok={gates_ok!r}）——闸门 A 照样放行，"
              "因为版式红字归人判断。**请确认你真的看过这张图**，"
              "⛔ 别把「闸门绿了」当成「封面合格了」", file=sys.stderr)
        for w in reds or ["（凭证里没有 🔴 原文：可能是老凭证、或渲染时没落 warnings——"
                          "⛔ 同样不代表这张图合格，去看图）"]:
            print(f"   {w}", file=sys.stderr)
    return {"template": tpl, "palette": hexes, "layout": layout,
            "render_gates_ok": gates_ok, "render_red_lights": reds}


def check_cover_receipt(cover: Path) -> dict:
    """校验封面的产出凭证。不过就抛 ValueError——**拒发，不是告警**。

    为什么校验的是凭证而不是文件名：命名约定只能挡住"忘了做封面"，挡不住"自己做了一张
    命名合规的"。凭证要求的 job/session id 与提示词摘要，只有真的走过③步出图才拿得到。
    """
    cover = Path(cover)
    if not cover.is_file():
        raise ValueError(f"封面文件不存在：{cover}")
    if cover.suffix.lower() not in COVER_EXTS:
        raise ValueError(f"封面扩展名不支持：{cover.suffix}（允许 {'/'.join(sorted(COVER_EXTS))}）")
    mp = cover_meta_path(cover)
    if not mp.is_file():
        raise ValueError(
            f"缺封面产出凭证 {mp.name}——⛔ 无凭证一律拒发。\n"
            "  封面必须走工序③（三形态共用同一道封面闸门，视频没有旁路）：\n"
            "  render_cover.py（HTML 渲染，封面主路径）与 gen_images.py 出封面时都会自动落盘\n"
            "  同名 .meta.json（字段见 SKILL.md 工序③「封面产出凭证」）；\n"
            "  人工/宿主出图的批次写 source=manual_confirmed 并记下是谁在什么时候认可的。")
    try:
        meta = json.loads(mp.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"封面凭证 {mp.name} 不是合法 JSON：{e}")

    def need(key):
        v = meta.get(key)
        if isinstance(v, str):
            v = v.strip()
        if v in (None, "", [], {}):
            raise ValueError(f"封面凭证 {mp.name} 缺字段 `{key}`")
        return v

    source = need("source")
    if source not in COVER_SOURCES:
        raise ValueError(f"封面凭证 source={source!r} 非法（只认 {'/'.join(COVER_SOURCES)}）——"
                         "视频截帧 / 随手找的图 / 手搓的 HTML 都不是合法来源："
                         "HTML 封面走 render_cover.py（它自己落凭证），AI 封面走工序③ gen_images.py")
    # 只比主名不比扩展名：发布前把 PNG 转 JPG 是文档要求的常规动作（PNG 八张 11MB 会撑爆
    # CF 100s 网关），而凭证是出图时写的、记的是 P01.png。转档换的是容器不是内容，
    # 凭证仍然为这张图背书；比全名会让「照文档转档」的人必撞（2026-08-16 干跑实测）。
    # ⛔ 主名不同仍然拒（P01 的凭证配 P02 的图＝张冠李戴，那才是要防的）。
    if meta.get("cover_file") and Path(meta["cover_file"]).stem != cover.stem:
        raise ValueError(
            f"封面凭证张冠李戴：cover_file={meta['cover_file']} ≠ 实际文件 {cover.name}"
            "（主名不同；若只是 png→jpg 转档不会报这条）")
    # 凭证与文件脱钩（2026-08-14 干跑报告 G3）：只比同名挡不住"封面重出后凭证没更新"——
    # 那份旧凭证指着上一个 job，等于拿旧证据给新图背书。图比凭证新即拒。
    if mp.stat().st_mtime + COVER_RECEIPT_MTIME_SLACK < cover.stat().st_mtime:
        raise ValueError(
            f"封面凭证 {mp.name} 比封面图 {cover.name} 旧（凭证 "
            f"{datetime.fromtimestamp(mp.stat().st_mtime).isoformat(timespec='seconds')}"
            f" < 图 {datetime.fromtimestamp(cover.stat().st_mtime).isoformat(timespec='seconds')}）"
            "——封面重出过、凭证却是旧那份，凭证与文件已脱钩：重跑 gen_images.py 出封面"
            "（会自动重写凭证），或人工出图的批次按新图重写 meta.json")
    if source == "gen_images":
        need("job_id")
        need("session_id")
    elif source == "render_cover":
        pass                     # 本地确定性渲染，没有 server job；凭据见 render_cover_evidence
    else:
        need("confirmed_by")     # 谁认可的——空串/纯空白不算数
        need("confirmed_at")
    # 单出确认（2026-08-14 复验 S4 证据 3）：凭证只能证明"这张图是工序③出的"，证明不了
    # "有人看过它"。批量出 P2…P8 时顺带重出的 P1 同样自动拿到一份合法凭证，于是把已确认的
    # 封面覆盖掉也照发不误——闸门 A 全程无感。故再要一项：**本次是单出封面，或事后有人工确认戳**。
    # ⚠️ 老凭证没有 cover_only 字段 → 判为"不是单出"（fail-closed）：宁可让人补一次确认戳，
    # 也不给"字段缺失＝默认放行"留口子。source=manual_confirmed 天然带确认戳，不受这条影响。
    confirmed_by = str(meta.get("confirmed_by") or "").strip()
    if not meta.get("cover_only") and not confirmed_by:
        ran = str(meta.get("run_pages") or "").strip()
        raise ValueError(
            f"封面凭证 {mp.name}：" + COVER_BATCH_REJECT_MSG + "\n"
            + (f"  本次出图 --pages {ran}\n" if ran else "")
            # 图文走 publish_note.py、视频/播客走 publish_video.py，两边同一个函数同一道判据，
            # 所以这里不点名脚本——点名了另一条线的人会以为要跨脚本操作。
            + f"  补戳：<本脚本> --confirm-cover {cover} --confirmed-by \"<姓名>\""
            "（看过这张图的人签名，⛔ 别代签）\n"
            "  单出：gen_images.py --note <稿件> --cover-only（出完看缩略图再批量出后续页）")
    # ④ **按来源分岔**：有提示词的路（AI 生图 / 人工出图）判提示词；HTML 确定性渲染那条路
    # 压根没有提示词，判模板/调色板/版式三个确定性字段。⛔ 别对 HTML 路要一段不存在的提示词。
    if source == "render_cover":
        extra = render_cover_evidence(cover, mp, meta)
    else:
        extra = {}
        excerpt = str(need("prompt_excerpt"))
        if not re.search(r"#[0-9A-Fa-f]{6}\b", excerpt):
            raise ValueError(f"封面凭证 {mp.name} 的 prompt_excerpt 里没有色值（#RRGGBB）——"
                             "说明这张封面没按本批风格档案的调色板出")
        if not any(v in excerpt for v in COVER_LAYOUTS):
            raise ValueError(f"封面凭证的 prompt_excerpt 里没有具名版式"
                             f"（{'/'.join(COVER_LAYOUTS)}）——封面版式工程没走，见 illustration-spec §2-b")
    sp = meta.get("style_profile") or {}
    # 🩸 **类型防御**（2026-08-22）：`typeset_longimage` 一度把 style_profile 写成**套名字符串**
    #    （更早还因为取错字段恒为 null）。字符串没有 `.get` ⇒ 这里会抛 **AttributeError**，
    #    ⚠️ 那是**崩溃**不是**拒绝**——闸门崩掉时给的是一条堆栈，人看不出"凭证格式不对"，
    #    更看不出该去修哪条产线。⇒ 显式判类型，把它变成一条能照着修的拒绝理由。
    if not isinstance(sp, dict):
        raise ValueError(f"封面凭证的 style_profile 是 {type(sp).__name__} 而不是对象——"
                         f"三条产线的口径是 {{套名, version}}（值：{sp!r}）。"
                         f"这份凭证是旧格式或产线写错了，重出封面即可")
    if not sp.get("套名") or sp.get("version") in (None, ""):
        raise ValueError(f"封面凭证缺 style_profile（套名 + version）——"
                         "审查端要按这一版档案判封面，缺了没法判")
    return {"cover": str(cover), "meta": str(mp), "source": source,
            "style_profile": sp, "job_id": meta.get("job_id"),
            "session_id": meta.get("session_id"),
            "cover_only": bool(meta.get("cover_only")),
            "run_pages": str(meta.get("run_pages") or "") or None,   # "1"/"2-8"/"1,3"/"all"
            "confirmed_by": confirmed_by or None, "ok": True, **extra}


def confirm_cover_receipt(cover: Path, who: str) -> dict:
    """给**已有**封面凭证补人工确认戳（闸门 A「单出确认」这一项的唯一正路）。

    ⛔ 只盖戳，不造证：凭证不存在就拒——凭空写一份不叫确认，叫伪造（同 COVER_SOURCES 的红线）。
    盖戳顺带刷新凭证 mtime（晚于封面图），G3 的「凭证比图旧」判据随之满足；盖完当场复校一遍，
    不让"戳盖上了、别的项仍不过"混过去。
    """
    cover = Path(cover)
    who = (who or "").strip()
    if not who:
        raise ValueError("--confirm-cover 需要 --confirmed-by <姓名>：确认戳要记下是谁看过这张图，"
                         "匿名戳等于没戳")
    if not cover.is_file():
        raise ValueError(f"封面文件不存在：{cover}")
    mp = cover_meta_path(cover)
    if not mp.is_file():
        raise ValueError(
            f"缺封面产出凭证 {mp.name}——⛔ 确认戳只能盖在已有凭证上：\n"
            "  先用 `gen_images.py --note <稿件> --cover-only` 出封面（会自动落凭证），再来盖戳。")
    try:
        meta = json.loads(mp.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"封面凭证 {mp.name} 不是合法 JSON：{e}")
    meta["confirmed_by"] = who
    meta["confirmed_at"] = now_iso()
    mp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    out = check_cover_receipt(cover)          # 复校：盖完仍不过就当场抛，别报假绿
    out["confirmed_by"] = who
    out["confirmed_at"] = meta["confirmed_at"]
    return out


def check_images_cover_receipt(note_path: Path, image_paths) -> dict:
    """图文线的闸门 A：**首图即封面**，校验它的产出凭证，报错带上是哪一篇。"""
    cover = image_paths[0]
    try:
        return check_cover_receipt(cover)
    except ValueError as e:
        raise ValueError(f"【{note_path.name}】封面（首图 {cover.name}）没过闸门 A：{e}")


# ---------------------------------------------------------------- 闸门 C · 台账
LEDGER_NAME = "publish-ledger.md"
LEDGER_HEADER = (
    "# 发布台账（意图 vs 实际 · 差集）\n\n"
    "> 由 `publish_note.py` / `publish_video.py` 自动维护。**这张表记的不是「做过什么」，是「还欠什么」。**\n"
    "> `- [ ]` = 未闭环（有欠账，⛔ 本批不许报完成）；`- [x]` = 意图与实际一致。\n"
    "> 接手第一件事：`python3 scripts/publish_note.py --ledger-check <本文件>`。\n\n"
)


def now_iso() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def ledger_path(args, note: Path = None) -> Path:
    """台账路径从稿件/媒体文件所在目录推导；**绝不在 cwd 推导出的位置新建台账**。

    2026-08-16 事故：`--recheck 340` 单独跑时既没 --ledger 也没 --note，旧代码无条件回落 cwd，
    于是台账被**新建**在 /home/roots/NBDpsy 仓库根——发布时那份真台账（在媒体目录里）永远闭不掉，
    还往别人仓库根撒文件。要害在「新建」而不在「cwd」：人就在稿件目录里跑复查是最自然的用法，
    那时 ./publish-ledger.md 本就是这批的台账。所以 cwd 只作**最后一档只读锚点**——
    文件已经在那儿才认，不在就抛错指路，绝不凭空造一份干净台账假装这批没欠账。"""
    if getattr(args, "ledger", None):
        return Path(args.ledger)
    # 🔴 **推导链的目的是「找到那份台账」，⛔ 不是「返回一个路径」**（2026-08-19 改）。
    #
    # 🩸 实炸（小红书发布线）：`--fix-cover --job 350 --cover <封面>` 是补封面的**典型用法**
    #    （手上只有 job 号和封面，没理由再带 --note），旧实现「第一个非空候选就 return」
    #    ⇒ 落到封面的父目录 `cover-brand7/`，而真台账在稿件目录 `seven/`
    #    ⇒ 补救号登记不进发布那一行 ⇒ recheck 永远闭不掉。
    #
    # ⚠️ **⛔ 别直接把 `--cover` 从链里摘掉**（我第一版就是那么改的，当场打断 5 个用例）：
    #    轮播/放映线的封面**就在媒体目录里**（`cover-1.jpg` 与稿件同级），摘了它们就推不出来了。
    #    ⇒ **两种用法都真实存在**，区别不在"是哪个参数"，在"那里到底有没有台账"。
    #
    # ⇒ 先按顺序找**已存在**的那一份；一份都没有时，再返回第一个候选——
    #   那是"最可能的位置"，用来把错误信息指到正确的地方（⛔ 仍然不新建）。
    cands = [c for c in (note, getattr(args, "note", None),
                         getattr(args, "content_file", None), getattr(args, "video", None),
                         getattr(args, "audio", None), getattr(args, "cover", None)) if c]
    for cand in cands:
        lp = Path(cand).parent / LEDGER_NAME
        if lp.exists():
            return lp
    here = Path.cwd() / LEDGER_NAME
    if here.exists():       # ⚠️ cwd 锚点提到候选之前判：人就在稿件目录里跑是最自然的用法
        return here
    if cands:
        return Path(cands[0]).parent / LEDGER_NAME
    raise ValueError(
        f"定位不到台账（{LEDGER_NAME}）：当前目录 {Path.cwd()} 下没有它，"
        "命令行也没给 `--ledger <台账路径>` 或 --note/--video/--audio/--cover。"
        "⛔ 不按当前工作目录**新建**——那会把台账落进无关仓库根目录（2026-08-16 实证）；"
        "请到稿件/媒体目录里跑，或显式指路。")


def ledger_append(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(LEDGER_HEADER, encoding="utf-8")
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def ledger_replace(path: Path, old: str, new: str) -> bool:
    """把台账里那一行原地换掉（意图行 → 回填实际与差集）。找不到就追加，绝不静默丢。"""
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if old in text:
            path.write_text(text.replace(old, new, 1), encoding="utf-8")
            return True
    ledger_append(path, new)
    return False


def ledger_find_by_job(path: Path, job_id) -> str:
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("- [") and f"job={job_id} " in line + " ":
            return line
    return ""


def ledger_row(closed: bool, ts: str, what: str, account: str, job_id, intent: str,
               actual: str, gap: str, remedies: dict = None, note_id: str = None) -> str:
    """写一行台账。

    🔴 **`note_id` 段（2026-08-21 加）**：出事时**对方（server/平台/用户）给的永远是 note_id**
    ——平台看得见的只有它。🩸 实测拿真实已发布 note_id grep 全部台账＝**零命中**，
    只能反向查台账拿标题再猜稿件（多一跳且靠猜）。

    ⚠️ **段位置**：跟在 `job=` 之后。**前 4 段位次不动、后面的段一律追加在尾部之前**
    ⇒ **旧行照样解析**（与 `补救:` 段当初的处置同一条规矩）。
    ⚠️ **没有 note_id 时整段不写**（⛔ 不写 `note=None`）——
    「这一行没有」与「这一行有但值是 None」必须分得开：
    前者是历史行，后者是发布回执真的没给。
    """
    box = "x" if closed else " "
    tail = "已闭环" if closed else "未闭环"
    nid = f" | note={note_id}" if note_id else ""
    # 补救段落放在差集之后、结论之前：既不动前面 7 段的位次（旧行照样解析），
    # 又让「这一项是靠补救达成的」留在纸上。
    mid = f" | 补救: {ledger_remedies_txt(remedies)}" if remedies else ""
    return (f"- [{box}] {ts} | {what} | {account} | job={job_id}{nid} | 意图: {intent} | "
            f"实际: {actual} | 差集: {gap}{mid} | {tail}")


_NOTE_SEG = re.compile(r"\|\s*note=([^|\s]+)")


def ledger_note_id(row: str):
    """从台账行读出 note_id；旧行没有这一段就返回 None。

    🔴 **返回 None ＝「这一行没记」，⛔ 不是「这条笔记没有 note_id」** ——
    两者后果完全不同（前者是台账欠账，后者是发布真的失败）。
    ⚠️ 这正是今天技术侧那条：**缺失被渲染成"值为空"**，
    于是"没记录"看起来像"记录了个空值"。
    """
    m = _NOTE_SEG.search(row or "")
    return m.group(1) if m else None


# 补救登记：`补救: cover=<note-components 任务号>`（多项逗号分隔）。
# ⚠️ 它只是**索引**，不是凭据——闭环判据永远是拿这个任务号回服务端读 applied（见 verify_remedies）。
_REMEDY_SEG = re.compile(r"\|\s*补救:\s*([^|]+)")


def ledger_remedies(row: str) -> dict:
    """从台账行里读出已登记的补救任务：{组件名: 补救任务号}。没有就空 dict。"""
    m = _REMEDY_SEG.search(row or "")
    if not m:
        return {}
    out = {}
    for item in m.group(1).split(","):
        key, _, jid = item.strip().partition("=")
        if key.strip() and jid.strip():
            out[key.strip()] = jid.strip()
    return out


def ledger_remedies_txt(remedies: dict) -> str:
    return ",".join(f"{k}={v}" for k, v in sorted((remedies or {}).items()))


def ledger_set_remedies(row: str, remedies: dict) -> str:
    """在既有台账行上写入/更新补救登记，**其余字段一字不动**（补救发生时差集还没重算，
    翻不翻 `- [x]` 由之后的 --recheck 说了算——补上封面不等于话题也挂上了）。"""
    body = _REMEDY_SEG.sub("", row, count=1)
    head, sep, tail = body.rpartition(" | ")
    if not sep:
        return body
    return f"{head} | 补救: {ledger_remedies_txt(remedies)}{sep}{tail}"


def verify_remedies(api_base: str, key: str, remedies: dict) -> dict:
    """拿登记的补救任务号回服务端读终态，**只有 applied.<组件> is True 才算数**。

    差集必须消费补救结果，否则闭环判据是死的：发布回执是**发布那一刻的快照**，
    补封面走的是另一条 note-components 任务，快照永远停在 cover=error，
    台账那行再怎么 --recheck 都翻不成 `- [x]`（2026-08-16 job340 实证）。
    ⛔ 反过来也不许「recheck 忽略 cover」——那是放弃校验，不是闭环。
    服务端没有「按 note_id 列补救任务」的端点，所以任务号只能由台账登记（fix_cover 落的），
    但**真伪一律回服务端问**：台账负责记得，服务端负责作数。"""
    ok = {}
    for comp, jid in (remedies or {}).items():
        try:
            resp = send_request("GET", f"{api_base}/api/note-components/{jid}", key)
            if resp.status_code >= 400:
                continue
            view = resp.json()
        except Exception:
            continue  # 读不到就当没补上——宁可留着欠账，也不放行假绿
        if (view.get("applied") or {}).get(comp) is True:
            ok[comp] = jid
    return ok


def ledger_check(path: Path) -> int:
    """读欠账。exit 语义三态（2026-08-14 干跑报告 G5 修正）：
      0 = 台账在、且全部闭环；3 = 台账在、有未闭环行；**4 = 台账不存在**。
    ⚠️ 以前"没有台账"与"全部闭环"回同一个 exit 0——「没写台账」被当成「这批没事」，
    正是闸门 C 要挡的那种假绿。没台账 ≠ 闭环：要么这批还没发，要么发了没落台账（更糟）。"""
    if not path.exists():
        print(json.dumps({"ledger": str(path), "exists": False, "open_rows": [],
                          "hint": "台账文件不存在——**这不是闭环，是没有证据**："
                                  "要么这批还没发过（发布走 publish_note.py / publish_video.py，"
                                  "⛔ 别手搓 payload 直调，那条路不落台账）；"
                                  "要么发过但没落台账（那就先 --list-jobs 把已发的 job 捞回来核对，"
                                  "⛔ 别据此报完成）"},
                         ensure_ascii=False))
        return 4
    rows = [l for l in path.read_text(encoding="utf-8").splitlines() if l.startswith("- [ ]")]
    print(json.dumps({"ledger": str(path), "exists": True, "open_count": len(rows),
                      "open_rows": rows,
                      "hint": ("有未闭环行＝本批还有欠账，⛔ 不许报完成：逐行按差集补救"
                               "（cover=FAIL → publish_video.py --fix-cover；topics 缺 → 换词重挂；"
                               "collection 缺 → note_ops.py --set-components），"
                               "补完跑 --recheck <job_id>（视频）或 --job <job_id> 复核闭环")
                              if rows else "全部闭环"},
                     ensure_ascii=False))
    return 3 if rows else 0


# ---------------------------------------------------------------- 回读校验（意图 vs 实际）

def diff_intent_actual(view: dict, intent: dict, remedied: dict = None) -> tuple:
    """拿服务端回执逐项比对意图，返回 (实际摘要, 差集摘要, 差集项数)。

    ⚠️ `published` ≠ 组件全成：封面/话题/合集失败**不阻断发布**，任务照样 published
    （2026-08-13 job337 实证：published + cover error + topics 全空）。所以判据在 applied 层。

    remedied = 已经**回服务端验过**的补救结果 {组件: 补救任务号}（verify_remedies 的产物）：
    发布回执是发布那一刻的快照，补救走的是另一条任务，不合并进来这行永远闭不掉。
    ⛔ 只接受验过的，别把台账里那句登记当凭据。
    """
    remedied = remedied or {}
    applied = view.get("applied") or {}
    comps = applied.get("components") or {}
    actual, gaps = [], []

    want_topics = list(intent.get("topics") or [])
    if want_topics:
        got = list(applied.get("topics_applied") or [])
        actual.append(f"topics={len(got)}/{len(want_topics)}")
        missing = [t for t in want_topics if t not in got]
        if missing:
            gaps.append(f"topics=缺{len(missing)}({','.join(missing)})")

    for key, label, fix in (
            ("cover", "cover", "publish_video.py --fix-cover --job {job} --cover <封面>"
                               "（note-components 链已真号验过；⚠️ 只对视频笔记有效，"
                               "图文没有独立封面通道、传 cover 直接 422）"),
            ("collection", "collection", "note_ops.py --set-components --collection-id/--collection-name 补挂"),
            ("quote", "quote", "note_ops.py --set-components --related-counselor 显式补挂"),
            ("activity", "activity", "⛔ 活动只能发布时挂，事后挂不上：记为不可补救，下次发布带上")):
        if not intent.get(key):
            continue
        st = (comps.get(key) or {}).get("status")
        if st not in ("done", "skipped") and remedied.get(key):
            # 发布时没成、事后补救任务已被服务端确认生效 → 这项意图已达成，不再计欠账
            actual.append(f"{label}={st or 'null'}→补救done(note-components {remedied[key]})")
            continue
        actual.append(f"{label}={st or 'null'}")
        if st not in ("done", "skipped"):
            gaps.append(f"{label}=FAIL(补救: {fix.format(job=view.get('job_id'))})")

    if view.get("status") != "published":
        gaps.append(f"status={view.get('status')}")
    return ("; ".join(actual) or "—"), ("; ".join(gaps) or "—"), len(gaps)


def intent_summary(intent: dict) -> str:
    bits = [f"topics={len(intent.get('topics') or [])}"]
    for k in ("cover", "collection", "quote", "activity"):
        if intent.get(k):
            bits.append(f"{k}={intent[k]}")
    return " ".join(bits)


def intent_from_view(view: dict) -> dict:
    """从服务端回执反推意图：topics_requested 与 components 的键集就是"这次请求过什么"。
    （台账行是给人读的，机器判据取服务端回执——避免两份意图对不上。）"""
    applied = view.get("applied") or {}
    comps = applied.get("components") or {}
    return {"topics": list(applied.get("topics_requested") or []),
            "cover": "cover" in comps, "collection": "collection" in comps,
            "quote": "quote" in comps, "activity": "activity" in comps}


def build_publish_intent(topics, extras: dict, cover_name=None) -> dict:
    """本次发布的「意图」——台账先行落的就是它，回执到了逐项比对算差集。"""
    return {"topics": list(topics or []),
            "cover": cover_name,
            "collection": extras.get("collection_name") or extras.get("collection_id"),
            "quote": extras.get("quoted_note_id") or extras.get("related_counselor"),
            "activity": extras.get("activity_id")}


def b64_items(paths):
    """图片转 API 的 {b64, ext} 形态（服务端无上传端点，图随 JSON 内联）。"""
    items = []
    for p in paths:
        items.append({"b64": base64.b64encode(p.read_bytes()).decode("ascii"),
                      "ext": p.suffix.lstrip(".").lower()})
    return items


# 发布可选字段里，允许写进笔记 frontmatter 的两个（创作时就定得下来）；
# collection_id / quoted_note_id / activity_id 是发布当下的运营决策，只走命令行。
_META_EXTRA_KEYS = ("note_purpose", "related_counselor")


def collect_extras(meta: dict, args) -> dict:
    """组装 publish-jobs 的可选字段：合集 / 引用笔记 / 活动 / 关联咨询师 / 核心目的。
    来源 = 命令行 > frontmatter。**只放用户显式给了值的键**——不传与传 null 在服务端语义不同，
    绝不替用户猜。related_counselor 会驱动服务端自动推导引用笔记（只在本账号内找，查不到就留空，
    绝不跨账号兜底——跨账号引用会把客户导到别的运营名下）。"""
    extras = {}
    for k in _META_EXTRA_KEYS:
        v = meta.get(k)
        if v not in (None, ""):
            extras[k] = str(v).strip()
    cli = {"collection_id": args.collection_id, "quoted_note_id": args.quoted_note_id,
           "activity_id": args.activity_id, "related_counselor": args.related_counselor,
           "note_purpose": args.note_purpose}
    for k, v in cli.items():
        if v not in (None, ""):
            extras[k] = v
    return extras


def extras_warnings(extras: dict):
    """可选字段的预警（都不阻断发布，只把服务端的副作用先说清楚）。"""
    w = []
    if extras.get("quoted_note_id") and extras.get("related_counselor"):
        w.append("同时给了 quoted_note_id 与 related_counselor：以 quoted_note_id 为准，"
                 "related_counselor 的引用自动推导不生效")
    if extras.get("activity_id"):
        w.append("关联活动会自动往正文末尾追加一个话题标签并真的发出去，且话题名由活动侧配置、"
                 "不等于活动名（如活动「明日方舟创作应援」注入的是 #明日方舟）")
    return w


def build_warnings(title: str, content: str, topics, image_paths, media_kind: str = "images"):
    w = []
    if len(title) > 20:
        w.append(f"标题 {len(title)} 字超 20，服务端会静默截断")
    if len(content) > 900:
        w.append(f"正文 {len(content)} 字超 900，服务端会静默截断")
    if len(topics) > 10:
        w.append(f"话题 {len(topics)} 个超 10，服务端会静默截断")
    # 视频/播客笔记不带图，图片张数校验只对图文生效
    if media_kind == "images" and not 1 <= len(image_paths) <= 18:
        w.append(f"图片 {len(image_paths)} 张不在 1–18 范围，服务端会拒绝（400）")
    return w


def send_request(method: str, url: str, key: str, payload=None, timeout=60, files=None):
    """带 Bearer 鉴权调 nbdpsy-api。网络异常向上抛，由调用方统一转 failed。
    files 非空时走 multipart/form-data（图床上传），否则 JSON 体（默认，兼容既有调用）。"""
    import requests
    headers = {"Authorization": f"Bearer {key}"}
    if files is not None:
        return requests.request(method, url, files=files, headers=headers, timeout=timeout)
    return requests.request(method, url, json=payload, headers=headers, timeout=timeout)


def api_error(resp) -> str:
    """nbdpsy-api 错误体：401/422 键是 detail，403/404/400/500 键是 error。"""
    try:
        data = resp.json()
        msg = data.get("error") or data.get("detail") or resp.text[:200]
    except Exception:
        msg = resp.text[:200]
    return f"HTTP {resp.status_code}: {msg}"


def sandbox_hint(exc) -> str:
    """网络被拦时给 agent 可执行的下一步（Claude 沙盒拦网是已知场景）。"""
    s = str(exc)
    if any(k in s for k in ("Host not allowed", "ProxyError", "Connection refused",
                            "ConnectionError", "timed out", "Max retries")):
        return ("网络请求失败。若在 Claude Code 沙盒内被拦（典型报错 Host not allowed），"
                "先跑 `python3 scripts/nbdpsy_common.py sandbox allow` 写入放行名单并重启 "
                "Claude Code；单次命令也可用 Bash 工具参数 dangerouslyDisableSandbox 重试。"
                f"原始错误：{s[:200]}")
    return s[:300]


def list_accounts(api_base: str, key: str):
    resp = send_request("GET", f"{api_base}/api/accounts", key)
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    accounts = resp.json().get("accounts", [])
    return [{"id": a.get("id"), "name": a.get("name"), "nickname": a.get("nickname"),
             "cookie_status": a.get("cookie_status")} for a in accounts]


def resolve_account(api_base: str, key: str, account: str):
    """--account 支持数字 id 或 名称/昵称 精确匹配；歧义/未命中时列出可选项。
    restricted 与 invalid 不是一回事：前者 cookie 好好的，是账号被小红书挂了风控验证墙，
    催人重新扫码登录没用（也治不好），得用手机小红书 App 扫码验证身份。"""
    if account.isdigit():
        # 数字入参也要换回账号名：给人看的一切文字只认名字（见 account_display）
        return int(account), account_display(api_base, key, int(account)), None
    accounts = list_accounts(api_base, key)
    hits = [a for a in accounts if account in (a["name"], a["nickname"])]
    if len(hits) == 1:
        a = hits[0]
        warn = None
        if a.get("cookie_status") == "invalid":
            warn = f"账号「{account}」cookie 已失效，发布大概率失败，先用 chrome 插件重新扫码登录"
        elif a.get("cookie_status") == "restricted":
            warn = (f"账号「{account}」被小红书挂了风控验证墙（cookie 没失效，重新扫码登录也没用），"
                    "发布会失败：让运营用手机小红书 App 扫码验证身份后重新检测；"
                    "若提示『请求太频繁』先晾一阵别再操作该号")
        return a["id"], a["name"] or account, warn
    avail = "、".join(f'{a["name"]}(id={a["id"]})' for a in accounts) or "（无可用账号）"
    raise ValueError(f"账号「{account}」{'匹配到多个' if hits else '不存在或未授权'}；可用：{avail}")


def account_display(api_base: str, key: str, account_id, label=None) -> str:
    """台账/报告里的账号字段——**只写账号名**。

    编号是 agent 与 server 之间的内部主键，运营脑子里只有名字；台账行写「号1」等于每次读都要
    去查一遍对照表（2026-08-16 现场：`号1(1)`——数字入参连 label 都是那个数字）。
    实在拿不到名字时写 `账号id=1`，**明示这是 id**，绝不把编号打扮成名字。"""
    name = (label or "").strip()
    if name.startswith("号") and name[1:2].isdigit():
        name = ""      # 旧台账行写的就是「号1(1)」，复查经过时顺手换回名字，别让它一直挂在那
    if name and not name.isdigit():
        return name
    try:
        hit = next((a for a in list_accounts(api_base, key)
                    if str(a.get("id")) == str(account_id)), None)
        if hit and hit.get("name"):
            return hit["name"]
    except Exception:
        pass  # 名字查不到不该挡住发布/复查，退化成明示 id 的写法
    return f"账号id={account_id}" if account_id not in (None, "") else "账号未知"


def extension_info(api_base: str, key: str) -> dict:
    """chrome 插件包信息：download_url（免鉴权可下）/version/install_steps/server_time。
    server_time 是 --wait-login 的 since 起点——必须在运营扫码**之前**取。"""
    resp = send_request("GET", f"{api_base}/api/extension", key)
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    return resp.json()


def wait_login(api_base: str, key: str, since: str, account_id=None,
               timeout: float = 600, interval: float = 5.0) -> dict:
    """轮询 GET /api/login/poll 等运营扫码完成。登新号不传 account_id（done 时带新号列表），
    重登旧号传 account_id。返回最后一次 poll 响应（done 布尔）。"""
    deadline = time.monotonic() + timeout
    path = f"/api/login/poll?since={quote(since)}"
    if account_id is not None:
        path += f"&account_id={account_id}"
    while True:
        resp = send_request("GET", f"{api_base}{path}", key)
        if resp.status_code >= 400:
            raise ValueError(api_error(resp))
        view = resp.json()
        if view.get("done") or time.monotonic() >= deadline:
            return view
        print("  等待扫码登录…", file=sys.stderr)
        time.sleep(interval)


def check_cookie(api_base: str, key: str, account_id: int,
                 timeout: float = 120, interval: float = 4.0) -> dict:
    """触发 cookie 活性检测（202 拿 check_id）并轮询到结果。
    六态：checking/valid/invalid/captcha/error/restricted——error 是基础设施失败≠cookie 失效；
    restricted 是账号被小红书挂了风控验证墙（cookie 好好的），重新扫码登录治不好，
    要运营用手机小红书 App 扫码验证身份后重新检测。"""
    resp = send_request("POST", f"{api_base}/api/accounts/{account_id}/cookie-checks", key)
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    check_id = resp.json()["check_id"]
    deadline = time.monotonic() + timeout
    while True:
        r = send_request("GET", f"{api_base}/api/cookie-checks/{check_id}", key)
        if r.status_code >= 400:
            raise ValueError(api_error(r))
        view = r.json()
        status = view.get("status")
        print(f"  cookie 检测: {status}", file=sys.stderr)
        if status != "checking" or time.monotonic() >= deadline:
            return view
        time.sleep(interval)


def self_check(api_base: str, key: str) -> dict:
    """一键接入自检（REST 侧）：连通性 + 身份 + 被授权账号 + 就绪判定。
    可反复调用——运营任何时候想确认「我配好了吗」都跑这个。凭据是否就绪由 doctor 管（本地侧）。"""
    try:
        who = send_request("GET", f"{api_base}/api/whoami", key)
    except Exception as e:  # 网络/沙盒拦截
        return {"ok": False, "stage": "whoami", "error": sandbox_hint(e),
                "hint": "网络或沙盒拦截：跑 nbdpsy_common.py sandbox allow 后重启 Claude 再试"}
    if who.status_code >= 400:
        return {"ok": False, "stage": "whoami", "error": api_error(who),
                "hint": "401=apikey 无效/已轮换（找管理员重发接入包）；000/超时=网络或沙盒拦截"
                        "（跑 nbdpsy_common.py sandbox allow 后重启 Claude）"}
    identity = who.json()
    try:
        accounts = list_accounts(api_base, key)
    except Exception as e:  # whoami 过了 accounts 却挂，多半瞬时——保持 self-check 信封而非落 publish 失败信封
        return {"ok": False, "stage": "accounts", "error": sandbox_hint(e),
                "identity": {"name": identity.get("name"), "role": identity.get("role")},
                "hint": "身份验证通过但拉账号列表失败，多半是瞬时故障，稍后重跑 --self-check"}
    # cookie_status: valid=可发；unknown=没验过（不算失败，发布前 --check-cookie 一下）；
    # invalid/captcha=需重新扫码；error=检测本身失败≠cookie 失效，稍后复验（不催重扫）；
    # restricted=cookie 好好的但账号被小红书挂了风控验证墙——催重扫没用，得手机 App 扫码验人
    usable = [a for a in accounts if a.get("cookie_status") in ("valid", "unknown")]
    need_login = [a for a in accounts if a.get("cookie_status") in ("invalid", "captcha")]
    restricted = [a for a in accounts if a.get("cookie_status") == "restricted"]
    ready = bool(accounts) and bool(usable)
    verdict = (
        "接入正常，可以开始发布" if ready
        else "已连上但没有被授权任何账号（找管理员在后台『调配账号』补授）" if not accounts
        else "没有可用账号：登录态失效的重新扫码，cookie 检测异常的稍后 --check-cookie 复验"
    )
    if restricted:
        # 单列一句，否则这些号既不在 usable 也不在 need_relogin，运营只会看到"号少了"却查不出原因
        verdict += (f"；另有 {len(restricted)} 个号被小红书挂了风控验证墙（cookie 没失效，"
                    "重新扫码登录治不好）：让运营用手机小红书 App 扫码验证身份后重新检测，"
                    "提示『请求太频繁』就先晾一阵别再操作该号")
    return {
        "ok": True, "ready": ready,
        "identity": {"name": identity.get("name"), "role": identity.get("role")},
        "account_count": len(accounts),
        "accounts": accounts,
        "need_relogin": [a.get("name") or a.get("id") for a in need_login],
        "restricted": [a.get("name") or a.get("id") for a in restricted],
        "verdict": verdict,
    }


def account_notes(api_base: str, key: str, account_id: int) -> dict:
    """拉某账号已发布笔记的清单与互动数据（供 Claude 分析）。
    该端点已上线（GET /api/accounts/{id}/notes，全功能文档 §4）——创作中心导出**无 note_id**，
    笔记业务主键是 (账号, 标题, 发布时间) 三元组。保留 404 兜底以防该账号暂无导出快照或路径调整。"""
    resp = send_request("GET", f"{api_base}/api/accounts/{account_id}/notes", key)
    if resp.status_code == 404:
        return {"available": False,
                "hint": "『笔记数据』接口返回 404：多半是该账号暂无导出快照——"
                        "先跑 --notes <账号> --refresh 触发一次导出再读（约 1–2 分钟，不是发布故障）"}
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    data = resp.json() if resp.text.strip() else {}
    return {"available": True, **(data if isinstance(data, dict) else {"notes": data})}


def poll_async_task(api_base: str, key: str, url: str, timeout: float,
                    interval: float = 4.0, max_transient: int = 3) -> dict:
    """轮询异步任务（笔记删除/导出）到终态。返回视图 dict：
      - 正常终态：{"status":"done"/"error", ...}
      - 台账 404 失效（server 重启即丢内存台账）：{"status":"gone"}
      - 超时未达终态：最后一次 running 视图（status 仍为 running）
    网络抖动 / 5xx 连续容忍 max_transient 次（一次抖动绝不误判）；401/403 永久错误立即抛。"""
    deadline = time.monotonic() + timeout
    transient = 0
    last = {"status": "running"}
    while True:
        try:
            resp = send_request("GET", url, key)
        except Exception as e:  # 网络抖动 → 瞬时
            transient += 1
            if transient > max_transient:
                raise
            print(f"  轮询瞬时失败（{transient}/{max_transient}）: {e}", file=sys.stderr)
            time.sleep(interval)
            continue
        if resp.status_code == 404:  # 进程内存台账失效
            return {"status": "gone"}
        if resp.status_code >= 500:  # 服务端瞬时故障
            transient += 1
            if transient > max_transient:
                raise ValueError(api_error(resp))
            print(f"  轮询瞬时失败（{transient}/{max_transient}）: {api_error(resp)}", file=sys.stderr)
            time.sleep(interval)
            continue
        if resp.status_code >= 400:  # 401/403 永久错误
            raise ValueError(api_error(resp))
        transient = 0
        last = resp.json()
        status = last.get("status")
        print(f"  任务: {status}", file=sys.stderr)
        if status in ("done", "error") or time.monotonic() >= deadline:
            return last
        time.sleep(interval)


def start_note_deletion(api_base: str, key: str, account_id: int, title: str, count: int) -> str:
    """触发按标题删除该号笔记（不可逆），返回 deletion_id。客户端预检 count 1–10（服务端亦校验）。"""
    if not 1 <= count <= 10:
        raise ValueError(f"count={count} 不在 1–10 范围（同题多篇一次会话最多删 10 篇）")
    resp = send_request("POST", f"{api_base}/api/accounts/{account_id}/note-deletions", key,
                        {"title": title, "count": count})
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    return resp.json()["deletion_id"]


def delete_note_result(view: dict, deletion_id: str):
    """删除终态视图 → 运营输出信封 + hint。返回 (out, exit_code)。
    删除不可逆：台账失效/超时一律 unknown（先复查再决定，绝不盲目重发），只有明确 done/error 才落定。"""
    status = view.get("status")
    if status == "done":
        out = {"outcome": "done", "deletion_id": deletion_id,
               "deleted": view.get("deleted"), "remaining": view.get("remaining")}
        if view.get("remaining"):
            out["hint"] = f"该标题还剩 {view['remaining']} 篇同题笔记"
        return out, 0
    if status == "error":
        reason = view.get("reason") or ""
        out = {"outcome": "failed", "deletion_id": deletion_id, "reason": reason}
        if "note_not_found" in reason:
            out["hint"] = "该号没有此标题的笔记——标题须精确匹配，可先 --notes 核对"
        elif "need_manual_login" in reason:
            out["hint"] = "creator 登录态失效，按 guide 手册②重新扫码后再试"
        return out, 1
    if status == "unknown":  # server 重启恰好打断删除执行（结果真实未知，服务端不冒充）
        return {"outcome": "unknown", "deletion_id": deletion_id, "reason": view.get("reason"),
                "hint": "server 重启打断了删除执行，结果真实未知：让运营人工到创作中心核对该标题"
                        "剩余篇数后再决定；删除不可逆，切勿盲目重发"}, 0
    if status == "gone":  # 台账已落库（2026-07-23 起 server 重启不丢终态），404 仅=该 deletion_id 不存在
        return {"outcome": "unknown", "deletion_id": deletion_id,
                "hint": "deletion_id 不存在（删除台账已落库、server 重启不丢终态）——多半是 ID 敲错"
                        "或从未发起。删除不可逆：先核对 deletion_id 用 --delete-status 重查；确实查无"
                        "此任务时用 --notes <账号> --refresh 核对剩余篇数（当天刚发的看板次日才有数据），"
                        "切勿盲目重发"}, 0
    # running：轮询超时未达终态——台账已落库随时可查，重查终态才是权威判据
    return {"outcome": "unknown", "deletion_id": deletion_id,
            "hint": f"轮询超时仍未出终态（任务可能仍在跑）。删除不可逆：先用 "
                    f"--delete-status {deletion_id} 重查并核对终态（deleted/remaining 是权威判据，"
                    f"台账已落库、server 重启也不丢），切勿盲目重发"}, 0


def start_note_export(api_base: str, key: str, account_id: int) -> str:
    """触发该号创作中心笔记数据导出，返回 export_id。"""
    resp = send_request("POST", f"{api_base}/api/accounts/{account_id}/note-exports", key)
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    return resp.json()["export_id"]


def refresh_notes(api_base: str, key: str, account_id: int, timeout: float = 300):
    """先触发导出并轮询到终态，成功后读快照。返回 (out, exit_code)。
    no_data（当天刚发的笔记次日才入看板）→ available:false 不算失败；其它 error 抛（落 failed）。"""
    export_id = start_note_export(api_base, key, account_id)
    print(f"  已触发导出 export_id={export_id}，轮询中…", file=sys.stderr)
    view = poll_async_task(api_base, key, f"{api_base}/api/note-exports/{export_id}", timeout)
    status = view.get("status")
    if status == "done":
        return account_notes(api_base, key, account_id), 0
    reason = view.get("reason") or ""
    if status == "error" and "no_data" in reason:
        return {"available": False, "no_data": True,
                "hint": "数据看板暂无数据：今天刚发的笔记次日才入看板，明天再拉即可（不是故障）"}, 0
    if status == "error":
        raise ValueError(f"导出失败：{reason}")
    if status == "gone":
        raise ValueError("导出任务台账失效（server 可能重启），请重跑 --notes <账号> --refresh")
    raise ValueError(f"导出轮询超时（export_id={export_id}），稍后重跑 --notes <账号> --refresh")


def manifest(api_base: str, key: str) -> dict:
    """拉服务端的机器可读契约（每个端点的参数/返回/注意）。**对接以它为实时真源**——
    skill 里写的能力说明是给人看的快照，两者冲突时以这份为准。"""
    resp = send_request("GET", f"{api_base}/api/manifest", key)
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    return resp.json()


def list_artifacts(api_base: str, key: str, job_id: int) -> dict:
    """列某次发布留下的现场截图（按发布流程真实时序，如 12_before_publish / 16_timeout）。
    **空清单不是异常**：本功能上线前的 job 没打截图标记，服务端会连 hint 一起说明原因。"""
    resp = send_request("GET", f"{api_base}/api/publish-jobs/{job_id}/artifacts", key)
    if resp.status_code == 404:
        return {"available": False, "job_id": job_id,
                "hint": "查不到这个 job（id 敲错，或该 job 不属于你被授权的账号）"}
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    view = resp.json()
    view["available"] = True
    return view


def _artifact_name(item):
    """清单元素兼容字符串与 {"name": ...} 两种形态。"""
    return item if isinstance(item, str) else (item.get("name") or item.get("filename"))


def download_artifacts(api_base: str, key: str, job_id: int, files, out_dir: Path, only=None):
    """把现场截图下载到 out_dir，返回落盘路径列表。only 非空时只下那一张。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for item in files:
        name = _artifact_name(item)
        if not name or (only and name != only):
            continue
        resp = send_request("GET", f"{api_base}/api/publish-jobs/{job_id}/artifacts/{quote(name)}",
                            key, timeout=120)
        if resp.status_code >= 400:
            raise ValueError(f"{name}: {api_error(resp)}")
        dest = out_dir / name
        dest.write_bytes(resp.content)
        saved.append(str(dest))
    return saved


def job_brief(view: dict) -> dict:
    """发布任务视图 → 运营信封。带上服务端的 `applied` 回显与 pending 详情：
    **参数被平台静默丢弃是当场可见的**（话题没挂上、组件没设上），不看这层就会以为全成了。"""
    out = {"outcome": view.get("status"), "job_id": view.get("job_id"),
           "note_url": view.get("note_url"), "error": view.get("error")}
    applied = view.get("applied")
    if applied:
        out["applied"] = applied
        if isinstance(applied, dict):
            failed_topics = applied.get("topics_failed") or []
            if failed_topics:
                out["topics_hint"] = ("有话题没挂上：`reason=no_exact_match` 说明平台话题库里没这个词"
                                      "（话题走下拉精选实体，不是随便打字），换个词就能解")
    for k in ("pending_reason", "pending_seconds_remaining", "pending_overdue", "pending_hint"):
        if view.get(k) is not None:
            out[k] = view[k]
    if view.get("pending_reason") == "waiting_schedule" and not view.get("pending_overdue"):
        # 定时任务等待是正常态。绝不能说成"超时/卡死"——按那个思路去"救"会杀掉定时发布
        out["hint"] = ("定时任务正在正常等待到点，**不是卡死也不是超时**，到点自动发；"
                       "只有 pending_overdue=true（到点超 30 分钟仍没派）才该报障")
    elif view.get("pending_overdue"):
        out["hint"] = "已到点超 30 分钟仍未派发（pending_overdue），这才是真异常，找服务端看"
    return out


def poll_job(api_base: str, key: str, job_id: int, timeout: float,
             interval: float = 10.0, max_transient: int = 3):
    """轮询到终态或超时；瞬时故障（网络异常/5xx）连续容忍 max_transient 次——
    一次抖动绝不能把仍在服务端跑的任务判成终态（会诱发重复发布）。
    401/403/404 是永久错误立即抛。超时返回最后一次视图（不算失败，可 --job 复查）。"""
    deadline = time.monotonic() + timeout
    transient = 0
    while True:
        try:
            resp = send_request("GET", f"{api_base}/api/publish-jobs/{job_id}", key)
        except Exception as e:  # 网络抖动 → 瞬时
            transient += 1
            if transient > max_transient:
                raise
            print(f"  轮询瞬时失败（{transient}/{max_transient}）: {e}", file=sys.stderr)
            time.sleep(interval)
            continue
        if resp.status_code >= 500:  # 服务端瞬时故障
            transient += 1
            if transient > max_transient:
                raise ValueError(api_error(resp))
            print(f"  轮询瞬时失败（{transient}/{max_transient}）: {api_error(resp)}", file=sys.stderr)
            time.sleep(interval)
            continue
        if resp.status_code >= 400:  # 401/403/404 永久错误
            raise ValueError(api_error(resp))
        transient = 0
        view = resp.json()
        status = view.get("status")
        print(f"  job {job_id}: {status}", file=sys.stderr)
        if status in TERMINAL_STATUSES or time.monotonic() >= deadline:
            return view
        time.sleep(interval)


# _job_view 精简视图字段（列任务用；与服务端 _job_view 同名，只挑运营关心的几个）。
_LIST_FIELDS = ("job_id", "account_id", "title", "status", "schedule_time",
                "note_url", "error", "created_at")


def _list_job_brief(job: dict) -> dict:
    return {k: job.get(k) for k in _LIST_FIELDS}


def list_jobs(api_base: str, key: str, account_id=None, status=None, limit=50) -> dict:
    """列发布任务（按 id 倒序）。status 原样透传——非法值由服务端 400 报合法清单，客户端不预判。"""
    params = {}
    if account_id is not None:
        params["account_id"] = account_id
    if status:
        params["status"] = status
    if limit:
        params["limit"] = limit
    qs = f"?{urlencode(params)}" if params else ""
    resp = send_request("GET", f"{api_base}/api/publish-jobs{qs}", key)
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    return {"jobs": [_list_job_brief(j) for j in resp.json().get("jobs", [])]}


def reschedule_job(api_base: str, key: str, job_id: int, schedule: str) -> dict:
    """改待发任务定时（PATCH 只带 schedule_time，绝不多带字段）。
    schedule=="now" → {"schedule_time": null} 清空转立即发；否则原样透传 ISO8601 时刻。
    仅 pending 可改：非 pending 服务端返 {ok:false,status}。"""
    payload = {"schedule_time": None if schedule == "now" else schedule}
    resp = send_request("PATCH", f"{api_base}/api/publish-jobs/{job_id}", key, payload)
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    return resp.json()


def cancel_job(api_base: str, key: str, job_id: int) -> dict:
    """撤稿（仅 pending 可取消）。{ok:true} 成功；{ok:false,status} 非 pending；404 抛。"""
    resp = send_request("POST", f"{api_base}/api/publish-jobs/{job_id}/cancel", key)
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    return resp.json()


def schedule_offset_warning(schedule: str):
    """定时时刻不带时区偏移时给 warning（服务端按 UTC 解释，会早/晚 8 小时发布）。
    建任务路径无运行时校验（保持不动），本函数仅供 reschedule 路径非阻塞提示、不硬失败。
    "now" 特殊值不校验。"""
    try:
        dt = datetime.fromisoformat(schedule)
    except ValueError:
        return f"schedule_time 无法解析为 ISO8601：{schedule}（应形如 2026-07-14T09:00:00+08:00）"
    if dt.tzinfo is None:
        return (f"schedule_time「{schedule}」不带时区偏移，服务端按 UTC 解释会早/晚 8 小时，"
                "建议带 +08:00")
    return None


def collect_upload_paths(inputs) -> list:
    """收集待上传图片：目录 → 取其中 png/jpg/jpeg/webp 按文件名排序；文件路径 → 原序保留。"""
    paths = []
    for item in inputs:
        p = Path(item)
        if p.is_dir():
            paths.extend(sorted(q for q in p.iterdir() if q.suffix.lower() in IMAGE_EXTS))
        elif p.is_file():
            paths.append(p)
        else:
            raise ValueError(f"路径不存在: {p}")
    return paths


def upload_image_batch(api_base: str, key: str, paths) -> dict:
    """上传一批图片得图床直链。客户端预检 1–18 张（服务端亦会 400），multipart 字段名统一 files。"""
    if not 1 <= len(paths) <= MAX_UPLOAD_IMAGES:
        raise ValueError(f"图片 {len(paths)} 张不在 1–{MAX_UPLOAD_IMAGES} 范围（服务端会拒绝 400）")
    files = [("files", (p.name, p.read_bytes(),
                        _IMAGE_MIME.get(p.suffix.lstrip(".").lower(), "application/octet-stream")))
             for p in paths]
    resp = send_request("POST", f"{api_base}/api/uploads/images", key, timeout=180, files=files)
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    return resp.json()


def list_uploads(api_base: str, key: str) -> dict:
    """列自己未过期的上传批次，透传 {batches:[...]}。"""
    resp = send_request("GET", f"{api_base}/api/uploads", key)
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    return resp.json()


def main():
    ap = argparse.ArgumentParser(description="经 nbdpsy-api 发布小红书图文笔记（异步）")
    ap.add_argument("--note", type=Path, help="笔记文件（post-NN.md，须含「## 发布文案」块）")
    ap.add_argument("--account", help="小红书账号：数字 id 或账号名/昵称")
    ap.add_argument("--video", type=Path, metavar="路径",
                    help="视频笔记：本机视频文件（.mp4/.mov/.flv/.f4v/.mkv/.rm/.rmvb/.m4v/.mpg/.mpeg/.ts）"
                         "；与图文/播客三选一。同机场景自动落进 server 数据目录（零传输）")
    ap.add_argument("--audio", type=Path, metavar="路径",
                    help="播客笔记：本机音频文件（.m4a/.mp3/.wav/.flac/.aac；时长须 10 分钟-2 小时、≤1GB）"
                         "；与图文/视频三选一")
    ap.add_argument("--cover", type=Path, metavar="路径",
                    help="视频/播客的自定义封面图（.jpg/.jpeg/.png/.webp）；不传则视频用平台截首帧")
    ap.add_argument("--images-dir", type=Path, help="配图目录（默认 <笔记同目录>/images/<笔记名>/）")
    ap.add_argument("--schedule", help="定时发布，ISO8601 带时区偏移，如 2026-07-14T09:00:00+08:00")
    ap.add_argument("--api-base", help="API base（默认凭据 NBDPSY_XHS_API_BASE 或 https://mcp.nbdpsy.com）")
    ap.add_argument("--no-wait", action="store_true", help="提交后不等结果（稍后 --job 查询）")
    ap.add_argument("--wait-timeout", type=float, default=None,
                    help="轮询等待上限秒数（发布默认 900，删除/导出默认 300）")
    ap.add_argument("--dry-run", action="store_true", help="只打 payload 摘要，不发请求")
    ap.add_argument("--job", type=int, help="只查询该发布任务状态")
    ap.add_argument("--list-accounts", action="store_true", help="列出可操作账号")
    ap.add_argument("--self-check", action="store_true",
                    help="一键接入自检：连通性+身份+被授权账号+就绪判定（可反复跑）")
    ap.add_argument("--extension-info", action="store_true",
                    help="chrome 插件下载地址+安装步骤+server_time（登录前先取）")
    ap.add_argument("--wait-login", action="store_true",
                    help="等运营扫码登录完成（须配 --since；重登旧号加 --account-id）")
    ap.add_argument("--since", help="--wait-login 用：--extension-info 返回的 server_time")
    ap.add_argument("--account-id", type=int, help="--wait-login 重登旧号时指定账号 id")
    ap.add_argument("--login-timeout", type=float, default=600, help="等登录上限秒数（默认 600）")
    ap.add_argument("--check-cookie", metavar="账号名或ID", help="触发该账号 cookie 验活并轮询到结果")
    ap.add_argument("--notes", metavar="账号名或ID",
                    help="拉该账号已发布笔记的清单与互动数据（供分析；已上线，(账号,标题,发布时间) 三元组主键）")
    ap.add_argument("--refresh", action="store_true",
                    help="--notes 前先触发一次导出拉最新数据再读（约 1–2 分钟）")
    ap.add_argument("--delete-note", action="store_true",
                    help="按标题删除已发布笔记（不可逆！须配 --account 与 --title；同题多篇用 --count）")
    ap.add_argument("--title", help="--delete-note 的笔记标题（精确匹配，容忍卡片截断）")
    ap.add_argument("--count", type=int, default=1,
                    help="--delete-note 同题多篇时一次最多删几篇（1–10，默认 1，留 1 篇清重复）")
    ap.add_argument("--delete-status", metavar="DELETION_ID",
                    help="重查删除任务终态（deleted/remaining 为权威判据；轮询超时后的首选复查通道）")
    ap.add_argument("--list-jobs", action="store_true",
                    help="列发布任务（可配 --account/--status/--limit 过滤）")
    ap.add_argument("--status", help="--list-jobs 过滤状态（pending/publishing/published/failed/canceled）")
    ap.add_argument("--limit", type=int, default=50, help="--list-jobs 取前 N 条（默认 50）")
    ap.add_argument("--reschedule", type=int, metavar="JOB_ID",
                    help="改待发任务定时（须配 --schedule <ISO8601带时区偏移|now>；now=转立即发）")
    ap.add_argument("--cancel", type=int, metavar="JOB_ID", help="撤稿（仅 pending 任务可取消）")
    ap.add_argument("--upload-images", nargs="+", metavar="路径",
                    help="上传图片得图床直链：目录（按名排序）或多个文件路径（1–18 张）")
    ap.add_argument("--list-uploads", action="store_true", help="列自己未过期的图床上传批次")
    ap.add_argument("--manifest", action="store_true",
                    help="拉服务端机器可读契约（端点/参数/返回/注意；对接的实时真源）")
    ap.add_argument("--artifacts", type=int, metavar="JOB_ID",
                    help="列该次发布留下的现场截图（排障用；空清单不是异常）")
    ap.add_argument("--out", metavar="DIR", help="--artifacts 配它则把截图下载到该目录")
    ap.add_argument("--artifact-name", help="--artifacts --out 时只下这一张")
    ap.add_argument("--collection-id", help=(
        "把这篇笔记【归拢进】该合集——它会成为合集成员、出现在合集页；"
        "⛔ 不是「在正文里引用/提及合集」，想提及请自己写进文案。"
        "按稿件 frontmatter 的『议题合集』挂；⛔ 科普笔记绝不挂「咨询师简介」（那里只放咨询师推介笔记）。"
        "id 每批用 note_ops.py --collections 现查、按合集名匹配，别写死。"
        "⚠️ 挂错只能人工去创作后台摘（server 无移出能力）"))
    ap.add_argument("--quoted-note-id", help="发布时引用该笔记（显式指定，优先级高于 --related-counselor）")
    ap.add_argument("--activity-id", help="发布时关联该活动（会往正文末尾追加活动话题；用 note_ops.py --activities 查）")
    ap.add_argument("--related-counselor", help="关联咨询师姓名（驱动服务端在本账号内自动推导引用笔记）")
    ap.add_argument("--note-purpose",
                    help="本篇核心目的（推介咨询师/概念解读/案例剖析/热点分析/互动引导/个人记录/其他，"
                         "词表会扩不强制）；也可写进笔记 frontmatter，命令行优先")
    ap.add_argument("--check-cover", type=Path, metavar="封面",
                    help="只校验封面产出凭证（图文传首图 images/<post名>/P01.png），不发布")
    ap.add_argument("--confirm-cover", type=Path, metavar="封面",
                    help="给已有封面凭证补人工确认戳（配 --confirmed-by 姓名），不发布——"
                         "封面是批量顺带出的时候，闸门 A 认这个戳或重新 --cover-only 单出")
    ap.add_argument("--confirmed-by", metavar="姓名",
                    help="--confirm-cover 的确认人：看过这张封面的人签名（⛔ 别代签）")
    ap.add_argument("--ledger", help=f"台账路径（默认 <稿件同目录>/{LEDGER_NAME}）")
    ap.add_argument("--ledger-check", nargs="?", const="", metavar="路径",
                    help="读欠账：列出所有未闭环行（有欠账 exit 3；台账不存在 exit 4，那不是闭环）")
    args = ap.parse_args()

    # 这两条不打网络、不需要凭据：出图后自查凭证、接手时先读欠账
    if args.ledger_check is not None:
        try:
            p = Path(args.ledger_check) if args.ledger_check else ledger_path(args, args.note)
        except ValueError as e:
            # 定位不到台账同样**不是闭环**（exit 4 的语义就是「没有证据」），⛔ 别回 0
            print(json.dumps({"ledger": None, "exists": False, "open_rows": [],
                              "hint": str(e)}, ensure_ascii=False))
            sys.exit(4)
        sys.exit(ledger_check(p))
    if args.check_cover:
        try:
            print(json.dumps(check_cover_receipt(args.check_cover), ensure_ascii=False, indent=2))
            sys.exit(0)
        except ValueError as e:
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
            sys.exit(1)
    if args.confirm_cover:
        try:
            print(json.dumps(confirm_cover_receipt(args.confirm_cover, args.confirmed_by),
                             ensure_ascii=False, indent=2))
            sys.exit(0)
        except ValueError as e:
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
            sys.exit(1)

    key = nbdpsy_common.get_secret(nbdpsy_common.XHS_API_KEY)
    if not key:
        print(f"MISSING:{nbdpsy_common.XHS_API_KEY} 找管理员要「运营接入配置包」，"
              "secret import 导入后重试", file=sys.stderr)
        sys.exit(1)
    api_base = (args.api_base or nbdpsy_common.xhs_api_base()).rstrip("/")

    submitted_job_id = None  # 已入队的任务号——之后的任何异常都不能丢它，否则会诱发重复发布
    submitted_deletion_id = None  # 已入队的删除任务号——删除不可逆，异常时绝不能落 failed 诱导重发
    ledger_state = None  # (台账路径, 时间戳, 账号, 意图行, 意图摘要, 稿件名)：异常时把那行改写成「状态未知」
    try:
        if args.list_accounts:
            print(json.dumps({"accounts": list_accounts(api_base, key)}, ensure_ascii=False))
            return
        if args.self_check:
            report = self_check(api_base, key)
            if report.get("ok"):
                print(f"✓ 已接入：{report['identity']['name']}，"
                      f"可操作 {report['account_count']} 个账号；{report['verdict']}", file=sys.stderr)
            else:
                print(f"✗ 接入自检未通过（{report.get('stage')}）：{report.get('error')}", file=sys.stderr)
            print(json.dumps(report, ensure_ascii=False))
            sys.exit(0 if report.get("ok") and report.get("ready") else 1)
        if args.extension_info:
            print(json.dumps(extension_info(api_base, key), ensure_ascii=False))
            return
        if args.wait_login:
            if not args.since:
                ap.error("--wait-login 需要 --since <server_time>（先跑 --extension-info 取）")
            view = wait_login(api_base, key, args.since, args.account_id,
                              timeout=args.login_timeout)
            if not view.get("done"):
                view["hint"] = "还没等到登录完成：确认运营已装插件并在无痕窗扫码，然后重跑本命令"
            print(json.dumps(view, ensure_ascii=False))
            sys.exit(0 if view.get("done") else 1)
        if args.check_cookie:
            aid, label, _ = resolve_account(api_base, key, args.check_cookie)
            view = check_cookie(api_base, key, aid)
            view["account"] = {"id": aid, "name": label}
            print(json.dumps(view, ensure_ascii=False))
            # valid=0；invalid/captcha 需人工处理=1；error 是基础设施失败≠失效，也回 1 但别让人重登
            sys.exit(0 if view.get("status") == "valid" else 1)
        if args.delete_note:
            if not args.account or not args.title:
                ap.error("--delete-note 需要 --account 与 --title")
            print(f"⚠ 删除不可逆（count={args.count}），应已与运营确认账号、完整标题与删几篇",
                  file=sys.stderr)
            aid, label, _ = resolve_account(api_base, key, args.account)
            deletion_id = start_note_deletion(api_base, key, aid, args.title, args.count)
            submitted_deletion_id = deletion_id  # 202 已入队：此后任何异常都走 unknown，绝不 failed
            print(f"  已触发删除 deletion_id={deletion_id}，轮询中…", file=sys.stderr)
            view = poll_async_task(api_base, key,
                                   f"{api_base}/api/note-deletions/{deletion_id}",
                                   timeout=300 if args.wait_timeout is None else args.wait_timeout)
            out, code = delete_note_result(view, deletion_id)
            out["account"] = {"id": aid, "name": label}
            print(json.dumps(out, ensure_ascii=False))
            sys.exit(code)
        if args.delete_status:
            # 权威复查通道：重查删除任务终态（deleted/remaining 是权威判据；台账 server 重启前一直有效）
            resp = send_request("GET", f"{api_base}/api/note-deletions/{args.delete_status}", key)
            if resp.status_code == 404:
                view = {"status": "gone"}
            elif resp.status_code >= 400:
                raise ValueError(api_error(resp))
            else:
                view = resp.json()
            if view.get("status") == "running":
                print(json.dumps({"outcome": "running", "deletion_id": args.delete_status,
                                  "hint": "删除仍在执行（约 1–2 分钟），稍后重跑 --delete-status 复查"},
                                 ensure_ascii=False))
                sys.exit(0)
            out, code = delete_note_result(view, args.delete_status)
            print(json.dumps(out, ensure_ascii=False))
            sys.exit(code)
        if args.manifest:
            print(json.dumps(manifest(api_base, key), ensure_ascii=False))
            return
        if args.artifacts is not None:
            view = list_artifacts(api_base, key, args.artifacts)
            files = view.get("files") or []
            if args.out and files:
                view["saved"] = download_artifacts(api_base, key, args.artifacts, files,
                                                   Path(args.out), args.artifact_name)
            elif args.out:
                view["saved"] = []
            print(json.dumps(view, ensure_ascii=False))
            return
        if args.notes:
            aid, label, _ = resolve_account(api_base, key, args.notes)
            if args.refresh:
                view, code = refresh_notes(api_base, key, aid,
                                           timeout=300 if args.wait_timeout is None else args.wait_timeout)
            else:
                view, code = account_notes(api_base, key, aid), 0
            view["account"] = {"id": aid, "name": label}
            print(json.dumps(view, ensure_ascii=False))
            sys.exit(code)  # available=false（no_data/无快照）不算失败，exit 0
        if args.list_jobs:
            account_id = None
            if args.account:
                account_id, _, _ = resolve_account(api_base, key, args.account)
            print(json.dumps(list_jobs(api_base, key, account_id, args.status, args.limit),
                             ensure_ascii=False))
            return
        if args.reschedule is not None:
            if not args.schedule:
                ap.error("--reschedule 必须配 --schedule <ISO8601带时区偏移|now>")
            if args.schedule != "now":
                w = schedule_offset_warning(args.schedule)
                if w:
                    print(f"⚠ {w}", file=sys.stderr)
            view = reschedule_job(api_base, key, args.reschedule, args.schedule)
            if not view.get("ok"):
                view["hint"] = (f"任务当前状态 {view.get('status')}：已在发/已终态，改不了；"
                                "需另建新任务")
                print(json.dumps(view, ensure_ascii=False))
                sys.exit(1)
            print(json.dumps(view, ensure_ascii=False))
            return
        if args.cancel is not None:
            view = cancel_job(api_base, key, args.cancel)
            if not view.get("ok"):
                st = view.get("status")
                view["hint"] = (
                    "任务已在发布中，撤稿拦不住；若已发出需到小红书端自行删除" if st == "publishing"
                    else f"任务已是终态（{st}），无需取消" if st in ("published", "failed", "canceled")
                    else f"当前状态 {st}，非 pending 取消不了"
                )
                print(json.dumps(view, ensure_ascii=False))
                sys.exit(1)
            print(json.dumps(view, ensure_ascii=False))
            return
        if args.upload_images:
            paths = collect_upload_paths(args.upload_images)
            result = upload_image_batch(api_base, key, paths)
            result["warnings"] = ["urls 即可直接作为发布 images/复用素材；默认 7 天后过期"]
            print(json.dumps(result, ensure_ascii=False))
            return
        if args.list_uploads:
            print(json.dumps(list_uploads(api_base, key), ensure_ascii=False))
            return
        if args.job is not None:
            submitted_job_id = args.job
            view = poll_job(api_base, key, args.job, timeout=0)
            out = job_brief(view)
            # 闸门 C：复查也算差集并回填台账（--no-wait / 轮询超时之后就靠这条闭环）。
            # 台账定位不到（既没 --ledger 也没 --note）时只算不写——绝不往 cwd 乱落台账文件。
            intent = intent_from_view(view)
            lp = ledger_path(args, args.note) if (args.ledger or args.note) else None
            old = ledger_find_by_job(lp, args.job) if lp else ""
            # 闭环判据必须合并事后补救的终态（台账登记任务号 → 回服务端验 applied）
            remedies = ledger_remedies(old)
            actual, gap, ngap = diff_intent_actual(
                view, intent, verify_remedies(api_base, key, remedies))
            out.update({"intent": intent_summary(intent), "actual": actual,
                        "gap": gap, "gap_count": ngap})
            if lp:
                closed = view.get("status") == "published" and ngap == 0
                row = ledger_row(closed, now_iso(), args.note.name if args.note else "—",
                                 account_display(api_base, key, view.get("account_id")), args.job,
                                 intent_summary(intent), actual, gap, remedies,
                                 note_id=view.get("note_id"))
                ledger_replace(lp, old, row) if old else ledger_append(lp, row)
                out["ledger"] = str(lp)
            owed = view.get("status") == "published" and ngap > 0
            if owed:
                out["hint"] = ("**published 但有欠账，这不是成功**：按差集逐项补救，"
                               f"补完再跑 --job {args.job} 复核闭环")
            print(json.dumps(out, ensure_ascii=False))
            sys.exit(1 if view.get("status") in ("failed", "canceled") else (3 if owed else 0))

        if args.video and args.audio:
            ap.error("--video 与 --audio 互斥（图文/视频/播客三选一）")
        if not args.note or not args.account:
            ap.error("发布需要 --note 与 --account（或改用 --job / --list-accounts）")

        meta, body = parse_frontmatter(args.note.read_text(encoding="utf-8"))
        title = str(meta.get("title") or "").strip()
        if not title:
            raise ValueError("frontmatter 缺 title")
        content, topics = split_content_topics(extract_publish_text(body), meta)
        # 🔴 **停用热线硬闸：放在发布路径最前面**（2026-08-21）。
        # 🩸 全仓扫出 **42 个在途稿件**仍带停用热线，而它们是从**排期稿**抓到的
        #    ⇒ **在途稿可以绕过稿件闸门直接发** ⇒ 只挂稿件闸门挡不住。
        # ⚠️ 这里**在 dry-run 之前**：预检的意义就是在花代价之前拦住。
        _hot = compliance_core.gate_hotlines("\n".join([title, content]))
        if _hot:
            raise ValueError("停用热线闸拒发（⛔ 不是格式问题，是会让人打不通的号码）：\n  · "
                             + "\n  · ".join(_hot))
        media_kind = "video" if args.video else ("audio" if args.audio else "images")
        # 图文误传 --cover 早拦（2026-08-16 干跑实测）：真发布路径本来就会抛，但那处在
        # dry-run 之后——于是「--dry-run 自查绿灯、真发才红」，且失败会在台账留一条
        # 永远闭不掉的「未入队」行。预检的意义就是在花代价之前拦住，所以提到这里。
        if args.cover and not (args.video or args.audio):
            raise ValueError(
                "⛔ 图文/文字版笔记没有独立封面通道：封面就是第一张图（P01），--cover 仅用于视频/播客。\n"
                "   封面闸门卡在出图阶段（工序③），发出去即定、事后无补救通道（唯一出路=删稿重发）。")
        # 闸门 B（2026-08-16 补代码化）：视频/播客发布必须走 publish_video.py。
        # 它能跑通不代表该跑——本脚本没有 --fix-cover/--recheck，而视频发布的设封面入口
        # 自上线起 31/31 全败，必然要走「发布→补封面→回读→闭台账」四步。用本脚本发视频
        # ＝第②③④步没有工具，台账永远闭不掉（08-13 丢补封面步的原样复现路径）。
        if media_kind != "images":
            raise ValueError(
                f"⛔ {media_kind} 发布不走 publish_note.py，改用 publish_video.py（闸门 B）：\n"
                f"   python3 publish_video.py --note <稿件> --account <账号> "
                f"--{media_kind} <媒体> --cover <封面> --collection ...\n"
                "   理由：视频/播客是两段式四步主路径（发布→--fix-cover 补封面→--recheck 回读→"
                "--ledger-check 闭台账），本脚本只有第①步。")
        image_paths = [] if media_kind != "images" else collect_images(args.note, args.images_dir)
        extras = collect_extras(meta, args)
        warnings = build_warnings(title, content, topics, image_paths, media_kind) + extras_warnings(extras)
        for w in warnings:
            print(f"⚠ {w}", file=sys.stderr)

        # 闸门 A：封面产出凭证——图文的封面就是第一张图（P01），逐篇校验它的同名 .meta.json；
        # 视频/播客走 publish_video.py，这里若仍传了 --cover 也过同一道闸（三形态一个判据）。
        # ⛔ 不过就抛，绝不带着往下走：无凭证拒发，凭证比图旧也拒发。
        if media_kind == "images":
            cover_receipt = check_images_cover_receipt(args.note, image_paths)
        elif args.cover:
            cover_receipt = check_cover_receipt(args.cover)
        else:
            cover_receipt = None

        # 闸门 C 的「意图」：图文没有独立 cover 组件（首图即封面），所以 cover 只在视频/播客路径记
        intent = build_publish_intent(
            topics, extras, args.cover.name if (args.cover and media_kind != "images") else None)
        intent_txt = intent_summary(intent)

        if args.dry_run:
            print(json.dumps({
                "outcome": "dry_run", "title": title, "content_chars": len(content),
                "topics": topics, "media_kind": media_kind,
                "video": str(args.video) if args.video else None,
                "audio": str(args.audio) if args.audio else None,
                "cover": str(args.cover) if args.cover else None,
                "images": [str(p) for p in image_paths],
                "cover_receipt": cover_receipt,
                "account": args.account, "schedule_time": args.schedule,
                "extras": extras, "intent": intent_txt, "warnings": warnings,
            }, ensure_ascii=False, indent=2))
            return

        account_id, account_label, acc_warn = resolve_account(api_base, key, args.account)
        if acc_warn:
            warnings.append(acc_warn)
            print(f"⚠ {acc_warn}", file=sys.stderr)

        # 闸门 C：**提交之前**先落意图行（台账先行）。会话断了、回执没读到，欠账仍在纸上。
        lp = ledger_path(args, args.note)
        ts = now_iso()
        who = account_display(api_base, key, account_id, account_label)
        pending_row = ledger_row(False, ts, args.note.name, who, "待回执", intent_txt, "—", "待回执")
        ledger_append(lp, pending_row)
        ledger_state = (lp, ts, who, pending_row, intent_txt, args.note.name)

        payload = {"account_id": account_id, "title": title, "content": content,
                   "topics": topics, **extras}
        if media_kind == "video":
            payload["video"] = stage_media(args.video, "video")
        elif media_kind == "audio":
            payload["audio"] = stage_media(args.audio, "audio")
        else:
            payload["images"] = b64_items(image_paths)
        if args.cover:
            if media_kind == "images":
                raise ValueError("图文笔记没有独立封面（封面就是第一张图），--cover 仅用于视频/播客")
            payload["cover"] = stage_media(args.cover, "cover")
        if args.schedule:
            payload["schedule_time"] = args.schedule

        what = {"video": f"视频 {args.video.name if args.video else ''}",
                "audio": f"播客 {args.audio.name if args.audio else ''}",
                "images": f"{len(image_paths)} 图"}[media_kind]
        print(f"提交发布：{args.note.name} → 账号 {account_label}（{what}）…", file=sys.stderr)
        resp = send_request("POST", f"{api_base}/api/publish-jobs", key, payload, timeout=180)
        if resp.status_code >= 400:
            raise ValueError(api_error(resp))
        job_id = resp.json()["job_id"]
        submitted_job_id = job_id
        print(f"  已入队 job_id={job_id}", file=sys.stderr)
        ledger_replace(lp, pending_row,
                       ledger_row(False, ts, args.note.name, who, job_id, intent_txt, "—", "待回执"))

        if args.no_wait:
            print(json.dumps({"outcome": "pending", "job_id": job_id, "note_url": None,
                              "error": None, "warnings": warnings, "ledger": str(lp),
                              "intent": intent_txt,
                              "hint": f"台账那一行仍是 `- [ ]`（未闭环）：稍后 --job {job_id} "
                                      "复查会自动回填实际与差集，差集空了才算闭环"},
                             ensure_ascii=False))
            return

        view = poll_job(api_base, key, job_id,
                        timeout=900 if args.wait_timeout is None else args.wait_timeout)
        out = job_brief(view)
        out["warnings"] = warnings
        # 闸门 C：回读服务端 applied 逐项比对意图 → 差集非空就是欠账（published 也不算成功）
        actual, gap, ngap = diff_intent_actual(view, intent)
        closed = view.get("status") == "published" and ngap == 0
        row = ledger_row(closed, ts, args.note.name, who, job_id, intent_txt, actual, gap)
        old = ledger_find_by_job(lp, job_id)
        ledger_replace(lp, old or pending_row, row)
        out.update({"ledger": str(lp), "intent": intent_txt, "actual": actual,
                    "gap": gap, "gap_count": ngap})
        if out["outcome"] not in TERMINAL_STATUSES:
            # 定时任务的 pending 是正常等待，job_brief 已给出准确说法，别用"仍在发布中"盖掉它
            out.setdefault("hint",
                           f"仍在发布中，稍后 python3 publish_note.py --job {job_id} 复查"
                           "（复查会回填台账并重算差集）")
        elif closed:
            pass
        elif out["outcome"] == "published":
            out["hint"] = ("**published 但有欠账，这不是成功**：按差集逐项补救"
                           "（合集/引用走 note_ops.py --set-components；话题没挂上换词重挂），"
                           f"补完跑 --job {job_id} 复核闭环")
        print(json.dumps(out, ensure_ascii=False))
        sys.exit(1 if out["outcome"] in ("failed", "canceled")
                 else (3 if (out["outcome"] == "published" and ngap) else 0))

    except Exception as e:
        msg = sandbox_hint(e)
        if submitted_deletion_id is not None:
            # 删除已在服务端入队且不依赖客户端连接——大概率已执行。绝不落 failed（文档把 failed
            # 定义为「删除没发生、修因重试」，会诱导 agent 重发不可逆删除，清重场景可致全灭）。
            print(f"  → 状态未知: {msg}", file=sys.stderr)
            print(json.dumps({
                "outcome": "unknown", "deletion_id": submitted_deletion_id, "error": msg,
                "hint": f"删除可能已在服务端执行（任务不依赖本地连接）。删除不可逆，绝不盲目重发："
                        f"先用 --delete-status {submitted_deletion_id} 重查终态"
                        f"（deleted/remaining 是权威判据），查到 404 再用 --notes <账号> --refresh "
                        f"核对剩余篇数后再决定",
            }, ensure_ascii=False))
            sys.exit(0)
        if submitted_job_id is not None:
            # 任务已在服务端入队（还会自动重试），绝不判 failed——那会让 agent 重发同一篇
            print(f"  → 状态未知: {msg}", file=sys.stderr)
            out = {"outcome": "unknown", "job_id": submitted_job_id, "note_url": None,
                   "error": msg,
                   "hint": f"任务可能仍在服务端跑（自动重试最长约 40 分钟），"
                           f"先用 --job {submitted_job_id} 复查，勿直接重发以免重复发布"}
            if ledger_state:  # 台账那一行必须落到「状态未知」，⛔ 不许留在「待回执」假装还没发
                lp, ts, who, pending_row, intent_txt, what = ledger_state
                ledger_replace(lp, pending_row,
                               ledger_row(False, ts, what, who, submitted_job_id, intent_txt,
                                          "状态未知", f"状态未知({msg[:60]})"))
                out["ledger"] = str(lp)
            print(json.dumps(out, ensure_ascii=False))
            sys.exit(0)
        # 未入队的异常（解析/账号/建任务失败/被闸门拦下）才是真 failed
        print(f"  → 失败: {msg}", file=sys.stderr)
        out = {"outcome": "failed", "job_id": None, "note_url": None, "error": msg}
        if ledger_state:  # 意图行已落但没入队：改写成「提交失败」，别把它留成待回执的幽灵行
            lp, ts, who, pending_row, intent_txt, what = ledger_state
            ledger_replace(lp, pending_row,
                           ledger_row(False, ts, what, who, "未入队", intent_txt,
                                      "提交失败", f"提交失败({msg[:60]})"))
            out["ledger"] = str(lp)
        print(json.dumps(out, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
