import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

SCRIPT = Path(__file__).parent.parent / "content-reviewer" / "scripts" / "check_images.py"


def _make_png(path: Path, w: int, h: int) -> None:
    Image.new("RGB", (w, h), (168, 181, 196)).save(path)


def _run(img_dir, pages: int):
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--dir", str(img_dir), "--pages", str(pages)],
        capture_output=True, text=True)
    return r, json.loads(r.stdout)


def test_wrong_size_and_missing_page(tmp_path):
    """brief 指定场景：1080×1440 合格 + 500×500 不合格，--pages 3 报缺 P03。"""
    _make_png(tmp_path / "P01.png", 1080, 1440)
    _make_png(tmp_path / "P02.png", 500, 500)

    r, report = _run(tmp_path, 3)
    assert r.returncode == 1
    assert report["ok"] is False
    assert report["found"] == 2
    assert report["expected"] == 3
    assert report["missing"] == ["P03"]
    assert len(report["wrong_size"]) == 1
    bad = report["wrong_size"][0]
    assert bad["file"] == "P02.png"
    assert bad["w"] == 500
    assert bad["h"] == 500


def test_all_good_exit_zero(tmp_path):
    for n in range(1, 4):
        _make_png(tmp_path / f"P{n:02d}.png", 1080, 1440)

    r, report = _run(tmp_path, 3)
    assert r.returncode == 0, r.stdout + r.stderr
    assert report["ok"] is True
    assert report["found"] == 3
    assert report["expected"] == 3
    assert report["missing"] == []
    assert report["wrong_size"] == []


def test_aspect_tolerance_two_percent(tmp_path):
    # 1090×1440 → 比例偏差约 0.9%，容差内应通过
    _make_png(tmp_path / "P01.png", 1090, 1440)
    # 1080×1500 → 比例偏差 4%，超出 ±2% 容差
    _make_png(tmp_path / "P02.png", 1080, 1500)

    r, report = _run(tmp_path, 2)
    assert r.returncode == 1
    assert [x["file"] for x in report["wrong_size"]] == ["P02.png"]


def test_min_short_side_1080(tmp_path):
    # 810×1080：3:4 比例完美，但最短边 810 < 1080 → 不合格
    _make_png(tmp_path / "P01.png", 810, 1080)

    r, report = _run(tmp_path, 1)
    assert r.returncode == 1
    assert report["ok"] is False
    assert [x["file"] for x in report["wrong_size"]] == ["P01.png"]
    assert report["missing"] == []


def test_page_number_from_loose_filenames(tmp_path):
    """页号识别：cptsd-p1-cover.png / 02.png 均应映射到页。"""
    _make_png(tmp_path / "cptsd-p1-cover.png", 1080, 1440)
    _make_png(tmp_path / "02.png", 1080, 1440)

    r, report = _run(tmp_path, 2)
    assert r.returncode == 0, r.stdout + r.stderr
    assert report["ok"] is True
    assert report["missing"] == []


def test_missing_dir_exit_two(tmp_path):
    r, report = _run(tmp_path / "nope", 3)
    assert r.returncode == 2
    assert "error" in report


def test_empty_dir_not_ok(tmp_path):
    r, report = _run(tmp_path, 2)
    assert r.returncode == 1
    assert report["ok"] is False
    assert report["found"] == 0
    assert report["missing"] == ["P01", "P02"]


def test_stdout_is_pure_json(tmp_path):
    _make_png(tmp_path / "P01.png", 1080, 1440)
    r, _ = _run(tmp_path, 1)
    json.loads(r.stdout.strip())  # stdout 只有 JSON，无杂质
