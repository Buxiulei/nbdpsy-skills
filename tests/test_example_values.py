"""示例串常设闸（跨 skill 全仓面）：**文档里的示例会被当成真值抄走**。

🩸 事故链（同一个形状咬了三次才立此闸）：
1. `render_cover.py` docstring 示例写 `--style-profile "图文 v3"`——**档案库里不存在的组合**
   （「图文」只有 v2，v3 是「暖米大字」的）⇒ 博客长文照抄 ⇒ **13 份凭证错标一路绿灯**到发布前；
2. `tests/test_render_cover.py` 四处硬编码同一组合——**测试成了第 14 个受害者**（校验闸门
   一上线它当场红，此前一路绿）；`gen_images` 的**告警文案**里还有第 15 个传播点——
   人看到告警就照抄；
3. `gzh-illustration-spec.md` 模板行写 `读取于 2026-08-04` ——日期被抄死后，
   trace_line 这条留痕就**从「哪天读的」退化成一个装饰**（服务号线修掉并点出）。

⇒ 规矩：**示例一律写成明显的占位符**（`<套名> v<N>`、`YYYY-MM-DD`），
⛔ 别写任何"看起来能直接用"的具体值。

本文件与 `test_style_gate_three_lines.py::test_告警与示例里不留可抄的错标组合` 的分工：
那条钉**两个具体文件**里的具体错标（`图文 v3`），更严、带语境断言；
本文件是**全仓面 + 模式化**——发现新形状往 `PATTERNS` 里加一行，⛔ 不用再写新测试。
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

# ── 模式表：每行 = (名字, 编译好的正则, 它防的事故) ─────────────────────────
# ⚠️ **发现新形状往这里加**（附事故出处），⛔ 别另起一个测试文件——
#    散开之后每个都只保护自己点名的那一处。
PATTERNS = [
    ("留痕行示例带具体套名+具体日期",
     re.compile(r"风格档案：(?!<)[^\s<（(]{1,12}\s*v\d+（[^）]*读取于\s*20\d\d-\d\d-\d\d"),
     "gzh-illustration-spec 模板行抄死日期：留痕从「哪天读的」退化成装饰"),
    ("--style-profile 示例带具体组合",
     re.compile(r'--style-profile\s+["\'"](?!<)[^\s"\'"]{1,10}\s+v\d+["\'"]'),
     "「图文 v3」被当真值抄：13 份凭证错标 + 测试第 14 个受害者 + 告警文案第 15 个传播点"),
]

# 豁免：本行或**前 3 行**含事故叙述词 ⇒ 那是在**讲**那次事故，⛔ 不是在**做**示例。
# （判据要看它该看的上下文——「引用旧版以说明它作废」的行，豁免词常在引导句里。）
EXEMPT = ("份", "错标", "只有 v2", "当真值抄", "作废", "旧版", "事故",
          "曾", "实证", "抄走", "抄用", "抄死", "原型案例", "传播源")

SCAN_SUFFIXES = (".md", ".py")


def scan_repo():
    bad = []
    for f in sorted(ROOT.rglob("*")):
        if f.suffix not in SCAN_SUFFIXES or "CHANGELOG" in f.name or ".git" in str(f):
            continue
        if f == Path(__file__):        # 本文件内置坏样本，⛔ 别扫自己
            continue
        try:
            lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for i, ln in enumerate(lines):
            for name, pat, _ in PATTERNS:
                if not pat.search(ln):
                    continue
                ctx = "\n".join(lines[max(0, i - 3):i + 1])
                if not any(k in ctx for k in EXEMPT):
                    bad.append(f"{f.relative_to(ROOT)}:{i+1} [{name}] {ln.strip()[:70]}")
    return bad


def test_全仓无可抄的示例串():
    bad = scan_repo()
    assert not bad, (
        "文档里出现了「看起来能直接用」的示例值——它会被当真值抄走"
        "（13 份凭证错标就是这么来的）。改成占位符 `<套名> v<N>` / `YYYY-MM-DD`，"
        "或若是在讲事故，把叙述词写进本行或前 3 行：\n  " + "\n  ".join(bad))


# ── 量具自检：⛔ 一个判据烂掉后恒绿的扫描，比没有扫描更糟 ─────────────────────
# （它占着"我们查过了"的位置。每个模式配一对 坏样本/好样本，模式改坏任何一边立刻红。）

_BAD = [
    "        风格档案：图文 v3（本人档案，读取于 2026-07-28）",     # 事故 1/2 的原样
    '或出图时显式传 --style-profile "图文 v3"',                      # 第 15 个传播点原样
    "> 风格档案：图文 v1（本人档案，读取于 2026-08-04）",           # 事故 3 的原样
]
_GOOD = [
    "        风格档案：<套名> v<N>（本人档案，读取于 YYYY-MM-DD）",  # 正确占位符
    '--style-profile "<套名> v<N>"',
    # 存量无套名格式的**描述**（parse_style_trace 在说明它认什么，不是给人抄的模板）：
    # ⚠️ 这是判据的已知边界——无套名旧格式不在 P1 覆盖内，新留痕都带套名，不会从它抄起
    "风格档案：v3（本人档案，读取于 2026-07-28）",
]


@pytest.mark.parametrize("line", _BAD)
def test_量具自检_历史坏样本必须抓到(line):
    assert any(p.search(line) for _, p, _ in PATTERNS), f"判据漏了历史事故原样：{line[:50]}"


@pytest.mark.parametrize("line", _GOOD)
def test_量具自检_正确写法必须放行(line):
    """⛔ 反向也要钉：占位符被误报 ⇒ 恒响 ⇒ 三天之内就没人看了。"""
    assert not any(p.search(line) for _, p, _ in PATTERNS), f"误报正确写法：{line[:50]}"


def test_量具自检_豁免只认叙述语境():
    """讲事故的引用（前 3 行有叙述词）放行；裸的具体值不放。"""
    assert any(k in "🩸 实证：13 份凭证标着 `图文 v3` 一路绿灯" for k in EXEMPT)
    assert not any(k in "示例：--style-profile 用法如下" for k in EXEMPT)
