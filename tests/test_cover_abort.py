"""封面设不上 ⇒ 整单弃发（server 0.24.16）：**「⛔ 不惯性重发」做进语义，⛔ 不只写进 hint**。

🔴 **这与旧语义相反**：
  旧（≤0.24.15）：发布链那条设封面入口 31/31 全败 ⇒ **发出去了但没封面**，
                  规格里甚至把 `exit 3 + cover=error` 写成「当前预期值，不是意外」
                  ——**那是「把红灯写进规格当成绿灯」的原型案例**。
  新（0.24.16+）：带封面发是**原子**的 ⇒ **要么 done，要么整单弃发（笔记根本没发出去）**。

⚠️ 服务端**已经自动退避重试 3 次（2/10/30min）才落到这个终态** ⇒ **退避已经用光了**。
客户端再重发就是**第 4 次盲试**。所以回执要给**结构化字段**让调用方读字段就能判，
⛔ 不必去解析一句人话。
"""
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import publish_video as pv  # noqa: E402

SRC = (SCRIPTS / "publish_video.py").read_text(encoding="utf-8")

# server 2026-08-22 给的**真实串骨架**（逐条实查，带行号）
REAL = ("cover_failed_publish_aborted: 封面没设上，整单弃发——这篇笔记没有发出去。"
        "封面步回执:cover_preview_unchanged: 预览区没变 | 当场取证:{...} | "
        "封面区 HTML(截断 800 字):<div>...</div>")


# ────────── 识别：按契约取值，⛔ 不按名字猜 ──────────

def test_认出弃发终态并取到内层码():
    r = pv.cover_abort_info({"status": "failed", "error": REAL})
    assert r is not None and r["inner"] == "cover_preview_unchanged"


@pytest.mark.parametrize("inner", list(pv.COVER_INNER_CODES))
def test_五个内层码都认得(inner):
    err = f"cover_failed_publish_aborted: 整单弃发。封面步回执:{inner}: 现场文案"
    assert pv.cover_abort_info({"error": err})["inner"] == inner


def test_内层码必须带cover前缀():
    """🩸 我第一版按契约摘要里的简称写成 `preview_unchanged`，**少了前缀就永远匹配不上**
    ——那会让识别看起来在工作（外层认出来了）而内层归因**恒为 None**。
    ⚠️ 「码名的简称」与「码名」是两回事，⛔ 别拿摘要里的说法当取值。"""
    assert all(c.startswith("cover_") for c in pv.COVER_INNER_CODES)


def test_内层码用引导词定位而不是全文搜():
    """⛔ 别全文搜码名：前段人话里不会出现码名，以引导词定位最稳（server 建议）。
    这条钉住实现方式——全文搜在遇到"现场文案里恰好提到另一个码"时会取错。"""
    err = ("cover_failed_publish_aborted: 整单弃发。"
           "封面步回执:cover_still_uploading: 上一次 cover_exception 的残留提示")
    assert pv.cover_abort_info({"error": err})["inner"] == "cover_still_uploading"


def test_取证段不存在也照样认得():
    """⚠️ 「当场取证 / 封面区 HTML」两段是**首验取证用的临时字段**，
    发布页结构一钉死就会撤 ⇒ ⛔ **别依赖它们存在**。"""
    err = "cover_failed_publish_aborted: 整单弃发。封面步回执:cover_exception: boom"
    assert pv.cover_abort_info({"error": err})["inner"] == "cover_exception"


@pytest.mark.parametrize("view", [
    {}, None, {"status": "published"},
    {"error": "别的失败原因"},
    {"error": None},
    {"reason": "cover_failed_publish_aborted: 放错字段了"},   # ⛔ 只认顶层 error
])
def test_不是这个终态就返回None(view):
    """⛔ 宽进会误判：把别的失败读成"整单弃发"，人就不会去查真正的原因。"""
    assert pv.cover_abort_info(view) is None


# ────────── 语义：结构化字段，⛔ 不只是 hint ──────────

def test_不可重试信号是结构化字段():
    """🔴 收口人 2026-08-22 定：**「⛔ 不惯性重发」要做进语义不是写进提醒**
    ——server 已退避 3 次，客户端再重发＝第 4 次盲试。
    ⇒ 调用方**读字段就能判**，⛔ 不必解析人话。"""
    assert '"published": False, "retry_exhausted": True' in SRC


