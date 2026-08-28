"""**文档里不许出现凭据真值**——本仓是公开仓，写进去就等于发布。

🩸 起因（2026-08-27～29，T106→T107）：`nbdpsy-seo-artical-creator/SKILL.md` 三处示例命令
带着数据库口令明文。8-29 01:04 基建完成本地库口令轮换，旧值已失效。

## 🔴 两个名单语义相反，⛔ 别混

| | 用途 | 存不存进本文件 |
|---|---|---|
| **历史泄漏值**（已轮换掉的旧口令） | 出现即红。**失效 ≠ 不用管**：它在本仓 git 历史里**永久可 clone**，且将来有人可能拿它推测口令生成规律 | ✅ 存 hash |
| **当前有效口令**（`.env` 里那个） | 出现即红——但它是**「有没有再次泄漏」的靶子**，⛔ **绝不能进「已泄漏」名单** | ❌ 只在运行时从 `.env` 动态读 |

🩸 **本文件第一版就把这件事写反了**：它 assert「`.env` 的口令必须在 `KNOWN_LEAKED` 里，
不在就红并提示**把新值加进去**」。照那个提示做，轮换后的新口令会被登记成「已泄漏」——
名单从此答不了「有没有再次泄漏」。基建 2026-08-29 指出后重构。
🔑 **两个东西的检查动作相同（都不许出现在仓里），语义却相反**——动作相同最容易让人把它们合并。

## 🔴 这个判据守什么、明确不守什么

- ✅ 守：**这些值有没有出现在仓库文件里**（三形态：明文 / `%40` URL 编码 / base64）。
- ⛔ **不守「那个凭据还有没有效」**。基建的硬判据值得抄在这里：
  > **「旧值必须已失效」是唯一能证明「轮换真的发生了」的判据。**
  > 服务探针 / 能连库 / 日志无认证失败这三条，在**什么都没做**的情况下也全会绿——
  > 它们答的是「服务还好吗」，⛔ 答不了「口令换了吗」。
  ⇒ 要判「某个泄漏凭据是否已处置」，得**拿它去连一次、必须失败**，⛔ 不是「文档里搜不到了」。
- ⛔ **不守 git 历史**。删文档不解决历史——那正是当初定「轮换是唯一根治」的依据（T107=A 裁「后议」）。
- ⛔ **不守远端**。本判据只读**本地工作区**；`origin/master` 上是什么它不知道。

🔴 **三层覆盖，绿灯只代表第一层**（基建 2026-08-29 提的，已写进断言消息）：

| 层 | 本判据 | 谁来管 |
|---|---|---|
| 本地工作区 | ✅ 覆盖 | 这条判据 |
| 远端 `origin/master` | ⛔ 不覆盖 | 发版前人工核（`git show origin/master:<path>`） |
| **git 历史** | ⛔ **不覆盖** | 只能靠**轮换让值失效**（T107=A 裁「后议」）；本仓历史里那批 blob 永久可 clone |

⚠️ 写死这张表是因为：**只看这条绿灯的人会以为「那个值已经不存在了」**。它实际只说明「本地工作区当前没有」。

## 🔴 为什么用 hash 比对而不是「口令样式正则」

同一批文件里有 7 处占位符 `PGPASSWORD='<生产库密码>'`——**那是正确写法，会永远在文档里**。
拿「`PGPASSWORD='...'` 里有值就红」当判据会把占位符一起扫进来 ⇒ **恒红 ⇒ 等于没有闸门**。
🩸 我最初还栽过一次：把七处的值做成指纹表，其中一个我当成「第二个来历不明的口令」上报，
实际它是**占位符那几个字符本身**的 hash。
🔑 **哈希能答「这两个一样吗」，⛔ 答不了「这是什么」**——分类问题必须回原始行看内容。

## 🔴 为什么用 `pathlib.rglob` 扫，⛔ 不用 grep

**本机 `grep` 是 shell function，底层 ugrep，递归时遵守 `.gitignore`**（实测：同一目录加个
内容为 `*` 的 `.gitignore`，`grep -rl` 命中 1→**0**，直指文件仍 1，**rc=1、无报错**）。
当时正是它让「全仓已排查干净」漏掉 `.superpowers/sdd/` 下 3 处现行口令明文。
⚠️ 被 gitignore 忽略的文件**恰恰是凭据最爱待的地方** ⇒ 这盲区专挡你最想找的东西。
（`/usr/bin/grep` 是 GNU grep 3.11，递归正常，也可用。）

## ⚠️ 三形态：明文只是其中一种

🩸 2026-08-29 基建实证：他做 `%40` URL 编码那一轮时**抓出 15 个文件，其中 5 个是他先前
宣布「残留 0」的**。口令进了 `DATABASE_URL` 就是 percent-encoded 形态，明文搜法完全看不见。
⚠️ 我自己也漏过：收口人 8-28 就顺带告诉过我「`DATABASE_URL` 里是 percent-encoding、hash 不同」，
我读到了却没据此扩展扫描范围——**注意力全在他纠正我的那两处错上，漏掉了顺带给的新信息**。
"""
import base64
import hashlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SELF = Path(__file__).resolve()
ENV = Path("/home/roots/NBDpsy/.env")

