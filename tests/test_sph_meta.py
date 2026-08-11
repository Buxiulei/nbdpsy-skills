import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-content-teardown" / "scripts"))

import sph_meta  # noqa: E402

# 真实 api body（get_feed_info）的精简版，字段名与层级与线上一致
FAKE_BODY = {
    "data": {
        "authorInfo": {"nickname": "迷走神经研习社"},
        "feedInfo": {
            "description": "保持好心情的秘诀 #焦虑",
            "favCountFmt": "1581",
            "likeCountFmt": "274",
            "forwardCountFmt": "2868",
            "commentCountFmt": "123",
            "createtime": 1786364700,
            "coverUrl": "https://x/cover",
        },
    }
}


# ---------- 入参归一 ----------

@pytest.mark.parametrize("raw", [
    "https://weixin.qq.com/sph/ARreWpEs3x",
    "https://channels.weixin.qq.com/finder-preview/pages/sph?id=ARreWpEs3x",
    "ARreWpEs3x",
])
def test_normalize_three_forms(raw):
    assert sph_meta.normalize_sph_id(raw) == "ARreWpEs3x"


def test_normalize_tolerates_noise():
    # 带尾巴的分享链、参数顺序换过的预览链、两边有空白/引号，都该归一到同一个 id
    assert sph_meta.normalize_sph_id("  https://weixin.qq.com/sph/ARreWpEs3x?from=timeline  ") == "ARreWpEs3x"
    assert sph_meta.normalize_sph_id(
        "https://channels.weixin.qq.com/finder-preview/pages/sph?scene=2&id=ARreWpEs3x") == "ARreWpEs3x"
    assert sph_meta.normalize_sph_id('"ARreWpEs3x"') == "ARreWpEs3x"


@pytest.mark.parametrize("bad", [
    "", "   ",
    "https://www.bilibili.com/video/BV1xx411c7mD",   # 别家平台
    "https://www.xiaohongshu.com/explore/6a4f50d0",  # 小红书链走另一个脚本
    "AR!",                                            # 太短且有非法字符
])
def test_normalize_rejects_unknown(bad):
    # 认不出必须抛，绝不能猜——猜错会去抓另一条作品，结论全错还看不出来
    with pytest.raises(ValueError):
        sph_meta.normalize_sph_id(bad)


# ---------- 计数与时间 ----------

def test_parse_count():
    assert sph_meta.parse_count("2089") == 2089
    assert sph_meta.parse_count("1.2万") == 12000
    assert sph_meta.parse_count("3.5亿") == 350000000
    assert sph_meta.parse_count("10万") == 100000


def test_parse_count_unknown_is_none_not_zero():
    # 「没解析出来」不能静默变 0，否则会长出很合理的错结论
    for v in (None, "", "赞", "1,024"):
        assert sph_meta.parse_count(v) is None


def test_beijing_str():
    assert sph_meta.beijing_str(1786364700) == "2026-08-10 20:25:00"
    assert sph_meta.beijing_str(None) is None
    assert sph_meta.beijing_str(0) is None


# ---------- 元数据整形 ----------

def test_shape_meta_from_real_body():
    meta = sph_meta.shape_meta(FAKE_BODY, "ARreWpEs3x")
    assert meta["id"] == "ARreWpEs3x"
    assert meta["nickname"] == "迷走神经研习社"
    assert meta["description"] == "保持好心情的秘诀 #焦虑"
    assert (meta["favCount"], meta["likeCount"],
            meta["forwardCount"], meta["commentCount"]) == (1581, 274, 2868, 123)
    # 原始展示串一并保留，便于跟平台页面逐字核对
    assert meta["favCountFmt"] == "1581" and meta["commentCountFmt"] == "123"
    # createtime 原值 + 换算北京时间字符串，两个都要
    assert meta["createtime"] == 1786364700
    assert meta["createtimeBeijing"] == "2026-08-10 20:25:00"
    assert meta["coverUrl"] == "https://x/cover"
    assert meta["pageUrl"].endswith("sph?id=ARreWpEs3x")


def test_shape_meta_marks_video_unavailable():
    # 正片流拿不到这件事必须写进产物，不能只在终端里一闪而过
    meta = sph_meta.shape_meta(FAKE_BODY, "ARreWpEs3x")
    assert meta["videoStream"] is None
    assert "人工录屏" in meta["videoStreamNote"]


def test_shape_meta_carries_cover_expiry():
    body = {"data": dict(FAKE_BODY["data"], sceneInfo={"expiredTime": 1786465602})}
    meta = sph_meta.shape_meta(body, "ARreWpEs3x")
    assert meta["coverExpireAt"] == 1786465602
    assert meta["coverExpireAtBeijing"] == "2026-08-12 00:26:42"


def test_shape_meta_raises_on_err_code():
    # errCode 非 0 时 feedInfo 是空壳，整形出来会是「一份全 None 的元数据」，必须炸出来
    with pytest.raises(ValueError) as e:
        sph_meta.shape_meta({"errCode": 300330, "errMsg": "feed not exist", "data": {}})
    assert "300330" in str(e.value)


def test_shape_meta_raises_without_feed_info():
    with pytest.raises(ValueError):
        sph_meta.shape_meta({"errCode": 0, "data": {"authorInfo": {"nickname": "x"}}})


def test_shape_meta_missing_counts_are_none():
    body = {"data": {"authorInfo": {"nickname": "x"},
                     "feedInfo": {"description": "d", "createtime": 1786364700}}}
    meta = sph_meta.shape_meta(body, "AR1")
    assert meta["likeCount"] is None and meta["likeCountFmt"] is None
