import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "content-reviewer" / "scripts"))

SCRIPT = Path(__file__).parent.parent / "content-reviewer" / "scripts" / "check_video.py"


def _write_cues(path: Path, cues: list[dict], duration: float | None = None) -> None:
    payload = {"cues": cues}
    if duration is not None:
        payload["duration"] = duration
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _make_shot(workdir: Path, nn: str, *, narr: bool = True, cues: list[dict] | None = None,
               cues_name: str | None = None) -> None:
    (workdir / f"shot-{nn}.mp4").write_bytes(b"x")
    if narr:
        (workdir / f"narr-{nn}.mp3").write_bytes(b"x")
    if cues is not None:
        name = cues_name or f"narr-{nn}.mp3.cues.json"
        _write_cues(workdir / name, cues)


def _patch_probe(monkeypatch, durations: dict[str, float]):
    """按文件名映射 ffprobe 实测时长，杜绝真实调用。"""
    import check_video

    def fake(path: Path) -> float:
        return durations[Path(path).name]

    monkeypatch.setattr(check_video, "probe_duration", fake)
    return check_video


GOOD_CUES = [
    {"text": "第一句。", "start": 0.0, "end": 3.0},
    {"text": "第二句。", "start": 3.0, "end": 5.8},
]


def test_happy_path_all_green(tmp_path, monkeypatch):
    cv = _patch_probe(monkeypatch, {
        "shot-01.mp4": 6.0, "shot-02.mp4": 8.0,
        "narr-01.mp3": 5.8, "narr-02.mp3": 7.9,
        "final.mp4": 14.0,
    })
    _make_shot(tmp_path, "01", cues=GOOD_CUES)
    _make_shot(tmp_path, "02", cues=[{"text": "第三句。", "start": 0.0, "end": 7.8}])
    (tmp_path / "final.mp4").write_bytes(b"x")

    report = cv.run(tmp_path, total_min=10, total_max=180)
    assert report["ok"] is True, report
    assert report["shots"] == 2
    assert report["final_exists"] is True
    assert report["total_sec"] == 14.0
    assert report["duration_violations"] == []
    assert report["cues_issues"] == []
    assert report["missing"] == []


def test_shot_duration_out_of_range(tmp_path, monkeypatch):
    """每镜实测须 ∈[4,15]±0.5s：20s 与 2s 都要抓出来。"""
    cv = _patch_probe(monkeypatch, {
        "shot-01.mp4": 20.0, "shot-02.mp4": 2.0,
        "narr-01.mp3": 19.0, "narr-02.mp3": 1.8,
        "final.mp4": 22.0,
    })
    _make_shot(tmp_path, "01", cues=[{"text": "长。", "start": 0.0, "end": 18.9}])
    _make_shot(tmp_path, "02", cues=[{"text": "短。", "start": 0.0, "end": 1.7}])
    (tmp_path / "final.mp4").write_bytes(b"x")

    report = cv.run(tmp_path, total_min=10, total_max=180)
    assert report["ok"] is False
    violated = {v["shot"] for v in report["duration_violations"]}
    assert "01" in violated and "02" in violated


def test_shot_duration_tolerance_half_second(tmp_path, monkeypatch):
    """边界：15.4s 在 15±0.5 容差内，不算违规。"""
    cv = _patch_probe(monkeypatch, {
        "shot-01.mp4": 15.4, "narr-01.mp3": 15.0, "final.mp4": 15.4,
    })
    _make_shot(tmp_path, "01", cues=[{"text": "句。", "start": 0.0, "end": 14.9}])
    (tmp_path / "final.mp4").write_bytes(b"x")

    report = cv.run(tmp_path, total_min=10, total_max=180)
    assert report["duration_violations"] == []
    assert report["ok"] is True


