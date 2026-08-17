#!/usr/bin/env python3
"""把一套 `kind="video"` 的风格档案，喂给视频产线的入口脚本当**默认值**。

这一段解决的是「档案里的字段没人读」——加一个没人读的字段就是一条死链。所以本模块只认
四个子形态各自**真读得到的旋钮**：每个字段在这里都能指到一个具体的命令行参数，
而那个参数在对应脚本里就是它今天已经在用的那一个。字段→参数的对照表见
`SKILL.md`「风格档案（视频那一类）」节（唯一真源），本文件是它的可执行副本。

用法（入口脚本里三行）：

    import video_style
    ...
    a = video_style.apply(p, "slideshow")     # 内部加 --style、预解析、set_defaults、parse

优先级（与 typeset_longimage.py --style 同一口径）：

    **命令行显式给的 > 档案里的 > 脚本内置默认**

实现靠 `ArgumentParser.set_defaults`：档案只改「没写在命令行上的那些参数」的默认值，
命令行上写了的照旧覆盖它。⛔ 别改成「读完档案直接赋值给 args」——那会让命令行显式传的
参数被档案悄悄盖掉，运营明明写了 `--voice X` 却出来别的声音，还查不出为什么。

档案本身出毛病一律**报错退出**（不静默回落到脚本默认）：拿错档案出的片子看不出来，
只有下次听到不对劲的声音才发现，那时素材钱已经花了。
"""
import argparse
import json
import sys
from pathlib import Path

FORMS = ("slideshow", "card", "microfilm", "podcast")
FORM_CN = {"slideshow": "放映", "card": "字卡", "microfilm": "微电影", "podcast": "播客"}

#: 每个子形态：`档案里的路径` → `入口脚本的 argparse dest`。
#: 路径用 ("a", "b") 表示 profile["video"]["a"]["b"]。**这张表就是「谁读这个字段」的答案**，
#: 表里没有的字段本模块一概不读（也就不该出现在档案里，style_profile.py 的 video_warnings 会提醒）。
FIELD_MAP = {
    "slideshow": {                      # 消费者：slideshow_video.py
        ("canvas",): "canvas",
        ("narration", "engine"): "engine",
        ("narration", "voice"): "voice",
        ("narration", "speed"): "speed",
        ("narration", "model"): "model",
        ("narration", "sentence_gap"): "sentence_gap",
        ("bgm", "source"): "bgm",
        ("bgm", "duck_db"): "bgm_duck",
        ("pace", "head"): "head",
        ("pace", "page_gap"): "page_gap",
        ("pace", "tail"): "tail",
        ("motion", "kenburns"): "kenburns",
        ("motion", "xfade"): "xfade",
    },
    "card": {                           # 消费者：build_oneline.py（仅 tpl-oneline 版式）
        ("oneline", "bg"): "bg",
        ("oneline", "canvas"): "canvas",
        ("oneline", "max_line_chars"): "max_line_chars",
    },
    "podcast": {                        # 消费者：podcast_gen.py synth + record_podcast.py
        ("narration", "voice_f"): "voice_f",
        ("narration", "voice_m"): "voice_m",
        ("narration", "model"): "model",
        ("player", "theme"): "theme",
        ("player", "fade_out"): "fade_out",
    },
    # 微电影没有「一条命令收口」的入口脚本：它的旋钮分别落在 shots.json（ratio / ai_label）、
    # direction.md 第一行（look）、第 3 步 tts_gen、第 7 步 gen_bgm 上，由 SKILL.md 那几道
    # 必经工序按档案填。所以这里**不给它 --style**，⛔ 也别硬造一个「读了没处用」的入口。
    "microfilm": {},
}


