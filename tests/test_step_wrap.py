"""递进行折行量具：**`step_fs` 正常的时候，递进区可能已经被撑到半屏**。

🩸 hero 与递进行的排版策略**相反**：
  · hero 靠**压字号**避免折行 ⇒ `hero_fs` 掉到多低就是它的告警；
  · **递进行是允许折行的**（模板 `.step .mk` 注释：「条目折行也不跑位」）。
⇒ 实测一条 46 字的递进行折成 **4 行**、吃掉近一半画面，
  而 `step_fs` 反而是 **42px**（比压缩时的 22px 还大）——**看数字完全正常**。
⚠️ 此前**没有任何量具在报这件事**。
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SCRIPTS = ROOT / "nbdpsy-xiaohongshu-creator" / "scripts"
TPL = ROOT / "nbdpsy-xiaohongshu-creator" / "assets" / "cover-templates" / "tpl-cover-jinjin.html"
sys.path.insert(0, str(SCRIPTS))

import render_cover as rc  # noqa: E402


# ────────── 阈值：来自 6 个真实样本，⛔ 不是拍的 ──────────

@pytest.mark.parametrize("sl", [[1, 1], [2, 2, 2], [1, 2, 2], [2], [1]])
def test_两行以内不报(sl):
    """**2 行是常态**——实测 6 个真实样本（`cover-html-proto` 那批）几乎全是 `[2,2,2]`。
    ⛔ 拿 2 行去卡人 = 恒响，而恒响的闸门等于没有闸门。"""
    assert rc.step_wrap_warning(sl) is None


def test_三行只提示不报红():
    """⚠️ 样本只有 6 个且同批 ⇒ 判据取保守侧。"""
    w = rc.step_wrap_warning([3, 1])
    assert w and not w.startswith("🔴")


@pytest.mark.parametrize("sl", [[4, 1], [2, 5], [4, 4]])
def test_四行以上报红(sl):
    w = rc.step_wrap_warning(sl)
    assert w and w.startswith("🔴")


def test_红灯要说清step_fs看不出来():
    """🔴 这是这条告警**存在的理由**：出问题时 `step_fs` 是正常的（甚至偏大），
    ⛔ 光看字号发现不了。红灯不说这句，人会去查字号然后判"没问题"。"""
    w = rc.step_wrap_warning([4, 1])
    assert "step_fs" in w and "看不出来" in w


def test_判据取单条最大不取总和():
    """⚠️ 「三条各 2 行」（总 6 行）是常态；「一条 4 行」才是失衡。
    ⇒ 取 **max**，⛔ 不取 sum——取 sum 会把正常的三条样本判红。"""
    assert rc.step_wrap_warning([2, 2, 2]) is None      # 总 6 行
    assert rc.step_wrap_warning([4]) is not None        # 总 4 行


@pytest.mark.parametrize("bad", [None, [], ["x"], [None], "2", [True]])
def test_坏输入不炸也不误报(bad):
    """⚠️ `True` 在 Python 里 `isinstance(True, int)` 为真——⛔ 别让布尔混进行数。"""
    assert rc.step_wrap_warning(bad) is None


# ────────── 量具本身：⛔ 别再用 getClientRects 量 flex item ──────────

def test_模板用Range量行数():
    """🩸 **量法返工过一次**：首版写 `el.getClientRects().length`，
    对一条**实测折成 4 行**的递进行报 **1** ——`.tx` 是 `flex:1 1 auto` 的
    **flex item（block-level）**，它自己只有**一个**边框盒，行数在它**内容**里。
    ⚠️ **那个 1 看起来完全合理**，拿"已知折 4 行"的样本去验才发现是假的。
    ⇒ 必须用 `Range.selectNodeContents`（Range 的 getClientRects **按行返回**）。"""
    tpl = TPL.read_text(encoding="utf-8")
    i = tpl.index("step_lines:")
    seg = tpl[i:i + 400]
    assert "selectNodeContents" in seg, "又回到按元素量了——那会对 flex item 恒报 1"
    assert "el.getClientRects().length" not in seg


def test_step_lines进了必需字段与输出():
    """⛔ 模板交回了但脚本不透出 = 白量（首版就是这样，stdout 里恒 None）。"""
    src = (SCRIPTS / "render_cover.py").read_text(encoding="utf-8")
    # ⚠️ 常量叫 `FIT_KEYS`（我一开始按印象写成 `REQUIRED_FIT`，split 直接 IndexError）
    #    ——**⛔ 别按印象写标识符**，这类错在测试里表现为"莫名其妙的 IndexError"而不是断言失败。
    assert "'step_lines'" in src.split("FIT_KEYS")[1][:700], "没进 FIT_KEYS"
    assert "'step_lines': fit.get('step_lines')" in src, "没透出到 stdout"
