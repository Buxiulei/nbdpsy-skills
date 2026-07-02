import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "xiaohongshu-creator" / "scripts" / "check_compliance.py"
FIXTURE = Path(__file__).parent / "fixtures" / "note.md"

def test_fixture_clean():
    r = subprocess.run([sys.executable, str(SCRIPT), str(FIXTURE)], capture_output=True, text=True)
    assert r.returncode == 0 and json.loads(r.stdout)["ok"] is True

def test_violation_detected(tmp_path):
    # "治愈你"（治愈 后接窄口径字符"你"）+ "加微信" 两处违规
    bad = FIXTURE.read_text(encoding="utf-8").replace("## 发布文案（复制这一段直接发布）\n\n姐妹", "## 发布文案（复制这一段直接发布）\n\n本方法可治愈你的创伤，加微信咨询。\n\n姐妹", 1)
    f = tmp_path / "bad.md"; f.write_text(bad, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True)
    d = json.loads(r.stdout)
    assert r.returncode == 1 and len(d["violations"]) >= 2   # 治愈你 + 微信

def test_fenced_prompt_not_scanned(tmp_path):
    bad = FIXTURE.read_text(encoding="utf-8") + "\n```\n画面中不要出现二维码和微信\n```\n"
    f = tmp_path / "b.md"; f.write_text(bad, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True)
    assert r.returncode == 0   # 围栏内负向指令不误伤

def test_zhengwen_alias_not_bypassed(tmp_path):
    """"## 正文"（旧别名标题）下的违规内容必须被扫描，不能因为只认"## 发布文案"而绕过。"""
    bad = "## 正文\n\n加微信咨询详情。\n\n本文为心理科普，援助热线 12356。\n"
    f = tmp_path / "zhengwen.md"; f.write_text(bad, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True)
    d = json.loads(r.stdout)
    assert r.returncode == 1
    assert any(v["rule"] == "站外导流" for v in d["violations"])

def test_missing_section_falls_back_to_full_scan(tmp_path):
    """完全没有"## 发布文案"/"## 正文"标题时，退化为全文扫描，不静默判全绿（合规兜底闸）。"""
    bad = "# 标题\n\n加微信咨询详情。\n\n12356\n"
    f = tmp_path / "no_section.md"; f.write_text(bad, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True)
    d = json.loads(r.stdout)
    assert r.returncode == 1
    assert any(v["rule"] == "站外导流" for v in d["violations"])
    assert "降级" in r.stderr

def test_healing_style_not_flagged(tmp_path):
    """"治愈系插画风格"（治愈 后接的字不在窄口径集合内）不应被误判违规。"""
    bad = FIXTURE.read_text(encoding="utf-8").replace(
        "## 发布文案（复制这一段直接发布）\n\n姐妹",
        "## 发布文案（复制这一段直接发布）\n\n姐妹（配图为治愈系插画风格）",
        1,
    )
    f = tmp_path / "style.md"; f.write_text(bad, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True)
    d = json.loads(r.stdout)
    assert r.returncode == 0 and d["ok"] is True

def test_healing_trauma_flagged(tmp_path):
    """"治愈了创伤"应命中医疗违禁窄口径。"""
    bad = FIXTURE.read_text(encoding="utf-8").replace(
        "## 发布文案（复制这一段直接发布）\n\n姐妹",
        "## 发布文案（复制这一段直接发布）\n\n本方法治愈了创伤。\n\n姐妹",
        1,
    )
    f = tmp_path / "trauma.md"; f.write_text(bad, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True)
    d = json.loads(r.stdout)
    assert r.returncode == 1 and any(v["rule"] == "医疗违禁" for v in d["violations"])

def test_missing_crisis_declaration(tmp_path):
    """全文（去围栏后）都没有 12356 → crisis_ok=false 且 ok=false（exit 1）。"""
    bad = FIXTURE.read_text(encoding="utf-8").replace("12356", "95511")
    f = tmp_path / "no_crisis.md"; f.write_text(bad, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True)
    d = json.loads(r.stdout)
    assert r.returncode == 1 and d["crisis_ok"] is False and d["ok"] is False

def test_violation_line_matches_file(tmp_path):
    """violations 的 line 字段应等于注入违规句在原文件中的真实 1-based 行号。"""
    lines = FIXTURE.read_text(encoding="utf-8").split("\n")
    marker = "本方法治愈了创伤，加微信咨询。"
    idx = next(i for i, l in enumerate(lines) if l.startswith("## 发布文案")) + 1
    lines.insert(idx, marker)
    bad = "\n".join(lines)
    expected_line = idx + 1   # 0-based 插入位置 -> 1-based 行号
    f = tmp_path / "lineno.md"; f.write_text(bad, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True)
    d = json.loads(r.stdout)
    matched = [v for v in d["violations"] if v["text"] == marker]
    assert matched and matched[0]["line"] == expected_line

def test_wechat_bare_word_variant_flagged(tmp_path):
    """"加我的微信好友"（不含固定搭配"加微信"/"微信号"）应被裸词"微信"兜底命中——
    对抗自检发现的漏报：原词表只认固定搭配，这类变体零命中。"""
    bad = FIXTURE.read_text(encoding="utf-8").replace(
        "## 发布文案（复制这一段直接发布）\n\n姐妹",
        "## 发布文案（复制这一段直接发布）\n\n加我的微信好友聊聊，我的微信是：xxx。\n\n姐妹",
        1,
    )
    f = tmp_path / "wechat_variant.md"; f.write_text(bad, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True)
    d = json.loads(r.stdout)
    assert r.returncode == 1
    assert any(v["rule"] == "站外导流" for v in d["violations"])

def test_carousel_page_text_scanned(tmp_path):
    """"## 配图轮播"下 "### PN 页面文字"（围栏外）里的违禁词必须被扫到——
    这段文字会逐字渲染进对外公开的配图，只扫"## 发布文案"会漏（对抗自检发现的盲区）。"""
    bad = FIXTURE.read_text(encoding="utf-8").replace(
        "### P1 · 封面\n**页面文字**\n",
        "### P1 · 封面\n**页面文字**\n- 联系方式：加我的微信好友咨询\n",
        1,
    )
    f = tmp_path / "carousel.md"; f.write_text(bad, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True)
    d = json.loads(r.stdout)
    assert r.returncode == 1
    assert any(v["rule"] == "站外导流" for v in d["violations"])

def test_carousel_prompt_fence_still_not_scanned(tmp_path):
    """违禁词若只写在"## 配图轮播"内围栏绘图提示词里（如负向指令），仍应跳过——
    扫描范围扩展到配图轮播不改变围栏排除语义（防误伤负向指令）。"""
    bad = FIXTURE.read_text(encoding="utf-8").replace(
        "柔和扁平矢量插画风", "画面中不要出现微信号或二维码。柔和扁平矢量插画风", 1)
    f = tmp_path / "carousel_fence.md"; f.write_text(bad, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True)
    d = json.loads(r.stdout)
    assert r.returncode == 0 and d["ok"] is True

def test_missing_file_errors_to_stdout(tmp_path):
    missing = tmp_path / "does_not_exist.md"
    r = subprocess.run([sys.executable, str(SCRIPT), str(missing)], capture_output=True, text=True)
    d = json.loads(r.stdout)          # 错误 JSON 打 stdout，而非 stderr
    assert r.returncode == 2 and "error" in d and r.stderr.strip() != ""
