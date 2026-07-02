import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "text-to-video" / "scripts"))


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
    # 移除可能存在的真实字体路径环境变量
    monkeypatch.delenv("PATH", raising=False)
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
