"""render_card.py 纯函数与脚本静态行为。⛔ 不在这里跑真渲染（要浏览器+GPU，见 SKILL 实跑验证）。"""
import subprocess, sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent / "nbdpsy-text-to-video" / "scripts"
SCRIPT = SCRIPTS / "render_card.py"
sys.path.insert(0, str(SCRIPTS))

import render_card as rc  # noqa: E402


# ────────── 分片范围 ──────────

def test_shard_range_整除():
    assert rc.shard_range(200, 1, 2) == (0, 100)
    assert rc.shard_range(200, 2, 2) == (100, 200)


def test_shard_range_不整除余数摊给靠前分片():
    assert [rc.shard_range(10, i, 3) for i in (1, 2, 3)] == [(0, 4), (4, 7), (7, 10)]


def test_shard_range_单片即全域():
    assert rc.shard_range(222, 1, 1) == (0, 222)


@pytest.mark.parametrize("n_frames,n", [(222, 2), (222, 4), (10, 3), (415, 4), (1, 1), (7, 7)])
def test_shard_range_首尾相接且并集覆盖全域(n_frames, n):
    rs = [rc.shard_range(n_frames, i, n) for i in range(1, n + 1)]
    assert rs[0][0] == 0 and rs[-1][1] == n_frames
    for a, b in zip(rs, rs[1:]):
        assert a[1] == b[0], "分片之间必须首尾相接：不能有缝也不能重叠"
    assert sum(hi - lo for lo, hi in rs) == n_frames


def test_shard_range_N大于总帧数时靠后分片拿空区间():
    rs = [rc.shard_range(2, i, 4) for i in range(1, 5)]
    assert rs == [(0, 1), (1, 2), (2, 2), (2, 2)]
    assert sum(hi - lo for lo, hi in rs) == 2


@pytest.mark.parametrize("i,n", [(0, 2), (3, 2), (-1, 2), (5, 4)])
def test_shard_range_序号越界报错(i, n):
    with pytest.raises(ValueError, match="越界"):
        rc.shard_range(100, i, n)


@pytest.mark.parametrize("n", [0, -1])
def test_shard_range_分片总数非法报错(n):
    with pytest.raises(ValueError):
        rc.shard_range(100, 1, n)


# ────────── 帧连续性 ──────────

def names(idxs, ext="png"):
    return [f"f{i:05d}.{ext}" for i in idxs]


def test_check_frames_全齐():
    assert rc.check_frames(names(range(10)), 10) == ([], [], [])


def test_check_frames_查出缺号():
    missing, dup, extra = rc.check_frames(names([0, 1, 2, 5, 6]), 7)
    assert missing == [3, 4] and dup == [] and extra == []


def test_check_frames_查出png_jpg双份重号():
    missing, dup, extra = rc.check_frames(names(range(3)) + ["f00001.jpg"], 3)
    assert dup == [1] and missing == [] and extra == []


def test_check_frames_查出位宽不一致的重号():
    """f001.png 与 f00001.png 是同一帧号的两份——ffmpeg 只认一种位宽，另一份是脏帧。"""
    missing, dup, extra = rc.check_frames(["f00000.png", "f00001.png", "f001.png"], 2)
    assert dup == [1]


def test_check_frames_查出超界残留帧():
    """R15 的「稀疏残留」：上一轮更长的渲染留下的尾帧。"""
    missing, dup, extra = rc.check_frames(names([0, 1, 2, 99]), 3)
    assert extra == [99] and missing == [] and dup == []


def test_check_frames_忽略非帧文件():
    junk = [".render.pid", ".render.pid.s1of2", ".shard-logs", "tpl.render.html", "out.mp4"]
    assert rc.check_frames(names(range(3)) + junk, 3) == ([], [], [])


def test_check_frames_不给期望值时按最大帧号推断():
    assert rc.check_frames(names([0, 1, 3])) == ([2], [], [])


