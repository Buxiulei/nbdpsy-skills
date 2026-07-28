"""路线② 文字版渲染器的纯函数测试（不打浏览器、不出图）。

浏览器那半截（行盒测量 + 截图）靠实跑目视验证，这里只钉住可确定性断言的部分：
frontmatter 解析、块解析、切页贪心、字数统计、HTML 组装的关键不变量。
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts"))

import typeset_longimage as T  # noqa: E402

SCRIPT = Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts" / "typeset_longimage.py"


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
                    blocks=[('p', '正文')], theme_name='clean')
        args.update(kw)
        return T.build_html(**args)

    def test_版心裁剪窗高度等于画布减上下边距(self):
        # stage 高度写错，页脚留白带就会被正文侵占（实测踩过：表格被切成半行）
        expected = T.PAGE_H - T.PAD_TOP - T.PAD_BOTTOM
        assert f'height:{expected}px' in self._html()

    def test_页脚固定是品牌名(self):
        # 页脚不写小红书号：换号就废，也没必要对外露账号
        html = self._html()
        assert 'NBDpsy心理咨询工作室' in html
        assert '小红书号' not in html

    def test_两套主题各用各的底色(self):
        assert T.THEMES['paper']['bg'] in self._html(theme_name='paper')
        assert T.THEMES['clean']['bg'] in self._html(theme_name='clean')

    def test_正文里的HTML被转义不执行(self):
        doc = self._html(blocks=[('p', '<script>alert(1)</script>')])
        assert '&lt;script&gt;alert(1)' in doc
        assert '<script>' not in doc

    def test_行内加粗与代码转成标签(self):
        assert '<b>粗</b>' in self._html(blocks=[('p', '**粗**')])

    def test_没有咨询师时不产推介层(self):
        assert 'class="promo"' not in self._html()


class TestStripComments:
    def test_注释被剥掉(self):
        body, todos = T.strip_comments('正文\n<!-- 普通注释 -->\n更多正文')
        assert '注释' not in body and todos == []

    def test_未填的TODO占位被拎出来(self):
        _, todos = T.strip_comments('<!-- TODO 承接段：写这里 -->\n正文')
        assert len(todos) == 1 and todos[0].startswith('TODO 承接段')


class TestBuildPromo:
    COUNSELOR = {
        'display_name': '张三', 'title': 'CPS注册心理师',
        'introduction': '一段介绍。',
        'profile_sections': {'specialties': [{'title': '创伤应激', 'desc': 'x'},
                                             {'title': '情绪困扰', 'desc': 'y'}]},
    }

    def _promo(self, **kw):
        c = dict(self.COUNSELOR); c.update(kw.pop('counselor', {}))
        return T.build_promo(c, kw.get('blurb', ''), T.THEMES['clean'])

    def test_专长从profile_sections取title(self):
        # --emp 详情里 specialties 是 [{title,desc}]，不是字符串数组（踩过：整行空白）
        assert '创伤应激 · 情绪困扰' in self._promo()

    def test_也兼容list接口的字符串数组(self):
        html = T.build_promo({'display_name': '李四', 'specialties': ['甲', '乙']}, '', T.THEMES['clean'])
        assert '甲 · 乙' in html

    def test_blurb覆盖官网introduction(self):
        html = self._promo(blurb='更短的推介')
        assert '更短的推介' in html and '一段介绍。' not in html

    def test_推介卡不放危机声明(self):
        # G6（xiaohongshu-spec §1.5）：危机声明不与商业 CTA 同页/同屏。
        # 这张卡带品牌行与「目前接受预约」这类 CTA，12356 的位置在发布正文里。
        html = self._promo()
        assert '12356' not in html
        assert 'NBDpsy · 咨询师全员北大硕博' in html      # 品牌行仍在

    def test_没有咨询师返回空串(self):
        assert T.build_promo(None, '', T.THEMES['clean']) == ''

    def test_咨询师字段被转义(self):
        html = T.build_promo({'display_name': '<b>x</b>'}, '', T.THEMES['clean'])
        assert '&lt;b&gt;x&lt;/b&gt;' in html


class TestHeadline:
    C = {'display_name': '李宇', 'title': '中级心理治疗师',
         'profile_sections': {'specialties': [{'title': '创伤应激'}, {'title': '情绪困扰'}]}}

    def test_显式标题原样用(self):
        # 好标题是内容判断（要结合本篇文章主题），agent 写好传进来，脚本不得改写
        assert T.build_headline(self.C, '心理咨询师-李宇，陪你整合创伤与秩序') \
            == '心理咨询师-李宇，陪你整合创伤与秩序'

    def test_兜底走三要素结构(self):
        assert T.build_headline(self.C) == '心理咨询师-李宇，陪你面对创伤应激'

    def test_没有专长时只留姓名前缀(self):
        assert T.build_headline({'display_name': '张三'}) == '心理咨询师-张三'

    def test_兜底也兼容list接口的字符串数组(self):
        assert T.build_headline({'display_name': '王五', 'specialties': ['亲密关系']}) \
            == '心理咨询师-王五，陪你面对亲密关系'

    def test_标题进了推介卡(self):
        html = T.build_promo(dict(self.C), '', T.THEMES['clean'], '心理咨询师-李宇，陪你整合创伤与秩序')
        assert '心理咨询师-李宇，陪你整合创伤与秩序' in html


class TestPromoComplianceGate:
    """推介文案的违禁词闸门：check_compliance.py 只吃文件路径，
    而 headline/blurb 是命令行字符串——不落盘就等于这段带 CTA 的文字完全没被扫过。"""

    def test_落盘后跑扫描并返回判定(self, tmp_path):
        verdict, draft = T.scan_promo_compliance('心理咨询师-李宇，陪你练习开口拒绝',
                                                 '他的方法针对的正是这类模式。', tmp_path)
        assert draft.exists() and draft.name == 'promo-draft.md'
        assert '心理咨询师-李宇' in draft.read_text(encoding='utf-8')
        assert verdict.get('ok') is True

    def test_违禁词被拦下(self, tmp_path):
        # 极限词违广告法 §9，是这条路线上最容易出现在 CTA 里的一类
        verdict, _ = T.scan_promo_compliance('心理咨询师-李宇，陪你练习开口拒绝',
                                             '找他一定能彻底根治你的讨好型人格。', tmp_path)
        assert verdict.get('ok') is False


class TestCheckHeadline:
    def test_老师称呼被拦(self):
        # counselor-note-spec §1.1 红线：直呼其名，绝不加「老师」
        assert any('老师' in w for w in T.check_headline('心理咨询师-李宇老师，陪你整合创伤'))

    def test_过长被拦(self):
        assert T.check_headline('心' * 25)

    def test_合格标题无告警(self):
        assert T.check_headline('心理咨询师-李宇，陪你整合创伤与秩序') == []


class TestSeriesMeta:
    def test_系列信息进副信息行(self):
        # 首页那行「全文1726字｜阅读需5分钟｜系列 2/2」
        html = T.build_html('标题', '全文100字｜阅读需1分钟｜系列 2/3',
                            [('p', '正文')], 'clean', '', None, '')
        assert '系列 2/3' in html


# ── 风格档案（--style）──────────────────────────────────────────────────────
def _style_file(tmp_path, typeset, kind='typeset', name='style.json'):
    f = tmp_path / name
    f.write_text(json.dumps({'kind': kind, 'typeset': typeset}, ensure_ascii=False),
                 encoding='utf-8')
    return f


class TestLoadStyle:
    def test_取出typeset段(self, tmp_path):
        f = _style_file(tmp_path, {'theme': 'paper', 'accent': '#123456'})
        assert T.load_style(f) == {'theme': 'paper', 'accent': '#123456'}

    def test_自动剥掉get的整份输出外层(self, tmp_path):
        # 运营多半直接 `style_profile.py --get --kind typeset > 文字版.json`，
        # 那份带 exists/base_version/trace_line 外层——不剥就读不到 kind，白报错
        f = tmp_path / 'get.json'
        f.write_text(json.dumps({'exists': True, 'base_version': 3,
                                 'profile': {'kind': 'typeset', 'typeset': {'theme': 'paper'}},
                                 'trace_line': '风格档案：文字版 v3'}), encoding='utf-8')
        assert T.load_style(f) == {'theme': 'paper'}

    def test_图文那套被拒(self, tmp_path):
        # carousel 里全是人物卡/配色/每页信息点，没有排版字段——拿它渲染文字版等于没设置
        f = _style_file(tmp_path, None, kind='carousel')
        try:
            T.load_style(f)
            assert False, '应当拒绝 carousel'
        except ValueError as exc:
            assert 'typeset' in str(exc)

    def test_整份多套档案被拒并指路(self, tmp_path):
        f = tmp_path / 'all.json'
        f.write_text(json.dumps({'schema': 'profiles-v1', 'active': '图文',
                                 'profiles': {'文字版': {'kind': 'typeset'}}}), encoding='utf-8')
        try:
            T.load_style(f)
            assert False, '应当拒绝整份多套档案'
        except ValueError as exc:
            assert '--kind typeset' in str(exc)

    def test_没有typeset段时返回空(self, tmp_path):
        f = tmp_path / 's.json'
        f.write_text(json.dumps({'kind': 'typeset'}), encoding='utf-8')
        assert T.load_style(f) == {}


class TestStyleOverrides:
    def test_null与缺省一律不覆盖(self):
        # 契约的核心一条：null = 「这项我没定，听主题的」。写进 CSS 会渲染成字面量 None
        all_null = {'theme': 'clean', 'bg': None, 'accent': None, 'accent_soft': None,
                    'font': None, 'title_font': None, 'indent': None, 'texture': None}
        assert T.style_overrides(all_null) == {}
        assert T.style_overrides({}) == {}

    def test_颜色原样覆盖(self):
        over = T.style_overrides({'bg': '#101820', 'accent': '#2F6FEB',
                                  'accent_soft': 'rgba(47,111,235,.12)'})
        assert over == {'bg': '#101820', 'accent': '#2F6FEB',
                        'accent_soft': 'rgba(47,111,235,.12)'}

    def test_字体只映射到既有三条字体链(self):
        assert T.style_overrides({'font': 'serif'})['font'] == T.FONT_SERIF
        assert T.style_overrides({'title_font': 'kai'})['h1_font'] == T.FONT_KAI
        assert T.style_overrides({'font': 'sans'})['font'] == T.FONT_SANS

    def test_缩进布尔转成CSS取值(self):
        assert T.style_overrides({'indent': True})['indent'] == '2em'
        assert T.style_overrides({'indent': False})['indent'] == '0'

    def test_纸纹映射(self):
        assert T.style_overrides({'texture': 'paper'})['texture'] == T.PAPER_TEXTURE
        assert T.style_overrides({'texture': 'none'})['texture'] == 'none'

    def test_非法取值报错而不是静默忽略(self):
        # 静默忽略 = 出一套「看着不对但说不上哪不对」的图，运营发现不了
        for bad in ({'font': 'kai'},            # kai 只给标题，正文没有楷体链
                    {'font': 'Comic Sans'},
                    {'title_font': 'mono'},
                    {'texture': 'linen'},
                    {'indent': '2em'},          # 只收 true/false
                    {'bg': '#fff; } body { display:none'}):   # 撑破 CSS
            try:
                T.style_overrides(bad)
                assert False, f'应当拒绝 {bad}'
            except ValueError:
                pass


class TestResolveTheme:
    def test_命令行最高档案次之再frontmatter(self):
        assert T.resolve_theme('paper', {'theme': 'clean'}, {'theme': 'clean'}) == 'paper'
        assert T.resolve_theme(None, {'theme': 'paper'}, {'theme': 'clean'}) == 'paper'
        assert T.resolve_theme(None, {}, {'theme': 'paper'}) == 'paper'
        assert T.resolve_theme(None, {}, {}) == 'clean'

    def test_档案theme为null时让位给frontmatter(self):
        # null 语义与其余字段一致：不参与，而不是「档案里有这个键就算数」
        assert T.resolve_theme(None, {'theme': None}, {'theme': 'paper'}) == 'paper'


class TestBuildHTMLWithStyle:
    ARGS = dict(title='标题', meta_line='全文100字｜阅读需1分钟',
                blocks=[('p', '正文')], theme_name='clean')

    def test_不传theme_over时与原来逐字一致(self):
        # 这条是本次最容易翻车处：不带 --style 的行为必须一字不变
        assert T.build_html(**self.ARGS) == T.build_html(**self.ARGS, theme_over=None)
        assert T.build_html(**self.ARGS) == T.build_html(**self.ARGS, theme_over={})

    def test_覆盖的键进了CSS(self):
        doc = T.build_html(**self.ARGS, theme_over={'accent': '#2F6FEB', 'indent': '2em'})
        assert '#2F6FEB' in doc and 'text-indent:2em' in doc
        assert T.THEMES['clean']['accent'] not in doc      # 主题原值已被顶掉

    def test_未覆盖的键仍走主题默认(self):
        doc = T.build_html(**self.ARGS, theme_over={'accent': '#2F6FEB'})
        assert T.THEMES['clean']['bg'] in doc
        assert f"font-size:{T.THEMES['clean']['body_size']}px" in doc

    def test_覆盖不污染THEMES本体(self):
        # dict(THEMES[t]) 拷了一份才 update；直接改会串到同进程后续每一次渲染
        T.build_html(**self.ARGS, theme_over={'bg': '#000000'})
        assert T.THEMES['clean']['bg'] == '#ffffff'


class TestStyleCLI:
    """整条 CLI 串起来跑（--html-only，不需要 playwright）。"""

    MD = '---\ntitle: 测试标题\ntheme: clean\n---\n\n一段正文。\n'

    def _run(self, tmp_path, *extra):
        md = tmp_path / 'body.md'
        md.write_text(self.MD, encoding='utf-8')
        r = subprocess.run([sys.executable, str(SCRIPT), '--md', str(md),
                            '--out', str(tmp_path / 'out'), '--html-only', *extra],
                           capture_output=True, text=True)
        return r, json.loads(r.stdout)

    def test_档案生效且theme来自档案(self, tmp_path):
        f = _style_file(tmp_path, {'theme': 'paper', 'accent': '#2F6FEB', 'indent': True,
                                   'bg': None, 'font': 'sans'})
        r, d = self._run(tmp_path, '--style', str(f))
        assert r.returncode == 0 and d['ok'] is True
        assert d['theme'] == 'paper' and d['style'] == str(f)
        html = Path(d['html']).read_text(encoding='utf-8')
        assert '#2F6FEB' in html and 'text-indent:2em' in html
        assert T.THEMES['paper']['bg'] in html               # bg=null → 仍用 paper 底色
        assert f'font-family:{T.FONT_SANS}' in html          # font=sans 顶掉 paper 的衬线

    def test_命令行theme压过档案(self, tmp_path):
        f = _style_file(tmp_path, {'theme': 'paper'})
        _, d = self._run(tmp_path, '--style', str(f), '--theme', 'clean')
        assert d['theme'] == 'clean'

    def test_不传style时与没这个功能之前一致(self, tmp_path):
        _, d = self._run(tmp_path)
        assert d['ok'] is True and d['theme'] == 'clean' and d['style'] is None
        html = Path(d['html']).read_text(encoding='utf-8')
        assert html == T.build_html('测试标题', '全文5字｜阅读需1分钟',
                                    T.parse_blocks('一段正文。'), 'clean', '')

    def test_档案坏了报人话而不是抛栈(self, tmp_path):
        bad = tmp_path / 'bad.json'
        bad.write_text('{"kind": "carousel"}', encoding='utf-8')
        r, d = self._run(tmp_path, '--style', str(bad))
        assert r.returncode == 1 and d['ok'] is False
        assert 'typeset' in d['error'] and d['how_to_fix']
