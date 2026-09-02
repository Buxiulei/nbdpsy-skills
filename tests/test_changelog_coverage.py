"""**把发版记账闸挂进 pytest**，并钉住它自己最容易恒绿的那几处。

🩸 起因（佰亿助理 2026-09-02 派单）：v2.42.0 之后 7 个提交 CHANGELOG 一个都没记，
其中 `1998975` 是 feat，静默积压五天。闸的实现在 `tools/check_changelog_coverage.py`，
本文件只做两件事：**发版提交上真跑一遍**，以及**守住闸自身的判据别被写成恒真**。

## 🔴 判据 1 为什么带 skip —— 以及这个 skip 本身就是已知失效方向

日常开发时 HEAD 不是发版提交，那些提交**本来就还没到记账的时候**，此时跑闸必红 ⇒ 是误报。
所以判据 1 只在「HEAD 是纯发版提交」时生效，其余 skip。

⚠️ 代价说明白：**若发版流程改成「先跑 pytest 再 commit release」，这条判据会永远 skip**
（HEAD 永远不是发版提交）⇒ 恒绿。pytest 这一层挡不住那种用法，
**真正的闸是 `README.md` 发版规范里那条「commit 完 release 再跑一次脚本」**。
skip 会打印原因，⛔ 别把 skip 读成通过。

## 其余判据守什么

- 判据 2：sha 匹配**不能用子串搜**。CHANGELOG 正文有热线电话 `4001619995`，
  子串法会让任何以 `4001619` 开头的 sha 白嫖记账（实测确实会）。
- 判据 3：记账词下限 7 位，⛔ 不能放低到四位——`3bee`、`2026` 这种串正文里遍地都是。
- 判据 4：**被后续发版吸收的中间发版**要跳过，否则基线落在它身上、范围只剩发版提交自己，
  闸绿却一个实质提交都没验到。这条路径在当前历史上**跑不到**（v2.42.1 被 reset 掉了、
  已不在主干上），所以这里用构造数据把它执行一遍，⛔ 不让它成为「写了但从没跑过」的代码。
- 判据 5：**夹带实质改动的发版提交不许豁免**。用真实的 `76b558f release: v2.42.0` 验——
  它除三个发版文件外还改了 7 个实质文件，无条件豁免 release 提交的话它就白嫖了。
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import check_changelog_coverage as 闸  # noqa: E402


def _git可用() -> bool:
    r = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                       capture_output=True, text=True)
    return r.returncode == 0


def test_发版提交上记账闸必须全绿():
    """判据 1：HEAD 是纯发版提交时，自上一版以来每个提交都得记过账。"""
    if not _git可用():
        pytest.skip("不在 git 工作树里（打包安装后的副本），记账闸无从判定 —— ⛔ 这不是通过")

    head = 闸._git("rev-parse", "HEAD").strip()
    标题 = 闸._git("log", "-1", "--format=%s").strip()
    if not 闸.是纯发版提交(head, 标题):
        pytest.skip(
            f"HEAD（{head[:7]} {标题[:40]}）不是纯发版提交 —— 日常开发的提交尚未到记账时点，"
            "此处 skip 是设计内的。发版时请跑 `python3 tools/check_changelog_coverage.py`。"
            "⛔ 别把这个 skip 读成通过。")

    码 = 闸.跑闸()
    assert 码 == 0, (
        "发版记账闸红了：自上一版以来有提交没写进 CHANGELOG.md。"
        "上面的输出已逐条列出是哪些提交 —— 把改动写进本次发版那一节并带上短 sha，"
        f"或给那个提交的提交信息加 `{闸.EXEMPT_MARK}`。⛔ 别改闸的判据来放行。")


def test_sha匹配不被正文里的电话号误命中():
    """判据 2：热线电话 `4001619995` 不得让以 `4001619` 开头的 sha 白嫖记账。"""
    正文 = 闸.读CHANGELOG()
    词 = set(闸.SHA_WORD_RE.findall(正文))

    assert "4001619995" in 词, (
        "CHANGELOG 里已经没有热线号 4001619995 了 —— 这条判据失去了它要防的那个真实样本，"
        "⛔ 别让它恒真地绿着。换一个正文里真实存在的、会被十六进制正则命中的数字串。")

    假sha = "4001619" + "a" * 33
    assert 假sha[:7] in 正文, "样本前提没了：那 7 位数字本应作为电话号的一部分出现在正文里"

    # 🔴 这条守的是**闸自己会被正文污染**这件事，⛔ 不是匹配逻辑坏了。
    # 我写 v2.43.1 那节时亲手踩过：为解释这个洞而在正文里写下裸的 7 位数字，
    # 它当场变成一个合法「记账词」，任何以它开头的提交从此白嫖。先报这条，
    # ⛔ 别让人拿着下面那条「实现退回子串法」的提示去翻根本没坏的匹配逻辑（假红最会带偏人）。
    assert 假sha[:7] not in 词, (
        f"CHANGELOG 正文里出现了裸的十六进制串 `{假sha[:7]}`，它已被当成合法的「记账词」——"
        "任何以它开头的提交从此都能白嫖记账。⇒ 改正文措辞，用文字描述这个前缀，"
        "⛔ 别写那串数字本身。⛔ 不是匹配逻辑坏了，别去改 `已记账`。")

    assert not 闸.已记账(假sha, 词), (
        "sha 匹配被电话号误命中了 —— 说明实现退回成了「拿短 sha 全文搜子串」。"
        "必须是「提取独立十六进制词 + 要求全 sha 以该词为前缀」，"
        "否则任何以 4001619 开头的提交都能白嫖记账，且没有人会发现。")

    # 反向（防误拦）：样本从词集里现取，⛔ 不写死某个 sha —— 写死的话，
    # 哪天那一节被归档删掉，这条会**假红**，把人朝「匹配逻辑坏了」的方向带（实测 M4 变异时发生过）。
    短词 = sorted(w for w in 词 if len(w) == 7)
    assert 短词, "CHANGELOG 里一个 7 位短 sha 都没有 —— 防误拦那半边失去样本，⛔ 别默认它还在验"
    assert 闸.已记账(短词[0] + "b" * 33, 词), (
        "CHANGELOG 写 7 位短 sha、这边拿 40 位全 sha 去比，必须仍能对上 —— "
        "现在对不上，判据从误放行滑到了误拦，会把正常发版卡死。")


def test_记账词下限七位():
    """判据 3：下限放低到四位，正文里随便一段话都能算记账 ⇒ 闸恒绿。"""
    assert not 闸.SHA_WORD_RE.fullmatch("3bee"), "四位串不该被当成 sha 记账词"
    assert not 闸.SHA_WORD_RE.fullmatch("2026"), "四位串不该被当成 sha 记账词"
    assert 闸.SHA_WORD_RE.fullmatch("1998975"), "7 位短 sha 必须能被认出来"
    assert 闸.SHA_WORD_RE.fullmatch("a" * 40), "40 位全 sha 必须能被认出来"


def test_基线跳过被后续发版吸收的中间发版(monkeypatch):
    """判据 4：中间发版的版本节已被吸收时，基线要继续往前找，⛔ 不能停在它身上。

    不这样做的后果：基线落在被吸收的那个发版上 ⇒ 范围只剩发版提交自己 ⇒
    闸绿，却一个实质提交都没验到。这次差一点就是这个局面（v2.42.1 的节被 v2.43.0 合并掉了），
    只因它的提交被 reset 出了主干才没触发 ⇒ 这条路径在真实历史上跑不到，用构造数据跑。
    """
    HEAD = "f" * 40
    吸收掉的 = "e" * 40
    真基线 = "d" * 40
    假历史 = [(HEAD, "release: v2.43.0（本次）"),
              (吸收掉的, "release: v2.42.1（节已被 2.43.0 合并掉）"),
              ("c" * 40, "fix(x): 一个实质提交"),
              (真基线, "release: v2.42.0 — 仍独立成节")]

    monkeypatch.setattr(闸, "主干提交", lambda 限制=400: 假历史)
    monkeypatch.setattr(闸, "_git", lambda *a: HEAD + "\n")

    sha, 标题 = 闸.定位基线("## [2.43.0] — x\n## [2.42.0] — y\n")
    assert sha == 真基线, (
        f"基线停在了 {sha[:7]}（应为 {真基线[:7]}）—— 版本节已不在 CHANGELOG 里的中间发版"
        "必须跳过，否则范围会缩到只剩发版提交自己，闸绿而没验到任何实质提交。")
    assert "2.42.0" in 标题


def test_夹带实质改动的发版提交不许豁免():
    """判据 5：`release:` 三个字不是免死金牌，只动三个发版文件才算纯发版提交。"""
    if not _git可用():
        pytest.skip("不在 git 工作树里 —— ⛔ 这不是通过")

    夹带 = "76b558f"   # release: v2.42.0，除三个发版文件外还改了 7 个实质文件
    存在 = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", f"{夹带}^{{commit}}"],
                          capture_output=True)
    if 存在.returncode != 0:
        pytest.skip(f"样本提交 {夹带} 不在本副本的历史里（浅克隆或历史被改写）—— ⛔ 这不是通过")

    标题 = 闸._git("log", "-1", "--format=%s", 夹带).strip()
    assert 标题.startswith(闸.RELEASE_PREFIX), f"样本前提变了：{夹带} 已不是 release 提交"
    assert not 闸.是纯发版提交(夹带, 标题), (
        f"{夹带} 除三个发版文件外还改了实质文件，却被判成可豁免的纯发版提交 —— "
        "这样谁把实质改动塞进发版提交谁就白嫖记账。豁免条件必须是「改动文件集 ⊆ 三个发版文件」。")

    纯的 = 闸._git("rev-parse", "HEAD").strip()
    if 闸._git("log", "-1", "--format=%s").strip().startswith(闸.RELEASE_PREFIX):
        assert 闸.是纯发版提交(纯的, 闸._git("log", "-1", "--format=%s").strip()), (
            "反向样本：当前 HEAD 是只动了三个发版文件的发版提交，必须判为可豁免 —— "
            "否则判据从误放行滑到了误拦，发版会被自己卡死。")
