"""update 子命令测试：全部走 `--source <tmp fixture 假仓库>`，一个字节都不打网络。

覆盖契约点名的五种情形：正常更新 / legacy 旧名被清 / 某 skill 复制后 SKILL.md 缺失即报错退出 /
--source 路径不存在时人话报错 / git 缺失时给两条备选。
"""
import json, os, subprocess, sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "shared"))

import nbdpsy_common

COMMON = Path(__file__).parent.parent / "shared" / "nbdpsy_common.py"


def _make_repo(tmp_path, version="9.9.9", skills=("nbdpsy-alpha", "nbdpsy-beta")):
    """造一个最小 nbdpsy-skills 假仓库：若干 nbdpsy-*/SKILL.md + plugin.json + git 提交。
    额外放一个没有 SKILL.md 的 nbdpsy-*-workspace 目录，验证它不会被派生进清单。"""
    repo = tmp_path / "repo"
    for s in skills:
        (repo / s / "scripts").mkdir(parents=True)
        (repo / s / "SKILL.md").write_text(f"# {s}\n", encoding="utf-8")
        (repo / s / "scripts" / "run.py").write_text("print('hi')\n", encoding="utf-8")
    (repo / "nbdpsy-alpha-workspace").mkdir(parents=True)      # 无 SKILL.md，应被排除
    (repo / ".claude-plugin").mkdir(parents=True)
    (repo / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "nbdpsy-content", "version": version}, ensure_ascii=False),
        encoding="utf-8")
    (repo / "requirements.txt").write_text("pyyaml\nrequests\n", encoding="utf-8")
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    subprocess.run(git + ["add", "-A"], check=True, capture_output=True)
    subprocess.run(git + ["commit", "-q", "-m", "fixture"], check=True, capture_output=True)
    return repo


def _fake_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


# ── 情形 1：正常更新 ──────────────────────────────────────────────

def test_update_copies_skills_and_writes_marker(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    home = _fake_home(tmp_path, monkeypatch)
    logs = []

    report = nbdpsy_common.update(source=str(repo), log=logs.append)

    assert report["ok"] is True
    assert report["skills"] == ["nbdpsy-alpha", "nbdpsy-beta"]     # workspace 目录被排除
    assert report["from"] == "unknown" and report["to"] == "9.9.9"
    assert report["source"] == "local-repo"
    # 默认落两个目的地（HOME 已隔离到 tmp）
    dests = [home / ".claude" / "skills", home / ".agents" / "skills"]
    assert report["dests"] == [str(d) for d in dests]
    for dest in dests:
        for s in report["skills"]:
            assert (dest / s / "SKILL.md").is_file()
            assert (dest / s / "scripts" / "run.py").is_file()     # 整棵子树都复制到位
        # 版本标记四字段，与 install.sh 逐字段同格式（doctor 要能读）
        marker = json.loads((dest / ".nbdpsy-skills-install.json").read_text(encoding="utf-8"))
        assert list(marker) == ["version", "commit", "installed_at", "source"]
        assert marker["version"] == "9.9.9"
        assert marker["source"] == "local-repo"
        assert marker["commit"] == subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True).stdout.strip()
        stamp = datetime.fromisoformat(marker["installed_at"])     # 可解析、带时区、秒级精度
        assert stamp.tzinfo is not None and stamp.microsecond == 0
    assert "✓ 工具包 vunknown → v9.9.9（%s）" % report["commit"] in logs
    assert any("依赖清单可能有变" in l for l in logs)               # 不自动装依赖，只提示


def test_update_reports_old_to_new_version(tmp_path, monkeypatch):
    """新旧版本报告：更新前已有标记时，from 取旧标记里的版本。"""
    repo = _make_repo(tmp_path, version="2.0.0")
    home = _fake_home(tmp_path, monkeypatch)
    dest = home / ".claude" / "skills"
    dest.mkdir(parents=True)
    (dest / ".nbdpsy-skills-install.json").write_text(
        '{"version": "1.41.0", "commit": "b4c5812", '
        '"installed_at": "2026-07-27T10:00:00+08:00", "source": "github-clone"}',
        encoding="utf-8")
    logs = []

    report = nbdpsy_common.update(source=str(repo), log=logs.append)

    assert report["from"] == "1.41.0" and report["to"] == "2.0.0"
    assert any(l.startswith("✓ 工具包 v1.41.0 → v2.0.0（") for l in logs)


def test_marker_is_readable_by_doctor(tmp_path, monkeypatch):
    """标记不是写给自己看的：doctor 的 find_install_marker 必须能读出来并报版本行。"""
    repo = _make_repo(tmp_path, version="3.1.4")
    home = _fake_home(tmp_path, monkeypatch)
    nbdpsy_common.update(source=str(repo), log=lambda _m: None)

    marker, path = nbdpsy_common.find_install_marker()
    assert path == home / ".claude" / "skills" / ".nbdpsy-skills-install.json"
    assert nbdpsy_common._toolkit_version_note(marker).startswith("工具包 v3.1.4（")


def test_skill_list_is_derived_from_source_not_hardcoded(tmp_path, monkeypatch):
    """防清单漂移：源仓库新增一个 nbdpsy-*/SKILL.md 就自动被带上，无需改本文件里的任何数组。"""
    repo = _make_repo(tmp_path, skills=("nbdpsy-alpha", "nbdpsy-zeta", "nbdpsy-brandnew"))
    _fake_home(tmp_path, monkeypatch)

    report = nbdpsy_common.update(source=str(repo), log=lambda _m: None)

    assert report["skills"] == ["nbdpsy-alpha", "nbdpsy-brandnew", "nbdpsy-zeta"]
    assert nbdpsy_common.discover_skills(repo) == report["skills"]


