import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts" / "check_compliance.py"
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

def test_no_crisis_skips_crisis_but_still_flags_violations(tmp_path):
    """--no-crisis（咨询师推介场景）：缺危机声明不判 FAIL，但违禁词仍一票否决。
    构造无 12356 且含站外导流「加微信」的文档——不带 --no-crisis 应 fail（缺声明+违禁词），
    带 --no-crisis 仍 fail（违禁词未被放过），证明豁免只跳过危机声明、不弄坏违禁词闸。"""
    bad = "## 发布文案\n\n黄老师擅长原生家庭创伤，加微信预约。\n"
    f = tmp_path / "no_crisis_scene.md"; f.write_text(bad, encoding="utf-8")
    # 带 --no-crisis：crisis 不再要求，但站外导流仍命中 → ok=false
    r = subprocess.run([sys.executable, str(SCRIPT), str(f), "--no-crisis"],
                       capture_output=True, text=True)
    d = json.loads(r.stdout)
    assert r.returncode == 1
    assert d["crisis_required"] is False
    assert d["ok"] is False
    assert any(v["rule"] == "站外导流" for v in d["violations"])


def test_no_crisis_passes_clean_note_without_declaration(tmp_path):
    """--no-crisis：一篇无 12356、无违禁词的干净推介文，应判 ok=true（危机声明被豁免）；
    同一文档不带 --no-crisis 应因缺声明 fail（证明科普场景的危机声明闸未被弄坏）。"""
    clean = "## 发布文案\n\n黄安麟老师，北大临床心理硕士，擅长复杂性创伤 CPTSD 的疗愈工作。\n"
    f = tmp_path / "clean_intro.md"; f.write_text(clean, encoding="utf-8")
    # 带 --no-crisis → 豁免危机声明 → ok=true
    r1 = subprocess.run([sys.executable, str(SCRIPT), str(f), "--no-crisis"],
                        capture_output=True, text=True)
    d1 = json.loads(r1.stdout)
    assert r1.returncode == 0 and d1["ok"] is True and d1["crisis_required"] is False
    # 不带 --no-crisis → 科普场景仍要求 12356 → 缺声明 fail
    r2 = subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True)
    d2 = json.loads(r2.stdout)
    assert r2.returncode == 1 and d2["crisis_ok"] is False and d2["ok"] is False


def test_missing_file_errors_to_stdout(tmp_path):
    missing = tmp_path / "does_not_exist.md"
    r = subprocess.run([sys.executable, str(SCRIPT), str(missing)], capture_output=True, text=True)
    d = json.loads(r.stdout)          # 错误 JSON 打 stdout，而非 stderr
    assert r.returncode == 2 and "error" in d and r.stderr.strip() != ""


# ---- 危机热线号码红线（2026-08-14 定案）----

CLEAN_DECL = "（本文为心理科普，不构成诊断或治疗；如持续困扰请寻求专业帮助 · 全国统一心理援助热线 12356）"


def _with_decl(tmp_path, decl, name="hotline.md", extra_args=()):
    """把夹具里那行干净的危机声明整行换掉，其余保持不变，跑检查。"""
    text = FIXTURE.read_text(encoding="utf-8")
    assert CLEAN_DECL in text, "夹具声明行已变，用例需同步"
    f = tmp_path / name
    f.write_text(text.replace(CLEAN_DECL, decl), encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(f), *extra_args],
                       capture_output=True, text=True)
    return r, json.loads(r.stdout)


def test_dead_hotline_number_fails(tmp_path):
    """停用热线号码 4001619995 回流即拦。"""
    r, d = _with_decl(tmp_path, "（心理科普 · 希望24热线 4001619995 · 全国统一心理援助热线 12356）")
    assert r.returncode == 1 and d["ok"] is False
    assert any(v["rule"] == "停用热线" for v in d["violations"])


def test_dead_hotline_name_with_space_fails(tmp_path):
    """只写机构名不写号码、中间还带空格（「希望 24」）也要拦——排版换行最容易长这样。"""
    r, d = _with_decl(tmp_path, "（心理科普 · 危机可拨希望 24 热线 · 全国统一心理援助热线 12356）")
    assert r.returncode == 1
    assert any(v["rule"] == "停用热线" for v in d["violations"])


