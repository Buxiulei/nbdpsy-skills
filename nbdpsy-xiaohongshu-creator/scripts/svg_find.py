#!/usr/bin/env python3
"""在本地 SVG 集合库里检索图标，并把选中的图标取成可直接内联的 SVG。

为什么有这个脚本（2026-08-17 立）：手工件只有 66 个，挑图老是「库里没有」。
现在 `assets/svg-library/collections/` 下按集合存了 6 份 `icons.json`（3 万多枚），
但**不能靠人眼翻 JSON**——这个脚本就是那个检索口。

⛔ **默认不联网**：检索、取图、落地全在本地 JSON 上跑。零命中时只提示「可以去
iconify.design 现搜」，**联网兜底没有实现**，⛔ 别以为 --online 存在（它不存在）。

用法:
    svg_find.py 咖啡杯                       # 中文检索（人读表格）
    svg_find.py coffee --json                # 英文检索，出 JSON 给排版 agent 用
    svg_find.py 心 --limit 20 --family all   # 放宽条数与族别
    svg_find.py --emit lucide:coffee         # 取图：打印可直接内联的完整 SVG
    svg_find.py --emit iconoir:coffee --stroke-width 2      # 跨族取图，线宽归一到 2
    svg_find.py --emit tabler:mood-sad --install --note "低落"   # 落地进素材库
    svg_find.py --list-collections           # 集合台账速查

**每条结果都打印许可证**：`LICENSES.md` 对集合只记到集合一级（38239 行台账没人维护得动），
所以「逐条许可证」这件事挪到了用的时候——检索输出里那一列就是免责依据的现场版。

族别标记（house style = 描边 · stroke-width 2 · 24 网格，跟 66 个手工件一致）:
    ★同族      描边 2/24，直接用
    ◇近亲      描边但线宽不是 2（iconoir 是 1.5）——取图时加 --stroke-width 2 归一
    ⚠️异族     纯填充（ph / mdi / heroicons 实心版），与静物封面的线条风格不同

落地（--install）是**扩库能被 render_cover.py 认出来的唯一通路**:
    render_cover.py 的闸门是 `SVG_LIB.glob('*.svg')`（平铺、不递归），且**拒收带
    `lucide:` 前缀的名字**。collections/ 在子目录里，闸门看不见也就管不着——闸门原样有效。
    `--install` 把图标写成 `svg-library/<集合前缀>-<图标名>.svg`，从此它就是一个正常的
    库内文件，闸门照常认；⛔ 没落地的图标 render_cover 一律报红，这是故意的。

退出码:
    0  有命中 / 取图成功
    1  零命中（含「中文缺词」——⛔ 不静默返回空，会明说缺的是映射不是图标）
    2  参数或环境错误（集合目录缺失、--emit 的名字不存在、集合未入库）
"""
import argparse
import json
import pathlib
import re
import sys
import unicodedata
from datetime import date

HERE = pathlib.Path(__file__).resolve().parent
SVG_LIB = HERE.parent / 'assets' / 'svg-library'
COLL_DIR = SVG_LIB / 'collections'

# house style：66 个手工件的形状——描边、线宽 2、24×24 网格。族别判定全部相对它。
HOUSE_STROKE_WIDTH = 2.0
HOUSE_GRID = 24

FAM_SAME, FAM_KIN, FAM_ALIEN = 'same', 'kin', 'alien'
FAM_LABEL = {FAM_SAME: '★同族', FAM_KIN: '◇近亲', FAM_ALIEN: '⚠️异族'}

# 集合台账。`bundled=False` 的集合**故意没入库**，原因写在 reason 里，也写在 LICENSES.md。
# ⛔ 顺序有意义：检索排序按这个顺序做同分优先级（越靠前越贴 house style）。
COLLECTIONS = [
    {'prefix': 'lucide', 'name': 'Lucide', 'spdx': 'ISC', 'bundled': True},
    {'prefix': 'tabler', 'name': 'Tabler Icons', 'spdx': 'MIT', 'bundled': True},
    {'prefix': 'iconoir', 'name': 'Iconoir', 'spdx': 'MIT', 'bundled': True},
    {'prefix': 'heroicons', 'name': 'HeroIcons', 'spdx': 'MIT', 'bundled': True},
    {'prefix': 'ph', 'name': 'Phosphor', 'spdx': 'MIT', 'bundled': True},
    {'prefix': 'mdi', 'name': 'Material Design Icons', 'spdx': 'Apache-2.0', 'bundled': True},
    {'prefix': 'ri', 'name': 'Remix Icon', 'spdx': 'RemixIcon-1.0', 'bundled': False,
     'reason': 'Remix Icon 2026-01 从 Apache-2.0 改成自订 Remix Icon License v1.0，'
               '§3.2 禁止「distribute a competing icon library or icon set」，'
               '与本目录「打包成素材库随公开仓库分发」的形态冲突——'
               '按本库对 unDraw 的同一条红线处理，**不入库**。'
               '许可证全文留档：licenses/ri-RemixIconLicense-v1.0-NOT-BUNDLED.txt',
     'add_cmd': 'npm i @iconify-json/ri && cp node_modules/@iconify-json/ri/{icons,info}.json '
                'assets/svg-library/collections/ri/'},
]
COLL_BY_PREFIX = {c['prefix']: c for c in COLLECTIONS}
# `local` = 66 个手工件里集合中没有的那几个（自绘）。排最前：手工件带 NBDpsy 文件头，优先用。
COLL_ORDER = {'local': -1}
COLL_ORDER.update({c['prefix']: i for i, c in enumerate(COLLECTIONS)})

