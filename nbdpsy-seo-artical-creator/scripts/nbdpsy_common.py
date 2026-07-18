#!/usr/bin/env python3
"""NBDpsy skills 共享工具：内容工作区解析 + 凭据三层解析。
此文件真源在仓库 shared/，由 tools/sync_shared.py 同步到各 skill 的 scripts/，勿单独改副本。
凭据存储：用户级 secrets 文件在任何仓库之外，永不入库。"""
import os, sys, json
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

REQUIRED_KEYS = ["NBDPSY_BLOG_API_KEY"]
DOUBAO_API_KEY = "VOLC_TTS_API_KEY"  # 新版控制台单一凭据，优先
DOUBAO_KEYS = ["VOLC_TTS_APPID", "VOLC_TTS_ACCESS_TOKEN"]  # 旧版双凭据，向后兼容
XHS_API_KEY = "NBDPSY_XHS_API_KEY"  # 小红书运营 API（nbdpsy-api）运营专属 apikey，可选
XHS_API_BASE_KEY = "NBDPSY_XHS_API_BASE"
DEFAULT_XHS_API_BASE = "https://mcp.nbdpsy.com"
# YouTube 视频搬运 REST（video-transport）：与小红书发布同一套运营接入 JWT 鉴权，
# 复用凭据 NBDPSY_XHS_API_KEY；仅基址不同，故单列一个 base 键（可选，默认见下）。
VIDEO_API_BASE_KEY = "NBDPSY_VIDEO_API_BASE"
DEFAULT_VIDEO_API_BASE = "https://xhs.nbdpsy.com"

def xhs_api_base() -> str:
    return get_secret(XHS_API_BASE_KEY) or DEFAULT_XHS_API_BASE

def video_api_base() -> str:
    return get_secret(VIDEO_API_BASE_KEY) or DEFAULT_VIDEO_API_BASE

def doctor():
    """自检可复制类凭据。返回 (report, exit_code)。绝不把密钥值放进 report。"""
    required_missing = [k for k in REQUIRED_KEYS if not get_secret(k)]
    doubao_ready = bool(get_secret(DOUBAO_API_KEY)) or all(get_secret(k) for k in DOUBAO_KEYS)
    xhs_ready = bool(get_secret(XHS_API_KEY))
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
    notes.append("视频画面用的即梦需在本机终端扫码一次：dreamina login --headless（抖音 App 扫码）；"
                 "登录态由 nbdpsy-text-to-video/scripts/check_env.py 检测。")
    return {"ok": ok, "required_missing": required_missing,
            "doubao_ready": doubao_ready, "xhs_ready": xhs_ready, "notes": notes}, (0 if ok else 1)

# ── Claude Code 沙盒网络放行 ──
# Claude Code 的 Bash 沙盒（macOS/Linux/WSL2；原生 Windows 无沙盒）默认拦外网，
# 典型报错 "Host not allowed" / proxy blocked。把 nbdpsy 域名并进用户级
# settings.json 的 sandbox.network.allowedDomains + permissions.allow 即放行。
SANDBOX_ALLOW_DOMAINS = ["mcp.nbdpsy.com", "xhs.nbdpsy.com", "www.nbdpsy.com", "database.nbdpsy.com"]
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

def _usage():
    print("用法: nbdpsy_common.py workspace | doctor | sandbox allow | "
          "secret {get K | set K V | ensure K... | import FILE}",
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