def test_12356_marked_24h_fails(tmp_path):
    """12356 标「24 小时」= 深夜照着打不通、手里又没备选号，必须拦。"""
    r, d = _with_decl(tmp_path, "（心理科普 · 全国统一心理援助热线 12356，24 小时）")
    assert r.returncode == 1 and d["ok"] is False
    v = [x for x in d["violations"] if x["rule"] == "热线时段误标"]
    assert v and "≥18小时" in v[0]["detail"]


def test_24h_on_bj_hotline_not_flagged(tmp_path):
    """标准声明里 12356 与「24 小时」同行、但 24 小时挂在 010-82951332 上——绝不能误伤。"""
    r, d = _with_decl(
        tmp_path,
        "（心理科普 · 全国统一心理援助热线 12356，或北京心理危机研究与干预中心热线 010-82951332（24 小时））",
    )
    assert r.returncode == 0 and d["ok"] is True
    assert not any(v["rule"] == "热线时段误标" for v in d["violations"])


def test_24h_separated_by_punctuation_not_flagged(tmp_path):
    """强句读隔开时「24 小时」归后一句的 010，不算误标（分段边界含句读）。"""
    r, d = _with_decl(tmp_path, "（心理科普 · 援助热线 12356。夜间可拨 24 小时热线 010-82951332）")
    assert r.returncode == 0 and d["ok"] is True


def test_dead_hotline_not_exempted_by_no_crisis(tmp_path):
    """--no-crisis 只豁免「声明在位」，不豁免错号码：推介笔记可以不带声明，不能带错的。"""
    bad = "## 发布文案\n\n黄安麟老师，北大临床心理硕士。危机可拨希望24热线 4001619995。\n"
    f = tmp_path / "intro_bad.md"; f.write_text(bad, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(f), "--no-crisis"],
                       capture_output=True, text=True)
    d = json.loads(r.stdout)
    assert r.returncode == 1 and d["ok"] is False and d["crisis_required"] is False
    assert any(v["rule"] == "停用热线" for v in d["violations"])


def test_hotline_rules_skip_fenced_prompts(tmp_path):
    """围栏内绘图提示词不误伤（与既有违禁词扫描同口径）。"""
    text = FIXTURE.read_text(encoding="utf-8") + "\n```\n画面中不要出现 4001619995 这类旧热线号码\n```\n"
    f = tmp_path / "fenced.md"; f.write_text(text, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True)
    assert r.returncode == 0


# ── 更正稿豁免（2026-08-17 加）────────────────────────────────────
# 起因：老板批 S1「已发布的不删不重发，在下一条推送里更正」。更正段**必须写出那个号码**——
# 不写读者不知道更正的是哪条热线，更正就等于没更正。原判据只认字符串、不认它在句子里的角色。
# ⚠️ 真正的危险不是被拦，是接下来那一步：有人照着闸门去「修」，会把更正段里的号码删掉，
# 于是更正废了、闸门反而变绿——闸门亲手制造了它本该防的那个后果。
def test_停用热线_更正声明放行(tmp_path):
    """引用以更正 → 放行。判据＝同行有停用声明词 且 无推荐动词。"""
    r, d = _with_decl(tmp_path, "（心理科普 · 全国统一心理援助热线 12356）\n\n"
                                "我们此前写过「希望 24 热线 4001619995」，这条热线已经停止服务，在此更正。")
    assert not any(v["rule"] == "停用热线" for v in d["violations"]), \
        "更正声明被拦了：" + json.dumps(d["violations"], ensure_ascii=False)


def test_停用热线_声明词在别行不豁免(tmp_path):
    """声明词必须与号码**同行**——否则文末一句「已停用」会把全篇的号码都豁免掉。"""
    r, d = _with_decl(tmp_path, "（心理科普 · 危机可拨希望24热线 4001619995 · 全国统一心理援助热线 12356）\n\n"
                                "（顺带一提，某些旧热线已经停止服务。）")
    assert any(v["rule"] == "停用热线" for v in d["violations"])


def test_停用热线_自相矛盾写法不豁免(tmp_path):
    """「已停止服务……请拨打 4001619995」有声明词，但它仍在叫人去拨那个号 → 必须拦。"""
    r, d = _with_decl(tmp_path, "（心理科普 · 全国统一心理援助热线 12356）\n\n"
                                "这条热线已停止服务，请拨打 4001619995 求助。")
    assert any(v["rule"] == "停用热线" for v in d["violations"])
