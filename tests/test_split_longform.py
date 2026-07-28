"""系列篇拆分器测试：切点必须落在 H2 边界、分组均衡、编号规则、TODO 占位。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts"))

import split_longform as S  # noqa: E402


class TestSplitSections:
    def test_按H2切段且H3留在章节内(self):
        md = '引言段\n\n## 甲\n甲的正文\n\n### 甲一\n子节内容\n\n## 乙\n乙的正文\n'
        secs = S.split_sections(md)
        assert [t for t, _ in secs] == [None, '甲', '乙']       # None = 第一个 H2 之前的引言
        assert '### 甲一' in secs[1][1]                          # H3 不构成切点

    def test_没有H2时只有一段(self):
        assert len(S.split_sections('只有正文\n\n还是正文\n')) == 1


class TestGroupSections:
    def _secs(self, sizes):
        # 造 N 个指定字数的假章节（用汉字凑长度）
        return [(f'章{i}', '啊' * n) for i, n in enumerate(sizes)]

    def test_绝不拆开单个章节(self):
        groups = S.group_sections(self._secs([100, 100, 100, 100]), 2)
        assert sum(len(g) for g in groups) == 4                  # 章节总数守恒
        assert all(len(g) >= 1 for g in groups)

    def test_分组保持原顺序(self):
        secs = self._secs([100, 200, 300, 400])
        flat = [t for g in S.group_sections(secs, 2) for t, _ in g]
        assert flat == ['章0', '章1', '章2', '章3']

    def test_DP比贪心均衡_长尾章节不会独占一组(self):
        # 5 个 100 字 + 1 个 500 字，拆 2 组：最优是 [100×5] / [500]
        groups = S.group_sections(self._secs([100, 100, 100, 100, 100, 500]), 2)
        sizes = [sum(S.han(b) for _, b in g) for g in groups]
        assert sizes == [500, 500]

    def test_组数等于章节数时每组一章(self):
        groups = S.group_sections(self._secs([10, 20, 30]), 3)
        assert [len(g) for g in groups] == [1, 1, 1]


class TestSeriesLabel:
    def test_两篇是上下(self):
        assert [S.series_label(i, 2) for i in range(2)] == ['上', '下']

    def test_三篇是上中下(self):
        assert [S.series_label(i, 3) for i in range(3)] == ['上', '中', '下']

    def test_四篇起用中文数字(self):
        assert [S.series_label(i, 4) for i in range(4)] == ['一', '二', '三', '四']


class TestHan:
    def test_口径剥掉markdown结构标记(self):
        # 与 typeset_longimage 图上「全文N字」同口径：标记不算，正文标点算
        assert S.han('## 标题\n') == 2
        assert S.han('- 列表项\n') == 3
        assert S.han('**加粗**\n') == 2
        assert S.han('| 甲 | 乙 |\n| --- | --- |\n') == 2

    def test_注释不计入(self):
        assert S.han('<!-- TODO 承接段 -->\n正文\n') == 2

    def test_标点计入(self):
        assert S.han('你好，世界。') == 6
