#!/usr/bin/env python3
"""NBDpsy skills 共享工具：内容工作区解析 + 凭据三层解析。
此文件真源在仓库 shared/，由 tools/sync_shared.py 同步到各 skill 的 scripts/，勿单独改副本。
凭据存储：用户级 secrets 文件在任何仓库之外，永不入库。"""
import os, sys
from pathlib import Path

def user_secrets_path() -> Path:
    if os.environ.get("NBDPSY_SECRETS"):
        return Path(os.environ["NBDPSY_SECRETS"]).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
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

def _usage():
    print("用法: nbdpsy_common.py workspace | secret {get K | set K V | ensure K...}", file=sys.stderr)
    return 2

def main(argv):
    if not argv:
        return _usage()
    if argv[0] == "workspace":
        print(resolve_workspace())
        return 0
    if argv[0] == "secret" and len(argv) >= 2:
        sub = argv[1]
        if sub == "get" and len(argv) == 3:
            v = get_secret(argv[2])
            if v is None:
                print(f"MISSING:{argv[2]}", file=sys.stderr)
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
    return _usage()

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