# ────────── 中文关键词映射 ──────────
# 集合里的图标名全是英文，中文查询必须先落到英文词上。收录的是心理科普选图的高频词
# ＋日常物件；⛔ 缺词时明说「没有中文映射」，绝不静默返回空——本仓判据：「没查到」≠「没有」。
ZH_KEYWORDS = {
    # 情绪与心理
    '心': ['heart'], '心形': ['heart'], '心碎': ['heart-crack', 'heart-broken'],
    '破碎': ['crack', 'broken'], '大脑': ['brain'], '头脑': ['brain', 'head'],
    '情绪': ['mood', 'emotion', 'smile'], '焦虑': ['mood-nervous', 'alert', 'nervous'],
    '抑郁': ['mood-sad', 'sad'], '压力': ['gauge', 'pressure', 'stress'],
    '疲惫': ['battery-low', 'tired'], '耗竭': ['battery-low', 'battery-empty'],
    '倦怠': ['battery-low', 'bed'], '愤怒': ['mood-angry', 'angry'],
    '生气': ['mood-angry', 'angry'], '悲伤': ['mood-sad', 'sad'],
    '难过': ['mood-sad', 'sad'], '哭': ['mood-cry', 'sad'], '眼泪': ['droplet', 'droplets'],
    '微笑': ['mood-smile', 'smile'], '笑': ['mood-happy', 'smile'],
    '开心': ['mood-happy', 'smile'], '快乐': ['mood-happy', 'smile'],
    '害怕': ['mood-scared', 'alert'], '恐惧': ['alert-triangle', 'scared'],
    '惊讶': ['mood-surprised', 'alert'], '平静': ['peace', 'yoga'],
    '放松': ['yoga', 'beach', 'sofa'], '冥想': ['yoga', 'meditation'],
    '呼吸': ['lungs', 'wind'], '睡眠': ['bed', 'moon', 'zzz'],
    '失眠': ['moon', 'bed', 'alarm-clock'], '做梦': ['cloud', 'moon'],
    '噩梦': ['ghost', 'moon'], '记忆': ['brain', 'bookmark'],
    '遗忘': ['eraser', 'trash'], '创伤': ['bandage', 'heart-crack'],
    '疗愈': ['bandage', 'heart-plus', 'first-aid'], '治愈': ['bandage', 'heart-plus'],
    '康复': ['trending-up', 'bandage'], '成长': ['sprout', 'plant', 'trending-up'],
    '觉察': ['eye', 'mirror'], '自我': ['user', 'mirror'], '内心': ['heart', 'brain'],
    '感受': ['heart', 'hand'], '共情': ['heart-handshake', 'hand-heart'],
    '同理': ['heart-handshake', 'hand-heart'], '陪伴': ['users', 'friends', 'heart-handshake'],
    '孤独': ['user', 'user-off'], '孤单': ['user', 'user-off'],
    '支持': ['hand-helping', 'lifebuoy', 'life-buoy'], '安慰': ['hand-heart', 'heart-handshake'],
    '拥抱': ['heart-handshake', 'users-round', 'friends'], '联结': ['link', 'link-2'],
    '关系': ['users', 'link', 'heart-handshake'], '亲密': ['heart', 'users'],
    '边界': ['shield', 'shield-check', 'fence'], '安全': ['shield-check', 'lock'],
    '信任': ['handshake', 'shield-check'], '依恋': ['heart-handshake', 'link'],
    '自尊': ['award', 'crown'], '自信': ['award', 'trophy'],
    '羞耻': ['mood-sad', 'eye-off'], '内疚': ['mood-sad', 'scale'],
    '愈合': ['bandage', 'heart-plus'], '倾诉': ['message-circle', 'messages'],
    '倾听': ['ear', 'headphones'], '沉默': ['message-off', 'volume-off'],
    # 身体与健康
    '身体': ['body', 'user'], '心跳': ['heart-pulse', 'heartbeat', 'activity'],
    '脉搏': ['activity', 'heart-pulse'], '医生': ['stethoscope', 'user-heart'],
    '医院': ['building-hospital', 'hospital'], '药': ['pill', 'medicine'],
    '药丸': ['pill'], '针': ['vaccine', 'needle'], '创可贴': ['bandage'],
    '绷带': ['bandage'], '急救': ['first-aid', 'lifebuoy', 'life-buoy'],
    '健康': ['heart-pulse', 'activity'], '运动': ['run', 'activity'],
    '跑步': ['run', 'running'], '瑜伽': ['yoga'], '睡觉': ['bed', 'zzz'],
    '牙齿': ['dental', 'tooth'], '眼睛': ['eye'], '耳朵': ['ear'],
    '鼻子': ['smell', 'face'], '嘴': ['mouth', 'lips'], '手': ['hand'], '脚': ['footprints', 'foot'],
    '骨头': ['bone'], '肺': ['lungs'], '胃': ['stomach'], '血': ['droplet', 'blood'],
    '神经': ['brain', 'nerve'], '基因': ['dna'], '细胞': ['cell', 'bacteria'],
    # 自然与天气
    '太阳': ['sun'], '月亮': ['moon'], '星星': ['star'], '云': ['cloud'],
    '雨': ['cloud-rain', 'rain'], '雪': ['snowflake', 'cloud-snow'], '风': ['wind'],
    '雷': ['cloud-bolt', 'thunder'], '闪电': ['zap', 'bolt'], '彩虹': ['rainbow'],
    '天空': ['cloud', 'sun'], '山': ['mountain'], '海': ['waves', 'beach'],
    '水': ['droplet', 'water'], '火': ['flame', 'fire'], '树': ['tree', 'tree-deciduous'],
    '叶子': ['leaf'], '花': ['flower'], '草': ['plant', 'grass'], '种子': ['seed', 'sprout'],
    '幼苗': ['sprout', 'seedling'], '植物': ['plant', 'sprout'], '森林': ['trees', 'forest'],
    '沙漠': ['cactus', 'desert'], '河': ['river', 'waves'], '湖': ['waves', 'lake'],
    '波浪': ['waves', 'wave'], '石头': ['rock', 'stone'], '土': ['shovel', 'soil'],
    '季节': ['leaf', 'snowflake'], '春天': ['flower', 'sprout'], '夏天': ['sun', 'beach'],
    '秋天': ['leaf', 'wind'], '冬天': ['snowflake'], '日出': ['sunrise', 'sun'],
    '日落': ['sunset', 'sun'], '地球': ['globe', 'world', 'earth'],
    # 日常物件
    '咖啡': ['coffee', 'cup'], '咖啡杯': ['coffee', 'cup'], '茶': ['teapot', 'cup'],
    '杯子': ['cup', 'glass', 'mug'], '水杯': ['cup-soda', 'glass-water'],
    '书': ['book'], '笔记本': ['notebook', 'note'], '笔': ['pen', 'pencil'],
    '铅笔': ['pencil'], '纸': ['file', 'paper'], '信': ['mail', 'letter'],
    '信封': ['mail', 'envelope'], '邮件': ['mail'], '电话': ['phone'],
    '手机': ['device-mobile', 'smartphone'], '电脑': ['device-laptop', 'laptop'],
    '键盘': ['keyboard'], '鼠标': ['mouse'], '相机': ['camera'], '照片': ['photo', 'image'],
    '音乐': ['music'], '耳机': ['headphones'], '麦克风': ['microphone', 'mic'],
    '音响': ['speaker', 'volume'], '电视': ['device-tv', 'tv'], '收音机': ['radio'],
    '钟': ['clock'], '表': ['clock', 'watch'], '闹钟': ['alarm-clock', 'alarm'],
    '沙漏': ['hourglass'], '日历': ['calendar'], '灯': ['lamp', 'bulb'],
    '灯泡': ['bulb', 'lightbulb'], '蜡烛': ['candle'], '手电': ['flashlight', 'torch'],
    '钥匙': ['key'], '锁': ['lock'], '门': ['door'], '窗': ['window'],
    '桌子': ['table', 'desk'], '椅子': ['chair', 'armchair'], '沙发': ['sofa'],
    '床': ['bed'], '镜子': ['mirror'], '伞': ['umbrella'], '包': ['bag', 'backpack'],
    '钱包': ['wallet'], '礼物': ['gift'], '盒子': ['box', 'package'],
    '袋子': ['bag'], '购物车': ['shopping-cart', 'cart'], '钱': ['coin', 'cash', 'money'],
    '衣服': ['shirt', 'hanger'], '鞋': ['shoe'], '帽子': ['hat', 'cap'],
    '眼镜': ['glasses', 'eyeglass'], '垃圾桶': ['trash'], '扫把': ['broom'],
    # 方向与路径
    '路': ['road', 'route'], '道路': ['road', 'route'], '地图': ['map'],
    '指南针': ['compass'], '箭头': ['arrow-right', 'arrow'], '方向': ['compass', 'direction'],
    '目标': ['target', 'goal'], '靶心': ['target'], '旗帜': ['flag'],
    '里程碑': ['milestone', 'flag'], '路标': ['signpost', 'sign'], '脚印': ['footprints'],
    '台阶': ['stairs', 'steps'], '楼梯': ['stairs'], '梯子': ['ladder'],
    '桥': ['bridge'], '隧道': ['tunnel'], '十字路口': ['crossroad', 'directions'],
    '起点': ['flag', 'play'], '终点': ['flag-checkered', 'flag'], '位置': ['map-pin', 'location'],
    '迷路': ['map-off', 'compass-off'], '循环': ['refresh', 'rotate', 'repeat'],
    # 工具与抽象
    '工具': ['tool', 'wrench'], '锤子': ['hammer'], '扳手': ['wrench'],
    '螺丝刀': ['screwdriver'], '剪刀': ['scissors'], '尺子': ['ruler'],
    '天平': ['scale', 'balance'], '秤': ['scale', 'weight'], '拼图': ['puzzle'],
    '齿轮': ['settings', 'gear', 'cog'], '设置': ['settings', 'adjustments'],
    '搜索': ['search', 'zoom'], '放大镜': ['search', 'zoom-in'], '过滤': ['filter'],
    '排序': ['sort', 'arrows-sort'], '链接': ['link'], '锚': ['anchor'],
    '盾牌': ['shield'], '保护': ['shield-check', 'shield'], '警告': ['alert-triangle', 'warning'],
    '危险': ['alert-octagon', 'danger'], '禁止': ['ban', 'forbid'],
    '勾': ['check'], '叉': ['x', 'cross'], '加': ['plus'], '减': ['minus'],
    '问号': ['help', 'question-mark'], '感叹号': ['alert-circle', 'exclamation'],
    '信息': ['info-circle', 'info'], '帮助': ['help', 'lifebuoy', 'life-buoy'],
    '救生圈': ['lifebuoy', 'life-buoy'], '灭火器': ['fire-extinguisher'],
    '电池': ['battery'], '充电': ['battery-charging', 'bolt'], '插头': ['plug'],
    '开关': ['toggle', 'switch'], '刷新': ['refresh'], '撤销': ['arrow-back-up', 'undo'],
    '重做': ['arrow-forward-up', 'redo'], '骨牌': ['dominos', 'domino'],
    '钟摆': ['pendulum', 'clock'], '绳子': ['rope'], '结': ['knot', 'rope'],
    # 人物与社交
    '人': ['user', 'person'], '用户': ['user'], '两个人': ['users', 'friends'],
    '一群人': ['users-group', 'users'], '团队': ['users-group', 'team'],
    '家庭': ['home', 'users'], '朋友': ['friends', 'users'], '握手': ['handshake'],
    '说话': ['message-circle', 'speakerphone'], '对话': ['messages', 'message-circle'],
    '气泡': ['message-circle', 'bubble'], '聊天': ['message-circle', 'messages'],
    '消息': ['message', 'mail'], '评论': ['message-dots', 'comment'],
    '分享': ['share'], '点赞': ['thumb-up', 'heart'], '收藏': ['bookmark', 'star'],
    '关注': ['user-plus', 'eye'], '群组': ['users-group'], '会议': ['users', 'presentation'],
    '演讲': ['presentation', 'speakerphone'], '老师': ['school', 'presentation'],
    '学生': ['school', 'backpack'], '孩子': ['baby-carriage', 'mood-kid'],
    '婴儿': ['baby-carriage', 'baby'], '老人': ['old', 'user'],
    '男人': ['man', 'gender-male'], '女人': ['woman', 'gender-female'],
    '头像': ['user-circle', 'avatar'], '家': ['home', 'house'],
    # 数据与图表
    '图表': ['chart'], '柱状图': ['chart-bar'], '折线图': ['chart-line'],
    '饼图': ['chart-pie'], '数据': ['database', 'chart'], '统计': ['chart-bar', 'stats'],
    '趋势': ['trending-up', 'chart-line'], '上升': ['trending-up', 'arrow-up'],
    '下降': ['trending-down', 'arrow-down'], '增长': ['trending-up', 'growth'],
    '表格': ['table'], '列表': ['list'], '文件': ['file'], '文件夹': ['folder'],
    '数据库': ['database'], '云端': ['cloud'], '服务器': ['server'],
    '下载': ['download'], '上传': ['upload'], '同步': ['refresh', 'sync'],
    '打印': ['printer'], '二维码': ['qrcode'], '日程': ['calendar', 'calendar-event'],
    # 食物
    '食物': ['food', 'meal'], '水果': ['apple', 'fruit'], '苹果': ['apple'],
    '香蕉': ['banana'], '面包': ['bread'], '蛋糕': ['cake'], '饼干': ['cookie'],
    '披萨': ['pizza'], '冰淇淋': ['ice-cream'], '糖果': ['candy'], '牛奶': ['milk'],
    '鸡蛋': ['egg'], '米饭': ['bowl', 'rice'], '面条': ['noodles', 'bowl'],
    '酒': ['wine', 'beer'], '勺子': ['spoon'], '叉子': ['fork'], '碗': ['bowl'],
    # 动物
    '动物': ['paw', 'cat', 'dog'], '猫': ['cat'], '狗': ['dog'], '鸟': ['bird'],
    '鱼': ['fish'], '蝴蝶': ['butterfly'], '蜜蜂': ['bee'], '兔子': ['rabbit'],
    '熊': ['bear'], '狐狸': ['fox'], '马': ['horse'], '象': ['elephant'],
    '蛇': ['snake'], '龟': ['turtle'], '鲸': ['dolphin', 'fish'], '爪印': ['paw'],
    # 交通
    '车': ['car'], '汽车': ['car'], '自行车': ['bike', 'bicycle'],
    '摩托车': ['motorbike', 'motorcycle'], '公交': ['bus'], '火车': ['train'],
    '飞机': ['plane'], '船': ['ship', 'boat'], '火箭': ['rocket'],
    '地铁': ['subway', 'train'], '出租车': ['taxi', 'car'], '轮椅': ['wheelchair'],
    # 时间与流程
    '时间': ['clock', 'hourglass'], '等待': ['hourglass', 'clock'],
    '开始': ['play', 'flag'], '结束': ['stop', 'flag-checkered'], '暂停': ['pause'],
    '进度': ['progress', 'loader'], '完成': ['circle-check', 'check'],
    '步骤': ['stairs', 'list-numbers'], '计划': ['calendar', 'checklist'],
    '清单': ['checklist', 'list-check'], '笔记': ['note', 'notebook'],
    '打卡': ['calendar-check', 'checkbox'], '提醒': ['bell', 'alarm'],
    '铃铛': ['bell'], '沙钟': ['hourglass'], '倒计时': ['clock-down', 'hourglass'],
}