# ── 历史泄漏值：只存 hash，本文件永不含明文 ────────────────────────────
# 值已失效（2026-08-29 01:04 轮换），但**仍要留着**：本仓 git 历史里永久可 clone。
# 新发现一个就加一行，附来历。⛔ 绝不把「当前有效口令」加进这里（见文件头）。
KNOWN_LEAKED = {
    "02dca5b729b5976104b50872c433089ce553d93b775cf5b89cf8ce50ab188c5a":
        "psychology_counseling 库口令（明文形态）：2026-08-26 从生产作废、08-29 从本地轮换掉，"
        "已实测失效。曾在 seo-artical-creator/SKILL.md 3 处与 .superpowers/sdd/ 简报里。",
    "b12af61d2755281634d27fe55b0ec90b48e3332f55d0522642bbf13b0518a790":
        "同上值的 %40 URL 编码形态（DATABASE_URL 里就是它）——⚠️ 明文搜法看不见这一种。",
    "5724667c8a84e8783c6267f213f39faff9fbf948b947a2c62210c895f7c4cd11":
        "同上值的 base64 形态。",
    # 🩸 上面三条最初我只从别人口头转述里拿到前 8 位就把后 56 位**编**了出来——
    #    编造的 hash 永远不匹配，是一颗长得很真的哑弹。⇒ 名单里每个 hash 都必须是
    #    自己用 `sha256(值)` 算过的；写不出「我从哪算的」就不许往这里加。
}

TEXT_EXT = {".md", ".py", ".sh", ".json", ".txt", ".yml", ".yaml",
            ".toml", ".cfg", ".ini", ".diff", ".patch", ".html", ".js"}

# 结构化位置的候选值——用于**拿不到明文时**（已轮换的旧值）按 hash 比对。
# ⚠️ 它比子串搜弱：只覆盖这几种写法。所以当前口令仍走子串搜（最强），两条腿一起走。
CANDIDATE_PATTERNS = [
    re.compile(r"PGPASSWORD=['\"]?([^'\"\s]+)"),
    re.compile(r"DB_PASSWORD=['\"]?([^'\"\s]+)"),
    re.compile(r"postgres(?:ql)?://[^:/\s]+:([^@\s]+)@"),
]


def iter_text_files():
    for f in ROOT.rglob("*"):
        if not f.is_file() or f.suffix not in TEXT_EXT:
            continue
        if ".git/" in str(f) or f.resolve() == SELF:
            continue
        yield f


def three_forms(secret):
    """一个口令在文档里可能长的三种样子。⚠️ 明文只是其中一种。"""
    return {
        "明文": secret,
        "%40 URL 编码": secret.replace("@", "%40"),
        "base64": base64.b64encode(secret.encode()).decode(),
    }


def current_db_password():
    """当前 `.env` 口令。取不到返回 None——**⛔ 不返回空串**：
    空串 `in` 任何文本都为真会让扫描全部命中；而空串的 sha256 长得跟正常 hash 一样，
    写进名单就是一颗哑弹。🩸 今天真算出过一次 `e3b0c442…`（空串 hash）。"""
    if not ENV.exists():
        return None
    for line in ENV.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("DB_PASSWORD="):
            v = line.split("=", 1)[1].strip().strip('"').strip("'")
            return v if len(v) > 5 else None
    return None


