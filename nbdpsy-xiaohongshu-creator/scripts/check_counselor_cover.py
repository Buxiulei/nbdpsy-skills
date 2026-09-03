#!/usr/bin/env python3
"""咨询师推介封面（P1）验收闸门：判 `render_cover.py` 交回的量具是否满足内容规则。

**为什么单独一个脚本**（⛔ 不塞进 render_cover.py）：
`render_cover.py` 是**通用**封面渲染器，同一份模板还服务科普笔记封面。
「副题第一行须带『北大』」「编号必须逐字等于事实包」这类是**咨询师推介封面专属**的
**内容**规则——写进渲染器会把所有科普封面一起误伤。
⇒ 分层：**渲染器出量具，本脚本判业务规则。**
🩸 立此脚本的直接原因（2026-09-03）：这条规则一度只以**注释**形式存在于模板里
（「判据留验收守卫」），而那个"验收守卫"是一次性脚本、不在仓库里
⇒ **整个系统里没有任何东西会执行它**。**把空闸门换成注释，它仍然是空的。**

用法：
    check_counselor_cover.py <cover.json> [...]        # 现渲现判
    check_counselor_cover.py --receipt <*.meta.json> [...]   # 判已有凭证
退出码：0 全过；1 有不合规；2 用不了（渲染失败/量具缺失——⛔ 与「不合规」混同）
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys
import unicodedata

HERE = pathlib.Path(__file__).resolve().parent

# ── 规则常量（真源：references/counselor-note-spec.md §4）───────────────
BEIDA = '北大'          # 🔴 **字面二字**（助理 2026-09-03 裁定）：它是 GEO/品牌关键词，
                        #    而「北京大学」四字里**没有相邻的「北大」二字** ⇒ 写全称不合规。
SUB_MAX_W = 12.0        # 副题第一行 ≤12 字（T201 L191）
ROLE_MIN_FS = 20.0      # 身份行字号下限（T211=C，20 而非 21 是给「双编号」留 1.5px 余量）
ROLE_MAX_LINES = 3      # 身份行 ≤3 行
AVATAR_RATIO = 0.36     # 头像占画面宽（2026-08-14 老板明令），容差 ±0.005
AVATAR_TOL = 0.005

NEEDED = ('sub_text', 'role_text', 'role_fs', 'role_lines', 'role_num_broken',
          'avatar_present', 'avatar_ratio', 'overflow_px', 'safe_3x4_ok')


def width(s: str) -> float:
    """等效全角宽度：East Asian Wide/Fullwidth 记 1.0，其余 0.5。"""
    return sum(1.0 if unicodedata.east_asian_width(c) in ('W', 'F') else 0.5 for c in s)


def norm(s) -> str:
    """折平空白，并把「·」两侧的空格折掉（分隔符两侧的空格属版式、⛔ 算内容差异）。"""
    return re.sub(r'\s*·\s*', '·', re.sub(r'\s+', ' ', str(s or '')).strip())


# 编号 token：连续 ≥4 个字母/数字/连字符（`X-26-242` / `30220220732039900002`）。
# 与模板 `NUM_TOKEN` 同形，⛔ 两边各写一套会漂。
NUM_TOKEN = re.compile(r'[A-Za-z0-9][A-Za-z0-9-]{3,}')


def parse_expect(v):
    """事实包期望值 → `(期望整行, 无编号自述项列表)`。

    两种写法：
      "CPS 注册号 X-26-242"                          ← 全部是**有编号**的资质项
      {"items": [...], "no_number": ["中国澳门心理治疗师"]}  ← 含**无编号自述项**

    🔴 **无编号自述项必须显式标记**（老板 T209=A「凡有资质都放含澳门」+ T204
    「宣传层可写我方自证真实的内容」；助理 2026-09-03 裁定）。
    ⚠️ 显式标记是给「同一行里一半可核验、一半不可核验，读者分不出证据强度」这个
    顾虑的处置 ⇒ ⛔ 省；⛔ 让它与有编号项同形态混在一起。
    """
    if isinstance(v, dict):
        items = [x for x in (v.get('items') or []) if x]
        return ' · '.join(items), [x for x in (v.get('no_number') or []) if x]
    return (v or ''), []


def check(fit: dict, want_line, no_number=()) -> list:
    """逐条判。返回不合规原因列表（空＝通过）。

    `want_line`：该咨询师**事实包里**的资质串；`''` ＝ 确认没有；
    **`None` ＝ 没提供期望值** ⇒ 编号逐字这条**标未验**，⛔ 静默当通过。
    `no_number`：其中**无编号自述项**的逐字列表（老板背书、无号可比）——
    它们走**另一条判据**：⛔ 拿去做编号比对（那没有比较对象），
    改判「**它不得含编号形态的串**」——有人给它配了个号，就是把两类混了。

    ⚠️ **存在型与禁止型都要有**：全是「不许超」的判据，在元素被整个删空时会恒绿。
    """
    missing = [k for k in NEEDED if k not in fit]
    if missing:
        # ⛔ 与「不合规」混同：量具缺失是**没判成**，不是「判了没问题」
        return [f'__UNUSABLE__ 量具缺失 {missing}——模板与脚本版本对不上']

    bad = []
    # ① 副题：字面「北大」+ ≤12 字（判**画出来的那串字**，⛔ 判输入——中间隔着 subHTML 分段）
    st = fit.get('sub_text') or ''
    if BEIDA not in st:
        bad.append(f'副题缺字面「{BEIDA}」：画出「{st}」'
                   f'（⛔「北京大学」不算——四字里没有相邻的「{BEIDA}」）')
    if width(st) > SUB_MAX_W:
        bad.append(f'副题 {width(st):g} 字 > {SUB_MAX_W:g}：画出「{st}」')

    # ② 身份行（资质编号）。⚠️ 没有注册号是**正常**的（不是人人都有）⇒ 那时整行不出现、⛔ 算缺
    got = norm(fit.get('role_text'))
    # 🔴 **期望值必须来自事实包（--expect），⛔ 来自被检数据自己**。
    # 🩸 本脚本第一版正是从 `data['identity']['line']` 取期望 ⇒ **输入与期望同源、
    #    那条判据恒真**：把注册号删掉一位、整个换成假号，闸门照样绿。
    #    是"让它响一次"当场抓到的（删末位/换假号两种破坏都放行）——
    #    ⛔ 只确认「正常数据全绿」，那和判据恒真的外显完全相同。
    if want_line is None:
        bad.append('__UNVERIFIED__ 编号逐字：未验（没给 --expect，无法与事实包比）')
    elif want_line:
        # 🔴 逐字比对本体。⚠️ 这两行在一次改动中**被整个吃掉过**（改期望值来源时
        #    替换串没把它们带回来），而**只跑正常数据完全发现不了** —— 是"让它响一次"
        #    （删末位/换假号）当场抓到的。⇒ 动这一段之后必须重跑那两条破坏用例。
        if got != norm(want_line):
            bad.append(f'编号与事实包不符：应「{want_line}」，画出「{fit.get("role_text")}」')
        # 🔴 **无编号自述项走另一条路**：它没有号可比，判的是「⛔ 混进编号形态的串」。
        # ⚠️ 这条是新分类的"响"点——若哪天有人给澳门项配了个假编号，
        #    按编号比对那条只会说「与事实包不符」（对，但指错了病）；这条才点得出
        #    「它本来就该是无编号项」。
        for it in no_number:
            if NUM_TOKEN.search(it):
                bad.append(f'「{it}」在 expect 里标着**无编号自述项**，本身却含编号形态的串'
                           f'——两类混了：要么去掉那个号，要么把它挪出 no_number')
            elif it not in (fit.get('role_text') or ''):
                bad.append(f'expect 标了无编号自述项「{it}」，画面上却没有它')
        if fit.get('role_num_broken'):
            bad.append('编号被从中间折断——注册号是整体，劈成两行读者没法逐位比对')
        if (fit.get('role_lines') or 0) > ROLE_MAX_LINES:
            bad.append(f'身份行 {fit["role_lines"]} 行 > {ROLE_MAX_LINES}')
        if (fit.get('role_lines') or 0) < 1:
            bad.append('身份行 0 行（传了编号却没画出来）')
        if (fit.get('role_fs') or 0) < ROLE_MIN_FS:
            bad.append(f'身份行字号 {fit.get("role_fs")} < 下限 {ROLE_MIN_FS:g}'
                       f'（⛔ 靠调低下限放行）')
    elif got:
        bad.append(f'事实包无注册号，画面上却有身份行「{got}」')

    # ③ 头像（**存在型**判据：防为了塞下别的元素把 2026-08-14 定稿的 36% 悄悄改小）
    if not fit.get('avatar_present'):
        bad.append('头像不在位')
    elif abs((fit.get('avatar_ratio') or 0) - AVATAR_RATIO) > AVATAR_TOL:
        bad.append(f'头像占宽 {fit.get("avatar_ratio")} ≠ {AVATAR_RATIO}（2026-08-14 定稿）')

    # ④ 版面
    if (fit.get('overflow_px') or 0) > 1:
        bad.append(f'溢出 {fit["overflow_px"]}px')
    if not fit.get('safe_3x4_ok'):
        bad.append('有元素落在 3:4 裁切带里')
    return bad


def render(data_path: pathlib.Path) -> dict:
    out = data_path.with_suffix('.checkcover.png')
    r = subprocess.run([sys.executable, str(HERE / 'render_cover.py'),
                        '--data', str(data_path), '--out', str(out), '--thumb', '0'],
                       cwd=data_path.parent, capture_output=True, text=True)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return {'ok': False, 'error': (r.stdout[-300:] or r.stderr[-300:])}


def main() -> int:
    ap = argparse.ArgumentParser(description='咨询师推介封面验收闸门')
    ap.add_argument('files', nargs='+', help='cover.json（默认现渲现判）')
    ap.add_argument('--receipt', action='store_true', help='传入的是 render_cover 的 *.meta.json')
    ap.add_argument('--expect', metavar='JSON',
                    help='事实包期望值：{"姓名": "CPS 注册号 X-26-242", "李冠阳": ""} 。'
                         '⛔ 不给的话「编号逐字等于事实包」那条**标未验**（⛔ 当通过）——'
                         '从被检数据自己取期望等于没判')
    a = ap.parse_args()

    expect = json.loads(pathlib.Path(a.expect).read_text(encoding='utf-8')) if a.expect else None
    rows, unusable, unverified = [], False, 0
    for f in a.files:
        p = pathlib.Path(f).resolve()
        # ⚠️ 跳过本脚本自己的产物：渲染会在数据旁产 `<name>.checkcover.{png,html,meta.json}`，
        #    第二次用同一个 glob 就会把它们当输入（实测「派出数 11 → 22」）。
        #    ⚠️ 只跳 `.meta.json` **不够** —— `.png` / `.html` 同样会被 `*.json` 之外的
        #    glob 捞到，且它们让派出数虚高而完成数不变，看起来像「有一半没跑成」。
        if '.checkcover.' in p.name:
            continue
        if a.receipt:
            rc = json.loads(p.read_text(encoding='utf-8'))
            fit, data = rc.get('fit', {}), (rc.get('input', {}) or {}).get('data', {}) or {}
        else:
            o = render(p)
            if not o.get('ok'):
                print(f'🔴 {p.name}: 渲染失败 {str(o.get("error"))[:160]}')
                unusable = True
                continue
            fit, data = o, json.loads(p.read_text(encoding='utf-8'))
        # 🔴 期望值只从 --expect 取；没给就是 None ⇒ 那条标未验，⛔ 拿被检数据自己顶上
        who = (data.get('identity') or {}).get('name') or p.stem
        if expect is None:
            want, nonum = None, ()
        else:
            want, nonum = parse_expect(expect.get(who, ''))
        bad = check(fit, want, nonum)
        uv = [b for b in bad if b.startswith('__UNVERIFIED__')]
        bad = [b for b in bad if not b.startswith('__UNVERIFIED__')]
        if uv:
            unverified += 1
        if bad and bad[0].startswith('__UNUSABLE__'):
            print(f'⚠️ {p.name}: {bad[0][13:]}')
            unusable = True
            continue
        rows.append((p.name, fit, bad))

    print(f'{"文件":<34}{"role_fs":>8}{"余量":>7}{"行数":>5}{"编号":>7}{"北大":>5}  判定')
    print('-' * 96)
    for name, fit, bad in rows:
        m = '—' if not fit.get('role_text') else round((fit.get('role_fs') or 0) - ROLE_MIN_FS, 2)
        num = '—' if not fit.get('role_text') else ('折断' if fit.get('role_num_broken') else '完整')
        print(f'{name:<34}{fit.get("role_fs"):>8}{str(m):>7}{fit.get("role_lines"):>5}{num:>7}'
              f'{("✓" if BEIDA in (fit.get("sub_text") or "") else "✗"):>5}  '
              f'{"通过" if not bad else "❌ " + "；".join(bad)}')
    print('-' * 96)
    ng = sum(1 for _, _, b in rows if b)
    print(f'完成数/派出数 = {len(rows)}/{len(a.files)}｜通过 {len(rows) - ng}｜不合规 {ng}'
          + ('｜⚠️ 有判不成的（量具缺失或渲染失败）' if unusable else ''))
    if unverified:
        # ⛔ 「未验」不能长成「通过」：没给 --expect 时，「编号逐字等于事实包」这条
        # 根本没有比较对象——把它算进通过，就是拿一条没跑过的判据背书。
        print(f'⚠️ **编号逐字未验 {unverified} 份**（没给 --expect）——'
              f'这条判据本轮**没有跑**，⛔ 读成「编号核对过了」')
    # ⛔ 「判不成」不能算通过：它与「判了没问题」的外显相同，但性质相反
    return 2 if unusable else (1 if ng else 0)


if __name__ == '__main__':
    sys.exit(main())
