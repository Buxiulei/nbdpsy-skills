#!/usr/bin/env python3
"""NBDpsy skills 共享工具：内容工作区解析 + 凭据三层解析。
此文件真源在仓库 shared/，由 tools/sync_shared.py 同步到各 skill 的 scripts/，勿单独改副本。
凭据存储：用户级 secrets 文件在任何仓库之外，永不入库。"""
import os, sys, json, re, shutil, subprocess, tempfile
from datetime import datetime
from pathlib import Path

def user_secrets_path() -> Path:
    if os.environ.get("NBDPSY_SECRETS"):
        return Path(os.environ["NBDPSY_SECRETS"]).expanduser()
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / "nbdpsy" / "secrets.env"
    return Path.home() / ".config" / "nbdpsy" / "secrets.env"

def resolve_workspace() -> Path:
    env = os.environ.get("NBDPSY_WORKSPACE")
    if env:
        return Path(env).expanduser()
    cand = Path.cwd() / "seo-geo" / "content"
    if cand.is_dir():
        return cand
    return Path.home() / "nbdpsy-content"

def _read_env_file(path: Path, key: str):
    if not path.is_file():
        return None
    val = None
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line.startswith(key + "="):
            val = line.split("=", 1)[1].strip().strip("'\"")
    return val or None

def get_secret(key: str):
    if os.environ.get(key):
        return os.environ[key]
    v = _read_env_file(resolve_workspace() / ".env", key)
    if v:
        return v
    return _read_env_file(user_secrets_path(), key)

def set_secret(key: str, value: str) -> Path:
    store = user_secrets_path()
    store.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if store.is_file():
        lines = [l for l in store.read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.startswith(key + "=")]
    lines.append(f"{key}={value}")
    store.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if os.name != "nt":
        os.chmod(store, 0o600)
    return store

def ensure_secrets(keys):
    return [k for k in keys if not get_secret(k)]

BLOG_API_KEY = "NBDPSY_BLOG_API_KEY"  # 发文凭据，必需
REQUIRED_KEYS = [BLOG_API_KEY]
DOUBAO_API_KEY = "VOLC_TTS_API_KEY"  # 新版控制台单一凭据，优先
DOUBAO_KEYS = ["VOLC_TTS_APPID", "VOLC_TTS_ACCESS_TOKEN"]  # 旧版双凭据，向后兼容
XHS_API_KEY = "NBDPSY_XHS_API_KEY"  # 小红书运营 API（nbdpsy-api）运营专属 apikey，可选
# 战略规划报告发布（管理后台 /strategy）凭据，**可选**：不配就回退用发文 key。
# 权限隔离在服务端的 scope 层已经完成——blog_api_keys.scopes 是 JSONB 数组，一把 key
# 天然可同时持有 ["blog:write","strategy:write"]，服务端逐 scope fail-closed 校验；
# 物理上分两把 key 只是签发时的选择，不构成额外隔离。故运营只需一把 key，权限由管理员
# 在后台勾选，不由凭据数量区分。本键保留为**显式覆盖**：真要一把能独立吊销的战略专用 key
# 时单配它即优先生效。
STRATEGY_API_KEY = "NBDPSY_STRATEGY_API_KEY"
XHS_API_BASE_KEY = "NBDPSY_XHS_API_BASE"
DEFAULT_XHS_API_BASE = "https://mcp.nbdpsy.com"
# 视频管线 REST（搬运 / 分镜级再制作 / 成片修订）：2026-07-23 薯营家（xhs.nbdpsy.com）整套停机，
# 视频与小红书发布已统一收口到 nbdpsy-server（mcp.nbdpsy.com），同一台主机、同一把 apikey
# （NBDPSY_XHS_API_KEY）。故默认基址与 xhs_api_base 同指 mcp.nbdpsy.com；单列 base 键仅为可覆盖。
VIDEO_API_BASE_KEY = "NBDPSY_VIDEO_API_BASE"
DEFAULT_VIDEO_API_BASE = "https://mcp.nbdpsy.com"

def get_base(key: str):
    """服务基址解析：只认 环境变量 > 用户级 secrets，**跳过 workspace/.env**。
    基址决定密钥被发往哪台主机——workspace/.env 可能随内容产物/克隆仓库到达，一旦允许它改写基址，
    攻击者放一个只写 *_API_BASE、不写 key 的 .env，密钥仍会从用户级穿透解析出来并随请求发去
    恶意主机（confused deputy）。密钥本身仍走 get_secret 三层不变；要临时改基址用环境变量或
    各脚本的 --api-base 参数（都需明确操作本机，不受工作区文件影响）。"""
    if os.environ.get(key):
        return os.environ[key]
    return _read_env_file(user_secrets_path(), key)