# ────────── 加载 ──────────


def load_collection(prefix: str):
    """读一个集合的 icons.json + info.json。⛔ 文件缺席不静默——返回 None 由调用方报。"""
    d = COLL_DIR / prefix
    ip, np_ = d / 'icons.json', d / 'info.json'
    if not ip.exists() or not np_.exists():
        return None
    icons = json.loads(ip.read_text(encoding='utf-8'))
    info = json.loads(np_.read_text(encoding='utf-8'))
    return {'icons': icons, 'info': info}


def load_all():
    """加载全部**已入库**集合。返回 (数据, 缺席集合名单)。"""
    data, missing = {}, []
    for c in COLLECTIONS:
        if not c['bundled']:
            continue
        got = load_collection(c['prefix'])
        if got is None:
            missing.append(c['prefix'])
        else:
            data[c['prefix']] = got
    return data, missing


def license_of(prefix: str, info: dict) -> str:
    """许可证短名。**以 LICENSES.md 台账为准**，⛔ 不直接采信 info.json——
    实测 mdi 与 ri 的 info.json 都写着 Apache-2.0，而上游 2026-01 已换成别的证。"""
    c = COLL_BY_PREFIX.get(prefix)
    if c:
        return c['spdx']
    return str((info.get('license') or {}).get('spdx') or '?')