def test_check_frames_空目录():
    assert rc.check_frames([], 5) == ([0, 1, 2, 3, 4], [], [])


# ────────── 锁：槽位与文件名 ──────────

def test_lock_filename_整片与分片各自成名():
    assert rc.lock_filename(None) == ".render.pid"
    assert rc.lock_filename((1, 4)) == ".render.pid.s1of4"


@pytest.mark.parametrize("slot", [None, (1, 2), (3, 4), (12, 12)])
def test_lock_文件名往返(slot):
    assert rc.parse_lock_name(rc.lock_filename(slot)) == slot


@pytest.mark.parametrize("bad", ["render.pid", ".render.pidx", "f00001.png", ".render.pid.s1of"])
def test_parse_lock_name_非锁名报错(bad):
    with pytest.raises(ValueError):
        rc.parse_lock_name(bad)


def test_slots_conflict_只有同N不同片才互不冲突():
    assert rc.slots_conflict((1, 2), (2, 2)) is False        # 兄弟分片，帧域不相交
    assert rc.slots_conflict((1, 4), (3, 4)) is False
    assert rc.slots_conflict((1, 2), (1, 2)) is True         # 同一片重入
    assert rc.slots_conflict((1, 2), (1, 3)) is True         # N 不同，帧域可能重叠
    assert rc.slots_conflict(None, None) is True             # 两个整片
    assert rc.slots_conflict(None, (1, 2)) is True           # 整片吃掉全域
    assert rc.slots_conflict((1, 2), None) is True


# ────────── 锁：pid 存活判定 ──────────

def test_pid_alive_进程不存在(monkeypatch):
    monkeypatch.setattr(rc.os, "kill", lambda p, s: (_ for _ in ()).throw(ProcessLookupError()))
    assert rc.pid_alive(4242) is False


def test_pid_alive_进程存在但不属于当前用户(monkeypatch):
    """PermissionError＝进程确实在，只是没权限发信号——必须当活的，否则会清别人的帧。"""
    monkeypatch.setattr(rc.os, "kill", lambda p, s: (_ for _ in ()).throw(PermissionError()))
    assert rc.pid_alive(1) is True


def test_pid_alive_正常存活(monkeypatch):
    monkeypatch.setattr(rc.os, "kill", lambda p, s: None)
    assert rc.pid_alive(4242) is True


# ────────── 锁：获取/拒绝/接管 ──────────

def alive(*pids):
    """构造 os.kill 替身：只有列出的 pid 算活着。"""
    def _kill(p, s):
        if p not in pids:
            raise ProcessLookupError()
    return _kill


def test_acquire_lock_空目录直接拿到(tmp_path, monkeypatch):
    monkeypatch.setattr(rc.os, "kill", alive())
    lk = rc.acquire_lock(tmp_path, None)
    assert lk.name == ".render.pid"
    assert lk.read_text().splitlines()[0] == str(rc.os.getpid())
    assert "slot=full" in lk.read_text()


def test_acquire_lock_活的整片锁挡住新整片(tmp_path, monkeypatch):
    (tmp_path / ".render.pid").write_text("5000\nslot=full\n")
    monkeypatch.setattr(rc.os, "kill", alive(5000))
    with pytest.raises(SystemExit) as e:
        rc.acquire_lock(tmp_path, None)
    assert "5000" in str(e.value), "必须把持锁的 pid 报出来"


def test_acquire_lock_活的整片锁挡住分片(tmp_path, monkeypatch):
    (tmp_path / ".render.pid").write_text("5000\nslot=full\n")
    monkeypatch.setattr(rc.os, "kill", alive(5000))
    with pytest.raises(SystemExit):
        rc.acquire_lock(tmp_path, (1, 2))