def strategy_api_key():
    """战略报告凭据：显式配的 NBDPSY_STRATEGY_API_KEY 优先，否则回退发文 key。
    回退不降级安全：服务端按 scope fail-closed，只带 blog:write 的 key 调 strategy
    端点会被 403 拦住，不会静默越权。"""
    return get_secret(STRATEGY_API_KEY) or get_secret(BLOG_API_KEY)

def xhs_api_base() -> str:
    return get_base(XHS_API_BASE_KEY) or DEFAULT_XHS_API_BASE

def video_api_base() -> str:
    return get_base(VIDEO_API_BASE_KEY) or DEFAULT_VIDEO_API_BASE

# ── 安装版本标记（install.sh / install.ps1 落盘，doctor 只读、不联网）──
# 装完本机曾经没有任何版本痕迹（版本号只住在仓库根 .claude-plugin/plugin.json，从没被拷到安装目的地），
# 想知道装的是哪版只能靠 mtime 猜。现在安装器在每个 skills 根写一份标记，doctor 读出来报给运营。
INSTALL_MARKER_NAME = ".nbdpsy-skills-install.json"

def _marker_search_dirs():
    """标记候选目录：本文件往上 4 层（scripts/ → skill 目录 → skills 根 → 其上），
    再退 ~/.claude/skills 与 ~/.agents/skills 两个固定安装位置。"""
    dirs = list(Path(__file__).resolve().parents[:4])
    dirs += [Path.home() / ".claude" / "skills", Path.home() / ".agents" / "skills"]
    return dirs

def find_install_marker():
    """读安装版本标记，返回 (data: dict|None, path: Path|None)。
    读不到 / 解析失败一律当没有——版本标记是纯信息项，绝不参与 doctor 的成败判定。"""
    for d in _marker_search_dirs():
        p = d / INSTALL_MARKER_NAME
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        if isinstance(data, dict):
            return data, p
    return None, None

def _toolkit_version_note(marker):
    """版本行文案。⚠️ 缺标记只是 info：存量机器全都没有这个文件，判 fail 会让所有人 doctor 变红。"""
    if not marker:
        return ("工具包版本标记缺失（旧版安装器装的）——重跑一次 install.sh 即可补上，不影响任何功能。")
    ver = str(marker.get("version") or "unknown")
    commit = str(marker.get("commit") or "unknown")
    date = str(marker.get("installed_at") or "unknown").split("T")[0]
    return f"工具包 v{ver}（{commit}，装于 {date}）"

def doctor():
    """自检可复制类凭据。返回 (report, exit_code)。绝不把密钥值放进 report。"""
    required_missing = [k for k in REQUIRED_KEYS if not get_secret(k)]
    doubao_ready = bool(get_secret(DOUBAO_API_KEY)) or all(get_secret(k) for k in DOUBAO_KEYS)
    xhs_ready = bool(get_secret(XHS_API_KEY))
    strategy_ready = bool(strategy_api_key())
    ok = not required_missing
    notes = []
    if required_missing:
        notes.append("缺发文凭据 NBDPSY_BLOG_API_KEY：找管理员要「凭据配置包」发给我一键导入"
                     "（管理员生成入口：manage.nbdpsy.com → 博客 → API Keys → 生成凭据配置包）。")
    if not doubao_ready:
        notes.append("豆包语音未配置（可选）：优先配 VOLC_TTS_API_KEY（新版控制台单一凭据，找管理员要"
                     "「凭据配置包」，或去控制台 speech/new/setting/apikeys 自建），也可用旧版 "
                     "VOLC_TTS_APPID+VOLC_TTS_ACCESS_TOKEN；都不配则视频旁白用免费 edge 引擎。")
    if not xhs_ready:
        notes.append("小红书自动发布未配置（可选）：缺 NBDPSY_XHS_API_KEY——管理员在后台"
                     "「小红书运营接入」生成的接入包里带此凭据；不配则小红书笔记只能人工发布。")
    if not strategy_ready:
        notes.append("战略规划报告发布不可用（可选）：本机一把 key 都没有——它默认复用发文凭据 "
                     "NBDPSY_BLOG_API_KEY，配好那一把即可，无需单配 NBDPSY_STRATEGY_API_KEY。")
    else:
        # 不谎报「可用」：这里只证明「有凭据可发」，能不能写进战略报告由服务端 scope 说了算。
        notes.append("战略规划报告发布：用的是发文凭据（若单配了 NBDPSY_STRATEGY_API_KEY 则以它为准）。"
                     "**权限由服务端按 scope 判定**——这把 key 若没勾 strategy:write，发布时会被 403 "
                     "拒绝；届时请管理员在管理后台 → 博客 → API Keys 页给它补勾该权限。")
    notes.append("视频画面用的即梦需登录一次：让 AI 帮你登录（会自动弹浏览器，用抖音 App 扫码/点确认即可）；"
                 "登录态由 nbdpsy-text-to-video/scripts/check_env.py 检测。")
    marker, _ = find_install_marker()
    notes.append(_toolkit_version_note(marker))
    return {"ok": ok, "required_missing": required_missing,
            "doubao_ready": doubao_ready, "xhs_ready": xhs_ready,
            "strategy_ready": strategy_ready, "install_marker": marker,
            "notes": notes}, (0 if ok else 1)