# ── 一、当前有效口令：绝不许出现在仓里（三形态子串搜）────────────────
def test_仓里不含当前有效口令():
    cur = current_db_password()
    if cur is None:
        pytest.skip("读不到 .env 的 DB_PASSWORD ⇒ **本条没有跑**，⛔ 不要当成通过")
    assert hashlib.sha256(cur.encode()).hexdigest() not in KNOWN_LEAKED, (
        "🔴 当前 .env 的口令出现在 KNOWN_LEAKED 里——要么它还没轮换，"
        "要么有人把当前口令误加进了「已泄漏」名单。后者会让这份名单再也答不了"
        "「有没有再次泄漏」，见文件头。")
    bad = [f"{f.relative_to(ROOT)}:{i} [{name}]"
           for f in iter_text_files()
           for i, ln in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1)
           for name, needle in three_forms(cur).items() if needle in ln]
    assert not bad, ("🔴 **当前有效**口令出现在仓库文件里（本仓公开）：\n  " + "\n  ".join(bad))
    # 绿灯语义（放在成功路径上，⛔ 不只写在文档里——只看测试输出的人看不到 docstring）：
    # 工作区 ✅ ／ 远端 HEAD ⛔ 本判据不查 ／ git 历史 ⛔ 不查（T107=A 后议，靠轮换根治）


# ── 二、历史泄漏值：拿不到明文，按结构化候选的 hash 比对 ──────────────
def test_仓里不含历史泄漏过的凭据():
    """⚠️ 这条比上一条弱——旧值已轮换、本文件不持有明文，只能从结构化位置提候选算 hash。
    覆盖不到「散落在自由文本里的旧值」。这是**为了不在判据里再存一份明文**付出的代价，
    写在这里让下一个人知道边界在哪。"""
    bad = []
    for f in iter_text_files():
        text = f.read_text(encoding="utf-8", errors="ignore")
        for i, ln in enumerate(text.splitlines(), 1):
            for pat in CANDIDATE_PATTERNS:
                for m in pat.finditer(ln):
                    h = hashlib.sha256(m.group(1).encode()).hexdigest()
                    if h in KNOWN_LEAKED:
                        bad.append(f"{f.relative_to(ROOT)}:{i} → {KNOWN_LEAKED[h][:40]}…")
    assert not bad, ("🔴 历史泄漏过的凭据又出现在仓里（可能是从 git 历史或旧文档抄回来的）：\n  "
                     + "\n  ".join(bad))


# ── 三、量具自检 ───────────────────────────────────────────────────────
def test_量具自检_三形态都能被抓到(tmp_path):
    """🩸 基建实证：`%40` 那一轮抓出 15 个文件，其中 5 个是先前宣布「残留 0」的。
    ⇒ 只验明文那一形态，等于没验。"""
    fake = "Secret@1234"
    for name, needle in three_forms(fake).items():
        assert needle, name
    assert three_forms(fake)["%40 URL 编码"] == "Secret%401234"
    assert three_forms(fake)["base64"] == base64.b64encode(b"Secret@1234").decode()
    assert three_forms(fake)["明文"] != three_forms(fake)["%40 URL 编码"], "两形态不该相同"


def test_量具自检_遍历覆盖被gitignore的文件(tmp_path):
    """造一个带 `.gitignore: *` 的目录，确认 rglob 仍看得到——
    当初 grep 正是在这里静默漏掉 3 处现行口令明文。"""
    d = tmp_path / "hidden"
    d.mkdir()
    (d / ".gitignore").write_text("*\n", encoding="utf-8")
    (d / "note.md").write_text("NEEDLE\n", encoding="utf-8")
    seen = [p.name for p in tmp_path.rglob("*") if p.is_file() and p.suffix in TEXT_EXT]
    assert "note.md" in seen, "遍历漏掉了被 .gitignore 忽略的文件——判据有静默盲区"


def test_量具自检_名单里没有空串hash也没有明文():
    assert hashlib.sha256(b"").hexdigest() not in KNOWN_LEAKED, "空串 hash 是哑弹"
    for h in KNOWN_LEAKED:
        assert len(h) == 64 and all(c in "0123456789abcdef" for c in h), f"不是合法 sha256：{h}"
    cur = current_db_password()
    if cur is not None:
        assert cur not in SELF.read_text(encoding="utf-8"), "判据文件里写了口令明文"


def test_守备范围_本判据不证明凭据已失效():
    """🔴 写成断言是怕下一个人把绿读成「那个泄漏已经处置完了」。
    文档里搜不到 ⛔ 不等于那个值失效了——要证明失效，**拿它去连一次、必须失败**。"""
    doc = __doc__ or ""
    assert "不守「那个凭据还有没有效」" in doc
    assert "拿它去连一次、必须失败" in doc
    # 三层覆盖表必须在，且必须写明后两层不覆盖
    assert "三层覆盖，绿灯只代表第一层" in doc
    assert doc.count("⛔ **不覆盖**") + doc.count("⛔ 不覆盖") >= 2, "远端与 git 历史两层都要标明不覆盖"