# ── 情形 2：legacy 旧名被清 ────────────────────────────────────────

def test_legacy_skill_names_are_removed(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    home = _fake_home(tmp_path, monkeypatch)
    dest = home / ".claude" / "skills"
    legacy = dest / "xiaohongshu-creator"
    legacy.mkdir(parents=True)
    (legacy / "SKILL.md").write_text("旧版无前缀 skill\n", encoding="utf-8")
    keep = dest / "别人的-skill"
    keep.mkdir()
    (keep / "SKILL.md").write_text("无关 skill，不许动\n", encoding="utf-8")
    logs = []

    nbdpsy_common.update(source=str(repo), log=logs.append)

    assert not legacy.exists()
    assert (keep / "SKILL.md").is_file()                    # 只清点名的旧名，不扫荡目录
    assert any("清理旧名 xiaohongshu-creator" in l for l in logs)


# ── 情形 3：复制后 SKILL.md 缺失 → 立即人话报错退出，绝不打 ✓ ──────────

def _copytree_without_skill_md(src, dst, **kw):
    """模拟「复制像是成功了、实际没落地」：只建空目录。"""
    Path(dst).mkdir(parents=True, exist_ok=True)


def test_missing_skill_md_after_copy_aborts_loudly(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    home = _fake_home(tmp_path, monkeypatch)
    monkeypatch.setattr(nbdpsy_common.shutil, "copytree", _copytree_without_skill_md)
    logs = []

    try:
        nbdpsy_common.update(source=str(repo), log=logs.append)
        raised = None
    except nbdpsy_common.UpdateError as e:
        raised = e

    assert raised is not None, "复制没落地却没报错——正是同事那台机器的静默失败"
    assert "nbdpsy-alpha" in str(raised) and "SKILL.md" in str(raised)
    assert "已中止" in str(raised)
    # 失败路径上一个 ✓ 都不许打
    assert not any("  ✓ nbdpsy-" in l for l in logs)
    assert not (home / ".claude" / "skills" / ".nbdpsy-skills-install.json").exists()


def test_missing_skill_md_exits_one_via_cli(tmp_path, monkeypatch, capsys):
    repo = _make_repo(tmp_path)
    _fake_home(tmp_path, monkeypatch)
    monkeypatch.setattr(nbdpsy_common.shutil, "copytree", _copytree_without_skill_md)

    code = nbdpsy_common.main(["update", "--source", str(repo)])

    assert code == 1
    out = capsys.readouterr()
    assert "✗ 更新失败" in out.err
    assert json.loads(out.out)["ok"] is False


# ── 情形 4：--source 路径不存在 ────────────────────────────────────

def test_missing_source_path_is_plain_language_error(tmp_path, monkeypatch, capsys):
    _fake_home(tmp_path, monkeypatch)
    nowhere = tmp_path / "nowhere"

    code = nbdpsy_common.main(["update", "--source", str(nowhere)])

    assert code == 1
    out = capsys.readouterr()
    assert "路径不存在" in out.err and str(nowhere) in out.err
    assert json.loads(out.out)["ok"] is False


def test_source_that_is_not_a_repo_aborts(tmp_path, monkeypatch):
    """目录在、但里面没有 nbdpsy-*/SKILL.md → 中止，且不动本机任何文件。"""
    empty = tmp_path / "empty"
    empty.mkdir()
    home = _fake_home(tmp_path, monkeypatch)

    try:
        nbdpsy_common.update(source=str(empty), log=lambda _m: None)
        raised = None
    except nbdpsy_common.UpdateError as e:
        raised = e

    assert raised is not None and "nbdpsy-*/SKILL.md" in str(raised)
    assert not (home / ".claude" / "skills").exists()


# ── 情形 5：git 缺失 → 人话报错 + 两条备选 ─────────────────────────

def test_missing_git_gives_two_fallbacks(tmp_path, monkeypatch):
    """把 PATH 清空 → shutil.which('git') 返回 None，报错先于任何网络动作发生。"""
    _fake_home(tmp_path, monkeypatch)
    monkeypatch.setenv("PATH", "")

    try:
        nbdpsy_common.update(log=lambda _m: None)          # 不给 source，走 clone 分支
        raised = None
    except nbdpsy_common.UpdateError as e:
        raised = e

    msg = str(raised)
    assert raised is not None and "没有 git" in msg
    assert "install.sh" in msg and "! bash install.sh" in msg   # 备选①②都在


# ── CLI 契约：stdout 是纯 JSON，stderr 是人话 ─────────────────────

def test_cli_stdout_is_pure_json(tmp_path):
    repo = _make_repo(tmp_path, version="5.5.5")
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))

    r = subprocess.run([sys.executable, str(COMMON), "update", "--source", str(repo)],
                       capture_output=True, text=True, env=env)

    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert set(payload) >= {"ok", "from", "to", "commit", "dests", "skills"}
    assert payload["to"] == "5.5.5"
    assert (home / ".claude" / "skills" / "nbdpsy-alpha" / "SKILL.md").is_file()
    assert (home / ".agents" / "skills" / "nbdpsy-beta" / "SKILL.md").is_file()
    assert "工具包 vunknown → v5.5.5" in r.stderr


def test_cli_bad_usage_returns_two(tmp_path):
    r = subprocess.run([sys.executable, str(COMMON), "update", "--source"],
                       capture_output=True, text=True)
    assert r.returncode == 2 and "用法" in r.stderr and "update [--source" in r.stderr
