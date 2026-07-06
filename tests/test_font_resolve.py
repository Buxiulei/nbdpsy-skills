import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-text-to-video" / "scripts"))


def test_env_override_wins(tmp_path, monkeypatch):
    """FONT_PATH 环境变量优先级最高"""
    f = tmp_path / "x.ttc"
    f.write_bytes(b"x")
    monkeypatch.setenv("FONT_PATH", str(f))
    # 需要重新导入以获取环境变量
    import importlib
    import compose_video
    importlib.reload(compose_video)
    assert compose_video.resolve_font() == str(f)


def test_missing_font_message(monkeypatch):
    """找不到字体时错误消息含 FONT_PATH 和 Noto"""
    monkeypatch.setenv("FONT_PATH", "/不存在/x.ttc")
    import importlib
    import compose_video
    importlib.reload(compose_video)
    try:
        compose_video.resolve_font()
        assert False, "应该抛出 RuntimeError"
    except RuntimeError as e:
        assert "FONT_PATH" in str(e) and "Noto" in str(e), f"错误信息缺少必要内容: {e}"


def test_env_not_exist_raises(monkeypatch):
    """FONT_PATH 指定的文件不存在则抛错"""
    monkeypatch.setenv("FONT_PATH", "/completely/nonexistent/path.ttc")
    import importlib
    import compose_video
    importlib.reload(compose_video)
    try:
        compose_video.resolve_font()
        assert False, "应该抛出 RuntimeError"
    except RuntimeError:
        pass  # 预期行为


def test_full_fallback_includes_font_path_hint(monkeypatch):
    """全失败分支：FONT_PATH 为空，fc-list 失败，Windows 候选不存在 → RuntimeError 含 FONT_PATH 指引"""
    import subprocess
    import importlib
    import compose_video

    # 清除 FONT_PATH
    monkeypatch.delenv("FONT_PATH", raising=False)
    # 模拟 fc-list 不可用（FileNotFoundError）
    def mock_run(*args, **kwargs):
        if args[0][0] == "fc-list" or args[0][0] == "fc-match":
            raise FileNotFoundError("fc-list not found")
        return subprocess.run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", mock_run)
    # 模拟 Windows 候选字体不存在
    import pathlib
    original_exists = pathlib.Path.exists
    def mock_exists(self):
        if "msyh.ttc" in str(self):
            return False
        return original_exists(self)

    monkeypatch.setattr(pathlib.Path, "exists", mock_exists)

    # 重载模块清除缓存
    importlib.reload(compose_video)

    try:
        compose_video.resolve_font()
        assert False, "应该抛出 RuntimeError"
    except RuntimeError as e:
        error_msg = str(e)
        assert "FONT_PATH" in error_msg, f"错误消息未含 FONT_PATH: {error_msg}"
        assert "apt-get" in error_msg or "Debian" in error_msg, f"错误消息未含安装指引: {error_msg}"
