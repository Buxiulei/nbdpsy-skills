"""nbdpsy-guide 上手向导 skill 的结构性校验：确保它被安装器登记、含关键触发语与六项 server 手册。"""
from pathlib import Path

ROOT = Path(__file__).parent.parent
SKILL = ROOT / "nbdpsy-guide" / "SKILL.md"


def test_guide_skill_file_exists_with_frontmatter():
    assert SKILL.is_file(), "nbdpsy-guide/SKILL.md 不存在"
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "缺 frontmatter"
    assert "name: nbdpsy-guide" in text


def test_guide_description_has_trigger_phrases():
    text = SKILL.read_text(encoding="utf-8")
    head = text.split("---", 2)[1]  # frontmatter 块
    for kw in ["教我用", "能干啥", "帮我上手", "怎么装插件", "怎么登录", "有哪些账号",
               "怎么发小红书", "拉取分析笔记数据"]:
        assert kw in head, f"description 缺触发语：{kw}"


def test_guide_body_covers_six_server_tools():
    text = SKILL.read_text(encoding="utf-8")
    for cmd in ["--extension-info", "--wait-login", "--list-accounts",
                "--check-cookie", "--note", "--notes", "--self-check", "sandbox allow"]:
        assert cmd in text, f"手册缺命令：{cmd}"


def test_guide_registered_in_installers_and_plugin():
    assert "nbdpsy-guide" in (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "nbdpsy-guide" in (ROOT / "install.ps1").read_text(encoding="utf-8")
    assert "./nbdpsy-guide" in (ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
