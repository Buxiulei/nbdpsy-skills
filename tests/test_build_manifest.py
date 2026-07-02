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
    (tmp_path / "narr-01.cues.json").write_text(
        json.dumps({"duration": 6.5, "cues": [{"text": "第一句。", "start": 0.0, "end": 3.0}]}),
        encoding="utf-8")
    # shot 2 故意不生成 narr-02.cues.json —— 覆盖「cues 缺失」分支

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
    assert seg1["cues"].endswith("narr-01.cues.json")
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