def load_style(path, form):
    """读一份 `kind="video"` 的**单套**档案，返回它的 `video` 段。

    两种输入形态都收（与 style_profile.py 的 load_profile 同一口径）：单套 JSON 本身，
    或 `style_profile.py --get --form <子形态>` 的整份输出（带 exists/profile 外层）。

    子形态对不上就报错：拿播客那套去跑放映，字段一个都对不上，脚本会安安静静地全用默认值
    出一条「档案完全没生效」的片子——那比报错难查得多。
    """
    data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} 不是 JSON 对象，不是一套风格档案")
    if "profile" in data and isinstance(data.get("profile"), dict):
        data = data["profile"]          # 直接喂 --get 整份输出时自动剥出那一套
    if data.get("kind") != "video":
        raise ValueError(
            f"这套档案 kind={data.get('kind')!r}，不是视频那一类（kind=\"video\"）——"
            f"图文/文字版那两套没有视频旋钮，用它跑视频等于没设置。"
            f"取视频那套：style_profile.py --get --form {form}")
    video = data.get("video")
    if not isinstance(video, dict):
        raise ValueError("档案里没有 video 段（或不是对象），读不出任何视频旋钮")
    got = video.get("form")
    if got != form:
        raise ValueError(
            f"这套是「{FORM_CN.get(got, got)}」那条产线的档案，"
            f"当前跑的是「{FORM_CN[form]}」——四条产线的旋钮完全不同，别混用。"
            f"取对的那套：style_profile.py --get --form {form}")
    return video


def defaults_for(video, form):
    """`video` 段 → 覆盖到 argparse 默认值上的 `{dest: 值}`。

    **null / 缺省一律不覆盖**（用脚本默认）——档案里的 null 是「这项我没定，听脚本的」，
    把 None 塞进 argparse 会让下游拿到 None 而不是默认值，直接炸在半路。
    """
    out = {}
    for path, dest in FIELD_MAP[form].items():
        cur = video
        for seg in path:
            cur = cur.get(seg) if isinstance(cur, dict) else None
            if cur is None:
                break
        if cur is not None:
            out[dest] = cur
    return out


def attach(parser, form, argv=None):
    """给 `parser` 加上 `--style` 并把档案里的值装成它的默认值（**不解析**）。

    ⚠️ 预解析用的是**独立的小 parser**（`parse_known_args`），因为真 parser 必须等
    `set_defaults` 之后才解析——顺序反了档案就永远盖不上去。

    ⚠️ 有子命令的脚本（podcast_gen.py）**必须把参数装在子 parser 上**：argparse 解析
    子命令时会用子 parser 的默认值覆盖顶层 namespace，装在顶层等于白装。
    """
    if form not in FORMS:
        raise ValueError(f"未知子形态 {form!r}，只有 {'/'.join(FORMS)}")
    parser.add_argument(
        "--style", default=None,
        help=f"这条产线的风格档案（kind=video、form={form} 的**单套** JSON）："
             f"style_profile.py --get --form {form} > style.json。"
             f"命令行显式传的参数优先级高于档案")
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--style", default=None)
    known, _ = pre.parse_known_args(argv if argv is not None else sys.argv[1:])
    if not known.style:
        return parser
    over = defaults_for(load_style(known.style, form), form)
    # 只落**这个 parser 真有的**参数：同一个子形态的旋钮可能分在两个脚本上
    # （播客的音色在 podcast_gen、播放器主题在 record_podcast）。不过滤的话
    # set_defaults 会往 namespace 里塞一堆本脚本根本不用的键，还要在 stderr 上
    # 报「生效 5 项」——运营会以为这个脚本吃了那 5 项。
    have = {act.dest for act in parser._actions}          # argparse 没给公开接口
    over = {k: v for k, v in over.items() if k in have}
    if over:
        parser.set_defaults(**over)
        print(f"· 风格档案（{FORM_CN[form]}）生效 {len(over)} 项："
              + "、".join(f"{k}={v!r}" for k, v in over.items()), file=sys.stderr)
    else:
        # 档案在、形态也对，但一个字段都没落上 —— 说出来，别让人以为它在起作用
        print(f"⚠ 风格档案里没有「{FORM_CN[form]}」这条产线读得到的字段，本次全用脚本默认值",
              file=sys.stderr)
    return parser


def apply(parser, form, argv=None):
    """`attach` + `parse_args`：没有子命令的脚本用这一个就够。"""
    return attach(parser, form, argv).parse_args(argv)
