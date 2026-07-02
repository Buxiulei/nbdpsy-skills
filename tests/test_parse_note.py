import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "text-to-video" / "scripts" / "parse_note.py"
FIXTURE = Path(__file__).parent / "fixtures" / "note.md"


def test_parses_pages_to_shots(tmp_path):
    out = tmp_path / "shots.json"
    r = subprocess.run(
        [sys.executable, str(SCRIPT), str(FIXTURE), "--out", str(out)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["video"]["ratio"] == "9:16" and len(d["shots"]) >= 6
    s1 = d["shots"][0]
    assert s1["index"] == 1 and s1["prompt"] and s1["narration_text"] and s1["duration"] is None


def test_images_mapping(tmp_path):
    imgs = tmp_path / "images"
    imgs.mkdir()
    (imgs / "P1.png").write_bytes(b"x")
    (imgs / "P02.png").write_bytes(b"x")
    out = tmp_path / "shots.json"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(FIXTURE),
            "--images-dir",
            str(imgs),
            "--out",
            str(out),
        ],
        check=True,
        capture_output=True,
    )
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["shots"][0]["image"].endswith("P1.png")
    assert d["shots"][1]["image"].endswith("P02.png")
    assert d["shots"][2]["image"] is None
