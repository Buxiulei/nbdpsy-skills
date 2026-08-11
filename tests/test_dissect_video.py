"""dissect_video.py 的纯函数与渲染测试。

只测确定性部分：幻觉守卫、probe 归一、REPORT/transcript 渲染、CLI --help。
**不在 pytest 里跑真 ASR / 真 ffmpeg 转码**（慢、要模型权重、要样片），
那部分靠人工实跑验证（见 skill 交付报告）。
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-content-teardown" / "scripts"))

import dissect_video as dv

SCRIPT = Path(__file__).parent.parent / "nbdpsy-content-teardown" / "scripts" / "dissect_video.py"

# 正常中文转写（v2.mp4 实测结果的节选，媒体实长 29.72s）
REAL_ZH = [
    {"start": 0.0, "end": 2.0, "text": "我们就第一个人啊，"},
    {"start": 16.0, "end": 18.0, "text": "别急啊兄弟，不用着急，"},
    {"start": 18.0, "end": 20.0, "text": "没人吹你一个嘛，你别急 慢慢坐，"},
]

FAKE_PROBE = {
    "file": "/x/v2.mp4", "name": "v2.mp4", "format_name": "mov,mp4",
    "duration": 29.72, "size_bytes": 17282856, "size_mb": 16.48,
    "streams": [], "audio": {"codec_name": "aac", "sample_rate": "44100", "channels": 1},
    "video": {"codec_name": "hevc", "width": 1440, "height": 3200, "fps": 24.27},
}


# ---------------------------------------------------------------- 幻觉守卫

def test_guard_empty_segments():
    """① 一句话都没转出来。"""
    v = dv.hallucination_verdict([], 0.95, 30.0)
    assert v["suspect"] is True
    assert any("为空" in r for r in v["reasons"])


def test_guard_punctuation_only():
    """② 全是标点 —— 纯音乐片最常见的幻觉产物（一串句号）。"""
    segs = [{"start": 0, "end": 2, "text": "。"}, {"start": 2, "end": 4, "text": " ，, "}]
    v = dv.hallucination_verdict(segs, 0.99, 30.0)
    assert v["suspect"] is True
    assert any("标点" in r for r in v["reasons"])


def test_guard_single_char_repeat():
    """② 变体：单字符重复（「啊啊啊啊」「嗯嗯嗯」）。"""
    segs = [{"start": 0, "end": 3, "text": "啊啊啊啊啊啊"}, {"start": 3, "end": 6, "text": "嗯嗯嗯"}]
    v = dv.hallucination_verdict(segs, 0.99, 30.0)
    assert v["suspect"] is True
    assert any("单字重复" in r for r in v["reasons"])


def test_guard_low_language_probability():
    """③ 语种都没听准（v3.mp4 实测 language=si p=0.17）。"""
    v = dv.hallucination_verdict(REAL_ZH, 0.17, 30.0)
    assert v["suspect"] is True
    assert any("0.17" in r and "置信度" in r for r in v["reasons"])


def test_guard_segment_overruns_media_duration():
    """④ 时间轴编到媒体实长之外：31.7s 的片子转出 30–55s 的段（2026-08-10 实测）。"""
    segs = [{"start": 30.0, "end": 55.0, "text": "谢谢观看"}]
    v = dv.hallucination_verdict(segs, 0.9, 31.7)
    assert v["suspect"] is True
    assert any("越出媒体实长" in r for r in v["reasons"])


def test_guard_passes_normal_chinese():
    """正常中文口播绝不能误伤（守卫宁可漏报也不能把真口播判成幻觉）。"""
    v = dv.hallucination_verdict(REAL_ZH, 0.9696, 29.72)
    assert v["suspect"] is False and v["reasons"] == []


def test_guard_tolerates_tail_rounding():
    """尾段轻微超出（取整误差）不算越界，容忍 0.5s。"""
    segs = [{"start": 0, "end": 29.9, "text": "结尾这句话说完了"}]
    assert dv.hallucination_verdict(segs, 0.9, 29.72)["suspect"] is False


def test_guard_accepts_list_segments():
    """段落也可以是 [start, end, text] 三元组形式。"""
    assert dv.hallucination_verdict([[0.0, 2.0, "。"]], 0.99, 30.0)["suspect"] is True
    assert dv.hallucination_verdict([[0.0, 2.0, "别急啊兄弟"]], 0.99, 30.0)["suspect"] is False


def test_guard_no_duration_skips_overrun_check():
    """拿不到媒体实长时不做越界判定（不能凭空造判据）。"""
    segs = [{"start": 30.0, "end": 55.0, "text": "正常的一句中文口播内容"}]
    assert dv.hallucination_verdict(segs, 0.9, 0)["suspect"] is False


def test_guard_single_segment_with_one_noise_among_real():
    """只要有一段是真内容就不判幻觉（v2 尾段是「嗨嗨嗨…」但全片有真口播）。"""
    segs = REAL_ZH + [{"start": 21.0, "end": 26.0, "text": "嗨嗨嗨嗨嗨嗨嗨嗨"}]
    assert dv.hallucination_verdict(segs, 0.9696, 29.72)["suspect"] is False


# ---------------------------------------------------------------- probe 归一

def test_normalize_probe_shape():
    raw = {"format": {"duration": "21.020907", "format_name": "mov,mp4", "size": "8864717"},
           "streams": [{"index": 0, "codec_type": "audio", "codec_name": "aac",
                        "sample_rate": "44100", "channels": 1},
                       {"index": 1, "codec_type": "video", "codec_name": "hevc",
                        "width": 1440, "height": 3200, "avg_frame_rate": "24264/1000"}]}
    p = dv.normalize_probe(raw, Path("/x/v3.mp4"), 8864717)
    assert p["duration"] == 21.021 and p["name"] == "v3.mp4" and p["size_mb"] == 8.45
    assert p["video"]["width"] == 1440 and p["video"]["fps"] == 24.26
    assert p["audio"]["sample_rate"] == "44100"


def test_normalize_probe_missing_duration_and_streams():
    """时长缺失/无流也不能抛 —— probe 崩了整条产线就断了。"""
    p = dv.normalize_probe({"format": {}, "streams": []}, Path("/x/a.bin"), 0)
    assert p["duration"] == 0.0 and p["video"] is None and p["audio"] is None


def test_parse_rate_edge_cases():
    assert dv._parse_rate("30000/1001") == 29.97
    assert dv._parse_rate("0/0") is None and dv._parse_rate(None) is None


# ---------------------------------------------------------------- 渲染

def test_render_transcript_txt_banner_on_suspect():
    guard = {"suspect": True, "reasons": ["转写 segments 为空（一句话都没转出来）"]}
    txt = dv.render_transcript_txt({"language": "si", "language_probability": 0.17,
                                    "segments": []}, guard)
    assert txt.splitlines()[0] == dv.NO_SPEECH_BANNER  # 告警必须压在第一行
    assert "字幕稿" in txt and "segments 为空" in txt


def test_render_transcript_txt_normal_has_no_banner():
    txt = dv.render_transcript_txt(
        {"language": "zh", "language_probability": 0.97, "segments": REAL_ZH},
        {"suspect": False, "reasons": []})
    assert dv.NO_SPEECH_BANNER not in txt
    assert "别急啊兄弟" in txt and "[00:16.0 → 00:18.0]" in txt


def test_render_transcript_txt_without_transcript():
    txt = dv.render_transcript_txt(None, None)
    assert "无转写" in txt


def test_render_report_full_skeleton():
    r = dv.render_report(FAKE_PROBE,
                         {"language": "zh", "language_probability": 0.9696, "segments": REAL_ZH},
                         {"suspect": False, "reasons": []},
                         ["frames/f01.jpg", "frames/f02.jpg"], ["sheet.jpg"], 0.5)
    # 骨架五节齐全，且人工节留空
    for heading in ("## 0. 基本信息", "## 1. 口播文字稿", "## 2. 帧看板",
                    "## 3. 形式拆解（人工填写）", "## 4. 数据（人工填写）",
                    "## 5. 建议（人工填写）"):
        assert heading in r, f"REPORT 缺少 {heading}"
    assert "29.72s" in r and "1440x3200 竖屏" in r and "16.48 MB" in r
    assert "别急啊兄弟" in r and "`sheet.jpg`" in r and "`frames/f02.jpg`" in r
    # 帧时间戳按 1/fps 递推
    assert "| `frames/f02.jpg` | 00:02.0 |" in r
    # 末尾必须给全分辨率核字幕的命令
    assert "-frames:v 1 -q:v 3 full.jpg" in r and "/x/v2.mp4" in r
    assert dv.NO_SPEECH_BANNER not in r


def test_render_report_carries_no_speech_banner():
    r = dv.render_report(FAKE_PROBE,
                         {"language": "si", "language_probability": 0.17, "segments": []},
                         {"suspect": True, "reasons": ["语种置信度 0.17 < 0.5"]},
                         ["frames/f01.jpg"], ["sheet.jpg"], 0.5,
                         ["疑无口播（幻觉守卫命中）：语种置信度 0.17 < 0.5"])
    assert dv.NO_SPEECH_BANNER in r and "语种置信度 0.17 < 0.5" in r
    assert "抓取告警" in r


def test_render_report_audio_only_and_no_transcript():
    """纯音频文件：没有视频流/帧/看板也要出完整骨架，不能崩。"""
    probe = dict(FAKE_PROBE, video=None, name="a.wav")
    r = dv.render_report(probe, None, None, [], [], 0.5, ["无视频流：跳过抽帧与帧看板"])
    assert "无视频流" in r and "（无看板：没抽到帧）" in r and "## 5. 建议（人工填写）" in r


def test_render_report_escapes_pipe_in_text():
    """转写文本里的 | 会撕烂 markdown 表格，必须转义。"""
    r = dv.render_report(FAKE_PROBE,
                         {"language": "zh", "language_probability": 0.9,
                          "segments": [{"start": 0, "end": 1, "text": "A|B"}]},
                         {"suspect": False, "reasons": []}, [], [], 0.5)
    assert "A\\|B" in r


def test_fmt_ts():
    assert dv._fmt_ts(0) == "00:00.0" and dv._fmt_ts(65.4) == "01:05.4"
    assert dv._fmt_ts(None) == "--:--"


# ---------------------------------------------------------------- CLI

def test_cli_help_runs():
    p = subprocess.run([sys.executable, str(SCRIPT), "--help"],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    for flag in ("--out", "--fps", "--no-asr", "--frame-width"):
        assert flag in p.stdout, f"--help 没提到 {flag}"


def test_cli_missing_file_reports_failure(tmp_path):
    """不存在的输入必须如实记账 + exit 1（绝不静默当成功）。"""
    p = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path / "nope.mp4"),
                        "--out", str(tmp_path / "out"), "--no-asr"],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 1
    summary = json.loads(p.stdout)
    assert summary["failed"] == 1 and summary["results"][0]["ok"] is False
    assert summary["results"][0]["error"] == "文件不存在"


def test_cli_rejects_bad_fps(tmp_path):
    p = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path / "x.mp4"), "--fps", "0"],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 2 and "--fps" in p.stderr
