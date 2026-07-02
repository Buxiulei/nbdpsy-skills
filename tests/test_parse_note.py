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


def _write_note(tmp_path, carousel_body):
    """写一个最小可解析的笔记文件，配图轮播区块内容由调用方传入"""
    note = tmp_path / "note.md"
    note.write_text(carousel_body, encoding="utf-8")
    return note


def _run(note, tmp_path, extra_args=()):
    out = tmp_path / "shots.json"
    r = subprocess.run(
        [sys.executable, str(SCRIPT), str(note), "--out", str(out), *extra_args],
        capture_output=True,
        text=True,
    )
    return r, out


def test_inline_bold_in_narration_not_truncated(tmp_path):
    """页面文字内含内联加粗（如 "- **大标题**：说明"）不应被 lookahead 截断成空值"""
    note = _write_note(
        tmp_path,
        """## 配图轮播

### P1 · 封面
**页面文字**
- **大标题**：总说自己"想太多"？
- 副标题：也许是复杂性创伤（CPTSD）

**绘图提示词（中文，含图中文字）**
```
一段提示词内容
```
""",
    )
    r, out = _run(note, tmp_path)
    assert r.returncode == 0, r.stderr
    d = json.loads(out.read_text(encoding="utf-8"))
    s1 = d["shots"][0]
    assert s1["narration_text"], "narration_text 不应为空"
    assert "大标题" in s1["narration_text"] and "总说自己" in s1["narration_text"]
    assert "副标题" in s1["narration_text"]
    assert "warning: P1 页面文字为空" not in r.stderr


def test_missing_prompt_fence_warns_but_narration_ok(tmp_path):
    """页体缺提示词围栏：prompt 为空并有警告，narration_text 仍正确提取"""
    note = _write_note(
        tmp_path,
        """## 配图轮播

### P1 · 封面
**页面文字**
- 大标题：测试标题
- 副标题：测试副标题

**绘图提示词（中文，含图中文字）**
提示词内容但没有围栏
""",
    )
    r, out = _run(note, tmp_path)
    assert r.returncode == 0, r.stderr
    d = json.loads(out.read_text(encoding="utf-8"))
    s1 = d["shots"][0]
    assert s1["prompt"] == ""
    assert "warning: P1 无提示词" in r.stderr
    assert s1["narration_text"] == "大标题：测试标题\n副标题：测试副标题"


def test_fence_with_language_tag(tmp_path):
    """```text 语言标记围栏：prompt 应正常提取"""
    note = _write_note(
        tmp_path,
        """## 配图轮播

### P1 · 封面
**页面文字**
- 大标题：测试

**绘图提示词（中文，含图中文字）**
```text
提示词正文
```
""",
    )
    r, out = _run(note, tmp_path)
    assert r.returncode == 0, r.stderr
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["shots"][0]["prompt"] == "提示词正文"


def test_carousel_heading_with_suffix(tmp_path):
    """「## 配图轮播（6页）」带后缀应正常解析"""
    note = _write_note(
        tmp_path,
        """## 配图轮播（6页）

### P1 · 封面
**页面文字**
- 大标题：测试

**绘图提示词（中文，含图中文字）**
```
提示词正文
```
""",
    )
    r, out = _run(note, tmp_path)
    assert r.returncode == 0, r.stderr
    d = json.loads(out.read_text(encoding="utf-8"))
    assert len(d["shots"]) == 1
    assert d["shots"][0]["prompt"] == "提示词正文"


def test_out_of_order_pages(tmp_path):
    """乱序页 P3 -> P1 -> P5：index 按出现顺序 1,2,3；page 保留原始页序号 3,1,5"""
    note = _write_note(
        tmp_path,
        """## 配图轮播

### P3 · 三
**页面文字**
- 内容三

**绘图提示词**
```
提示词三
```

### P1 · 一
**页面文字**
- 内容一

**绘图提示词**
```
提示词一
```

### P5 · 五
**页面文字**
- 内容五

**绘图提示词**
```
提示词五
```
""",
    )
    r, out = _run(note, tmp_path)
    assert r.returncode == 0, r.stderr
    d = json.loads(out.read_text(encoding="utf-8"))
    shots = d["shots"]
    assert [s["index"] for s in shots] == [1, 2, 3]
    assert [s["page"] for s in shots] == [3, 1, 5]


def test_out_creates_nested_directory(tmp_path):
    """--out 指向不存在的深层目录：自动创建，成功写出"""
    note = _write_note(
        tmp_path,
        """## 配图轮播

### P1 · 封面
**页面文字**
- 大标题：测试

**绘图提示词**
```
提示词正文
```
""",
    )
    # 指向不存在的深层目录
    out = tmp_path / "deep" / "nested" / "dir" / "shots.json"
    assert not out.parent.exists(), "父目录应该不存在"

    r = subprocess.run(
        [sys.executable, str(SCRIPT), str(note), "--out", str(out)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert out.exists(), "shots.json 应该被成功创建"
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["shots"][0]["prompt"] == "提示词正文"
