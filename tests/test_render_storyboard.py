import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "text-to-video" / "scripts" / "render_storyboard.py"


def make_workdir(tmp_path, name="cptsd-01"):
    wd = tmp_path / name
    wd.mkdir()
    shots = {
        "video": {"title": "CPTSD 第一镜测试", "ratio": "9:16"},
        "shots": [
            {"index": 1, "page": 1, "prompt": "视频运镜提示词甲",
             "image_prompt": "去文字版生图提示词甲", "subtitle": "字幕一",
             "narration_text": "旁白第一句。", "image": None, "duration": None},
            {"index": 2, "page": 2, "prompt": "视频运镜提示词乙", "subtitle": "字幕二",
             "narration_text": "旁白第二句。", "image": None, "duration": 9.7},
        ],
    }
    (wd / "shots.json").write_text(json.dumps(shots, ensure_ascii=False), encoding="utf-8")
    return wd


def run(args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def test_renders_named_html(tmp_path):
    wd = make_workdir(tmp_path)
    r = run(["--workdir", str(wd)])
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["html"].endswith("cptsd-01-storyboard.html")  # 按内容命名，不叫固定名
    text = Path(out["html"]).read_text(encoding="utf-8")
    assert "镜 01" in text and "镜 02" in text
    assert "去文字版生图提示词甲" in text          # image_prompt 优先
    assert "视频运镜提示词乙" in text              # 无 image_prompt 回退 prompt
    assert "旁白第一句。" in text and "copyEl" in text
    assert "P2.png" in text                        # 缺图镜给出回传命名指引


def test_attach_images_writes_back(tmp_path):
    wd = make_workdir(tmp_path)
    imgs = wd / "images"
    imgs.mkdir()
    (imgs / "P1.png").write_bytes(b"x")
    r = run(["--workdir", str(wd), "--attach-images", str(imgs)])
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["attached"] == 1
    shots = json.loads((wd / "shots.json").read_text(encoding="utf-8"))
    assert shots["shots"][0]["image"].endswith("P1.png")
    assert shots["shots"][1]["image"] is None            # 未回传的镜不动
    assert shots["shots"][1]["duration"] == 9.7          # 其余字段原样保留


def test_empty_shots_exit1(tmp_path):
    wd = tmp_path / "empty-01"
    wd.mkdir()
    (wd / "shots.json").write_text('{"video":{},"shots":[]}', encoding="utf-8")
    r = run(["--workdir", str(wd)])
    assert r.returncode == 1 and "error" in json.loads(r.stdout)


def test_missing_shots_exit2(tmp_path):
    wd = tmp_path / "none-01"
    wd.mkdir()
    r = run(["--workdir", str(wd)])
    assert r.returncode == 2 and "error" in json.loads(r.stdout)


def test_malicious_page_field_does_not_crash_or_inject(tmp_path):
    wd = tmp_path / "evil-01"
    wd.mkdir()
    shots = {
        "video": {"title": "恶意 page 测试", "ratio": "9:16"},
        "shots": [
            {"index": 1, "page": "<img onerror=x>", "prompt": "提示词",
             "subtitle": "字幕", "narration_text": "旁白。", "image": None, "duration": None},
        ],
    }
    (wd / "shots.json").write_text(json.dumps(shots, ensure_ascii=False), encoding="utf-8")
    r = run(["--workdir", str(wd)])
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    text = Path(out["html"]).read_text(encoding="utf-8")
    assert "<img onerror=x>" not in text          # 未转义注入不得进 HTML
    assert "onerror=x" not in text
    assert "页 P1 ·" in text                       # 无法转 int 时回退用 index=1
    assert "警告" in r.stderr                       # stderr 有回退警告
