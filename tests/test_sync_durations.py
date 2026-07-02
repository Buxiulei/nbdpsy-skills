import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "text-to-video" / "scripts"))

def make_shots(tmp_path, n=2):
    d = {"video": {"ratio": "9:16"}, "shots": [{"index": i+1, "duration": None} for i in range(n)]}
    p = tmp_path / "shots.json"; p.write_text(json.dumps(d), encoding="utf-8"); return p

def test_writes_back_clamped(tmp_path, monkeypatch):
    import sync_durations
    monkeypatch.setattr(sync_durations, "probe_duration", lambda f: {"narr-01.mp3": 2.0, "narr-02.mp3": 9.4}[f.name])
    audio = tmp_path / "a"; audio.mkdir()
    for n in ("narr-01.mp3", "narr-02.mp3"): (audio / n).write_bytes(b"x")
    shots = make_shots(tmp_path)
    report = sync_durations.run(shots, audio, min_d=4, max_d=15)
    d = json.loads(shots.read_text(encoding="utf-8"))
    assert d["shots"][0]["duration"] == 4.0      # 2.0+0.3 clamp 到下限 4
    assert d["shots"][1]["duration"] == 9.7
    assert report["ok"] is True

def test_overflow_flagged(tmp_path, monkeypatch):
    import sync_durations
    monkeypatch.setattr(sync_durations, "probe_duration", lambda f: 20.0)
    audio = tmp_path / "a"; audio.mkdir(); (audio / "narr-01.mp3").write_bytes(b"x")
    shots = make_shots(tmp_path, 1)
    report = sync_durations.run(shots, audio, min_d=4, max_d=15)
    assert report["overflow"] and report["ok"] is False

def test_missing_audio_file(tmp_path, monkeypatch):
    import sync_durations
    monkeypatch.setattr(sync_durations, "probe_duration", lambda f: 2.0)
    audio = tmp_path / "a"; audio.mkdir()
    shots = make_shots(tmp_path, 2)
    # narr-01.mp3 存在，narr-02.mp3 缺失
    (audio / "narr-01.mp3").write_bytes(b"x")
    report = sync_durations.run(shots, audio, min_d=4, max_d=15)
    assert 2 in report["missing"]
    assert report["ok"] is False
    d = json.loads(shots.read_text(encoding="utf-8"))
    # 存在的应该被更新，缺失的保持原状
    assert d["shots"][0]["duration"] == 4.0
    assert d["shots"][1]["duration"] is None

def test_probe_duration_real(tmp_path):
    """真实 ffprobe 冒烟测试（本机有 ffprobe 才能跑）。"""
    import subprocess
    try:
        subprocess.run(["ffprobe", "-version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        # 跳过，如果 ffprobe 不可用
        return

    import sync_durations

    # 生成 2 秒的正弦波音频
    audio_file = tmp_path / "test_2sec.mp3"
    subprocess.run([
        "ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-q:a", "9",
        str(audio_file),
    ], capture_output=True, check=True)

    # 验证 probe_duration 能正确读取
    duration = sync_durations.probe_duration(audio_file)
    assert abs(duration - 2.0) < 0.1  # 允许小的浮点误差