# ── Claude Code 沙盒网络放行 ──
# Claude Code 的 Bash 沙盒（macOS/Linux/WSL2；原生 Windows 无沙盒）默认拦外网，
# 典型报错 "Host not allowed" / proxy blocked。把 nbdpsy 域名并进用户级
# settings.json 的 sandbox.network.allowedDomains + permissions.allow 即放行。
SANDBOX_ALLOW_DOMAINS = ["mcp.nbdpsy.com", "www.nbdpsy.com", "database.nbdpsy.com"]
SANDBOX_ALLOW_PERMISSIONS = ["WebFetch(domain:mcp.nbdpsy.com)", "WebFetch(domain:www.nbdpsy.com)"]

def claude_settings_path() -> Path:
    if os.environ.get("NBDPSY_CLAUDE_SETTINGS"):  # 测试用覆盖
        return Path(os.environ["NBDPSY_CLAUDE_SETTINGS"]).expanduser()
    return Path.home() / ".claude" / "settings.json"

def _ensure_dict(parent: dict, key: str):
    """取/建子 dict；已有同名非 dict 值时返回 None（类型冲突，不动用户配置）。"""
    v = parent.get(key)
    if v is None:
        v = {}
        parent[key] = v
    return v if isinstance(v, dict) else None

def _merge_into_list(parent: dict, key: str, values) -> bool:
    cur = parent.get(key)
    if cur is None:
        cur = []
        parent[key] = cur
    if not isinstance(cur, list):
        return False
    changed = False
    for v in values:
        if v not in cur:
            cur.append(v)
            changed = True
    return changed

def sandbox_allow():
    """把 nbdpsy 域名合并进 Claude Code 用户级 settings.json 的沙盒放行名单。
    只追加不覆盖、不碰 sandbox.enabled（是否启沙盒由用户自己决定）。
    返回 (changed: bool, path: Path, error: str|None)；解析失败时绝不写盘。"""
    path = claude_settings_path()
    settings = {}
    if path.is_file():
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            return False, path, f"settings.json 解析失败（{e}），为避免破坏现有配置未写入，请手动合并"
        if not isinstance(settings, dict):
            return False, path, "settings.json 顶层不是 JSON 对象，未写入，请手动合并"
    changed = False
    sandbox = _ensure_dict(settings, "sandbox")
    network = _ensure_dict(sandbox, "network") if sandbox is not None else None
    if network is not None:
        changed |= _merge_into_list(network, "allowedDomains", SANDBOX_ALLOW_DOMAINS)
    permissions = _ensure_dict(settings, "permissions")
    if permissions is not None:
        changed |= _merge_into_list(permissions, "allow", SANDBOX_ALLOW_PERMISSIONS)
    if sandbox is None and permissions is None:
        return False, path, "settings.json 里 sandbox/permissions 均为非对象类型，未写入，请手动合并"
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed, path, None

IMPORT_ALLOWLIST_PREFIXES = ("NBDPSY_", "VOLC_TTS_")

def _import_allowed(key: str) -> bool:
    return any(key.startswith(p) for p in IMPORT_ALLOWLIST_PREFIXES)

def import_bundle(path):
    """从凭据包文件导入白名单 key。返回 (written, skipped) 均为 key 名列表；绝不返回/打印值。"""
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    written, skipped = [], []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if not key:
            continue
        if _import_allowed(key):
            set_secret(key, value)
            written.append(key)
        else:
            skipped.append(key)
    return written, skipped

