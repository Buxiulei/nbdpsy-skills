"""**文档里不许出现凭据真值**——本仓是公开仓，写进去就等于发布。

🩸 起因（2026-08-27～28，T106→T107）：`nbdpsy-seo-artical-creator/SKILL.md` 三处示例命令
带着数据库口令明文。查下来那是**本地开发库的现行口令**（8/26 已从生产作废）。

## 🔴 判据为什么用 hash 比对，⛔ 不用「口令样式正则」

同一批文件里还有 4 处写的是占位符 `PGPASSWORD='<生产库密码>'`——**那是正确写法，会永远留在文档里**。
拿「`PGPASSWORD='...'` 里有值就红」当判据，会把占位符一起扫进来 ⇒ **恒红** ⇒ 三天之内没人看
⇒ 等于没有闸门。⇒ 只认**已知真值的 hash**：占位符 hash 不在表里，天然放行。

🩸 我最初就是栽在这上面：把七处的值做成指纹表，其中 `c82a201f` 我当成「第二个来历不明的口令」
上报，实际它是**占位符 `<生产库密码>` 这几个字符本身**的 hash。
🔑 **哈希能答「这两个一样吗」，⛔ 答不了「这是什么」**——分类问题必须回原始行看内容性质。

## 🔴 为什么用 `pathlib.rglob` 扫，⛔ 不用 grep

**本机 `grep` 是一个 shell function，底层是 ugrep，递归时会遵守 `.gitignore`。**
实测（2026-08-28）：同一目录加一个内容为 `*` 的 `.gitignore`，`grep -rl` 命中从 1 变 **0**，
而直指文件仍命中 1，**且 rc=1、无任何报错**——一个完全静默的盲区。

⇒ 当时正是它让「全仓已排查干净」漏掉了 `.superpowers/sdd/` 下 3 处**现行口令明文**
（那目录有个 `.gitignore` 内容就是 `*`）。而**被 gitignore 忽略的文件恰恰是凭据最爱待的地方**
（本地笔记、临时产物、工作简报）。⇒ 凡是「查无 ⇒ 干净」这类**全称否定**的结论，
⛔ 不能用会静默跳过文件的量具得出（[[查无是全称否定，其强度＝搜索范围完整度]]）。
"""
import hashlib
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SELF = Path(__file__).resolve()

# 已知**曾经泄露过**的凭据真值 sha256（⛔ 只存 hash，本文件永不含明文）。
# 新发现一个就往这里加一行，附来历——它防的是「旧值被从别处抄回来」。
KNOWN_LEAKED = {
    "02dca5b729b5976104b50872c433089ce553d93b775cf5b89cf8ce50ab188c5a":
        "psychology_counseling 库口令：2026-08-26 从生产作废；8/28 时仍是本地开发库现行值"
        "（基建已排期轮换）。曾出现在 seo-artical-creator/SKILL.md 与 .superpowers/sdd/ 简报里。",
}

TEXT_EXT = {".md", ".py", ".sh", ".json", ".txt", ".yml", ".yaml",
            ".toml", ".cfg", ".ini", ".diff", ".patch", ".html", ".js"}


def iter_text_files():
    """⚠️ 用 rglob 而**不是** grep——见模块 docstring：本机 grep 递归会静默跳过 gitignore 的文件。"""
    for f in ROOT.rglob("*"):
        if not f.is_file() or f.suffix not in TEXT_EXT:
            continue
        if ".git/" in str(f) or f.resolve() == SELF:
            continue
        yield f


def current_db_password():
    """本地 `.env` 的现行口令。取不到就返回 None——**⛔ 不返回空串**：
    空串 `in` 任何文本都为真，会让扫描全部命中（恒红）；而空串的 sha256 长得跟正常 hash
    一模一样，写进上面那张表就是一颗哑弹。🩸 今天真算出过一次 `e3b0c442…`（空串 hash）。"""
    env = Path("/home/roots/NBDpsy/.env")
    if not env.exists():
        return None
    for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("DB_PASSWORD="):
            v = line.split("=", 1)[1].strip().strip('"').strip("'")
            return v if len(v) > 5 else None
    return None


def test_全仓不含已知泄露过的凭据():
    """按 hash 比对：把每个文件里出现的候选串与 KNOWN_LEAKED 对照。
    实现上反过来做——拿已知明文（从 .env 取当前值）直接子串搜，命中即红。"""
    cur = current_db_password()
    if cur is None:
        pytest.skip("读不到本地 .env 的 DB_PASSWORD ⇒ **本条没有跑**，⛔ 不要当成通过")
    assert hashlib.sha256(cur.encode()).hexdigest() in KNOWN_LEAKED, (
        "本地 .env 的口令不在已知表里——它可能刚轮换过。请把新值的 sha256 加进 KNOWN_LEAKED "
        "（⛔ 只加 hash 不加明文），否则本判据在保护一个已经不存在的值。")
    bad = [f"{f.relative_to(ROOT)}:{i}"
           for f in iter_text_files()
           for i, ln in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1)
           if cur in ln]
    assert not bad, (
        "这些行含数据库口令**明文**。本仓是公开仓，写进去等于发布。\n"
        "改成占位符 `<生产库密码>` 或从 .env 读：\n  " + "\n  ".join(bad))


def test_占位符写法必须放行():
    """🔴 反向钉：占位符会**永远**留在文档里。判据若把它判红就是恒红，
    而恒红的闸门等于没有闸门——还占着「我们查过了」的位置。"""
    cur = current_db_password()
    if cur is None:
        pytest.skip("读不到 .env")
    assert cur not in "PGPASSWORD='<生产库密码>' psql -h localhost -U root", "占位符被误判为泄露"


def test_量具自检_扫描确实覆盖被gitignore的文件(tmp_path):
    """🩸 这条是本文件的核心自检：**证明我们的遍历不会漏掉 gitignore 掉的文件**。
    造一个带 `.gitignore: *` 的目录，确认 rglob 仍能看到里面的文件——
    当初 grep 正是在这里静默漏掉 3 处现行口令明文。"""
    d = tmp_path / "hidden"
    d.mkdir()
    (d / ".gitignore").write_text("*\n", encoding="utf-8")
    (d / "note.md").write_text("NEEDLE_FOR_SELFTEST\n", encoding="utf-8")
    seen = [p.name for p in tmp_path.rglob("*") if p.is_file() and p.suffix in TEXT_EXT]
    assert "note.md" in seen, "遍历漏掉了被 .gitignore 忽略的文件——判据有静默盲区"


def test_量具自检_已知表里没有空串hash():
    """空串的 sha256 是个合法长相的 hash，写进表里会变成一颗永不响的哑弹
    （而 `"" in text` 恒真，若走子串路径则相反——恒红）。两个方向都糟。"""
    assert hashlib.sha256(b"").hexdigest() not in KNOWN_LEAKED
    for h in KNOWN_LEAKED:
        assert len(h) == 64 and all(c in "0123456789abcdef" for c in h), f"不是合法 sha256：{h}"


def test_本文件不含任何明文凭据():
    """判据自己不能是泄露源。

    🩸 这条第一版还加了「本文件不许出现 `PGPASSWORD=` 字面量」——**当场把自己判红了**，
    因为那条断言的代码本身就含这个字符串。⇒ 又一次演示了文件头那个理由：
    **样式判据会连正当出现一起打**。这里只认**真值**，⛔ 不认样式。"""
    cur = current_db_password()
    if cur is None:
        pytest.skip("读不到 .env")
    assert cur not in SELF.read_text(encoding="utf-8"), "判据文件里写了口令明文"