def test_acquire_lock_兄弟分片放行(tmp_path, monkeypatch):
    """并行分片的核心：1/2 在渲时 2/2 必须能起来。"""
    (tmp_path / ".render.pid.s1of2").write_text("5000\nslot=1/2\n")
    monkeypatch.setattr(rc.os, "kill", alive(5000))
    lk = rc.acquire_lock(tmp_path, (2, 2))
    assert lk.name == ".render.pid.s2of2"
    assert (tmp_path / ".render.pid.s1of2").read_text().startswith("5000"), "绝不能动别人的锁"


def test_acquire_lock_同一片重入被挡(tmp_path, monkeypatch):
    (tmp_path / ".render.pid.s1of2").write_text("5000\nslot=1/2\n")
    monkeypatch.setattr(rc.os, "kill", alive(5000))
    with pytest.raises(SystemExit):
        rc.acquire_lock(tmp_path, (1, 2))


def test_acquire_lock_不同N被挡(tmp_path, monkeypatch):
    (tmp_path / ".render.pid.s1of2").write_text("5000\nslot=1/2\n")
    monkeypatch.setattr(rc.os, "kill", alive(5000))
    with pytest.raises(SystemExit):
        rc.acquire_lock(tmp_path, (1, 3))


def test_acquire_lock_死锁接管(tmp_path, monkeypatch, capsys):
    (tmp_path / ".render.pid").write_text("5000\nslot=full\n")
    monkeypatch.setattr(rc.os, "kill", alive())  # 5000 已死
    lk = rc.acquire_lock(tmp_path, None)
    assert lk.read_text().splitlines()[0] == str(rc.os.getpid())
    assert "接管" in capsys.readouterr().err


def test_acquire_lock_损坏的锁文件当死锁(tmp_path, monkeypatch):
    (tmp_path / ".render.pid").write_text("这不是数字")
    monkeypatch.setattr(rc.os, "kill", alive(5000))
    assert rc.acquire_lock(tmp_path, None).name == ".render.pid"


def test_acquire_lock_多把死锁里混一把活锁也要挡住(tmp_path, monkeypatch):
    (tmp_path / ".render.pid.s1of4").write_text("5000\n")
    (tmp_path / ".render.pid.s2of4").write_text("5001\n")
    (tmp_path / ".render.pid").write_text("5002\n")  # 整片，活着
    monkeypatch.setattr(rc.os, "kill", alive(5002))
    with pytest.raises(SystemExit) as e:
        rc.acquire_lock(tmp_path, (3, 4))
    assert "5002" in str(e.value)


def test_release_lock_删掉自己的锁(tmp_path, monkeypatch):
    monkeypatch.setattr(rc.os, "kill", alive())
    lk = rc.acquire_lock(tmp_path, (1, 2))
    rc.release_lock(lk)
    assert not lk.exists()
    rc.release_lock(lk)  # 重复释放不炸


# ────────── CLI 契约 ──────────