# ────────── 族别与线宽 ──────────

_SW_RE = re.compile(r'stroke-width="([^"]+)"')


def classify(body: str, grid_w: int):
    """判族别与线宽。返回 (family, 主线宽 或 None, 是否描边)。

    ⚠️ 按图标逐个判，⛔ 不按集合判——tabler 里有 1088 个纯填充图标，
    整包当成描边族会把填充图当同族推荐出去。
    """
    is_stroke = 'stroke="currentColor"' in body
    if not is_stroke:
        return FAM_ALIEN, None, False
    vals = _SW_RE.findall(body)
    sw = None
    if vals:
        # 取出现最多的那个值当主线宽（iconoir 少数图标混了 1.22 这类细节线）
        sw = float(max(set(vals), key=vals.count))
    if sw is not None and abs(sw - HOUSE_STROKE_WIDTH) < 1e-6 and grid_w == HOUSE_GRID:
        return FAM_SAME, sw, True
    return FAM_KIN, sw, True


def family_note(fam: str, sw, grid_w: int) -> str:
    if fam == FAM_SAME:
        return f'描边{_fmt_num(sw)}/{grid_w}'
    if fam == FAM_KIN:
        s = f'描边{_fmt_num(sw)}/{grid_w}' if sw is not None else f'描边/{grid_w}'
        return f'{s} 需线宽归一'
    # ⚠️ 「填充」不等于「看起来是实心块」：Phosphor 的常规档是**用填充路径描出轮廓**，
    # 目视跟线条图几乎一样。真正的差别是**线宽写死在路径几何里**，--stroke-width 调不动它。
    return '填充(线宽不可调)'


