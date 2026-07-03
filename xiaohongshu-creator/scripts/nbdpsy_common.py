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
DOUBAO_KEYS = ["VOLC_TTS_APPID", "VOLC_TTS_ACCESS_TOKEN"]

def doctor():
    """自检可复制类凭据。返回 (report, exit_code)。绝不把密钥值放进 report。"""
    required_missing = [k for k in REQUIRED_KEYS if not get_secret(k)]
    doubao_ready = all(get_secret(k) for k in DOUBAO_KEYS)
    ok = not required_missing
    notes = []
    if required_missing:
        notes.append("缺发文凭据 NBDPSY_BLOG_API_KEY：找管理员要「凭据配置包」发给我一键导入"
                     "（管理员生成入口：manage.nbdpsy.com → 博客 → API Keys → 生成凭据配置包）。")
    if not doubao_ready:
        notes.append("豆包语音未配置（可选）：不配则视频旁白用免费 edge 引擎；同一个凭据配置包会带上豆包。")
    notes.append("视频画面用的即梦需在本机终端扫码一次：dreamina login --headless（抖音 App 扫码）；"
                 "登录态由 text-to-video/scripts/check_env.py 检测。")
    return {"ok": ok, "required_missing": required_missing,
            "doubao_ready": doubao_ready, "notes": notes}, (0 if ok else 1)

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
    print("用法: nbdpsy_common.py workspace | doctor | secret {get K | set K V | ensure K... | import FILE}",
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
            print("✓ 发文凭据已就绪" + tail, file=sys.stderr)
        else:
            print("✗ 缺少必需凭据，暂时无法发文。", file=sys.stderr)
        for n in report["notes"]:
            print("  · " + n, file=sys.stderr)
        print(json.dumps(report, ensure_ascii=False))
        return code
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
