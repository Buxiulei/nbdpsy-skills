import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "text-to-video" / "scripts" / "build_manifest.py"


def _write_shots(workdir: Path, shots: list[dict]) -> None:
    (workdir / "shots.json").write_text(
        json.dumps({"video": {"title": "t", "ratio": "9:16", "source_note": "x.md"}, "shots": shots},
                   ensure_ascii=False),
        encoding="utf-8")


def _run(workdir: Path, out: Path | None = None):
    cmd = [sys.executable, str(SCRIPT), "--workdir", str(workdir)]
    if out is not None:
        cmd += ["--out", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r, json.loads(r.stdout)


def test_complete_workdir_builds_manifest(tmp_path):
    shots = [
        {"index": 1, "page": 1, "prompt": "p1", "subtitle": "第一页字幕",
         "narration_text": "第一句。第二句。", "image": None, "duration": 6.5},
        {"index": 2, "page": 2, "prompt": "p2", "subtitle": "第二页字幕",
         "narration_text": "第三句。", "image": None, "duration": None},
    ]
    _write_shots(tmp_path, shots)
    for n in ("shot-01.mp4", "shot-02.mp4", "narr-01.mp3", "narr-02.mp3", "bgm.mp3"):
        (tmp_path / n).write_bytes(b"x")
    (tmp_path / "narr-01.mp3.cues.json").write_text(
        json.dumps({"duration": 6.5, "cues": [{"text": "第一句。", "start": 0.0, "end": 3.0}]}),
        encoding="utf-8")
    # shot 2 故意不生成 narr-02.mp3.cues.json —— 覆盖「cues 缺失」分支

    r, report = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    assert report["ok"] is True
    assert report["shots"] == 2
    assert report["missing"] == []
    assert report["manifest"] == str(tmp_path / "manifest.json")

    manifest = json.loads(Path(report["manifest"]).read_text(encoding="utf-8"))
    # 顶层字段名——锁定自 compose_video.py 消费处
    assert manifest["output"]
    assert manifest["ai_label"] == "AI 生成"
    assert manifest["resolution"] == "720x1280"       # ratio 9:16 映射
    assert manifest["bgm"].endswith("bgm.mp3")
    assert len(manifest["segments"]) == 2

    seg1 = manifest["segments"][0]
    assert seg1["video"].endswith("shot-01.mp4")
    assert seg1["narration"].endswith("narr-01.mp3")
    assert seg1["cues"].endswith("narr-01.mp3.cues.json")
    assert seg1["narration_text"] == "第一句。第二句。"
    assert seg1["subtitle"] == "第一页字幕"
    assert seg1["duration"] == 6.5

    seg2 = manifest["segments"][1]
    assert seg2["video"].endswith("shot-02.mp4")
    assert seg2["narration"].endswith("narr-02.mp3")
    assert "cues" not in seg2          # 没造 narr-02.cues.json，manifest 不带该键（非 null 占位）
    assert "duration" not in seg2      # shots.json 里是 null，manifest 也不带该键


def test_missing_files_reported_and_manifest_not_written(tmp_path):
    shots = [
        {"index": 1, "page": 1, "prompt": "p1", "subtitle": "s1",
         "narration_text": "n1", "image": None, "duration": None},
        {"index": 2, "page": 2, "prompt": "p2", "subtitle": "s2",
         "narration_text": "n2", "image": None, "duration": None},
    ]
    _write_shots(tmp_path, shots)
    # 只造齐第 1 镜；第 2 镜的视频和旁白都缺
    (tmp_path / "shot-01.mp4").write_bytes(b"x")
    (tmp_path / "narr-01.mp3").write_bytes(b"x")

    r, report = _run(tmp_path)
    assert r.returncode == 1
    assert report["ok"] is False
    assert report["manifest"] is None
    assert {"index": 2, "expect": "shot-02.mp4"} in report["missing"]
    assert {"index": 2, "expect": "narr-02.mp3"} in report["missing"]
    assert not (tmp_path / "manifest.json").exists()


def test_custom_out_path(tmp_path):
    shots = [{"index": 1, "page": 1, "prompt": "p1", "subtitle": "s1",
              "narration_text": "n1", "image": None, "duration": None}]
    _write_shots(tmp_path, shots)
    (tmp_path / "shot-01.mp4").write_bytes(b"x")
    (tmp_path / "narr-01.mp3").write_bytes(b"x")
    out = tmp_path / "custom.json"

    r, report = _run(tmp_path, out=out)
    assert r.returncode == 0, r.stderr
    assert report["manifest"] == str(out)
    assert out.is_file()


def test_stderr_output_complete(tmp_path):
    """Test that stderr reports each shot and summary line."""
    workdir = tmp_path

    # Create shots.json with 2 shots
    shots_data = {
        "video": {"ratio": "9:16"},
        "shots": [
            {"index": 1, "narration_text": "Test 1", "duration": 5},
            {"index": 2, "narration_text": "Test 2", "duration": 5},
        ]
    }
    (workdir / "shots.json").write_text(json.dumps(shots_data), encoding="utf-8")

    # Create shot-01.mp4 and narr-01.mp3 only
    (workdir / "shot-01.mp4").touch()
    (workdir / "narr-01.mp3").touch()

    # Run build_manifest.py
    r, report = _run(workdir)

    stderr = r.stderr
    stdout = r.stdout

    # Check stderr has shot reports
    assert "镜01" in stderr, f"Missing shot 01 report in stderr:\n{stderr}"
    assert "镜02" in stderr, f"Missing shot 02 report in stderr:\n{stderr}"

    # Check stderr has summary
    assert "清单完成" in stderr or "manifest 已写入" in stderr, \
        f"Missing summary in stderr:\n{stderr}"

    # Check stdout is valid JSON
    assert report["ok"] == False, "Should fail (missing shot-02.mp4 and narr-02.mp3)"
    assert len(report["missing"]) == 2, f"Expected 2 missing files, got {len(report['missing'])}"


def test_stderr_output_success(tmp_path):
    """Test stderr output when all files exist."""
    workdir = tmp_path

    # Create shots.json with 1 shot
    shots_data = {
        "video": {"ratio": "9:16"},
        "shots": [
            {"index": 1, "narration_text": "Test", "duration": 5},
        ]
    }
    (workdir / "shots.json").write_text(json.dumps(shots_data), encoding="utf-8")

    # Create all required files
    (workdir / "shot-01.mp4").touch()
    (workdir / "narr-01.mp3").touch()

    # Run build_manifest.py
    r, report = _run(workdir)

    stderr = r.stderr
    stdout = r.stdout

    # Check stderr has success message
    assert "manifest 已写入" in stderr, f"Missing success message in stderr:\n{stderr}"
    assert "镜01" in stderr, f"Missing shot 01 report in stderr:\n{stderr}"

    # Check stdout is valid JSON with manifest path
    assert report["ok"] == True, f"Should succeed, got: {report}"
    assert report["manifest"] is not None, "Should have manifest path"


def test_stdout_is_pure_json(tmp_path):
    """Test that stdout contains only JSON (no stderr leakage)."""
    workdir = tmp_path

    shots_data = {
        "video": {"ratio": "9:16"},
        "shots": [
            {"index": 1, "narration_text": "Test", "duration": 5},
        ]
    }
    (workdir / "shots.json").write_text(json.dumps(shots_data), encoding="utf-8")
    (workdir / "shot-01.mp4").touch()
    (workdir / "narr-01.mp3").touch()

    r, report = _run(workdir)

    stdout = r.stdout.strip()

    # stdout should be valid JSON (no stderr pollution)
    try:
        json.loads(stdout)
    except json.JSONDecodeError as e:
        raise AssertionError(f"stdout is not valid JSON:\n{stdout}\nError: {e}")


def test_cues_fallback_to_old_naming(tmp_path):
    """Test that old cues naming narr-NN.cues.json is recognized as fallback."""
    shots = [
        {"index": 1, "page": 1, "prompt": "p1", "subtitle": "字幕",
         "narration_text": "旁白。", "image": None, "duration": 5.0},
    ]
    _write_shots(tmp_path, shots)
    for n in ("shot-01.mp4", "narr-01.mp3"):
        (tmp_path / n).write_bytes(b"x")
    # 只生成旧命名 narr-01.cues.json，不生成主命名 narr-01.mp3.cues.json
    (tmp_path / "narr-01.cues.json").write_text(
        json.dumps({"duration": 5.0, "cues": [{"text": "旁白。", "start": 0.0, "end": 5.0}]}),
        encoding="utf-8")

    r, report = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    assert report["ok"] is True
    assert report["shots"] == 1
    assert report["missing"] == []

    manifest = json.loads(Path(report["manifest"]).read_text(encoding="utf-8"))
    seg = manifest["segments"][0]
    # 应该成功识别兜底的旧命名
    assert "cues" in seg
    assert seg["cues"].endswith("narr-01.cues.json")