def test_missing_gap_shot_and_missing_narr(tmp_path, monkeypatch):
    """编号断档（缺 shot-02.mp4）与缺旁白（narr-01.mp3）都进 missing。"""
    cv = _patch_probe(monkeypatch, {
        "shot-01.mp4": 6.0, "shot-03.mp4": 6.0,
        "narr-03.mp3": 5.8, "final.mp4": 12.0,
    })
    _make_shot(tmp_path, "01", narr=False)
    _make_shot(tmp_path, "03", cues=[{"text": "句。", "start": 0.0, "end": 5.7}])
    (tmp_path / "final.mp4").write_bytes(b"x")

    report = cv.run(tmp_path, total_min=10, total_max=180)
    assert report["ok"] is False
    assert "shot-02.mp4" in report["missing"]
    assert "narr-01.mp3" in report["missing"]


def test_cues_missing_flagged(tmp_path, monkeypatch):
    cv = _patch_probe(monkeypatch, {
        "shot-01.mp4": 6.0, "narr-01.mp3": 5.8, "final.mp4": 6.0,
    })
    _make_shot(tmp_path, "01")  # 不写 cues
    (tmp_path / "final.mp4").write_bytes(b"x")

    report = cv.run(tmp_path, total_min=5, total_max=180)
    assert report["ok"] is False
    assert any(i["shot"] == "01" and i["type"] == "cues_missing" for i in report["cues_issues"])


def test_cues_old_naming_fallback(tmp_path, monkeypatch):
    """兜底旧名 narr-NN.cues.json 应被识别，不报 cues_missing。"""
    cv = _patch_probe(monkeypatch, {
        "shot-01.mp4": 6.0, "narr-01.mp3": 5.8, "final.mp4": 6.0,
    })
    _make_shot(tmp_path, "01", cues=GOOD_CUES, cues_name="narr-01.cues.json")
    (tmp_path / "final.mp4").write_bytes(b"x")

    report = cv.run(tmp_path, total_min=5, total_max=180)
    assert report["cues_issues"] == []
    assert report["ok"] is True


def test_cues_not_monotonic(tmp_path, monkeypatch):
    cv = _patch_probe(monkeypatch, {
        "shot-01.mp4": 6.0, "narr-01.mp3": 5.8, "final.mp4": 6.0,
    })
    bad = [
        {"text": "第一句。", "start": 0.0, "end": 3.0},
        {"text": "第二句。", "start": 2.0, "end": 5.0},  # start 回退到上句结束之前
    ]
    _make_shot(tmp_path, "01", cues=bad)
    (tmp_path / "final.mp4").write_bytes(b"x")

    report = cv.run(tmp_path, total_min=5, total_max=180)
    assert report["ok"] is False
    assert any(i["shot"] == "01" and i["type"] == "not_monotonic" for i in report["cues_issues"])


def test_cues_tail_exceeds_narration(tmp_path, monkeypatch):
    """末句 end 超过旁白实测时长 +0.2s → 字幕悬空。"""
    cv = _patch_probe(monkeypatch, {
        "shot-01.mp4": 6.0, "narr-01.mp3": 5.0, "final.mp4": 6.0,
    })
    _make_shot(tmp_path, "01", cues=[{"text": "句。", "start": 0.0, "end": 5.5}])
    (tmp_path / "final.mp4").write_bytes(b"x")

    report = cv.run(tmp_path, total_min=5, total_max=180)
    assert report["ok"] is False
    assert any(i["shot"] == "01" and i["type"] == "tail_exceeds_narration"
               for i in report["cues_issues"])


def test_final_duration_mismatch(tmp_path, monkeypatch):
    """final.mp4 实测须 ≈ Σ每镜时长 ±10%：Σ=12 而 final=20 → 违规。"""
    cv = _patch_probe(monkeypatch, {
        "shot-01.mp4": 6.0, "shot-02.mp4": 6.0,
        "narr-01.mp3": 5.8, "narr-02.mp3": 5.8,
        "final.mp4": 20.0,
    })
    _make_shot(tmp_path, "01", cues=[{"text": "句。", "start": 0.0, "end": 5.7}])
    _make_shot(tmp_path, "02", cues=[{"text": "句。", "start": 0.0, "end": 5.7}])
    (tmp_path / "final.mp4").write_bytes(b"x")

    report = cv.run(tmp_path, total_min=10, total_max=180)
    assert report["ok"] is False
    assert any(v["shot"] == "final" for v in report["duration_violations"])


