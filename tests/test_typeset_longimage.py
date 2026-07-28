"""路线② 排版长图渲染器的纯函数测试（不打浏览器、不出图）。

浏览器那半截（行盒测量 + 截图）靠实跑目视验证，这里只钉住可确定性断言的部分：
frontmatter 解析、块解析、切页贪心、字数统计、HTML 组装的关键不变量。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts"))

import typeset_longimage as T  # noqa: E402


class TestFrontmatter:
    def test_解析出字段并剥掉frontmatter(self):
        meta, body = T.split_frontmatter('---\ntitle: 标题\ntheme: paper\n---\n正文第一段')
        assert meta == {'title': '标题', 'theme': 'paper'}
        assert body.strip() == '正文第一段'

    def test_没有frontmatter时原样返回(self):
        meta, body = T.split_frontmatter('直接就是正文')
        assert meta == {}
        assert body == '直接就是正文'

    def test_值两侧的引号被剥掉(self):
        meta, _ = T.split_frontmatter('---\ntitle: "带引号的标题"\n---\n正文')
        assert meta['title'] == '带引号的标题'


class TestParseBlocks:
    def test_标题段落列表各归各类(self):
        blocks = T.parse_blocks('## 二级\n\n一段正文\n\n### 三级\n\n- 甲\n- 乙\n')
        assert blocks == [('h2', '二级'), ('p', '一段正文'), ('h3', '三级'), ('ul', ['甲', '乙'])]

    def test_整段加粗成为红色强调句而行内加粗不是(self):
        blocks = T.parse_blocks('**整段都加粗**\n\n句中有**局部加粗**的段落\n')
        assert blocks[0] == ('hl', '整段都加粗')
        assert blocks[1][0] == 'p'

    def test_表格解析且跳过对齐行(self):
        md = '| 场景 | 无效化 |\n| --- | --- |\n| 你哭了 | 别哭了 |\n'
        assert T.parse_blocks(md) == [('table', [['场景', '无效化'], ['你哭了', '别哭了']])]

    def test_正文里的一级标题降级为二级(self):
        # H1 只由 frontmatter title 提供，正文里出现的 # 不能再渲染成首页大标题
        assert T.parse_blocks('# 正文里的H1\n') == [('h2', '正文里的H1')]

    def test_多行软换行合并成一段(self):
        assert T.parse_blocks('第一行\n第二行\n\n另一段\n') == [('p', '第一行第二行'), ('p', '另一段')]

    def test_列表支持圆点与星号前缀(self):
        assert T.parse_blocks('○ 甲\n* 乙\n')[0] == ('ul', ['甲', '乙'])


class TestPaginate:
    def test_贪心取不超页高的最靠下切点(self):
        # 页高 100，切点 [30,60,90,140]：第一页应切在 90 而不是 60
        assert T.paginate([30, 60, 90, 140], 140, 100)[0] == (0, 90)

    def test_逐页推进直到覆盖全文(self):
        pages = T.paginate([50, 100, 150, 200], 200, 100)
        assert pages[0][0] == 0 and pages[-1][1] == 200
        # 页与页首尾相接，不重不漏
        assert all(pages[i][1] == pages[i + 1][0] for i in range(len(pages) - 1))

    def test_单块高于一页时硬切不死循环(self):
        # 候选切点只有末尾 500，页高 100 —— 必须硬切推进，否则死循环
        pages = T.paginate([500], 500, 100)
        assert len(pages) == 5 and pages[-1][1] == 500

    def test_内容不足一页时只出一页(self):
        assert T.paginate([80], 80, 100) == [(0, 80)]


class TestCountChars:
    def test_只数可见文字且剥掉标记符(self):
        han, total = T.count_chars([('p', '**五个汉字啊**'), ('ul', ['甲乙']), ('h2', '丙')])
        assert han == 8          # 五个汉字啊 + 甲乙 + 丙
        assert total == 8        # ** 已剥掉

    def test_表格单元格计入(self):
        han, _ = T.count_chars([('table', [['甲', '乙'], ['丙', '丁']])])
        assert han == 4


class TestBuildHTML:
    def _html(self, **kw):
        args = dict(title='标题', meta_line='全文100字｜阅读需1分钟',
                    blocks=[('p', '正文')], theme_name='clean', xhs_id='123')
        args.update(kw)
        return T.build_html(**args)

    def test_版心裁剪窗高度等于画布减上下边距(self):
        # stage 高度写错，页脚留白带就会被正文侵占（实测踩过：表格被切成半行）
        expected = T.PAGE_H - T.PAD_TOP - T.PAD_BOTTOM
        assert f'height:{expected}px' in self._html()

    def test_不给小红书号就不画页脚(self):
        assert 'class="footer"' not in self._html(xhs_id='')
        assert '小红书号 123' in self._html()

    def test_两套主题各用各的底色(self):
        assert T.THEMES['paper']['bg'] in self._html(theme_name='paper')
        assert T.THEMES['clean']['bg'] in self._html(theme_name='clean')

    def test_正文里的HTML被转义不执行(self):
        doc = self._html(blocks=[('p', '<script>alert(1)</script>')])
        assert '&lt;script&gt;alert(1)' in doc
        assert '<script>' not in doc

    def test_行内加粗与代码转成标签(self):
        assert '<b>粗</b>' in self._html(blocks=[('p', '**粗**')])