def run_cli(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def test_help_可跑():
    r = run_cli("--help")
    assert r.returncode == 0
    assert "--shard" in r.stdout and "--angle" in r.stdout


@pytest.fixture
def spy(monkeypatch):
    """拦住真渲染，只看 main() 把参数解析成了什么。"""
    seen = {}
    monkeypatch.setattr(rc, "render", lambda *a, **k: seen.update(args=a, kw=k))
    return seen


def test_旧契约_两个位置参数解析不变(spy):
    assert rc.main(["tpl-basic.html", "out.mp4"]) == 0
    assert spy["args"] == ("tpl-basic.html", "out.mp4", None, "swiftshader", False), \
        "不带新参数时必须还是「整片渲染+混音」、分片为 None、且后端默认 CPU（与存量批次一致）"


def test_分片参数解析(spy):
    rc.main(["tpl.html", "out.mp4", "--shard", "2", "4"])
    assert spy["args"][2] == (2, 4)


def test_angle参数解析(spy):
    rc.main(["tpl.html", "out.mp4", "--angle", "egl"])
    assert spy["args"][3] == "egl"


def test_deterministic参数解析(spy):
    rc.main(["tpl.html", "out.mp4", "--deterministic"])
    assert spy["args"][4] is True


def test_egl映射到gl_egl而不是裸egl():
    """实测 `--use-angle=egl` 不是合法取值、会静默回落 SwiftShader——必须映射成 gl-egl。"""
    assert rc.ANGLE_BACKEND["egl"] == "gl-egl"
    assert rc.ANGLE_BACKEND["vulkan"] == "vulkan"


def test_默认CPU路径不带任何GPU启动参数():
    """存量已过审的字卡片都是「只有 BASE_ARGS」渲的——默认路径必须逐字节复现那套参数，
    多传一个 --enable-gpu 都可能换掉光栅路径。"""
    assert rc.launch_args("swiftshader") == rc.BASE_ARGS
    for flag in rc.GPU_ARGS + ["--use-angle=swiftshader"]:
        assert flag not in rc.launch_args("swiftshader")


@pytest.mark.parametrize("angle,backend", [("vulkan", "vulkan"), ("egl", "gl-egl")])
def test_显式开GPU才加GPU参数(angle, backend):
    args = rc.launch_args(angle)
    assert args[:len(rc.BASE_ARGS)] == rc.BASE_ARGS
    for flag in rc.GPU_ARGS:
        assert flag in args
    assert f"--use-angle={backend}" in args


def test_launch_args不污染BASE_ARGS():
    rc.launch_args("swiftshader").append("--脏")
    assert "--脏" not in rc.BASE_ARGS


def test_分片序号越界在开渲前就报错(spy):
    r = run_cli("tpl.html", "out.mp4", "--shard", "5", "4")
    assert r.returncode != 0
    assert "越界" in r.stdout + r.stderr


def test_整片模式缺out参数报错():
    r = run_cli("tpl.html")
    assert r.returncode == 2
    assert "out" in r.stderr


def test_mux_only缺out参数报错():
    r = run_cli("tpl.html", "--mux-only")
    assert r.returncode == 2


def test_非法angle被拒():
    assert run_cli("tpl.html", "out.mp4", "--angle", "metal").returncode == 2


def test_verify_frames_帧目录不存在时报错(monkeypatch, tmp_path):
    monkeypatch.setattr(rc, "HERE", tmp_path)
    assert rc.verify_frames("tpl-不存在.html") == 1


def test_verify_frames_连续则通过(monkeypatch, tmp_path):
    monkeypatch.setattr(rc, "HERE", tmp_path)
    fd = tmp_path / "frames_tpl"
    fd.mkdir()
    for i in range(5):
        (fd / f"f{i:05d}.png").write_bytes(b"x")
    assert rc.verify_frames("tpl.html", 5) == 0


def test_verify_frames_缺号则失败(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(rc, "HERE", tmp_path)
    fd = tmp_path / "frames_tpl"
    fd.mkdir()
    for i in [0, 1, 3]:
        (fd / f"f{i:05d}.png").write_bytes(b"x")
    assert rc.verify_frames("tpl.html", 4) == 1
    assert "缺" in capsys.readouterr().err


# ────────── wrapper 静态检查 ──────────

def test_render_sharded_语法正确且可执行():
    sh = SCRIPTS / "render_sharded.sh"
    assert sh.exists()
    assert subprocess.run(["bash", "-n", str(sh)], capture_output=True).returncode == 0


def test_render_sharded_参数不足时给用法():
    r = subprocess.run(["bash", str(SCRIPTS / "render_sharded.sh"), "a.html"],
                       capture_output=True, text=True)
    assert r.returncode == 2 and "用法" in r.stderr


@pytest.mark.parametrize("bad", ["0", "-1", "abc"])
def test_render_sharded_非法N被拒(bad, tmp_path):
    r = subprocess.run(["bash", str(SCRIPTS / "render_sharded.sh"), "a.html", "o.mp4", bad],
                       capture_output=True, text=True)
    assert r.returncode == 2 and "N 必须" in r.stderr