def test_final_missing_not_ok(tmp_path, monkeypatch):
    cv = _patch_probe(monkeypatch, {"shot-01.mp4": 6.0, "narr-01.mp3": 5.8})
    _make_shot(tmp_path, "01", cues=[{"text": "句。", "start": 0.0, "end": 5.7}])

    report = cv.run(tmp_path, total_min=5, total_max=180)
    assert report["final_exists"] is False
    assert report["ok"] is False


def test_total_out_of_default_range(tmp_path, monkeypatch):
    """默认 total ∈ [30,180]：14s 的成片要被抓总时长违规。"""
    cv = _patch_probe(monkeypatch, {
        "shot-01.mp4": 6.0, "shot-02.mp4": 8.0,
        "narr-01.mp3": 5.8, "narr-02.mp3": 7.9,
        "final.mp4": 14.0,
    })
    _make_shot(tmp_path, "01", cues=[{"text": "句。", "start": 0.0, "end": 5.7}])
    _make_shot(tmp_path, "02", cues=[{"text": "句。", "start": 0.0, "end": 7.8}])
    (tmp_path / "final.mp4").write_bytes(b"x")

    report = cv.run(tmp_path, total_min=30, total_max=180)
    assert report["ok"] is False
    assert any(v["shot"] == "total" for v in report["duration_violations"])


def test_shots_json_declares_more_shots_than_files(tmp_path, monkeypatch):
    """shots.json 声明 2 镜但只有 1 镜文件 → 遍历上界须对照声明镜数补齐，
    缺的 shot-02.mp4 必须进 missing（原逻辑只按已存在文件最大序号推断上界，
    永远遍历不到 idx=2，是对抗自检抓到的盲区）。"""
    cv = _patch_probe(monkeypatch, {
        "shot-01.mp4": 6.0, "narr-01.mp3": 5.8, "final.mp4": 6.0,
    })
    (tmp_path / "shots.json").write_text(
        json.dumps({"shots": [{"index": 1}, {"index": 2}]}, ensure_ascii=False),
        encoding="utf-8")
    _make_shot(tmp_path, "01", cues=[{"text": "句。", "start": 0.0, "end": 5.7}])
    (tmp_path / "final.mp4").write_bytes(b"x")

    report = cv.run(tmp_path, total_min=5, total_max=180)
    assert report["ok"] is False
    missing_files = [m["file"] if isinstance(m, dict) else m for m in report["missing"]]
    assert "shot-02.mp4" in missing_files
    # 有 shots.json 声明时，缺件条目须附 expect 说明来源
    shot02 = next(m for m in report["missing"] if isinstance(m, dict) and m["file"] == "shot-02.mp4")
    assert "expect" in shot02


def test_no_shots_json_keeps_legacy_behavior(tmp_path, monkeypatch):
    """无 shots.json 时行为不变：遍历上界仍按已存在文件最大序号推断，
    missing 条目仍是纯文件名字符串（向后兼容）。"""
    cv = _patch_probe(monkeypatch, {
        "shot-01.mp4": 6.0, "narr-01.mp3": 5.8, "final.mp4": 6.0,
    })
    _make_shot(tmp_path, "01", cues=[{"text": "句。", "start": 0.0, "end": 5.7}])
    (tmp_path / "final.mp4").write_bytes(b"x")

    report = cv.run(tmp_path, total_min=5, total_max=180)
    assert report["ok"] is True
    assert report["missing"] == []


def test_cli_empty_workdir_valid_json_exit_one(tmp_path):
    """CLI 冒烟：空目录 0 镜、无 final → 合法 JSON、exit 1（不触发 ffprobe）。"""
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--workdir", str(tmp_path)],
        capture_output=True, text=True)
    assert r.returncode == 1
    report = json.loads(r.stdout)
    assert report["shots"] == 0
    assert report["final_exists"] is False
    assert report["ok"] is False


def test_cli_missing_workdir_exit_two(tmp_path):
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--workdir", str(tmp_path / "nope")],
        capture_output=True, text=True)
    assert r.returncode == 2
    assert "error" in json.loads(r.stdout)
