"""中文文案里的半角标点：**提示级 warn**；以及 `hero_max_line` 改为**按宽度计**。

🩸 **这两件的因果一度被转述反了**，值得原样记住：
> 转述版：「hero 里一个**半角**逗号使字高 9.79%→8.33%」⇒ 要 warn 半角。
> 8/21 原文：「试排写半角逗号→9.79%；落稿改**全角**→掉到 8.33%」。
> **6 组对照实测**（同一句只换标点）：无标点 11.04% ／ **全角 9.67%** ／ **半角 11.58%**。

⇒ **压字高的是全角**（占 1.0 字宽＝多一个字），半角只占 0.6、几乎不吃宽度。
🔴 照转述做会得到一个**「warn 无害写法、放过真凶」**的闸门——响错理由的极端形式。
⇒ 分成两件：**字高交给 `hero_max_line`（按宽度计）**；**半角只按「中文排版规范」提示**。
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SCRIPTS = ROOT / "nbdpsy-xiaohongshu-creator" / "scripts"
TPL = ROOT / "nbdpsy-xiaohongshu-creator" / "assets" / "cover-templates" / "tpl-cover-jinjin.html"
sys.path.insert(0, str(SCRIPTS))

import render_cover as rc  # noqa: E402

SRC = (SCRIPTS / "render_cover.py").read_text(encoding="utf-8")
TPL_SRC = TPL.read_text(encoding="utf-8")


# ────────── 半角 warn：只在紧邻中文时才算 ──────────

@pytest.mark.parametrize("data", [
    {"hero": ["不是想太多,是离得太近"]},
    {"subtitle": "所以解法不是「少想」."},
    {"steps": ["第一条", "第二条,带半角"]},
    {"footer": "NBDpsy 心理科普!"},
])
def test_中文里的半角要提示(data):
    assert rc.halfwidth_punct_warning(data) is not None


@pytest.mark.parametrize("data", [
    {"hero": ["不是想太多，是离得太近"]},          # 全角＝正确写法
    {"hero": ["NBDpsy 心理"], "footer": "NBDpsy 心理科普"},   # 品牌名
    {"subtitle": "每天 3.5 小时"},                # 数字小数点
    {"hero": ["P01.png 这个文件"]},               # 文件名
    {"steps": ["A/B test 的结果"]},
    {}, {"hero": []}, {"hero": [None]},
])
def test_这些不该被误伤(data):
    """🔴 **恒响的提示三天之内就没人看了**，那比没有提示更糟——它还占着"我们查过了"的位置。
    ⇒ 判据必须是「半角标点**紧邻中文**」，⛔ 不是「文本里有半角标点」。"""
    assert rc.halfwidth_punct_warning(data) is None


def test_提示级不阻断():
    """⛔ 中文里偶尔出现半角有正当场合（品牌写法、英文夹注），**判在人**。
    做成阻断会逼人为了过闸去改成不该改的写法。"""
    w = rc.halfwidth_punct_warning({"hero": ["不是想太多,是离得太近"]})
    assert not w.startswith("🔴"), "这条是提示，⛔ 不是红灯"
    assert "不阻断" in w and "判在人" in w


def test_warn理由不许写成拉崩字高():
    """🔴 **防理由退回**：这条 warn 的理由是「中文排版规范」。
    ⚠️ 若哪天有人把「会让字高掉下去」写回这条 warn，就等于**又指错了真凶**
    ——真正吃字宽的是**全角**标点，那件已由最长行判据接住。"""
    w = rc.halfwidth_punct_warning({"hero": ["不是想太多,是离得太近"]})
    assert "中文排版规范" in w
    assert "与字高无关" in w
    assert "全角" in w, "要指明真正吃字宽的是谁，否则人还会以为半角是元凶"


# ────────── hero_max_line：按宽度计，⛔ 不是数汉字 ──────────

def test_模板不再只数汉字():
    """🩸 8/21 事件的**真 bug**：`match(/[一-龥]/g).length` **只数汉字，标点一个都不算**
    ⇒ 「5 字 + 1 个全角逗号」被判成 5 字（**判过**），而全角占 1.0 字宽、实际就是 6 字。
    ⚠️ 上面那张实证表（5字→11.12%｜6字→9.22–9.37%）按这个计数在卡 ⇒ **判据自己有个洞**。"""
    i = TPL_SRC.index("hero_max_line:")
    seg = TPL_SRC[i:i + 500]
    assert "match(/[一-龥]/g)" not in seg, "又退回只数汉字了"
    assert "0.6" in seg and "1.0" in seg, "要按宽度计（全角 1.0 / 半角 0.6）"


def test_hero_max_line进了必需字段与输出():
    """🩸 它**被红灯文案硬取**（「最长那一行 {ml} 字」）却一直不在 `FIT_KEYS` 里，
    而取值写的是 `.get()` ⇒ 模板哪天不交回，红灯会**静默变成「最长那一行 None 字」**，
    ⛔ 不会报「模板与脚本版本对不上」——正是那张表要防的情况，它自己漏了这一个。"""
    assert "'hero_max_line'" in SRC.split("FIT_KEYS")[1][:900], "没进 FIT_KEYS"
    assert "'hero_max_line': fit.get('hero_max_line')" in SRC, "没透出到 stdout"


def test_宽度模型与实测字高对得上():
    """⚠️ 这条不跑浏览器，钉的是**已实测的对应关系**（6 组对照，同一句只换标点）：

    | hero | 实测字高 | 按宽度计 | 模板实证表 |
    |---|---|---|---|
    | 5 字无标点 | 11.04% | 5   | 5 字 → 11.12% |
    | 5 字+全角  | 9.67%  | **6** | 6 字 → 9.22–9.37% |
    | 5 字+半角  | 11.58% | 5.6 | 介于两档 |

    ⇒ **全角把它推进了下一档，半角没有。** 这就是整件事的全部。"""
    def w(text):                      # 与模板同口径：< 0x2E80 记 0.6，其余 1.0
        return round(sum(0.6 if ord(c) < 0x2E80 else 1.0
                         for c in text.strip() if not c.isspace()), 1)
    assert w("不是想太多") == 5
    assert w("不是想太多，") == 6      # 全角 ⇒ 进 6 字档（实测 9.67%）
    assert w("不是想太多,") == 5.6     # 半角 ⇒ 仍在 5 档（实测 11.58%）
    assert w("NBDpsy") == 3.6          # 纯 ASCII
