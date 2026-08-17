"""video_style.py：把 `kind=video` 的风格档案喂给视频入口脚本当默认值。

盯死四条：

1. **优先级**：命令行显式给的 > 档案里的 > 脚本内置默认。反了就会「明明写了 --voice X
   却出来别的声音」，而且查不出为什么。
2. **拿错档案要报错，⛔ 不静默回落**：拿播客那套去跑放映，字段一个都对不上，脚本会安静地
   全用默认值出一条「档案完全没生效」的片子——那比报错难查得多（钱已经花了）。
3. **null 不覆盖**：档案里的 null 是「这项我没定，听脚本的」，塞进 argparse 会让下游拿到
   None 而不是默认值，直接炸在半路。
4. **只落这个 parser 真有的参数**：同一子形态的旋钮分在两个脚本上（播客的音色在
   podcast_gen、播放器主题在 record_podcast），不过滤就会报「生效 5 项」骗人。
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent / "nbdpsy-text-to-video" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts"))

import style_profile as sp  # noqa: E402
import video_style  # noqa: E402


def _write(tmp_path, obj, name="style.json"):
    p = tmp_path / name
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return str(p)


# ────────── load_style：拿错档案一律报错 ──────────

def test_收单套json(tmp_path):
    v = video_style.load_style(_write(tmp_path, sp.video_skeleton("podcast")), "podcast")
    assert v["form"] == "podcast" and v["narration"]["voice_m"]


def test_收get的整份输出(tmp_path):
    """运营（和 agent）把 --get 的 stdout 存成文件再喂回来是最自然的操作，必须认。"""
    envelope = {"exists": True, "version": 3, "set": "播客", "kind": "video",
                "profile": sp.video_skeleton("podcast")}
    v = video_style.load_style(_write(tmp_path, envelope), "podcast")
    assert v["form"] == "podcast"


def test_拿图文那套跑视频要报错(tmp_path):
    with pytest.raises(ValueError, match="不是视频那一类"):
        video_style.load_style(_write(tmp_path, {"kind": "carousel", "visual": {}}), "podcast")


def test_拿错子形态要报错(tmp_path):
    """⛔ 这条最要紧：拿播客那套跑放映，不报错就会出一条「档案完全没生效」的片子。"""
    with pytest.raises(ValueError, match="播客"):
        video_style.load_style(_write(tmp_path, sp.video_skeleton("podcast")), "slideshow")


def test_没有video段要报错(tmp_path):
    with pytest.raises(ValueError, match="没有 video 段"):
        video_style.load_style(_write(tmp_path, {"kind": "video"}), "podcast")


def test_不是json对象要报错(tmp_path):
    with pytest.raises(ValueError, match="不是 JSON 对象"):
        video_style.load_style(_write(tmp_path, ["a"]), "podcast")


# ────────── defaults_for：字段 → 命令行参数 ──────────

@pytest.mark.parametrize("form,期望", [
    ("slideshow", {"canvas", "engine", "voice", "speed", "model", "sentence_gap",
                   "bgm", "bgm_duck", "head", "page_gap", "tail", "kenburns", "xfade"}),
    ("podcast", {"voice_f", "voice_m", "model", "theme", "fade_out"}),
])
def test_骨架能落满这条产线的旋钮(form, 期望):
    got = video_style.defaults_for(sp.video_skeleton(form)["video"], form)
    assert set(got) == 期望


def test_微电影没有入口脚本(tmp_path):
    """微电影的旋钮分别落在 shots.json / direction.md / tts_gen / gen_bgm 上，没有
    「一条命令收口」的入口脚本。⛔ 别硬造一个「读了没处用」的入口。"""
    assert video_style.FIELD_MAP["microfilm"] == {}
    v = video_style.load_style(_write(tmp_path, sp.video_skeleton("microfilm")), "microfilm")
    assert video_style.defaults_for(v, "microfilm") == {}


def test_null不覆盖():
    """null = 「这项我没定，听脚本的」。塞进 argparse 会让下游拿到 None 而不是默认值。"""
    v = {"form": "podcast", "narration": {"voice_f": None, "voice_m": "男声"}, "player": None}
    assert video_style.defaults_for(v, "podcast") == {"voice_m": "男声"}


def test_缺段不炸():
    assert video_style.defaults_for({"form": "slideshow"}, "slideshow") == {}


def test_未知子形态报错():
    with pytest.raises(ValueError, match="未知子形态"):
        video_style.attach(argparse.ArgumentParser(), "vlog")


# ────────── attach / apply：优先级与过滤 ──────────

def _parser():
    p = argparse.ArgumentParser()
    p.add_argument("--voice-f", default="脚本默认女声")
    p.add_argument("--voice-m", default="脚本默认男声")
    p.add_argument("--model", default="脚本默认模型")
    return p


def test_档案改默认值(tmp_path, capsys):
    prof = sp.video_skeleton("podcast")
    prof["video"]["narration"]["voice_m"] = "换个男声"
    a = video_style.apply(_parser(), "podcast", ["--style", _write(tmp_path, prof)])
    assert a.voice_m == "换个男声"
    assert a.voice_f == prof["video"]["narration"]["voice_f"]


def test_命令行赢过档案(tmp_path):
    """⛔ 这条反了 = 运营明明写了 --voice-m 却出来别的声音，还查不出为什么。"""
    prof = sp.video_skeleton("podcast")
    prof["video"]["narration"]["voice_m"] = "档案里的男声"
    a = video_style.apply(_parser(), "podcast",
                          ["--style", _write(tmp_path, prof), "--voice-m", "命令行的男声"])
    assert a.voice_m == "命令行的男声"


def test_不给style就一字不变():
    a = video_style.apply(_parser(), "podcast", [])
    assert (a.voice_f, a.voice_m, a.model) == ("脚本默认女声", "脚本默认男声", "脚本默认模型")
    assert a.style is None


def test_只落这个parser真有的参数(tmp_path, capsys):
    """播客的音色在 podcast_gen、播放器主题在 record_podcast：不过滤就会往 namespace 里
    塞一堆本脚本不用的键，还在 stderr 报「生效 5 项」——运营会以为这个脚本吃了那 5 项。"""
    p = argparse.ArgumentParser()
    p.add_argument("--theme", default="shenye")
    p.add_argument("--fade-out", type=float, default=0.0)
    a = video_style.apply(p, "podcast", ["--style", _write(tmp_path, sp.video_skeleton("podcast"))])
    assert not hasattr(a, "voice_f")
    assert "生效 2 项" in capsys.readouterr().err


def test_一项都没落上要说出来(tmp_path, capsys):
    """档案在、形态也对，但这个脚本一个字段都读不到 —— 说出来，别让人以为它在起作用。"""
    p = argparse.ArgumentParser()
    p.add_argument("--别的", dest="qita", default=1)
    video_style.apply(p, "podcast", ["--style", _write(tmp_path, sp.video_skeleton("podcast"))])
    assert "全用脚本默认值" in capsys.readouterr().err


# ────────── 四个入口脚本真的接上了 ──────────

@pytest.mark.parametrize("脚本,form", [
    ("slideshow_video.py", "slideshow"),
    ("podcast_gen.py", "podcast"),
    ("record_podcast.py", "podcast"),
    ("build_oneline.py", "card"),
])
def test_入口脚本的help里有style(脚本, form):
    """接线断了（忘了 attach / import 名写错）只有真跑一次才看得出来。"""
    argv = [sys.executable, str(SCRIPTS / 脚本)]
    if 脚本 == "podcast_gen.py":
        argv += ["synth"]
    r = subprocess.run(argv + ["--help"], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-800:]
    assert "--style" in r.stdout


def test_oneline缺bg和canvas时报人话(tmp_path):
    """把 required=True 换成后置检查之后，缺参数仍必须拒跑——⛔ 绝不给它们编个默认值悄悄出片。"""
    cues = tmp_path / "c.json"
    cues.write_text(json.dumps([{"start": 0, "end": 1, "text": "你好"}]), encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPTS / "build_oneline.py"),
                        "--cues", str(cues), "--out", str(tmp_path / "o")],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode != 0
    assert "--bg" in r.stderr and "--canvas" in r.stderr and "--style" in r.stderr


def test_oneline用档案补齐bg和canvas(tmp_path):
    """端到端：档案里的 oneline 段真的替代了命令行的 --bg / --canvas。"""
    prof = sp.video_skeleton("card")
    prof["video"]["template"] = "tpl-oneline"
    prof["video"]["oneline"] = {"bg": "kepu", "canvas": "16:9", "max_line_chars": 10}
    cues = tmp_path / "c.json"
    cues.write_text(json.dumps([{"start": 0, "end": 2, "text": "今天想跟你聊聊"}]),
                    encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPTS / "build_oneline.py"),
                        "--cues", str(cues), "--out", str(tmp_path / "o"),
                        "--style", _write(tmp_path, prof)],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-1500:]
    assert "生效 3 项" in r.stderr
    html = (tmp_path / "o" / "card-oneline.html").read_text(encoding="utf-8")
    assert "1920" in html, "16:9 画幅没生效"
    assert "#EDEFF1" in html, "kepu 背景档没生效"