def _fmt_num(v) -> str:
    if v is None:
        return '?'
    return str(int(v)) if float(v).is_integer() else str(v)


# ────────── 已入库（66 个手工件）──────────

# 手工件文件头形如：`来源：Lucide · coffee` / `来源：Tabler Icons · outline/friends`
_SRC_RE = re.compile(r'来源：([^|\n]+?)\s*·\s*([^\s|]+)')
_LIB_NAME_TO_PREFIX = {'Lucide': 'lucide', 'Tabler Icons': 'tabler', 'Iconoir': 'iconoir',
                       'HeroIcons': 'heroicons', 'Phosphor': 'ph',
                       'Material Design Icons': 'mdi', 'Remix Icon': 'ri'}


_LIC_RE = re.compile(r'许可证：([^（(|\n，]+)')


def scan_local():
    """扫平铺的 *.svg，分成两拨。返回 (manifest, orphans)。

    manifest = {(前缀, 集合内图标名): 文件名}——**这些图集合里也有**，检索时不重复成条，
      只在对应集合那条上打「已入库」标记（落地件的文件头也是这个格式，一样被认出来）。
      Tabler 的 `filled/heart` 在 Iconify 里叫 `heart-filled`，这里做同一化。
    orphans  = 集合里**没有**的本地件（domino-fall / plant-stake 这两个自绘）。
      ⛔ 不把它们纳入检索，「骨牌」就会查不到——而库里明明有，这正是本仓
      「『没查到』≠『没有』」那条判据要防的形状。
    """
    manifest, orphans = {}, []
    if not SVG_LIB.is_dir():
        return manifest, orphans
    for p in sorted(SVG_LIB.glob('*.svg')):
        text = p.read_text(encoding='utf-8', errors='replace')
        head = text[:600]
        hit = _SRC_RE.search(head)
        prefix = _LIB_NAME_TO_PREFIX.get(hit.group(1).strip()) if hit else None
        if prefix:
            name = hit.group(2).strip()
            if '/' in name:                   # `outline/friends` / `filled/heart`
                variant, name = name.split('/', 1)
                if variant == 'filled':
                    name = f'{name}-filled'
            manifest.setdefault((prefix, name), p.name)
            continue
        lic = _LIC_RE.search(head)
        body = re.sub(r'<!--[\s\S]*?-->', '', text)
        grid = 24
        vb = re.search(r'viewBox="0 0 (\d+) (\d+)"', body)
        if vb:
            grid = int(vb.group(1))
        orphans.append({'name': p.stem, 'file': p.name, 'body': body, 'grid': grid,
                        'license': lic.group(1).strip() if lic else '?'})
    return manifest, orphans


# ────────── 检索 ──────────

CJK = re.compile(r'[一-鿿]')


def is_chinese(q: str) -> bool:
    return bool(CJK.search(q))


def zh_expand(q: str):
    """中文 → 英文词表。返回 (英文词表, 用到的映射键)。⛔ 查不到就交空表，由调用方明说。"""
    q = q.strip()
    if q in ZH_KEYWORDS:
        return list(ZH_KEYWORDS[q]), [q]
    terms, used = [], []
    # 长键优先：「咖啡杯」先撞上「咖啡杯」，撞不上再退到「咖啡」
    for k in sorted(ZH_KEYWORDS, key=len, reverse=True):
        if k in q:
            for t in ZH_KEYWORDS[k]:
                if t not in terms:
                    terms.append(t)
            used.append(k)
    return terms, used


def zh_near_misses(q: str, limit: int = 6):
    """缺词时给「共享汉字」的近邻键，帮人改口再查一次。"""
    chars = set(q)
    scored = [(len(chars & set(k)), k) for k in ZH_KEYWORDS]
    return [k for n, k in sorted(scored, key=lambda x: (-x[0], len(x[1]))) if n > 0][:limit]


def score_name(name: str, term: str) -> int:
    """单个英文词对一个图标名的匹配分。⛔ 不做模糊/编辑距离——宁可零命中也别给错图。"""
    if name == term:
        return 100
    parts = name.split('-')
    if term in parts:
        return 78 if parts[0] == term else 72
    if name.startswith(term + '-'):
        return 84
    if name.endswith('-' + term):
        return 76
    if name.startswith(term):
        return 66
    if term in name:
        return 52
    return 0


