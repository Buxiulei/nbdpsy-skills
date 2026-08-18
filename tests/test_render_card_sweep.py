"""帧目录清理 —— 🩸 2026-08-18 立，起因是跑批前的一次体积核算。

**1080×1440 30fps 的 PNG ≈2.3MB/帧，一条 3–6 分钟口播＝12–25GB，12 条并存 241GB。**
而磁盘是**共享的**——撑爆不只本线失败，**会连同时在出片的别条线一起死**。
⇒ 清帧从「跑批脚本各自记得做」提到**产线默认行为**。
"""
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent / "nbdpsy-text-to-video" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import render_card as rc  # noqa: E402


def _mk(tmp_path, monkeypatch, mp4_ok: bool):
    monkeypatch.setattr(rc, "HERE", tmp_path)
    fd = tmp_path / "frames_x"
    fd.mkdir()
    (fd / "f00000.png").write_bytes(b"\x89PNG")
    out = tmp_path / "o.mp4"
    if mp4_ok:
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi",
                        "-i", "color=c=black:s=64x64:d=1", "-y", str(out)], check=True)
    else:
        out.write_bytes(b"not a real mp4")     # ⚠️ 存在且非空，但读不出
    return fd, out


def test_成片可读才删帧(tmp_path, monkeypatch):
    fd, _ = _mk(tmp_path, monkeypatch, mp4_ok=True)
    msg = rc.sweep_frames("x.html", "o.mp4")
    assert not fd.exists() and "已删帧目录" in msg


def test_成片读不出时必须保留帧(tmp_path, monkeypatch):
    """🔴 ⛔ 别拿「文件存在且非空」当判据：MP4 的 moov atom 在**末尾**写入，
    混音进行中的半成品同样存在、同样有几 MB（实测 3.8MB 半成品 ffprobe 报
    moov atom not found，写完是 25MB）。**拿它当「渲完了」去删帧，
    会把还在用的帧删掉。**"""
    fd, _ = _mk(tmp_path, monkeypatch, mp4_ok=False)
    msg = rc.sweep_frames("x.html", "o.mp4")
    assert fd.exists(), "成片读不出却把帧删了——这是不可逆的数据损失"
    assert "保留" in msg and "这不是「渲完了」" in msg


def test_keep_frames_开关必须真的保留(tmp_path, monkeypatch):
    fd, _ = _mk(tmp_path, monkeypatch, mp4_ok=True)
    assert "保留" in rc.sweep_frames("x.html", "o.mp4", keep=True) and fd.exists()


def test_分片模式不清帧_由调用方保证():
    """⚠️ 帧还要给别的片和 --mux-only 收口用。这条靠 main 里的 `if a.shard is None` 守，
    ⛔ 别把清理塞进 render() —— 那样分片跑到一半就会互删。"""
    src = (SCRIPTS / "render_card.py").read_text(encoding="utf-8")
    assert "if a.shard is None:\n        msg = sweep_frames" in src