# ── 自更新（update 子命令）──
# 做什么：从官方仓库取最新版，覆盖 ~/.claude/skills 与 ~/.agents/skills 里的 7 个 skill。
#
# ⚠️ 这是一次「改写 agent 行为准则」的操作：skill 目录里的 SKILL.md 就是 agent 之后办事的指令，
# 覆盖 = 拉来的内容直接成为它的行为方式。**因此调用方（agent）必须先征得运营明确同意再跑**，
# 不是可以自作主张的日常维护命令（口径见 nbdpsy-guide「更新工具包」一节）。
#
# 为什么用它而不是让 agent 手搓 shell：运营多是非技术人员、不该被要求开终端敲命令；而 agent
# 通读安装器后**手写等效脚本**已经出过事故——zsh 不对无引号变量做分词，
# `SKILLS="a b c"; for s in $SKILLS` 把 7 个名字当成一个路径，一个 skill 都没复制、
# 循环里的 ✓ 照常打满屏（静默失败），还伴随 rm -rf 误删风险。本命令是纯 Python、跨系统一致，
# 且**每复制完一个 skill 都校验 SKILL.md 真的落地，失败立即报错退出**——绝不在失败路径打 ✓。
UPDATE_REPO_URL = "https://github.com/Buxiulei/nbdpsy-skills.git"
# 旧版（无 nbdpsy- 前缀）skill 名，更新时顺带清理，防新旧并存重复触发（与 install.sh 同一份名单）
LEGACY_SKILL_NAMES = ["seo-artical-creator", "xiaohongshu-creator", "text-to-video",
                      "content-reviewer", "content-pipeline"]
UPDATE_FALLBACK_HINT = (
    "退路（需要运营本人动手，请一步步指路）：① 让他在系统终端里跑 "
    "curl -fsSL https://raw.githubusercontent.com/Buxiulei/nbdpsy-skills/master/install.sh | bash"
    "；② 或在 Claude Code 输入框里由他亲自敲 `! bash install.sh`（`!` 前缀 = 他本人执行）。")


class UpdateError(Exception):
    """更新失败：异常消息本身就是给运营看的人话，main() 打印后 exit 1。"""


def update_dests():
    """两个安装目的地，与 install.sh 的 copy_to 一致。惰性取 HOME，便于测试隔离。"""
    return [Path.home() / ".claude" / "skills", Path.home() / ".agents" / "skills"]


def discover_skills(src: Path):
    """skill 清单**从源仓库派生，绝不硬编码**：源里凡 `nbdpsy-*/SKILL.md` 存在的目录即是。
    硬编码一份数组意味着 install.sh 往后加了 skill 而这里忘了同步 → update 悄悄少装一个
    （清单漂移）。派生法让「仓库里实际有什么」成为唯一真源；顺带天然排除
    nbdpsy-xiaohongshu-creator-workspace 这类没有 SKILL.md 的辅助目录。"""
    if not src.is_dir():
        return []
    return sorted(d.name for d in src.iterdir()
                  if d.is_dir() and d.name.startswith("nbdpsy-") and (d / "SKILL.md").is_file())