def search(terms, data, manifest, orphans=(), family_filter='all', limit=12):
    """在已加载集合＋本地自绘件里检索。terms 是英文词表（任一命中即算），按分排序。"""
    hits = []
    for o in orphans:
        best = max((score_name(o['name'], t) for t in terms), default=0)
        if best <= 0:
            continue
        fam, sw, _ = classify(o['body'], o['grid'])
        if family_filter == 'same' and fam != FAM_SAME:
            continue
        if family_filter == 'stroke' and fam == FAM_ALIEN:
            continue
        hits.append({
            'id': f'local:{o["name"]}', 'prefix': 'local', 'name': o['name'],
            'resolved': o['name'], 'alias': False, 'license': o['license'],
            'family': fam, 'family_label': FAM_LABEL[fam],
            'family_note': family_note(fam, sw, o['grid']),
            'stroke_width': sw, 'grid': f'{o["grid"]}x{o["grid"]}',
            'deprecated': False, 'installed': o['file'],
            'installed_path': str(SVG_LIB / o['file']),
            'score': best + {FAM_SAME: 12, FAM_KIN: 6, FAM_ALIEN: 0}[fam] + 20 + 1,
        })
    for prefix, pack in data.items():
        icons = pack['icons']
        cw = int(pack['icons'].get('width') or 24)
        ch = int(pack['icons'].get('height') or 24)
        lic = license_of(prefix, pack['info'])
        entries = []
        for name, spec in icons.get('icons', {}).items():
            entries.append((name, name, spec, False))
        for name, spec in icons.get('aliases', {}).items():
            parent = spec.get('parent')
            pspec = icons.get('icons', {}).get(parent)
            if pspec is None:
                continue                      # 指向别名的别名：不追链，跳过
            entries.append((name, parent, pspec, True))
        for name, real, spec, is_alias in entries:
            best = max((score_name(name, t) for t in terms), default=0)
            if best <= 0:
                continue
            body = spec['body']
            gw = int(spec.get('width') or cw)
            gh = int(spec.get('height') or ch)
            fam, sw, _ = classify(body, gw)
            if family_filter == 'same' and fam != FAM_SAME:
                continue
            if family_filter == 'stroke' and fam == FAM_ALIEN:
                continue
            local = manifest.get((prefix, real))
            s = best
            s += {FAM_SAME: 12, FAM_KIN: 6, FAM_ALIEN: 0}[fam]
            s += 20 if local else 0
            s -= 30 if spec.get('hidden') else 0
            s -= 4 if is_alias else 0
            s -= COLL_ORDER.get(prefix, 9)
            hits.append({
                'id': f'{prefix}:{name}', 'prefix': prefix, 'name': name,
                'resolved': real, 'alias': is_alias, 'license': lic,
                'family': fam, 'family_label': FAM_LABEL[fam],
                'family_note': family_note(fam, sw, gw),
                'stroke_width': sw, 'grid': f'{gw}x{gh}',
                'deprecated': bool(spec.get('hidden')),
                'installed': local,
                'installed_path': str(SVG_LIB / local) if local else None,
                'score': s,
            })
    hits.sort(key=lambda h: (-h['score'], COLL_ORDER.get(h['prefix'], 9),
                             len(h['name']), h['name']))
    return hits[:limit]


# ────────── 取图 ──────────

def _uniform(body: str, attr: str):
    """body 里某属性的值若全库唯一就返回它，否则 None（不唯一时不敢往根上提）。"""
    vals = set(re.findall(rf'\b{re.escape(attr)}="([^"]*)"', body))
    return vals.pop() if len(vals) == 1 else None


def _drop_attr(body: str, attr: str) -> str:
    return re.sub(rf'\s{re.escape(attr)}="[^"]*"', '', body)