def test_弃发退exit1而不是3():
    """🔴 exit 3 的语义是「**已发**但有欠账」。整单弃发是**没发出去** ⇒ 必须落 exit 1。
    ⚠️ 判成 3 会让人以为"发出去了、去补一下就好"——而根本没有那条笔记可补。"""
    i = SRC.index("abort = cover_abort_info(view)")
    seg = SRC[i:i + 1400]
    assert "code = 1" in seg and "code = 3" not in seg


def test_弃发时明说不会有重复笔记():
    """⚠️ 这是与旧语义最大的区别，也是**决定人要不要重发**的那一句。"""
    i = SRC.index("abort = cover_abort_info(view)")
    seg = SRC[i:i + 1400]
    assert "没有发出去" in seg and "不会有重复笔记" in seg
    assert "退避" in seg and "用光" in seg, "必须说明 server 已重试过，否则人还是会惯性重跑"


def test_弃发时明说别走fix_cover():
    """⛔ `--fix-cover` 是老帖补救——**这里根本没有"已发布的笔记"可补**。"""
    i = SRC.index("abort = cover_abort_info(view)")
    assert "别走 `--fix-cover`" in SRC[i:i + 1400]


def test_弃发判断在status判断之前():
    """⚠️ 弃发单的 `status` 就是 `failed`。若先落进 `status in ("failed","canceled")`
    那一支，就只剩一句泛泛的失败，**内层归因与"不会有重复笔记"都丢了**。"""
    assert SRC.index("abort = cover_abort_info(view)") < SRC.index('elif status in ("failed", "canceled")')


# ────────── 时序陷阱：退避中 ≠ 卡死 ──────────

def test_退避中不当卡死报():
    """⚠️ server 点名：弃发单在退避重试期间 `status` 回到 `pending` 并带 `next_retry_at`
    ——**这不是卡死**。把它读成"卡住了"会引出一次多余的重发，
    而这条路径上的重发就是**重复发出去**。"""
    assert 'retry_at = view.get("next_retry_at")' in SRC
    i = SRC.index('retry_at = view.get("next_retry_at")')
    seg = SRC[i:i + 700]
    assert "退避重试" in seg and "不是卡死" in seg


# ────────── 旧 lore 不许复活 ──────────

def test_旧lore不许复活():
    """🩸 「`exit 3` + `cover=error` 是**当前预期值，不是意外**」——
    这句曾写在四个文件里（清理时共 14 处）。它是**把红灯写进规格当成绿灯**的原型案例。
    ⚠️ 判据只查**当作规格在陈述**的写法，⛔ 不查讲那次事故的引用。

    🩸 **判据本身返工过一次**：首版只看**命中行**有没有豁免词，于是把
    「引用旧版原文以说明它作废」的那一行判成了复活——**豁免词写在上一行**
    （`> 旧版把主路径写成四步……并在第①步旁边写着：`）。
    ⇒ **判据要看它该看的上下文**：一句话是不是「当前规格」，取决于**它周围在说什么**。
    ⚠️ 这与「⛔ 抓词不抓句法」「单独看见时它替我们说了什么」是同一族。"""
    root = Path(__file__).parent.parent
    EXEMPT = ("旧版", "作废", "原型案例", "曾", "翻回", "已死", "不再")
    bad = []
    for md in root.rglob("*.md"):
        if "CHANGELOG" in md.name or ".git" in str(md):
            continue
        lines = md.read_text(encoding="utf-8", errors="ignore").splitlines()
        for i, ln in enumerate(lines):
            if "预期就是 exit 3" not in ln and "是发布链的预期值" not in ln:
                continue
            # 看**本行 + 前 3 行**：引用旧文时，"这是旧的/已作废"通常写在引导句里
            ctx = "\n".join(lines[max(0, i - 3):i + 1])
            if not any(k in ctx for k in EXEMPT):
                bad.append(f"{md.relative_to(root)}:{i+1}: {ln.strip()[:60]}")
    assert not bad, "旧 lore 复活了：" + "; ".join(bad)