def _src_version(src: Path) -> str:
    """版本号从源仓库 .claude-plugin/plugin.json 正则提取（与 install.sh 的 grep 同口径）。
    取不到一律 unknown——版本标记是锦上添花，绝不因此中断更新。"""
    try:
        text = (src / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "unknown"
    m = re.search(r'"version"\s*:\s*"([^"]*)"', text)
    return m.group(1) if m and m.group(1) else "unknown"


def _src_commit(src: Path) -> str:
    try:
        r = subprocess.run(["git", "-C", str(src), "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else "unknown"


def _installed_version(dests) -> str:
    """更新前本机装的是哪版：按目的地顺序读第一份能读懂的标记，没有就 unknown。"""
    for d in dests:
        try:
            data = json.loads((Path(d) / INSTALL_MARKER_NAME).read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        if isinstance(data, dict) and data.get("version"):
            return str(data["version"])
    return "unknown"


def _remove(path: Path):
    """删目录/文件/软链，不存在则无操作。软链必须 unlink——rmtree 对软链无效（会留下死链）。"""
    if path.is_symlink() or path.is_file():
        try:
            path.unlink()
        except OSError:
            pass
    else:
        shutil.rmtree(path, ignore_errors=True)


def _requirements_note(src: Path, dests, skills):
    """依赖不自动装：只比对、只提示，绝不跑 pip（动本机 Python 环境须由人拍板）。
    已装 skill 内并没有 requirements 副本可比（依赖清单只住在仓库根），所以绝大多数情况是
    「无从比对」→ 照样给一行提示。保持简单，不引入任何状态文件。必须在复制**之前**调用，
    否则比的是刚写进去的新副本。"""
    try:
        new = (src / "requirements.txt").read_bytes()
    except OSError:
        return None
    for dest in dests:
        for name in skills:
            old = Path(dest) / name / "requirements.txt"
            try:
                if old.is_file() and old.read_bytes() == new:
                    return None          # 有副本且一致 → 依赖没变，不打扰
            except OSError:
                pass
    return "依赖清单可能有变，如遇 import 报错跑一次 setup.py（本命令不装依赖）"


def _clone_repo(url: str, workdir: str) -> Path:
    if not shutil.which("git"):
        raise UpdateError("本机没有 git，克隆不了官方仓库。" + UPDATE_FALLBACK_HINT)
    target = Path(workdir) / "repo"
    try:
        r = subprocess.run(["git", "clone", "--depth", "1", url, str(target)],
                           capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as e:
        raise UpdateError(f"克隆官方仓库失败（{e}）。" + UPDATE_FALLBACK_HINT)
    if r.returncode != 0:
        tail = (r.stderr or "").strip().splitlines()
        why = tail[-1] if tail else f"git 退出码 {r.returncode}"
        raise UpdateError(f"克隆官方仓库失败（{why}）——多半是网络/代理不通。" + UPDATE_FALLBACK_HINT)
    return target


def _install_skills(src: Path, dest: Path, skills, log):
    """把 skills 从 src 复制到 dest。**绝不在失败路径打 ✓**：每个 skill 复制完立即验证
    SKILL.md 落地，缺了就人话报错退出（同事那台机器静默零复制、✓ 照打的直接教训）。
    自更新安全：本文件自己的已安装副本也会在这里被覆盖——Python 启动时已把源码读进内存
    并关掉文件句柄，Linux/macOS/Windows 删除它都不影响正在跑的这次进程，新版下次运行生效。"""
    dest.mkdir(parents=True, exist_ok=True)
    for name in LEGACY_SKILL_NAMES:
        old = dest / name
        if old.exists() or old.is_symlink():
            _remove(old)
            log(f"  ✗ 清理旧名 {name}")
    for name in skills:
        target = dest / name
        _remove(target)
        try:
            shutil.copytree(src / name, target)
        except OSError as e:
            raise UpdateError(f"复制 {name} 到 {target} 失败（{e}）——更新未完成，已中止。"
                              "请检查磁盘空间与目录权限后重试。")
        # 显式判断而非 assert：assert 在 python -O 下会被整条剥掉，正好退化成我们要防的静默失败
        if not (target / "SKILL.md").is_file():
            raise UpdateError(f"{name} 复制后没找到 {target / 'SKILL.md'}——更新未完成，已中止。"
                              "请检查磁盘空间与目录权限，或改用 install.sh。")
        log(f"  ✓ {name}")


def _write_marker(dest: Path, version: str, commit: str, source_kind: str, log) -> bool:
    """版本标记：四字段与 install.sh 的 write_marker 逐字段同格式，doctor 直接读得懂。
    写失败只提示不中断——skill 已经装好了，标记是锦上添花。"""
    payload = {"version": version, "commit": commit,
               "installed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
               "source": source_kind}
    try:
        (dest / INSTALL_MARKER_NAME).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as e:
        log(f"  ! 版本标记写入失败（{e}），不影响 skill 安装")
        return False
    log(f"  ✓ 版本标记 v{version}（{commit}）")
    return True


def update(source=None, dests=None, log=None):
    """更新本机已安装的 nbdpsy skills。source 为 None 时 git clone 官方仓库；给了就用本地仓库。
    返回报告 dict；任何会导致「装了一半还报成功」的情况一律抛 UpdateError（消息即人话）。"""
    log = log or (lambda msg: print(msg, file=sys.stderr))
    dests = [Path(d) for d in dests] if dests else update_dests()
    tmp = None
    try:
        if source:
            src = Path(source).expanduser()
            if not src.is_dir():
                raise UpdateError(f"--source 指定的路径不存在或不是目录：{src}")
            source_kind = "local-repo"
        else:
            tmp = tempfile.mkdtemp(prefix="nbdpsy-update-")
            log(f"→ 临时克隆 {UPDATE_REPO_URL} ...")
            src = _clone_repo(UPDATE_REPO_URL, tmp)
            source_kind = "github-clone"
        skills = discover_skills(src)
        if not skills:
            raise UpdateError(f"源目录里没有任何 nbdpsy-*/SKILL.md：{src}"
                              "——它看起来不是 nbdpsy-skills 仓库，已中止（没动本机任何文件）。")
        version, commit = _src_version(src), _src_commit(src)
        old_version = _installed_version(dests)
        req_note = _requirements_note(src, dests, skills)   # 必须赶在复制前比
        for dest in dests:
            log(f"→ 更新 {dest}")
            _install_skills(src, dest, skills, log)
            _write_marker(dest, version, commit, source_kind, log)
        log(f"✓ 工具包 v{old_version} → v{version}（{commit}）")
        if req_note:
            log("  · " + req_note)
        return {"ok": True, "from": old_version, "to": version, "commit": commit,
                "dests": [str(d) for d in dests], "skills": skills, "source": source_kind}
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def _usage():
    print("用法: nbdpsy_common.py workspace | doctor | update [--source 本地仓库路径] | "
          "sandbox allow | secret {get K | set K V | ensure K... | import FILE}",
          file=sys.stderr)
    return 2

def main(argv):
    if not argv:
        return _usage()
    if argv[0] == "workspace":
        print(resolve_workspace())
        return 0
    if argv[0] == "doctor":
        report, code = doctor()
        if report["ok"]:
            tail = "；豆包语音已配置" if report["doubao_ready"] else "；豆包语音未配置（可选，视频用免费 edge 旁白）"
            tail += "；小红书自动发布已配置" if report["xhs_ready"] else "；小红书自动发布未配置（可选）"
            print("✓ 发文凭据已就绪" + tail, file=sys.stderr)
        else:
            print("✗ 缺少必需凭据，暂时无法发文。", file=sys.stderr)
        for n in report["notes"]:
            print("  · " + n, file=sys.stderr)
        print(json.dumps(report, ensure_ascii=False))
        return code
    if argv[0] == "update":
        rest = argv[1:]
        if rest and not (len(rest) == 2 and rest[0] == "--source"):
            return _usage()
        try:
            report = update(rest[1] if rest else None)
        except UpdateError as e:
            print(f"✗ 更新失败：{e}", file=sys.stderr)
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
            return 1
        print(json.dumps(report, ensure_ascii=False))
        return 0
    if argv[0] == "sandbox" and len(argv) == 2 and argv[1] == "allow":
        changed, path, err = sandbox_allow()
        if err:
            print(f"✗ {err}（{path}）", file=sys.stderr)
            print(json.dumps({"ok": False, "changed": False, "path": str(path), "error": err},
                             ensure_ascii=False))
            return 1
        msg = "已写入沙盒放行名单，重启 Claude Code 生效" if changed else "沙盒放行名单已就位，无需改动"
        print(f"✓ {msg}：{path}", file=sys.stderr)
        print(json.dumps({"ok": True, "changed": changed, "path": str(path),
                          "domains": SANDBOX_ALLOW_DOMAINS}, ensure_ascii=False))
        return 0
    if argv[0] == "secret" and len(argv) >= 2:
        sub = argv[1]
        if sub == "get" and len(argv) == 3:
            v = get_secret(argv[2])
            if v is None:
                print(f"MISSING:{argv[2]}", file=sys.stderr)
                print("提示：缺少凭据。请向管理员索要「凭据配置包」，然后运行 "
                      "python3 nbdpsy_common.py secret import <凭据包文件> 一键导入；"
                      "python3 nbdpsy_common.py doctor 可查看全部缺项。", file=sys.stderr)
                return 1
            print(v)
            return 0
        if sub == "set" and len(argv) == 4:
            p = set_secret(argv[2], argv[3])
            print(f"✓ 已记录 {argv[2]} → {p}（不会入库）", file=sys.stderr)
            return 0
        if sub == "ensure":
            for k in ensure_secrets(argv[2:]):
                print(k)
            return 0
        if sub == "import" and len(argv) == 3:
            written, skipped = import_bundle(Path(argv[2]))
            if written:
                print(f"✓ 已写入 {len(written)} 项凭据：{', '.join(written)}（值不回显，已存本机）",
                      file=sys.stderr)
            else:
                print("未发现可导入的凭据（请确认粘贴了完整配置包）", file=sys.stderr)
            if skipped:
                print(f"已跳过非白名单键：{', '.join(skipped)}", file=sys.stderr)
            return 0
    return _usage()

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