def build_svg(prefix: str, name: str, pack: dict, stroke_width=None):
    """把集合里的 body 拼成一个完整、可直接内联的 SVG。

    两件事跟手工件对齐，⛔ 少做一件模板 CSS 就管不住它：
      ① `class="nbd-svg-icon"` 加在根上——模板靠这个 class 统一着色与线宽；
      ② 把 body 里**取值唯一**的 stroke/fill/stroke-width/linecap/linejoin **提到根上**。
         Iconify 的 body 把这些写在子元素上，写在子元素上的呈现属性**盖得过**从根继承的
         CSS，`.nbd-svg-icon{stroke-width:1.6}` 会静默失效——提上来才跟手工件行为一致。
         取值不唯一的（描边图里嵌了实心点，fill 同时有 none 和 currentColor）原样留在
         子元素上，只在根上给个默认值，渲染结果不变。

    stroke_width 给了就归一：body 里每个 stroke-width 都改写成它，根上也写它。
    ⚠️ 网格不是 24 时按比例折算（ph 是 256 网格），保证视觉粗细一致而不是数字一致。
    """
    icons = pack['icons']
    real = name
    if real in icons.get('aliases', {}):
        real = icons['aliases'][real]['parent']
    spec = icons.get('icons', {}).get(real)
    if spec is None:
        return None, None
    body = spec['body']
    gw = int(spec.get('width') or icons.get('width') or 24)
    gh = int(spec.get('height') or icons.get('height') or 24)
    fam, cur_sw, is_stroke = classify(body, gw)

    target_sw = None
    if stroke_width is not None:
        if is_stroke:
            target_sw = round(float(stroke_width) * gw / HOUSE_GRID, 4)
            body = _SW_RE.sub(f'stroke-width="{_fmt_num(target_sw)}"', body)
        else:
            # ⛔ 不静默吞掉：填充族的线宽写死在路径几何里，给了 --stroke-width 也调不动，
            # 不说一声的话调用方会以为归一成功了
            print(f'⚠️ {prefix}:{name} 是填充族，--stroke-width 对它无效'
                  f'（线宽写死在路径几何里，不是 stroke 属性）——已原样取图', file=sys.stderr)

    root = ['class="nbd-svg-icon"', 'xmlns="http://www.w3.org/2000/svg"',
            'width="24"', 'height="24"', f'viewBox="0 0 {gw} {gh}"']
    if is_stroke:
        hoist = ['fill', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin']
        defaults = {'fill': 'none', 'stroke': 'currentColor'}
    else:
        hoist = ['fill']
        defaults = {'fill': 'currentColor'}
    attrs = {}
    for a in hoist:
        v = _uniform(body, a)
        if v is not None:
            body = _drop_attr(body, a)
            attrs[a] = v
        elif a in defaults:
            attrs[a] = defaults[a]
    if target_sw is not None:
        attrs['stroke-width'] = _fmt_num(target_sw)
    elif is_stroke and 'stroke-width' not in attrs and cur_sw is not None:
        attrs['stroke-width'] = _fmt_num(cur_sw)
    for a in hoist:
        if a in attrs:
            root.append(f'{a}="{attrs[a]}"')
    body = re.sub(r'\s{2,}', ' ', body).strip()
    # 属性全被提到根上之后，外层那个 <g> 就空了（iconoir 常见）；只在它确实是唯一且
    # 包住全部内容时脱掉，⛔ 有嵌套 <g> 时不动，免得改变分组语义
    if body.startswith('<g>') and body.endswith('</g>') and body.count('<g') == 1:
        body = body[3:-4]
    svg = '<svg ' + ' '.join(root) + '>' + body + '</svg>'
    meta = {'prefix': prefix, 'name': name, 'resolved': real, 'grid': f'{gw}x{gh}',
            'family': fam, 'family_label': FAM_LABEL[fam],
            'stroke_width': attrs.get('stroke-width'), 'normalized': target_sw is not None,
            'license': license_of(prefix, pack['info'])}
    return svg, meta


def install_header(prefix: str, meta: dict, note: str) -> str:
    c = COLL_BY_PREFIX[prefix]
    info = f'{c["name"]} · {meta["resolved"]}'
    norm = f'；线宽归一至 {meta["stroke_width"]}' if meta['normalized'] else ''
    return (f'<!-- NBDpsy 封面素材库 | 意象：{note or "（未注明）"}\n'
            f'     来源：{info} | 集合包 collections/{prefix}/icons.json\n'
            f'     许可证：{meta["license"]}（见 LICENSES.md 集合台账）| 需署名：否（商用免署名）\n'
            f'     入库日期：{date.today().isoformat()} | 改造：svg_find.py --emit --install 落地，'
            f'加 class="nbd-svg-icon"，属性提到根上{norm} -->\n')


# ────────── 输出 ──────────

def _dw(s: str) -> int:
    """显示宽度：中文与全角标点占两列。⛔ 用 len() 对齐会让带中文的那列全歪。"""
    return sum(2 if unicodedata.east_asian_width(ch) in 'WF' else 1 for ch in s)


def _pad(s: str, width: int) -> str:
    return s + ' ' * max(0, width - _dw(s))


def print_table(hits, manifest_note=True):
    w_id = max((_dw(h['id']) for h in hits), default=8)
    w_lic = max((_dw(h['license']) for h in hits), default=7)
    w_fam = max((_dw(h['family_note']) for h in hits), default=8)
    for h in hits:
        bits = [_pad(h['id'], w_id), _pad(h['license'], w_lic),
                _pad(h['family_note'], w_fam), h['family_label']]
        if h['alias']:
            bits.append(f'（别名→{h["resolved"]}）')
        if h['deprecated']:
            bits.append('⚠️上游已弃用')
        if manifest_note and h['installed']:
            bits.append(f'已入库 assets/svg-library/{h["installed"]}')
        print('  '.join(bits))


def die(msg: str, code: int = 2, **extra):
    print(f'⛔ {msg}', file=sys.stderr)
    for k, v in extra.items():
        print(f'   {k}: {v}', file=sys.stderr)
    return code


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='本地 SVG 集合库检索与取图（⛔ 默认不联网）')
    ap.add_argument('query', nargs='?', help='中文或英文关键词')
    ap.add_argument('--json', action='store_true', help='出 JSON（给排版 agent 用）')
    ap.add_argument('--limit', type=int, default=12, help='最多几条（默认 12）')
    ap.add_argument('--family', choices=['all', 'same', 'stroke'], default='all',
                    help='族别过滤：all=全部；same=只要同族(描边2/24)；stroke=只要描边')
    ap.add_argument('--emit', metavar='前缀:名字', help='取图：打印完整可内联 SVG')
    ap.add_argument('--stroke-width', type=float, default=None,
                    help='取图时把线宽归一到这个值（跨族混用时用，默认保留上游值）')
    ap.add_argument('--install', action='store_true',
                    help='把 --emit 的结果落地成 svg-library/<前缀>-<名字>.svg（render_cover 才认得）')
    ap.add_argument('--note', default='', help='落地时写进文件头的意象说明')
    ap.add_argument('--list-collections', action='store_true', help='集合台账速查')
    args = ap.parse_args(argv)

    if not COLL_DIR.is_dir():
        return die(f'集合目录不存在：{COLL_DIR}', collections=COLL_DIR)

    if args.list_collections:
        data, missing = load_all()
        rows = []
        for c in COLLECTIONS:
            p = c['prefix']
            if p in data:
                ic = data[p]['icons']
                n = len(ic.get('icons', {})) + len(ic.get('aliases', {}))
                rows.append((p, c['name'], c['spdx'], str(n), '已入库'))
            else:
                rows.append((p, c['name'], c['spdx'], '—',
                             '⛔ 未入库' if not c['bundled'] else '⚠️ 文件缺失'))
        if args.json:
            print(json.dumps([dict(zip(('prefix', 'name', 'license', 'icons', 'status'), r))
                              for r in rows], ensure_ascii=False, indent=2))
        else:
            for r in rows:
                print(f'{r[0]:<10} {r[1]:<24} {r[2]:<14} {r[3]:>6}  {r[4]}')
            for c in COLLECTIONS:
                if not c['bundled']:
                    print(f'\n⛔ {c["prefix"]} 未入库：{c["reason"]}\n   要加库：{c["add_cmd"]}')
        return 0

    if args.emit:
        spec = args.emit
        if ':' not in spec:
            return die(f'--emit 要写成 `前缀:名字`（比如 lucide:coffee），收到的是 `{spec}`')
        prefix, name = spec.split(':', 1)
        if prefix == 'local':
            # 手工件已经是成品：剥掉版权注释头就能内联，⛔ 不重新拼装（会丢掉手工改造）
            p = SVG_LIB / f'{name}.svg'
            if not p.exists():
                return die(f'素材库里没有 {p.name}', 目录=str(SVG_LIB))
            out = re.sub(r'^<!--[\s\S]*?-->\s*', '', p.read_text(encoding='utf-8')).strip()
            print(json.dumps({'prefix': 'local', 'name': name, 'resolved': name,
                              'installed': str(p), 'icon_name': name, 'svg': out},
                             ensure_ascii=False, indent=2) if args.json else out)
            return 0
        c = COLL_BY_PREFIX.get(prefix)
        if c is None:
            return die(f'没有叫 `{prefix}` 的集合', 集合=', '.join(COLL_BY_PREFIX))
        if not c['bundled']:
            return die(f'集合 `{prefix}` **故意没有入库**——{c["reason"]}', 要加库=c['add_cmd'])
        pack = load_collection(prefix)
        if pack is None:
            return die(f'集合 `{prefix}` 的文件缺失', 目录=str(COLL_DIR / prefix))
        svg, meta = build_svg(prefix, name, pack, args.stroke_width)
        if svg is None:
            return die(f'集合 `{prefix}` 里没有叫 `{name}` 的图标——'
                       f'⛔ 不会替你猜近似名，先用 `svg_find.py {name}` 查准确名字')
        if args.install:
            out = SVG_LIB / f'{prefix}-{meta["resolved"]}.svg'
            out.write_text(install_header(prefix, meta, args.note) + svg + '\n',
                           encoding='utf-8')
            payload = dict(meta, installed=str(out), icon_name=out.stem)
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(f'✅ 已落地 {out}')
                print(f'   render_cover.py 里用这个名字：{out.stem}')
                print(f'   ⚠️ 别忘了 LICENSES.md 的落地件计数（集合行覆盖许可证，'
                      f'计数口径见台账顶部）')
            return 0
        if args.json:
            print(json.dumps(dict(meta, svg=svg), ensure_ascii=False, indent=2))
        else:
            print(svg)
        return 0

    if not args.query:
        ap.print_help()
        return 2

    q = args.query.strip()
    data, missing = load_all()
    if missing:
        return die(f'这些集合的文件缺失：{missing}', 目录=str(COLL_DIR))
    manifest, orphans = scan_local()

    used_keys = []
    if is_chinese(q):
        terms, used_keys = zh_expand(q)
        if not terms:
            # ⛔ 这里是本仓的老坑：静默返回空会让人以为「库里没有」，
            # 实际缺的是中文映射。必须把这两件事分开说。
            print(f'⚠️ 「{q}」**没有中文映射**——不是库里没有这个图标，是这个词还没进映射表。',
                  file=sys.stderr)
            near = zh_near_misses(q)
            if near:
                print(f'   映射表里相近的词：{"、".join(near)}', file=sys.stderr)
            print('   ⛔ 请改用英文关键词再查一次（图标名本身全是英文），'
                  '比如 `svg_find.py coffee`。', file=sys.stderr)
            print(f'   要补词就往 {pathlib.Path(__file__).name} 的 ZH_KEYWORDS 里加一行。',
                  file=sys.stderr)
            if args.json:
                print(json.dumps({'query': q, 'zh_mapping': False, 'hits': [],
                                  'reason': '没有中文映射，不等于库里没有',
                                  'near_keys': near}, ensure_ascii=False, indent=2))
            return 1
    else:
        terms = [t for t in re.split(r'[\s,]+', q.lower()) if t]

    hits = search(terms, data, manifest, orphans, args.family, args.limit)
    if args.json:
        print(json.dumps({'query': q, 'zh_mapping': bool(used_keys),
                          'zh_keys': used_keys, 'terms': terms,
                          'count': len(hits), 'hits': hits},
                         ensure_ascii=False, indent=2))
        return 0 if hits else 1
    if used_keys:
        print(f'# 「{q}」→ 英文词：{", ".join(terms)}（命中映射键：{"、".join(used_keys)}）')
    if not hits:
        print(f'零命中：{terms}', file=sys.stderr)
        print('   ⛔ 本脚本**不联网**，这里只查了本地 6 个集合。换个英文词再试；'
              '确实要现搜就自己去 https://icon-sets.iconify.design 找，'
              '找到后回来核许可证再入库。', file=sys.stderr)
        return 1
    print_table(hits)
    return 0


if __name__ == '__main__':
    sys.exit(main())
