"""母带响度归一共享模块的测试 —— **拿真 ffmpeg 跑、量真成品**，不 mock。

⛔ 不用 mock 的理由：这次事故的形状就是「代码看着对、成品没归一」。mock 掉 ffmpeg 的
测试对这类问题一律绿，等于没测。所以这里全部真跑真量（素材是几秒的合成正弦波，很快）。
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent / "nbdpsy-text-to-video" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import audio_master as am  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="需要 ffmpeg")


def _tone(path: Path, *, seconds=3.0, gain_db=-6, freq=300, channels=1):
    """造一段刻意偏安静的「口播」，模拟 TTS 的 −28 LUFS 量级原始电平。"""
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", f"sine=frequency={freq}:duration={seconds}:sample_rate=48000",
                    "-af", f"volume={gain_db}dB", "-ar", "48000", "-ac", str(channels),
                    "-c:a", "pcm_s16le", str(path)], check=True)
    return path


def _silence(path: Path, seconds=2.0):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", f"anullsrc=r=48000:cl=mono:d={seconds}",
                    "-t", str(seconds), "-c:a", "pcm_s16le", str(path)], check=True)
    return path


def _video_with(audio: Path, out: Path):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "color=c=black:s=320x240:d=3:r=15", "-i", str(audio),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", str(out)], check=True)
    return out


# ---------- 量具 ----------

def test_loudness_stats_reads_quiet_source(tmp_path):
    stats = am.loudness_stats(_tone(tmp_path / "q.wav"))
    assert -35 < stats["i"] < -20          # 刻意做安静的素材
    assert set(stats) == {"i", "tp", "lra", "thresh", "offset"}


def test_loudness_stats_survives_silence(tmp_path):
    """全静音时 loudnorm 吐 -inf；必须回落成有限值，否则第二遍会被 ffmpeg 拒参数。"""
    stats = am.loudness_stats(_silence(tmp_path / "s.wav"))
    assert stats["i"] == -70.0 and stats["tp"] == -99.0


def test_loudness_stats_raises_on_unreadable(tmp_path):
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not audio")
    with pytest.raises(RuntimeError, match="读不到"):
        am.loudness_stats(bad)


def test_loudnorm_filter_is_two_pass_linear():
    """第二遍必须带上第一遍的 measured_* 且 linear=true——单遍是流式自适应，片头响度会飘。"""
    f = am.loudnorm_filter({"i": -28.0, "tp": -22.0, "lra": 2.0, "thresh": -38.0,
                            "offset": 0.1}, target=-16.0)
    for token in ("measured_I=-28.00", "measured_TP=-22.00", "measured_LRA=2.00",
                  "measured_thresh=-38.00", "offset=0.10", "linear=true", "I=-16.00"):
        assert token in f, token


# ---------- 母带归一：量成品，不量中间文件 ----------

def test_master_audio_hits_target(tmp_path):
    src, dst = _tone(tmp_path / "n.wav"), tmp_path / "out.m4a"
    am.master_audio(src, dst, target=-16.0)
    assert abs(am.loudness(dst) - (-16.0)) <= am.LUFS_TOLERANCE


def test_master_audio_lifts_quiet_source_by_a_lot(tmp_path):
    """事故的核心判据：安静源必须被**抬上来**，不是只做个样子。"""
    src, dst = _tone(tmp_path / "n.wav", gain_db=-20), tmp_path / "out.m4a"
    before = am.loudness(src)
    info = am.master_audio(src, dst, target=-16.0)
    assert info["gain_db"] > 10
    assert am.loudness(dst) - before > 10


def test_master_video_copies_video_and_normalizes_audio(tmp_path):
    src = _video_with(_tone(tmp_path / "n.wav"), tmp_path / "in.mp4")
    dst = tmp_path / "out.mp4"
    info = am.master_video(src, dst, target=-16.0)
    assert "skipped" not in info
    assert abs(am.loudness(dst) - (-16.0)) <= am.LUFS_TOLERANCE
    # A3：48 kHz / 双声道 / AAC
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
                            "-show_entries", "stream=codec_name,channels,sample_rate",
                            "-of", "default=nw=1", str(dst)],
                           capture_output=True, text=True).stdout
    assert "codec_name=aac" in probe and "channels=2" in probe and "sample_rate=48000" in probe


def test_master_video_skips_silence_but_still_writes_output(tmp_path):
    """近乎全静音时跳过归一（否则底噪被抬 54 dB），但**片子照出**——
    静默跳过和不出片都是错的：一个把 bug 放回来，一个把合成假报成失败。"""
    src = _video_with(_silence(tmp_path / "s.wav"), tmp_path / "in.mp4")
    dst = tmp_path / "out.mp4"
    info = am.master_video(src, dst, target=-16.0)
    assert info["skipped"] == "silent" and info["gain_db"] == 0.0
    assert dst.is_file() and dst.stat().st_size > 0


# ---------- 收尾自检必须能证伪 ----------

def test_verify_master_passes_normalized(tmp_path):
    src, dst = _tone(tmp_path / "n.wav"), tmp_path / "out.m4a"
    am.master_audio(src, dst, target=-16.0)
    assert am.verify_master(dst, target=-16.0)["passed"] is True


def test_verify_master_fails_unnormalized(tmp_path):
    """没归一的片子必须报红——自检要是对未归一的也报绿，它就不是闸门。"""
    v = am.verify_master(_tone(tmp_path / "n.wav", gain_db=-20), target=-16.0)
    assert v["passed"] is False
    assert "母带响度" in v["checks"][0][0]


# ---------- BGM 相对压低（与母带是两件事） ----------

def test_prepare_bgm_ducks_below_narration_and_reads_back(tmp_path):
    bgm = _tone(tmp_path / "bgm.wav", seconds=30.0, gain_db=-10, freq=440, channels=2)
    out, got = am.prepare_bgm(str(bgm), 25.0, tmp_path, narration_lufs=-28.0, duck_db=14.0)
    assert out.is_file()
    # 回读实测（不是"目标写了多少"）；两端 1.5s 淡化会把 integrated 拉低一点点
    assert abs(got - (-42.0)) <= 1.0
    assert abs(am.loudness(out) - got) < 0.01


def test_prepare_bgm_guard_trips_on_very_short_films(tmp_path):
    """⚠️ 已知边界（不是 bug，是量具的物理）：两端各 1.5s 淡化在**极短片**上占比过大，
    把 integrated 拉低超过 1 LU，回读闸门就会拒跑。实测拐点在 ~10s：
    5s 差 −1.53 / 8s 差 −1.06 / 12s 差 −0.66 / 40s 差 −0.15。
    ⛔ 不要为此放宽阈值——阈值是用来抓「立体声下混白丢 3 dB」那类真隐性损失的。
    本产线成片是 1–3 分钟量级，正常不会撞到；真要做 <10s 带 BGM 的片子，改淡化时长。"""
    bgm = _tone(tmp_path / "bgm.wav", seconds=10.0, gain_db=-10, freq=440, channels=2)
    with pytest.raises(RuntimeError, match="BGM 归一没打准"):
        am.prepare_bgm(str(bgm), 5.0, tmp_path, narration_lufs=-28.0, duck_db=14.0)


def test_prepare_bgm_rejects_out_of_range_target(tmp_path):
    """⚠️ 拿全静音旁白（−70）去减 duck 会算出 −82，超出 loudnorm 的 I 取值范围 [−70,−5]。
    ffmpeg 报的是一句看不懂的 "Numerical result out of range"，所以调用方必须先特判
    「没有旁白」（compose_video.finalize 按纯气氛片处理），⛔ 别把这个值直接送进来。"""
    bgm = _tone(tmp_path / "bgm.wav", seconds=30.0, gain_db=-10, freq=440, channels=2)
    with pytest.raises(RuntimeError, match="读不到"):
        am.prepare_bgm(str(bgm), 25.0, tmp_path, narration_lufs=-70.0, duck_db=12.0)


def test_prepare_bgm_rejects_missing_file(tmp_path):
    with pytest.raises(RuntimeError, match="BGM 文件不存在"):
        am.prepare_bgm(str(tmp_path / "nope.mp3"), 5.0, tmp_path,
                       narration_lufs=-28.0, duck_db=14.0)


# ---------- 形态分档 ----------

def test_bgm_duck_default_is_shared_by_every_form():
    """🩸 BGM 压差默认值只许有一个来源。

    2026-08-17 之前轮播线用 14、微电影线用 12，**同一个老板会听到一响一不响的两个形态**——
    上一次事故的形状就是「修复只落在他点名的那个形态上」，两个默认值分开写就是让它再发生一次。
    ⛔ 谁要在自己脚本里写死另一个数，这条测试就该红。
    （14 是老板 2026-08-16 实听从 18 调下来的，改它要重新实听，不是改测试。）
    """
    import inspect

    import compose_video

    assert am.BGM_DUCK_LU == 14.0
    assert inspect.signature(compose_video.finalize).parameters["bgm_gap_db"].default \
        == am.BGM_DUCK_LU
    # slideshow 的 --bgm-duck 默认值建在 main() 的 argparse 里，取不到对象；
    # 这里直接查源码：只要它引用的是常量而不是又写一个字面量，就不会再漂。
    src = (SCRIPTS / "slideshow_video.py").read_text(encoding="utf-8")
    assert "default=audio_master.BGM_DUCK_LU" in src
    assert "--bgm-duck" in src


def test_form_targets_cover_all_four_outputs():
    """四条合成出口各有一档位。当前同值 −16（调研结论：不按时长分档，按投放渠道分档）。"""
    assert set(am.FORM_TARGETS) == {"slideshow", "microfilm", "card", "podcast"}
    assert set(am.FORM_TARGETS.values()) == {-16.0}
